"""
Testes unitários para src.core.telemetry.TelemetryLogger.

Cobre:
  - is_enabled() — sem DB, DB com setting off, DB com setting on
  - log_operation() — não grava quando desabilitado, grava quando habilitado
  - Formato das entradas JSONL (campos obrigatórios e opcionais)
  - read_entries() — arquivo inexistente, entradas inválidas, múltiplas entradas
  - clear() — remove o arquivo de log
  - Thread safety — gravação concorrente não corrompe o arquivo
  - enable() / disable() — persistem a configuração no banco
  - Branches de exceção silenciosa em is_enabled, enable, disable, _write, clear

Estratégia:
  - tmp_path do pytest para log_path (nunca toca o log real do usuário)
  - Stub minimalista de banco de dados (dict in-memory) para testar enable/disable
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest

import src.core.telemetry as _telemetry_module
from src.core.telemetry import TelemetryLogger


# ─────────────────────────────────────────────────────────────────────────────
# Stubs
# ─────────────────────────────────────────────────────────────────────────────

class _FakeDB:
    """Banco de dados em memória para testes (interface mínima)."""

    def __init__(self, initial_settings: dict[str, str] | None = None):
        self._settings: dict[str, str] = initial_settings or {}

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: str) -> None:
        self._settings[key] = value


# ─────────────────────────────────────────────────────────────────────────────
# is_enabled
# ─────────────────────────────────────────────────────────────────────────────

class TestIsEnabled:
    def test_disabled_when_no_db(self, tmp_path):
        tl = TelemetryLogger(db=None, log_path=tmp_path / "t.jsonl")
        assert not tl.is_enabled()

    def test_disabled_when_setting_missing(self, tmp_path):
        db = _FakeDB()
        tl = TelemetryLogger(db=db, log_path=tmp_path / "t.jsonl")
        assert not tl.is_enabled()

    def test_disabled_when_setting_false(self, tmp_path):
        db = _FakeDB({"telemetry_enabled": "false"})
        tl = TelemetryLogger(db=db, log_path=tmp_path / "t.jsonl")
        assert not tl.is_enabled()

    def test_enabled_when_setting_true(self, tmp_path):
        db = _FakeDB({"telemetry_enabled": "true"})
        tl = TelemetryLogger(db=db, log_path=tmp_path / "t.jsonl")
        assert tl.is_enabled()


# ─────────────────────────────────────────────────────────────────────────────
# log_operation — comportamento quando desabilitado
# ─────────────────────────────────────────────────────────────────────────────

class TestLogOperationDisabled:
    def test_no_file_created_when_disabled(self, tmp_path):
        log_path = tmp_path / "t.jsonl"
        tl = TelemetryLogger(db=None, log_path=log_path)
        tl.log_operation("MOVER", source="ui", success=True)
        assert not log_path.exists()

    def test_no_file_created_when_setting_false(self, tmp_path):
        log_path = tmp_path / "t.jsonl"
        db = _FakeDB({"telemetry_enabled": "false"})
        tl = TelemetryLogger(db=db, log_path=log_path)
        tl.log_operation("DELETAR", source="ai:mcp", success=True)
        assert not log_path.exists()


# ─────────────────────────────────────────────────────────────────────────────
# log_operation — comportamento quando habilitado
# ─────────────────────────────────────────────────────────────────────────────

class TestLogOperationEnabled:
    @pytest.fixture
    def enabled_logger(self, tmp_path):
        db = _FakeDB({"telemetry_enabled": "true"})
        return TelemetryLogger(db=db, log_path=tmp_path / "t.jsonl")

    def test_creates_file_on_first_log(self, enabled_logger):
        enabled_logger.log_operation("SCAN", source="ui", success=True)
        assert enabled_logger._log_path.exists()

    def test_entry_has_required_fields(self, enabled_logger):
        enabled_logger.log_operation("MOVER", source="ui", success=True, file_count=2)
        entries = enabled_logger.read_entries()
        assert len(entries) == 1
        entry = entries[0]
        assert "ts" in entry
        assert "op" in entry
        assert "src" in entry
        assert "ok" in entry
        assert "n" in entry

    def test_entry_values_correct(self, enabled_logger):
        enabled_logger.log_operation("DELETAR", source="ai:ollama", success=False, file_count=3)
        entry = enabled_logger.read_entries()[0]
        assert entry["op"] == "DELETAR"
        assert entry["src"] == "ai:ollama"
        assert entry["ok"] is False
        assert entry["n"] == 3

    def test_error_category_included_when_provided(self, enabled_logger):
        enabled_logger.log_operation(
            "MOVER", source="ui", success=False, error_category="PERMISSION_ERROR"
        )
        entry = enabled_logger.read_entries()[0]
        assert entry["err"] == "PERMISSION_ERROR"

    def test_error_category_absent_when_none(self, enabled_logger):
        enabled_logger.log_operation("SCAN", source="ui", success=True)
        entry = enabled_logger.read_entries()[0]
        assert "err" not in entry

    def test_multiple_entries_appended(self, enabled_logger):
        for i in range(5):
            enabled_logger.log_operation("DELETAR", source="ui", success=True)
        entries = enabled_logger.read_entries()
        assert len(entries) == 5

    def test_no_pii_in_entry(self, enabled_logger):
        """Nenhuma chave no entry deve conter caminhos de arquivo."""
        enabled_logger.log_operation("MOVER", source="ui", success=True)
        entry = enabled_logger.read_entries()[0]
        for val in entry.values():
            val_str = str(val)
            assert "\\" not in val_str, f"PII detectada: {val_str}"
            assert "Users" not in val_str


# ─────────────────────────────────────────────────────────────────────────────
# read_entries
# ─────────────────────────────────────────────────────────────────────────────

class TestReadEntries:
    def test_returns_empty_list_for_missing_file(self, tmp_path):
        tl = TelemetryLogger(log_path=tmp_path / "nope.jsonl")
        assert tl.read_entries() == []

    def test_skips_invalid_json_lines(self, tmp_path):
        log_path = tmp_path / "t.jsonl"
        log_path.write_text(
            '{"ts":"2026","op":"SCAN","src":"ui","ok":true,"n":1}\n'
            'not-valid-json\n'
            '{"ts":"2026","op":"MOVER","src":"ui","ok":false,"n":2}\n',
            encoding="utf-8",
        )
        db = _FakeDB({"telemetry_enabled": "true"})
        tl = TelemetryLogger(db=db, log_path=log_path)
        entries = tl.read_entries()
        assert len(entries) == 2


# ─────────────────────────────────────────────────────────────────────────────
# clear
# ─────────────────────────────────────────────────────────────────────────────

class TestClear:
    def test_clear_removes_file(self, tmp_path):
        log_path = tmp_path / "t.jsonl"
        db = _FakeDB({"telemetry_enabled": "true"})
        tl = TelemetryLogger(db=db, log_path=log_path)
        tl.log_operation("SCAN", source="ui", success=True)
        assert log_path.exists()
        tl.clear()
        assert not log_path.exists()

    def test_clear_when_no_file_is_safe(self, tmp_path):
        tl = TelemetryLogger(log_path=tmp_path / "nope.jsonl")
        tl.clear()  # deve ser silencioso


# ─────────────────────────────────────────────────────────────────────────────
# enable / disable
# ─────────────────────────────────────────────────────────────────────────────

class TestEnableDisable:
    def test_enable_sets_setting_in_db(self, tmp_path):
        db = _FakeDB()
        tl = TelemetryLogger(db=db, log_path=tmp_path / "t.jsonl")
        assert not tl.is_enabled()
        tl.enable()
        assert tl.is_enabled()

    def test_disable_unsets_setting_in_db(self, tmp_path):
        db = _FakeDB({"telemetry_enabled": "true"})
        tl = TelemetryLogger(db=db, log_path=tmp_path / "t.jsonl")
        assert tl.is_enabled()
        tl.disable()
        assert not tl.is_enabled()

    def test_enable_without_db_is_silent(self, tmp_path):
        tl = TelemetryLogger(db=None, log_path=tmp_path / "t.jsonl")
        tl.enable()  # não deve lançar exceção
        assert not tl.is_enabled()


# ─────────────────────────────────────────────────────────────────────────────
# Thread safety
# ─────────────────────────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_writes_do_not_corrupt_file(self, tmp_path):
        """20 threads gravando simultaneamente — todas as entradas devem ser válidas."""
        db = _FakeDB({"telemetry_enabled": "true"})
        log_path = tmp_path / "concurrent.jsonl"
        tl = TelemetryLogger(db=db, log_path=log_path)

        n_threads = 20

        def write_entry():
            tl.log_operation("SCAN", source="ui", success=True)

        threads = [threading.Thread(target=write_entry) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        entries = tl.read_entries()
        assert len(entries) == n_threads
        for entry in entries:
            assert "ts" in entry
            assert "op" in entry


# ─────────────────────────────────────────────────────────────────────────────
# _default_log_path — branch sem LOCALAPPDATA (L61-62)
# ─────────────────────────────────────────────────────────────────────────────

class TestDefaultLogPath:
    def test_uses_home_when_localappdata_missing(self, monkeypatch):
        """Branch L61: quando LOCALAPPDATA não está no ambiente, usa Path.home()."""
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        path = _telemetry_module._default_log_path()
        assert "GestaoPC" in str(path)
        assert path.name == "telemetry.jsonl"

    def test_uses_localappdata_when_set(self, monkeypatch, tmp_path):
        """Branch L58: quando LOCALAPPDATA está definido, usa-o como base."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        path = _telemetry_module._default_log_path()
        assert str(tmp_path) in str(path)
        assert path.name == "telemetry.jsonl"


