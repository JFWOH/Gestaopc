"""
Testes para src.core.config — Sprint 7.6.

Cobre:
  - Todas as constantes esperadas existem com tipos corretos
  - Valores estão dentro de faixas razoáveis (sanity checks)
  - Aliases backward-compat em outros módulos refletem config canônico
"""

from __future__ import annotations

from src.core import config


# ─────────────────────────────────────────────────────────────────────────────
# Existência e tipos
# ─────────────────────────────────────────────────────────────────────────────

class TestScannerConstants:
    def test_scan_min_partition_bytes_is_positive_int(self):
        assert isinstance(config.SCAN_MIN_PARTITION_BYTES, int)
        assert config.SCAN_MIN_PARTITION_BYTES > 0
        # Pelo menos 10 MB; idealmente 100 MB
        assert config.SCAN_MIN_PARTITION_BYTES >= 10 * 1024 * 1024

    def test_scan_top_files_per_disk(self):
        assert isinstance(config.SCAN_TOP_FILES_PER_DISK, int)
        assert 1 <= config.SCAN_TOP_FILES_PER_DISK <= 1000

    def test_scan_top_dirs_per_disk(self):
        assert isinstance(config.SCAN_TOP_DIRS_PER_DISK, int)
        assert 1 <= config.SCAN_TOP_DIRS_PER_DISK <= 1000

    def test_scan_dir_max_depth(self):
        assert isinstance(config.SCAN_DIR_MAX_DEPTH, int)
        assert 1 <= config.SCAN_DIR_MAX_DEPTH <= 10


class TestHashConstants:
    def test_hash_sample_size(self):
        assert isinstance(config.HASH_SAMPLE_SIZE, int)
        # Deve ser uma potência de 2 razoável (1KB–16MB)
        assert 1024 <= config.HASH_SAMPLE_SIZE <= 16 * 1024 * 1024

    def test_hash_full_chunk_size(self):
        assert isinstance(config.HASH_FULL_CHUNK_SIZE, int)
        assert config.HASH_FULL_CHUNK_SIZE > 0
        # E3: 1 MB (era 8 KB) para minimizar iterações/syscalls em arquivos grandes.
        assert 1024 <= config.HASH_FULL_CHUNK_SIZE <= 1024 * 1024

    def test_hash_cache_mtime_tolerance(self):
        assert isinstance(config.HASH_CACHE_MTIME_TOLERANCE, float)
        assert config.HASH_CACHE_MTIME_TOLERANCE >= 0.0
        # Tolerância máxima razoável: 60 segundos
        assert config.HASH_CACHE_MTIME_TOLERANCE <= 60.0


class TestExecutorConstants:
    def test_max_batch_size(self):
        assert isinstance(config.EXECUTOR_MAX_BATCH_SIZE, int)
        assert 1 <= config.EXECUTOR_MAX_BATCH_SIZE <= 1000


class TestAIConstants:
    def test_max_exec_per_minute(self):
        assert isinstance(config.AI_MAX_EXEC_PER_MINUTE, int)
        assert 1 <= config.AI_MAX_EXEC_PER_MINUTE <= 100

    def test_token_ttl_seconds(self):
        assert isinstance(config.AI_TOKEN_TTL_SECONDS, int)
        assert config.AI_TOKEN_TTL_SECONDS > 0


class TestOllamaConstants:
    def test_default_host_is_url(self):
        assert isinstance(config.OLLAMA_DEFAULT_HOST, str)
        assert config.OLLAMA_DEFAULT_HOST.startswith(("http://", "https://"))


class TestLogBridgeConstants:
    def test_max_message_length(self):
        assert isinstance(config.LOG_BRIDGE_MAX_MESSAGE_LENGTH, int)
        assert 50 <= config.LOG_BRIDGE_MAX_MESSAGE_LENGTH <= 10_000


class TestWorkerTimeouts:
    def test_quit_timeout_ms(self):
        assert isinstance(config.WORKER_QUIT_TIMEOUT_MS, int)
        assert config.WORKER_QUIT_TIMEOUT_MS > 0

    def test_cleanup_timeout_ms(self):
        assert isinstance(config.WORKER_CLEANUP_TIMEOUT_MS, int)
        assert 0 < config.WORKER_CLEANUP_TIMEOUT_MS

    def test_restart_timeout_ms(self):
        assert isinstance(config.WORKER_RESTART_TIMEOUT_MS, int)
        assert config.WORKER_RESTART_TIMEOUT_MS > 0

    def test_terminate_timeout_ms(self):
        assert isinstance(config.WORKER_TERMINATE_TIMEOUT_MS, int)
        assert config.WORKER_TERMINATE_TIMEOUT_MS > 0

    def test_cleanup_shorter_than_quit(self):
        """Cleanup pós-finished_response deve ser menor que quit defensivo."""
        assert (
            config.WORKER_CLEANUP_TIMEOUT_MS < config.WORKER_QUIT_TIMEOUT_MS
        )


# ─────────────────────────────────────────────────────────────────────────────
# Aliases backward-compat refletem config
# ─────────────────────────────────────────────────────────────────────────────

class TestBackwardCompatAliases:
    """Garante que aliases em módulos legados ainda batem com config."""

    def test_analyzer_sample_size_alias(self):
        from src.core import analyzer
        assert analyzer._SAMPLE_SIZE == config.HASH_SAMPLE_SIZE

    def test_executor_max_batch_size_alias(self):
        from src.core.executor import MAX_BATCH_SIZE
        assert MAX_BATCH_SIZE == config.EXECUTOR_MAX_BATCH_SIZE

    def test_ai_toolbelt_max_exec_alias(self):
        from src.core import ai_toolbelt
        assert ai_toolbelt._MAX_EXEC_PER_MINUTE == config.AI_MAX_EXEC_PER_MINUTE
        assert ai_toolbelt._TOKEN_TTL_SECONDS == config.AI_TOKEN_TTL_SECONDS

    def test_log_bridge_max_message_length_alias(self):
        from src.gui import log_bridge
        assert log_bridge._MAX_MESSAGE_LENGTH == config.LOG_BRIDGE_MAX_MESSAGE_LENGTH


# ─────────────────────────────────────────────────────────────────────────────
# Smoke: módulo é importável sem PySide6
# ─────────────────────────────────────────────────────────────────────────────

class TestPureCore:
    def test_config_does_not_import_pyside(self):
        """src/core/config.py deve ser stdlib-only — importável em qualquer contexto."""
        import sys
        # Capturar módulos antes do import
        before = set(sys.modules)
        # Forçar reimport do config
        if "src.core.config" in sys.modules:
            del sys.modules["src.core.config"]
        from src.core import config as _cfg  # noqa: F401
        after = set(sys.modules)

        new_modules = after - before
        # Nenhum novo módulo de PySide6 / Qt deve ter sido carregado
        for m in new_modules:
            assert not m.startswith("PySide6"), (
                f"config.py importou {m} indiretamente — deve ser stdlib-only"
            )
            assert not m.startswith("PyQt6"), (
                f"config.py importou {m} indiretamente"
            )
