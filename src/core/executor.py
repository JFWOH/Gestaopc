"""
Executor — Operações de arquivo seguras (Mover / Deletar).

Implementa executores para as ações sugeridas pelo Motor de Regras (Seção 3.4)
e pela aba de Duplicatas.

Princípios de segurança:
  • Deleção por padrão envia para a Lixeira do Windows (send2trash).
  • Toda operação é registrada em log (undo log serializável).
  • Erros de permissão (AV / Kaspersky) são tratados graciosamente.
  • Um QThread (FileActionWorker) permite execução sem travar a GUI.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# PySide6 é necessário apenas para FileActionWorker (QThread de GUI).
# O import é defensivo para que executor.py seja importável em contextos
# headless (MCP server, scripts CLI, .venv sem Qt) onde PySide6 não está
# instalado. SafeFileExecutor e todos os helpers puros não dependem de Qt.
try:
    from PySide6.QtCore import QThread, Signal
    _HAS_PYSIDE6 = True
except ImportError:  # ambiente headless (MCP server, CLI, etc.)
    _HAS_PYSIDE6 = False

from src.core.config import EXECUTOR_MAX_BATCH_SIZE
from src.core.storage_db import StorageManagerDB
from src.core.path_guard import validate_path

logger = logging.getLogger(__name__)

# Limite máximo de arquivos em uma única operação em batch.
# Protege contra loops infinitos ou ações acidentais em grande escala.
# Sprint 7.6: valor canônico em src/core/config.py; alias mantido para
# compatibilidade com tests que checam `from src.core.executor import MAX_BATCH_SIZE`.
MAX_BATCH_SIZE: int = EXECUTOR_MAX_BATCH_SIZE

# Tentar importar send2trash para deleção segura (Lixeira).
try:
    from send2trash import send2trash as _send2trash

    _HAS_SEND2TRASH = True
except ImportError:
    _HAS_SEND2TRASH = False
    logger.warning(
        "Pacote 'send2trash' não encontrado. "
        "Deleção de arquivos será PERMANENTE (sem Lixeira)."
    )


# ---------------------------------------------------------------------------
# Registro de operação (undo log)
# ---------------------------------------------------------------------------

@dataclass
class OperationRecord:
    """Registro de uma operação executada (para auditoria / undo)."""
    timestamp: float
    action: Literal["MOVER", "DELETAR"]
    source_path: str
    target_path: str = ""       # Preenchido apenas para MOVER
    success: bool = False
    error: str = ""
    used_trash: bool = False    # True se foi para a Lixeira

    @property
    def timestamp_str(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp))

    def __repr__(self) -> str:
        status = "OK" if self.success else f"FALHA: {self.error}"
        return (
            f"<Op [{self.action}] {Path(self.source_path).name} "
            f"→ {self.target_path or 'Lixeira'} | {status}>"
        )


# ---------------------------------------------------------------------------
# SafeFileExecutor
# ---------------------------------------------------------------------------

class SafeFileExecutor:
    """
    Executor seguro de operações de arquivo.

    Uso::

        executor = SafeFileExecutor()
        record = executor.move_file("C:/a.mkv", "D:/Videos/a.mkv")
        record = executor.delete_file("C:/copia.txt")
        print(executor.history)
    """

    def __init__(self, db: StorageManagerDB | None = None):
        self.history: list[OperationRecord] = []
        self._db = db

    def _persist_record(self, record: OperationRecord) -> None:
        """Persiste o OperationRecord no banco de dados, se configurado."""
        if self._db is None:
            return
        self._db.insert_operation(
            timestamp=record.timestamp,
            action=record.action,
            source_path=record.source_path,
            target_path=record.target_path,
            success=record.success,
            error=record.error or "",
            used_trash=record.used_trash,
        )

    def move_file(self, source: str, target: str) -> OperationRecord:
        """
        Move um arquivo de `source` para `target`.

        Cria diretórios intermediários automaticamente. Preserva metadados.
        Se já existir arquivo no destino, adiciona sufixo numérico.

        Parameters
        ----------
        source : str
            Caminho completo do arquivo de origem.
        target : str
            Caminho completo do destino (incluindo nome do arquivo).

        Returns
        -------
        OperationRecord com o resultado da operação.
        """
        record = OperationRecord(
            timestamp=time.time(),
            action="MOVER",
            source_path=source,
            target_path=target,
        )

        # Validar caminhos antes de qualquer operação de I/O
        for label, path_str in (("origem", source), ("destino", target)):
            ok, err = validate_path(path_str)
            if not ok:
                record.error = f"Caminho de {label} inválido: {err}"
                logger.warning("Move bloqueado — %s", record.error)
                self.history.append(record)
                return record

        try:
            src = Path(source)
            if not src.exists():
                record.error = "Arquivo de origem não encontrado."
                logger.error("Move falhou — arquivo não existe: %s", source)
                self.history.append(record)
                return record

            # Criar diretório de destino se não existir.
            dst = Path(target)
            dst.parent.mkdir(parents=True, exist_ok=True)

            # Evitar sobrescrever: se destino existe, adicionar sufixo.
            if dst.exists():
                dst = self._unique_path(dst)
                record.target_path = str(dst)

            shutil.move(str(src), str(dst))
            record.success = True
            logger.info("Arquivo movido: %s → %s", source, dst)

        except PermissionError as exc:
            record.error = f"Sem permissão (possível bloqueio de antivírus): {exc}"
            logger.warning("PermissionError ao mover %s: %s", source, exc)
        except OSError as exc:
            record.error = f"Erro de I/O: {exc}"
            logger.error("OSError ao mover %s: %s", source, exc)
        except Exception as exc:
            record.error = f"Erro inesperado: {exc}"
            logger.exception("Erro inesperado ao mover %s", source)

        self.history.append(record)
        self._persist_record(record)
        return record

    def delete_file(self, filepath: str, permanent: bool = False) -> OperationRecord:
        """
        Deleta um arquivo, enviando para a Lixeira quando possível.

        Parameters
        ----------
        filepath : str
            Caminho completo do arquivo a deletar.
        permanent : bool
            Se True, força deleção permanente mesmo com send2trash disponível.

        Returns
        -------
        OperationRecord com o resultado da operação.
        """
        record = OperationRecord(
            timestamp=time.time(),
            action="DELETAR",
            source_path=filepath,
        )

        # Validar caminho antes de qualquer operação de I/O
        ok, err = validate_path(filepath)
        if not ok:
            record.error = f"Caminho inválido: {err}"
            logger.warning("Delete bloqueado — %s", record.error)
            self.history.append(record)
            return record

        try:
            p = Path(filepath)
            if not p.exists():
                record.error = "Arquivo não encontrado."
                logger.error("Delete falhou — arquivo não existe: %s", filepath)
                self.history.append(record)
                return record

            if permanent:
                os.remove(filepath)
                record.success = True
                logger.info("Arquivo deletado permanentemente: %s", filepath)
            elif _HAS_SEND2TRASH:
                _send2trash(filepath)
                record.used_trash = True
                record.success = True
                logger.info("Arquivo enviado à Lixeira: %s", filepath)
            else:
                # Hardening S10: usuário pediu Lixeira (reversível) mas send2trash
                # está ausente — recusar em vez de deletar PERMANENTEMENTE sem
                # querer. Para deleção definitiva, usar permanent=True explícito.
                record.error = (
                    "send2trash indisponível — deleção recusada para evitar "
                    "perda permanente. Use permanent=True para deletar de vez."
                )
                logger.warning("Delete recusado (send2trash ausente): %s", filepath)

        except PermissionError as exc:
            record.error = f"Sem permissão (possível bloqueio de antivírus): {exc}"
            logger.warning("PermissionError ao deletar %s: %s", filepath, exc)
        except OSError as exc:
            record.error = f"Erro de I/O: {exc}"
            logger.error("OSError ao deletar %s: %s", filepath, exc)
        except Exception as exc:
            record.error = f"Erro inesperado: {exc}"
            logger.exception("Erro inesperado ao deletar %s", filepath)

        self.history.append(record)
        self._persist_record(record)
        return record

    def undo_last_move(self) -> OperationRecord | None:
        """
        Desfaz a última operação de MOVER bem-sucedida.

        Retorna None se não houver operação para desfazer.
        """
        for record in reversed(self.history):
            if record.action == "MOVER" and record.success:
                # Inverter: mover de volta de target para source.
                return self.move_file(record.target_path, record.source_path)
        return None

    @property
    def successful_operations(self) -> list[OperationRecord]:
        return [r for r in self.history if r.success]

    @property
    def failed_operations(self) -> list[OperationRecord]:
        return [r for r in self.history if not r.success]

    # ---- Helpers -----------------------------------------------------------

    @staticmethod
    def _unique_path(path: Path) -> Path:
        """Gera um caminho único adicionando sufixo numérico."""
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        counter = 1
        while path.exists():
            path = parent / f"{stem}_{counter}{suffix}"
            counter += 1
        return path


# ---------------------------------------------------------------------------
# FileActionWorker — QThread para execução em batch
# ---------------------------------------------------------------------------

@dataclass
class FileAction:
    """Define uma ação para o worker executar."""
    action: Literal["MOVER", "DELETAR"]
    source_path: str
    target_path: str = ""


if _HAS_PYSIDE6:
    class FileActionWorker(QThread):  # type: ignore[misc]
        """
        Thread para executar uma lista de ações de arquivo em background.

        Disponível apenas quando PySide6 está instalado (ambiente GUI).
        Em contextos headless (MCP server, CLI) este bloco é ignorado.

        Signals
        -------
        progress(str)
            Mensagem de status intermediário.
        progress_percent(int)
            Porcentagem de progresso (0–100).
        action_completed(OperationRecord)
            Emitido após cada ação individual.
        finished_all(list[OperationRecord])
            Emitido quando todas as ações terminam.
        """

        progress = Signal(str)
        progress_percent = Signal(int)
        action_completed = Signal(object)     # OperationRecord
        finished_all = Signal(object)         # list[OperationRecord]

        def __init__(self, actions: list[FileAction], db: StorageManagerDB | None = None, parent=None):
            super().__init__(parent)
            self._actions = actions
            self._abort = False
            self._executor = SafeFileExecutor(db=db)

        def abort(self):
            """Sinaliza para a thread parar na próxima oportunidade."""
            self._abort = True

        def run(self):
            """Executa todas as ações em sequência."""
            results: list[OperationRecord] = []
            total = len(self._actions)

            # Proteção contra batches excessivamente grandes
            if total > MAX_BATCH_SIZE:
                err_msg = (
                    f"Batch de {total} ações excede o limite de {MAX_BATCH_SIZE}. "
                    "Divida em operações menores."
                )
                logger.warning(err_msg)
                for action in self._actions:
                    results.append(
                        OperationRecord(
                            timestamp=time.time(),
                            action=action.action,
                            source_path=action.source_path,
                            target_path=action.target_path,
                            success=False,
                            error=err_msg,
                        )
                    )
                self.progress.emit(err_msg)
                self.finished_all.emit(results)
                return

            for idx, action in enumerate(self._actions):
                if self._abort:
                    break

                pct = int(((idx + 1) / max(total, 1)) * 100)
                name = Path(action.source_path).name
                self.progress.emit(f"[{idx+1}/{total}] {action.action}: {name}")
                self.progress_percent.emit(pct)

                if action.action == "MOVER":
                    record = self._executor.move_file(action.source_path, action.target_path)
                else:
                    record = self._executor.delete_file(action.source_path)

                results.append(record)
                self.action_completed.emit(record)

            self.progress.emit("Operacoes concluidas.")
            self.finished_all.emit(results)

        @property
        def executor(self) -> SafeFileExecutor:
            return self._executor
