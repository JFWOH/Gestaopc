"""
Telemetria local opt-in — GestaoPC Storage Manager.

Registra eventos operacionais de forma anônima em um arquivo JSONL local.
Nenhuma informação pessoal (PII) é incluída: sem caminhos de arquivo,
sem nomes de usuário, sem identificadores de máquina.

O log é habilitado somente quando a configuração ``telemetry_enabled``
estiver definida como ``"true"`` no banco de dados de configurações.

Formato de cada linha do arquivo JSONL::

    {"ts": "2026-05-08T12:00:00", "op": "MOVER", "src": "ui", "ok": true, "n": 3}

Campos:
    ts  — Timestamp ISO 8601 (UTC).
    op  — Tipo de operação: "MOVER", "DELETAR", "UNDO", "SCAN", "SCAN_ERROR".
    src — Origem da ação: "ui", "ai:ollama", "ai:mcp".
    ok  — True se bem-sucedida, False se falhou.
    n   — Número de arquivos envolvidos na operação.
    err — (opcional) Categoria de erro, sem detalhes de arquivo.

O arquivo é gravado em::

    %LOCALAPPDATA%\\GestaoPC\\telemetry.jsonl

Uso::

    from src.core.telemetry import TelemetryLogger
    from src.core.storage_db import StorageManagerDB, get_default_db_path

    db = StorageManagerDB(get_default_db_path())
    logger = TelemetryLogger(db=db)
    logger.log_operation("MOVER", source="ui", success=True, file_count=2)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# Tipo de operação registrável
OperationType = Literal["MOVER", "DELETAR", "UNDO", "SCAN", "SCAN_ERROR"]
# Origem da ação
SourceType = Literal["ui", "ai:ollama", "ai:mcp"]


def _default_log_path() -> Path:
    """Retorna o caminho padrão do arquivo de telemetria."""
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        base = Path(localappdata)
    else:
        base = Path.home() / "AppData" / "Local"
    return base / "GestaoPC" / "telemetry.jsonl"


class TelemetryLogger:
    """
    Logger de telemetria local opt-in.

    Thread-safe: usa threading.Lock para proteger escritas no arquivo.
    Silencioso: qualquer erro de I/O é absorvido — telemetria nunca
    interrompe o fluxo principal da aplicação.

    Parameters
    ----------
    db : StorageManagerDB | None
        Banco de dados para ler a configuração ``telemetry_enabled``.
        Se None, a telemetria é sempre desabilitada.
    log_path : Path | None
        Caminho personalizado para o arquivo JSONL. Padrão: pasta GestaoPC
        dentro de %LOCALAPPDATA%.
    """

    SETTING_KEY = "telemetry_enabled"
    SETTING_VALUE_ON = "true"

    def __init__(
        self,
        db: object | None = None,
        log_path: Path | None = None,
    ) -> None:
        # `db` é tipado como `object | None` em vez de `StorageManagerDB` para
        # evitar import circular; chamadas a métodos do db são protegidas por
        # try/except (Sprint 7.5/7.6).
        self._db = db
        self._log_path = log_path or _default_log_path()
        self._lock = threading.Lock()

    # ──────────────────────────────────────────────────────────────────────────
    # API pública
    # ──────────────────────────────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        """Retorna True se a telemetria está habilitada nas configurações."""
        if self._db is None:
            return False
        try:
            # _db é tipado como object para evitar import circular; o método
            # get_setting() existe via duck-typing em StorageManagerDB.
            value = self._db.get_setting(self.SETTING_KEY)  # type: ignore[attr-defined]
            return bool(value == self.SETTING_VALUE_ON)
        except Exception:
            return False

    def enable(self) -> None:
        """Habilita a telemetria persistindo a configuração no banco."""
        if self._db is not None:
            try:
                self._db.set_setting(self.SETTING_KEY, self.SETTING_VALUE_ON)  # type: ignore[attr-defined]
            except Exception:
                pass

    def disable(self) -> None:
        """Desabilita a telemetria persistindo a configuração no banco."""
        if self._db is not None:
            try:
                self._db.set_setting(self.SETTING_KEY, "false")  # type: ignore[attr-defined]
            except Exception:
                pass

    def log_operation(
        self,
        operation_type: OperationType,
        source: SourceType = "ui",
        success: bool = True,
        file_count: int = 1,
        error_category: str | None = None,
    ) -> None:
        """
        Registra uma operação no log de telemetria.

        A gravação é silenciosa: se o log estiver desabilitado ou ocorrer
        qualquer erro de I/O, o método retorna sem fazer nada.

        Parameters
        ----------
        operation_type : str
            Tipo de operação: "MOVER", "DELETAR", "UNDO", "SCAN", "SCAN_ERROR".
        source : str
            Origem: "ui", "ai:ollama" ou "ai:mcp".
        success : bool
            True se a operação foi bem-sucedida.
        file_count : int
            Número de arquivos processados.
        error_category : str | None
            Categoria de erro sem PII (ex.: "PERMISSION_ERROR", "NOT_FOUND").
            Omitido se None.
        """
        if not self.is_enabled():
            return

        entry: dict = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "op": operation_type,
            "src": source,
            "ok": success,
            "n": file_count,
        }
        if error_category:
            entry["err"] = error_category

        self._write(entry)

    def read_entries(self) -> list[dict]:
        """
        Lê e retorna todas as entradas do arquivo de telemetria.

        Retorna lista vazia se o arquivo não existir ou for ilegível.
        """
        if not self._log_path.exists():
            return []
        try:
            entries = []
            with open(self._log_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            return entries
        except Exception:
            return []

    def clear(self) -> None:
        """Remove o arquivo de telemetria (útil para testes e manutenção)."""
        try:
            if self._log_path.exists():
                self._log_path.unlink()
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────────
    # Internos
    # ──────────────────────────────────────────────────────────────────────────

    def _write(self, entry: dict) -> None:
        """Grava uma entrada no arquivo JSONL de forma thread-safe."""
        with self._lock:
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as exc:
                # Telemetria nunca deve crashar o app — absorver silenciosamente
                logger.debug("Falha ao gravar telemetria: %s", exc)
