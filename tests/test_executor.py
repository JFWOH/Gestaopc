"""
Testes para src.core.executor — SafeFileExecutor + FileAction.

Cobre:
  - move_file() com arquivos reais
  - delete_file() (permanente)
  - undo_last_move()
  - Colisão de nomes (_unique_path)
  - Resiliência a erros de permissão
  - Histórico de operações
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.executor import (
    SafeFileExecutor,
    OperationRecord,
    FileAction,
)


# ---------------------------------------------------------------------------
# SafeFileExecutor.move_file()
# ---------------------------------------------------------------------------

class TestMoveFile:
    """Testa movimentação segura de arquivos."""

    def test_moves_file_successfully(self, tmp_path: Path):
        src = tmp_path / "source.txt"
        src.write_bytes(b"conteudo original")
        dst = tmp_path / "destino" / "moved.txt"

        executor = SafeFileExecutor()
        record = executor.move_file(str(src), str(dst))

        assert record.success is True
        assert record.action == "MOVER"
        assert not src.exists(), "Arquivo de origem deve ser removido"
        assert dst.exists(), "Arquivo de destino deve existir"
        assert dst.read_bytes() == b"conteudo original"

    def test_creates_destination_dir(self, tmp_path: Path):
        src = tmp_path / "file.txt"
        src.write_bytes(b"dados")
        dst = tmp_path / "a" / "b" / "c" / "file.txt"

        executor = SafeFileExecutor()
        record = executor.move_file(str(src), str(dst))

        assert record.success is True
        assert dst.exists()
        assert dst.parent.exists()

    def test_handles_name_collision(self, tmp_path: Path):
        src = tmp_path / "file.txt"
        src.write_bytes(b"novo conteudo")

        # Criar arquivo no destino com mesmo nome
        dst = tmp_path / "destino" / "file.txt"
        dst.parent.mkdir()
        dst.write_bytes(b"conteudo existente")

        executor = SafeFileExecutor()
        record = executor.move_file(str(src), str(dst))

        assert record.success is True
        # O destino original deve ser preservado
        assert (tmp_path / "destino" / "file.txt").read_bytes() == b"conteudo existente"
        # O novo arquivo deve ter sufixo numérico
        moved_path = Path(record.target_path)
        assert moved_path.exists()
        assert "file_1" in moved_path.name

    def test_fails_for_nonexistent_source(self, tmp_path: Path):
        executor = SafeFileExecutor()
        record = executor.move_file(
            str(tmp_path / "nao_existe.txt"),
            str(tmp_path / "destino.txt"),
        )

        assert record.success is False
        assert "não encontrado" in record.error or "not found" in record.error.lower() or "encontrado" in record.error

    def test_appends_to_history(self, tmp_path: Path):
        src = tmp_path / "a.txt"
        src.write_bytes(b"dados")

        executor = SafeFileExecutor()
        executor.move_file(str(src), str(tmp_path / "b.txt"))

        assert len(executor.history) == 1
        assert executor.history[0].action == "MOVER"


# ---------------------------------------------------------------------------
# SafeFileExecutor.delete_file()
# ---------------------------------------------------------------------------

class TestDeleteFile:
    """Testa deleção segura de arquivos."""

    def test_deletes_file_permanently(self, tmp_path: Path):
        target = tmp_path / "to_delete.txt"
        target.write_bytes(b"deletar este")

        executor = SafeFileExecutor()
        record = executor.delete_file(str(target), permanent=True)

        assert record.success is True
        assert record.action == "DELETAR"
        assert not target.exists()

    def test_fails_for_nonexistent_file(self, tmp_path: Path):
        executor = SafeFileExecutor()
        record = executor.delete_file(str(tmp_path / "fantasma.txt"))

        assert record.success is False
        assert "encontrado" in record.error.lower() or "not found" in record.error.lower()

    def test_appends_to_history(self, tmp_path: Path):
        target = tmp_path / "file.txt"
        target.write_bytes(b"x")

        executor = SafeFileExecutor()
        executor.delete_file(str(target), permanent=True)

        assert len(executor.history) == 1


# ---------------------------------------------------------------------------
# undo_last_move()
# ---------------------------------------------------------------------------

class TestUndoLastMove:
    """Testa desfazer última movimentação."""

    def test_undoes_last_move(self, tmp_path: Path):
        src = tmp_path / "original.txt"
        src.write_bytes(b"conteudo")
        dst = tmp_path / "movido.txt"

        executor = SafeFileExecutor()
        executor.move_file(str(src), str(dst))

        assert dst.exists()
        assert not src.exists()

        # Desfazer
        undo_record = executor.undo_last_move()

        assert undo_record is not None
        assert undo_record.success is True
        assert src.exists(), "Arquivo original deve ser restaurado"
        assert not dst.exists(), "Arquivo movido deve ser removido"

    def test_returns_none_when_no_moves(self):
        executor = SafeFileExecutor()
        result = executor.undo_last_move()
        assert result is None

    def test_returns_none_when_only_deletes(self, tmp_path: Path):
        target = tmp_path / "file.txt"
        target.write_bytes(b"x")

        executor = SafeFileExecutor()
        executor.delete_file(str(target), permanent=True)

        result = executor.undo_last_move()
        assert result is None


# ---------------------------------------------------------------------------
# _unique_path()
# ---------------------------------------------------------------------------

class TestUniquePath:
    """Testa geração de caminhos únicos para colisão de nomes."""

    def test_increments_suffix(self, tmp_path: Path):
        base = tmp_path / "file.txt"
        base.write_bytes(b"original")

        result = SafeFileExecutor._unique_path(base)
        assert result.name == "file_1.txt"

        # Criar file_1 também
        result.write_bytes(b"second")
        result2 = SafeFileExecutor._unique_path(base)
        assert result2.name == "file_2.txt"

    def test_preserves_extension(self, tmp_path: Path):
        base = tmp_path / "video.mkv"
        base.write_bytes(b"video data")

        result = SafeFileExecutor._unique_path(base)
        assert result.suffix == ".mkv"

    def test_returns_same_if_not_exists(self, tmp_path: Path):
        base = tmp_path / "new_file.txt"
        # Não existe → _unique_path entra no while, mas Path.exists() é False
        # A implementação testa while path.exists(), então se não existe, retorna o mesmo
        # Mas o parâmetro 'path' é reatribuído, vamos ver...
        # Na verdade, o método só é chamado quando o path JÁ existe
        # Mas vamos testar o caso limítrofe
        # Se não existe, o while não executa e retorna path com counter=1 nunca executado
        # Ah wait, reler o código: ele faz path = parent / f"{stem}_{counter}" DENTRO do while
        # Portanto se path.exists() é False, retorna path inalterado
        result = SafeFileExecutor._unique_path(base)
        assert result == base


# ---------------------------------------------------------------------------
# Propriedades filtradas
# ---------------------------------------------------------------------------

class TestExecutorProperties:
    """Testa propriedades de histórico filtrado."""

    def test_successful_operations(self, tmp_path: Path):
        executor = SafeFileExecutor()

        # 1 sucesso
        f = tmp_path / "ok.txt"
        f.write_bytes(b"ok")
        executor.delete_file(str(f), permanent=True)

        # 1 falha
        executor.delete_file(str(tmp_path / "nao_existe.txt"))

        assert len(executor.successful_operations) == 1
        assert len(executor.failed_operations) == 1

    def test_operation_record_timestamp_str(self):
        import time
        record = OperationRecord(
            timestamp=time.time(),
            action="DELETAR",
            source_path="C:\\file.txt",
            success=True,
        )
        ts = record.timestamp_str
        assert len(ts) > 0
        assert "-" in ts  # formato YYYY-MM-DD

    def test_operation_record_repr(self):
        record = OperationRecord(
            timestamp=0,
            action="MOVER",
            source_path="C:\\source.txt",
            target_path="D:\\dest.txt",
            success=True,
        )
        r = repr(record)
        assert "MOVER" in r
        assert "OK" in r


# ---------------------------------------------------------------------------
# FileAction dataclass
# ---------------------------------------------------------------------------

class TestFileAction:
    def test_defaults(self):
        a = FileAction(action="DELETAR", source_path="C:\\file.txt")
        assert a.action == "DELETAR"
        assert a.target_path == ""


# ---------------------------------------------------------------------------
# Sprint 6 — Hardening: path guard integration
# ---------------------------------------------------------------------------

class TestPathGuardInExecutor:
    """Garante que executor.py rejeita caminhos inválidos antes de tocar no disco."""

    def test_move_rejects_relative_source(self, tmp_path: Path):
        executor = SafeFileExecutor()
        record = executor.move_file("relative/path.txt", str(tmp_path / "dest.txt"))
        assert record.success is False
        assert "relativo" in record.error.lower() or "invalid" in record.error.lower() or "inválido" in record.error.lower()

    def test_move_rejects_relative_destination(self, tmp_path: Path):
        src = tmp_path / "file.txt"
        src.write_bytes(b"data")
        executor = SafeFileExecutor()
        record = executor.move_file(str(src), "relative/dest.txt")
        assert record.success is False
        assert record.error

    def test_move_rejects_protected_source(self, tmp_path: Path):
        executor = SafeFileExecutor()
        record = executor.move_file(
            "C:\\Windows\\System32\\kernel32.dll",
            str(tmp_path / "kernel32.dll"),
        )
        assert record.success is False
        assert record.error

    def test_move_rejects_protected_destination(self, tmp_path: Path):
        src = tmp_path / "file.txt"
        src.write_bytes(b"data")
        executor = SafeFileExecutor()
        record = executor.move_file(str(src), "C:\\Windows\\malware.exe")
        assert record.success is False
        assert record.error

    def test_delete_rejects_relative_path(self):
        executor = SafeFileExecutor()
        record = executor.delete_file("relative/path.txt")
        assert record.success is False
        assert record.error

    def test_delete_rejects_protected_file(self):
        executor = SafeFileExecutor()
        record = executor.delete_file("C:\\Windows\\System32\\ntdll.dll")
        assert record.success is False
        assert record.error

    def test_invalid_path_appended_to_history(self):
        """Mesmo ao rejeitar, o record deve ser adicionado ao histórico."""
        executor = SafeFileExecutor()
        executor.delete_file("relative/path.txt")
        assert len(executor.history) == 1
        assert executor.history[0].success is False


# ---------------------------------------------------------------------------
# Sprint 6 — Hardening: batch size cap
# ---------------------------------------------------------------------------

class TestBatchSizeCap:
    """Garante a constante e a lógica de rejeição de batch excessivo."""

    def test_max_batch_size_constant_exists(self):
        from src.core.executor import MAX_BATCH_SIZE
        assert isinstance(MAX_BATCH_SIZE, int)
        assert MAX_BATCH_SIZE >= 10, "Limite de batch deve ser pelo menos 10"
        assert MAX_BATCH_SIZE <= 500, "Limite de batch deve ser razoável (≤ 500)"

    def test_max_batch_size_is_50(self):
        from src.core.executor import MAX_BATCH_SIZE
        assert MAX_BATCH_SIZE == 50

    def test_worker_constructor_stores_actions(self, tmp_path: Path):
        """FileActionWorker armazena as ações corretamente."""
        from src.core.executor import FileActionWorker, MAX_BATCH_SIZE
        actions = [
            FileAction(action="DELETAR", source_path=str(tmp_path / f"f{i}.txt"))
            for i in range(3)
        ]
        worker = FileActionWorker(actions)
        # Verificar que as ações foram armazenadas (acesso ao atributo interno)
        assert len(worker._actions) == 3

    def test_oversized_batch_produces_failure_records(self, tmp_path: Path):
        """
        Simula a lógica de rejeição sem rodar o QThread.

        Verifica que n > MAX_BATCH_SIZE ações geram n OperationRecords de falha.
        Abordagem: instanciar o worker e chamar run() diretamente em mock.
        """
        from src.core.executor import FileActionWorker, MAX_BATCH_SIZE
        import time as _time

        n = MAX_BATCH_SIZE + 1
        actions = [
            FileAction(action="DELETAR", source_path=str(tmp_path / f"f{i}.txt"))
            for i in range(n)
        ]

        # Interceptar o sinal finished_all via monkey-patch
        collected: list = []

        worker = FileActionWorker(actions)
        # Substituir emissão do sinal por coleta direta para evitar QApplication
        worker.finished_all = type(
            "_FakeSignal", (), {
                "emit": staticmethod(lambda results: collected.extend(results)),
                "connect": staticmethod(lambda *a: None),
            }
        )()
        worker.progress = type(
            "_FakeSignal", (), {
                "emit": staticmethod(lambda *a: None),
                "connect": staticmethod(lambda *a: None),
            }
        )()
        worker.progress_percent = type(
            "_FakeSignal", (), {
                "emit": staticmethod(lambda *a: None),
                "connect": staticmethod(lambda *a: None),
            }
        )()
        worker.action_completed = type(
            "_FakeSignal", (), {
                "emit": staticmethod(lambda *a: None),
                "connect": staticmethod(lambda *a: None),
            }
        )()

        worker.run()  # chamada direta sem thread

        assert len(collected) == n
        assert all(not r.success for r in collected)
        assert all(
            "limite" in r.error.lower() or "batch" in r.error.lower()
            for r in collected
        )
