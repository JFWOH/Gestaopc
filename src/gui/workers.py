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

from PySide6.QtCore import QThread, Signal

from src.core.scanner import StorageScanner, FileEntry, PartitionInfo, DirEntry
from src.core.analyzer import (
    DuplicateDetector,
    DuplicateGroup,
    SmartRulesEngine,
    ReallocationSuggestion,
)
from src.core.storage_db import StorageManagerDB, get_default_db_path
from src.core.hash_cache import InMemoryHashCache
from src.core.config import (
    HASH_CACHE_MTIME_TOLERANCE,
    SCAN_DIR_MAX_DEPTH,
    SCAN_MIN_PARTITION_BYTES,
    SCAN_TOP_DIRS_PER_DISK,
    SCAN_TOP_FILES_PER_DISK,
)

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
    progress_indeterminate(bool)
        True → operação longa sem progresso mensurável (spinner busy).
        False → retomar barra determinística normal.
    finished_result(ScanResult)
        Emitido quando a varredura termina (sucesso ou erro).
    """

    progress = Signal(str)
    progress_percent = Signal(int)
    progress_indeterminate = Signal(bool)
    finished_result = Signal(object)  # ScanResult
    # Resultado PRELIMINAR emitido logo após a Etapa 2 (listagem), antes da
    # detecção de duplicatas (lenta). Carrega partitions/top_files/top_dirs;
    # duplicates/suggestions ainda vazios. Permite popular as abas em segundos
    # em vez de esperar minutos pela fase de hash SHA-256.
    partial_result = Signal(object)  # ScanResult parcial

    # Sprint 7.1 — Painel de status por disco
    partitions_detected = Signal(list)         # list[PartitionInfo] varredores
    disk_state_changed = Signal(str, str, str) # letter, status, stage_label
    global_stage_changed = Signal(str)         # estágio não-per-disk

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
            map_msg = "Mapeando particoes..."
            self.progress.emit(map_msg)
            self.global_stage_changed.emit(map_msg)
            self.progress_percent.emit(5)
            result.partitions = scanner.list_partitions()
            logger.info("Particoes mapeadas: %d", len(result.partitions))

            if self._abort:
                return

            # ── Etapa 2: Varrer maiores arquivos+pastas por disco ───
            # Sprint 7.1: combinamos as duas passagens (files + dirs) em
            # um único loop por disco para que o painel de status mostre
            # cada disco progredindo de pendente → em curso → concluído.
            self.progress.emit("Varrendo discos...")
            self.progress_percent.emit(10)

            all_files: list[FileEntry] = []
            all_dirs: list[DirEntry] = []
            scannable = [
                p for p in result.partitions
                if p.total_bytes > SCAN_MIN_PARTITION_BYTES
            ]

            # Inicializa o painel com todos os discos no estado "pending".
            self.partitions_detected.emit(scannable)
            for part in scannable:
                self.disk_state_changed.emit(part.letter, "pending", "")

            for idx, part in enumerate(scannable):
                if self._abort:
                    return

                pct_start = 10 + int((idx / max(len(scannable), 1)) * 55)
                self.progress.emit(
                    f"Varrendo {part.letter} ({idx+1}/{len(scannable)})..."
                )
                self.progress_percent.emit(pct_start)

                # ── Sub-etapa 2.a: maiores arquivos do disco ───────
                self.disk_state_changed.emit(
                    part.letter, "scanning", "Analisando arquivos…"
                )
                disk_had_error = False
                try:
                    scan_targets = self._get_scan_targets(part.letter)
                    for target in scan_targets:
                        if self._abort:
                            return
                        try:
                            files = scanner.top_largest_files(
                                target, n=SCAN_TOP_FILES_PER_DISK,
                            )
                            all_files.extend(files)
                        except Exception as exc:
                            logger.debug("Erro em subdir %s: %s", target, exc)
                except Exception as exc:
                    disk_had_error = True
                    logger.warning(
                        "Erro ao varrer arquivos de %s: %s — continuando.",
                        part.letter, exc,
                    )

                if self._abort:
                    return

                # ── Sub-etapa 2.b: maiores pastas do disco ─────────
                self.disk_state_changed.emit(
                    part.letter, "scanning", "Analisando pastas…"
                )
                try:
                    scan_targets = self._get_scan_targets(part.letter)
                    for target in scan_targets:
                        if self._abort:
                            return
                        try:
                            dirs = scanner.top_largest_dirs(
                                target,
                                n=SCAN_TOP_DIRS_PER_DISK,
                                max_depth=SCAN_DIR_MAX_DEPTH,
                            )
                            all_dirs.extend(dirs)
                        except Exception as exc:
                            logger.debug(
                                "Erro ao listar dirs de %s: %s", target, exc
                            )
                except Exception as exc:
                    disk_had_error = True
                    logger.debug(
                        "Erro ao analisar pastas de %s: %s", part.letter, exc
                    )

                # Marcar disco como concluído (ou falhou) antes do próximo
                final_state = "error" if disk_had_error else "done"
                self.disk_state_changed.emit(part.letter, final_state, "")

            # Consolidar top global de todos os discos.
            all_files.sort(key=lambda f: f.size_bytes, reverse=True)
            result.top_files = all_files[:SCAN_TOP_FILES_PER_DISK]

            total_files = len(all_files)
            total_bytes = sum(f.size_bytes for f in all_files)

            logger.info("Top files global: %d entradas.", len(result.top_files))

            all_dirs.sort(key=lambda d: d.total_size_bytes, reverse=True)
            result.top_dirs = all_dirs[:SCAN_TOP_DIRS_PER_DISK]
            logger.info("Top dirs global: %d entradas.", len(result.top_dirs))

            if self._abort:
                return

            # ── Persistência antecipada + abas preliminares ─────────────
            # Bug fix: antes, as abas e o file_index só eram preenchidos no FIM,
            # depois da detecção de duplicatas (hash SHA-256 — minutos a >1h em
            # discos grandes). Quem fechasse o app antes do fim ficava com abas
            # vazias e índice desatualizado. Agora persistimos os arquivos e
            # emitimos um resultado PARCIAL aqui: as abas de arquivos/pastas
            # aparecem em segundos; duplicatas e sugestões chegam depois.
            #
            # Sprint 7.4: o cache de hash é hidratado ANTES da persistência para
            # não sobrescrever hashes válidos do DB com None (re-scans reusam
            # hashes de scans anteriores; arquivos novos ficam sem hash até a
            # Etapa 3 computá-los).
            hash_cache = self._build_hash_cache(all_files, db)
            logger.info(
                "Hash cache hidratado: %d hashes parciais e %d hashes completos.",
                hash_cache.partial_count,
                hash_cache.full_count,
            )
            self._persist_file_index(db, result.top_files, hash_cache)
            self.partial_result.emit(result)
            self.progress.emit("Arquivos listados — detectando duplicatas...")

            # ── Etapa 3: Detectar duplicatas ────────────────────────
            # Esta etapa pode rodar 5–15 minutos (ou mais) em discos grandes
            # (hash SHA-256 completo). A barra entra em modo indeterminado para
            # comunicar atividade sem sugerir tempo restante mensurável.
            dup_msg = (
                "Comparando duplicatas (hash SHA-256, pode demorar varios minutos)..."
            )
            self.global_stage_changed.emit(dup_msg)
            self.progress_percent.emit(65)
            self.progress_indeterminate.emit(True)

            detector = DuplicateDetector()
            try:
                result.duplicates = detector.find_duplicates(
                    all_files, cache=hash_cache,
                )
            finally:
                # Sempre retornar para modo determinístico, mesmo se find_duplicates
                # lançar exceção (ela será capturada pelo except externo).
                self.progress_indeterminate.emit(False)
            logger.info(
                "Duplicatas: %d grupos. Cache: %d hits parciais, %d novos parciais; "
                "%d hits completos, %d novos completos.",
                len(result.duplicates),
                hash_cache.partial_hits, len(hash_cache.partial_writes),
                hash_cache.full_hits, len(hash_cache.full_writes),
            )

            if self._abort:
                return

            # ── Etapa 4: Motor de regras ────────────────────────────
            rules_msg = "Avaliando regras de realocacao..."
            self.progress.emit(rules_msg)
            self.global_stage_changed.emit(rules_msg)
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
            
            # Sprint 7.4: re-persistir top_files agora COM os full-hashes que a
            # Etapa 3 computou (a persistência antecipada gravou os arquivos sem
            # os full-hashes ainda inexistentes). upsert idempotente.
            self._persist_file_index(db, result.top_files, hash_cache)

            logger.info("Sugestoes geradas: %d.", len(result.suggestions))

            self.progress_percent.emit(100)
            self.progress.emit("Varredura concluida!")
            self.global_stage_changed.emit("")  # limpa estágio global no painel

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
    def _persist_file_index(db, files, cache) -> None:
        """
        Faz upsert dos arquivos no file_index, gravando os hashes disponíveis
        no cache (seedados do DB ou recém-computados). Chamado duas vezes por
        varredura: cedo (após Etapa 2, hashes parciais/None) e ao final (com os
        full-hashes da Etapa 3). upsert idempotente — a 2ª chamada só enriquece.
        """
        now = time.time()
        for f in files:
            drive_letter = (
                f.path[:2] if len(f.path) >= 2 and f.path[1] == ":" else None
            )
            db.upsert_file_index(
                path=f.path,
                disk_letter=drive_letter,
                size_bytes=f.size_bytes,
                mtime=f.modified_time,
                category=f.category,
                partial_hash=cache.get_partial(f.path),
                full_hash=cache.get_full(f.path),
                last_seen=now,
            )

    # Tolerância em segundos ao comparar mtime do filesystem com o cacheado.
    # Sprint 7.6: valor canônico em config.HASH_CACHE_MTIME_TOLERANCE.
    _MTIME_TOLERANCE_SECONDS: float = HASH_CACHE_MTIME_TOLERANCE

    @classmethod
    def _build_hash_cache(
        cls, files: list[FileEntry], db: StorageManagerDB,
    ) -> InMemoryHashCache:
        """
        Sprint 7.4: monta um InMemoryHashCache pré-populado com hashes do DB
        cujos size_bytes e mtime ainda batem com o estado atual do filesystem.

        Retorna o cache pronto para passar a `DuplicateDetector.find_duplicates`.
        Hashes obsoletos (size ou mtime mudaram) são silenciosamente descartados;
        os novos serão computados durante a varredura e re-persistidos depois.
        """
        cache = InMemoryHashCache()
        if not files:
            return cache
        try:
            paths = [f.path for f in files]
            rows = db.get_file_index_batch(paths)
        except Exception as exc:
            # Falha do cache não deve bloquear a varredura — segue sem cache.
            logger.warning("Falha ao hidratar cache de hash do DB: %s", exc)
            return cache

        stale = 0
        for f in files:
            row = rows.get(f.path)
            if row is None:
                continue
            # Validar staleness: tamanho e mtime devem bater
            if row["size_bytes"] != f.size_bytes:
                stale += 1
                continue
            if abs(row["mtime"] - f.modified_time) > cls._MTIME_TOLERANCE_SECONDS:
                stale += 1
                continue
            # Hashes válidos vão para o cache como seed (não-write)
            if row["partial_hash"]:
                cache.seed_partial(f.path, row["partial_hash"])
            if row["full_hash"]:
                cache.seed_full(f.path, row["full_hash"])

        if stale:
            logger.info(
                "Hash cache: %d entradas obsoletas (size/mtime mudaram) descartadas.",
                stale,
            )
        return cache

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
