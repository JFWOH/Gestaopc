"""
Workers — QThreads para operações pesadas de I/O.

Cada worker emite sinais de progresso e resultado para a GUI
sem bloquear o event loop do Qt. Referência: spec seção 6.4.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

from PyQt6.QtCore import QThread, pyqtSignal

from src.core.scanner import StorageScanner, FileEntry, PartitionInfo, DirEntry
from src.core.analyzer import (
    DuplicateDetector,
    DuplicateGroup,
    SmartRulesEngine,
    ReallocationSuggestion,
)
from src.core.storage_db import StorageManagerDB, get_default_db_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data class que agrupa todos os resultados de uma varredura completa
# ---------------------------------------------------------------------------

@dataclass
class ScanResult:
    """Container com todos os resultados de uma varredura completa."""
    partitions: list[PartitionInfo] = field(default_factory=list)
    top_files: list[FileEntry] = field(default_factory=list)
    top_dirs: list[DirEntry] = field(default_factory=list)
    duplicates: list[DuplicateGroup] = field(default_factory=list)
    suggestions: list[ReallocationSuggestion] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# Worker de Varredura Completa
# ---------------------------------------------------------------------------

class FullScanWorker(QThread):
    """
    Thread que executa a pipeline completa:
      1. list_partitions()    → mapeia discos
      2. top_largest_files()  → varre pastas do usuário de cada disco
      3. find_duplicates()    → detecta duplicatas
      4. evaluate_batch()     → gera sugestões do motor de regras

    Signals
    -------
    progress(str)
        Mensagem de status intermediário para a barra de status.
    progress_percent(int)
        Porcentagem de progresso (0–100).
    finished_result(ScanResult)
        Emitido quando a varredura termina (sucesso ou erro).
    """

    progress = pyqtSignal(str)
    progress_percent = pyqtSignal(int)
    finished_result = pyqtSignal(object)  # ScanResult

    def __init__(self, parent=None):
        super().__init__(parent)
        self._abort = False

    def abort(self):
        """Sinaliza para a thread parar na próxima oportunidade."""
        self._abort = True

    def run(self):
        """Executa a pipeline completa em background."""
        result = ScanResult()
        start = time.perf_counter()
        
        # Conexão própria para esta thread
        db = StorageManagerDB(get_default_db_path())
        db.initialize()
        
        session_id = db.create_scan_session(started_at=time.time(), scan_mode="full")
        total_files = 0
        total_bytes = 0

        try:
            scanner = StorageScanner()

            # ── Etapa 1: Mapear partições ───────────────────────────
            self.progress.emit("Mapeando particoes...")
            self.progress_percent.emit(5)
            result.partitions = scanner.list_partitions()
            logger.info("Particoes mapeadas: %d", len(result.partitions))

            if self._abort:
                return

            # ── Etapa 2: Varrer maiores arquivos de cada disco ──────
            self.progress.emit("Varrendo discos (maiores arquivos)...")
            self.progress_percent.emit(10)

            all_files: list[FileEntry] = []
            scannable = [
                p for p in result.partitions
                if p.total_bytes > 1024 * 1024 * 100  # Ignorar partições minúsculas (<100MB)
            ]

            for idx, part in enumerate(scannable):
                if self._abort:
                    return

                pct = 10 + int((idx / max(len(scannable), 1)) * 50)
                self.progress.emit(f"Varrendo {part.letter} ({idx+1}/{len(scannable)})...")
                self.progress_percent.emit(pct)

                try:
                    # Estratégia otimizada: varrer subdiretórios prioritários
                    # em vez de os.walk na raiz inteira (que leva horas em discos de TB).
                    scan_targets = self._get_scan_targets(part.letter)
                    for target in scan_targets:
                        if self._abort:
                            return
                        try:
                            files = scanner.top_largest_files(target, n=50)
                            all_files.extend(files)
                        except Exception as exc:
                            logger.debug("Erro em subdir %s: %s", target, exc)
                except Exception as exc:
                    logger.warning(
                        "Erro ao varrer %s: %s — continuando.", part.letter, exc
                    )

            # Consolidar top 50 global de todos os discos.
            all_files.sort(key=lambda f: f.size_bytes, reverse=True)
            result.top_files = all_files[:50]
            
            total_files = len(all_files)
            total_bytes = sum(f.size_bytes for f in all_files)
            
            logger.info("Top files global: %d entradas.", len(result.top_files))

            if self._abort:
                return

            # ── Etapa 2.5: Top pastas consumidoras ───────────────────
            self.progress.emit("Analisando pastas mais pesadas...")
            self.progress_percent.emit(62)

            all_dirs: list[DirEntry] = []
            for idx, part in enumerate(scannable):
                if self._abort:
                    return
                try:
                    scan_targets = self._get_scan_targets(part.letter)
                    for target in scan_targets:
                        if self._abort:
                            return
                        try:
                            dirs = scanner.top_largest_dirs(target, n=20, max_depth=2)
                            all_dirs.extend(dirs)
                        except Exception as exc:
                            logger.debug("Erro ao listar dirs de %s: %s", target, exc)
                except Exception as exc:
                    logger.debug("Erro ao analisar pastas de %s: %s", part.letter, exc)

            all_dirs.sort(key=lambda d: d.total_size_bytes, reverse=True)
            result.top_dirs = all_dirs[:20]
            logger.info("Top dirs global: %d entradas.", len(result.top_dirs))

            if self._abort:
                return

            # ── Etapa 3: Detectar duplicatas ────────────────────────
            self.progress.emit("Analisando duplicatas...")
            self.progress_percent.emit(65)

            detector = DuplicateDetector()
            result.duplicates = detector.find_duplicates(all_files)
            logger.info("Duplicatas: %d grupos.", len(result.duplicates))

            if self._abort:
                return

            # ── Etapa 4: Motor de regras ────────────────────────────
            self.progress.emit("Avaliando regras de realocacao...")
            self.progress_percent.emit(85)

            engine = SmartRulesEngine()
            result.suggestions = engine.evaluate_batch(
                result.top_files,
                result.partitions,
                result.duplicates,
            )
            
            # -- Persistir Resultados no DB --
            db.clear_suggestions()
            for sugg in result.suggestions:
                db.insert_suggestion(
                    scan_session_id=session_id,
                    rule_id=sugg.rule_id,
                    rule_name=sugg.rule_name,
                    file_path=sugg.file_path,
                    action=sugg.action,
                    detail=sugg.detail,
                    target_disk=sugg.target_disk,
                    priority=sugg.priority,
                    created_at=time.time()
                )
            
            for f in result.top_files:
                drive_letter = f.path[:2] if len(f.path) >= 2 and f.path[1] == ':' else None
                db.upsert_file_index(
                    path=f.path,
                    disk_letter=drive_letter,
                    size_bytes=f.size_bytes,
                    mtime=f.modified_time,
                    category=f.category,
                    last_seen=time.time()
                )
                
            logger.info("Sugestoes geradas: %d.", len(result.suggestions))

            self.progress_percent.emit(100)
            self.progress.emit("Varredura concluida!")

        except Exception as exc:
            logger.exception("Erro fatal durante a varredura.")
            result.error = str(exc)
            self.progress.emit(f"ERRO: {exc}")

        finally:
            result.elapsed_seconds = time.perf_counter() - start
            
            db.finish_scan_session(
                session_id,
                elapsed_seconds=result.elapsed_seconds,
                total_files_seen=total_files,
                total_bytes_seen=total_bytes,
                error=result.error
            )
            db.close()
            
            self.finished_result.emit(result)

    # ---- Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _get_scan_targets(drive_letter: str) -> list[str]:
        """
        Retorna diretórios prioritários para varredura em um disco.

        Estratégia:
          - Disco C: → varrer apenas pastas do usuário (Downloads, Desktop, etc.)
          - Outros discos → varrer subdiretórios de 1o nível (não recursivo na raiz)

        Isso evita os.walk percorrer milhões de arquivos em discos de 3TB.
        """
        root = f"{drive_letter}\\"

        if drive_letter.upper() == "C:":
            # No C:, focar nas pastas do usuário atual.
            user_home = os.path.expanduser("~")
            user_dirs = [
                os.path.join(user_home, d)
                for d in [
                    "Downloads", "Desktop", "Documents", "Videos",
                    "Music", "Pictures", "OneDrive",
                ]
            ]
            return [d for d in user_dirs if os.path.isdir(d)]

        # Para outros discos, listar subdiretórios de 1o nível.
        # Cada subdir será varrido recursivamente pelo scanner.
        targets = []
        try:
            for entry in os.scandir(root):
                if entry.is_dir(follow_symlinks=False):
                    # Pular pastas de sistema e reciclagem.
                    if entry.name.startswith(("$", "System")):
                        continue
                    targets.append(entry.path)
        except (PermissionError, OSError) as exc:
            logger.debug("Nao foi possivel listar %s: %s", root, exc)

        # Se nenhum subdir acessível, varrer a raiz como fallback.
        return targets if targets else [root]