# ─────────────────────────────────────────────────────────────────────────────
# Branches de exceção silenciosa
# ─────────────────────────────────────────────────────────────────────────────

class _BrokenDB:
    """DB cujos métodos sempre lançam exceção — para testar branches de except."""

    def get_setting(self, key: str, default=None):
        raise RuntimeError("DB unavailable")

    def set_setting(self, key: str, value: str) -> None:
        raise RuntimeError("DB unavailable")


class TestSilentExceptionBranches:
    """Garante que exceções em operações de DB/IO são absorvidas silenciosamente."""

    def test_is_enabled_returns_false_when_get_setting_raises(self, tmp_path):
        """L106-107: except Exception → return False."""
        tl = TelemetryLogger(db=_BrokenDB(), log_path=tmp_path / "t.jsonl")
        assert not tl.is_enabled()

    def test_enable_is_silent_when_set_setting_raises(self, tmp_path):
        """L114-115: except Exception → pass."""
        tl = TelemetryLogger(db=_BrokenDB(), log_path=tmp_path / "t.jsonl")
        tl.enable()  # não deve lançar exceção

    def test_disable_is_silent_when_set_setting_raises(self, tmp_path):
        """L122-123: except Exception → pass."""
        tl = TelemetryLogger(db=_BrokenDB(), log_path=tmp_path / "t.jsonl")
        tl.disable()  # não deve lançar exceção

    def test_write_is_silent_when_open_raises(self, tmp_path):
        """L209-211: except Exception → logger.debug (sem propagação)."""
        db = _FakeDB({"telemetry_enabled": "true"})
        tl = TelemetryLogger(db=db, log_path=tmp_path / "t.jsonl")
        with patch("builtins.open", side_effect=OSError("Disco cheio")):
            tl.log_operation("SCAN", source="ui", success=True)
        # Nenhuma exceção deve ter sido propagada; arquivo não deve existir
        assert not (tmp_path / "t.jsonl").exists()

    def test_read_entries_returns_empty_on_ioerror(self, tmp_path):
        """L187-188: except Exception → return []."""
        log_path = tmp_path / "t.jsonl"
        log_path.write_text(
            '{"ts":"2026","op":"SCAN","src":"ui","ok":true,"n":1}\n',
            encoding="utf-8",
        )
        tl = TelemetryLogger(log_path=log_path)
        with patch("builtins.open", side_effect=IOError("Leitura falhou")):
            result = tl.read_entries()
        assert result == []

    def test_clear_is_silent_when_unlink_raises(self, tmp_path):
        """L195-196: except Exception → pass."""
        log_path = tmp_path / "t.jsonl"
        log_path.write_text("data", encoding="utf-8")
        tl = TelemetryLogger(log_path=log_path)
        with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
            tl.clear()  # não deve lançar exceção
