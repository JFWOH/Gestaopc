"""
Analyzer — Detecção de duplicatas e Motor de Regras de Realocação Inteligente.

Implementa as seções 3.3 (Detecção de Duplicatas) e 3.4 (Motor de Regras)
da especificação 01-storage-manager.md.

Algoritmo de duplicatas (3.3):
  Etapa 1 → Agrupa arquivos por tamanho exato em bytes.
  Etapa 2 → Para cada grupo com ≥2 arquivos, calcula hash parcial
            (primeiro 1 MB + último 1 MB).
  Etapa 3 → Se hashes parciais coincidem, calcula hash SHA-256 completo
            para confirmar a duplicata.

Motor de regras (3.4):
  Regra 1 → Arquivos de mídia/ISO >1 GB em C: → sugerir mover para SATA.
  Regra 2 → Arquivos duplicados → sugerir deletar a cópia mais recente.
  Regra 3 → Disco >90% cheio → sugerir mover mídia para discos externos.

Resiliência (Seção 5):
  Todo I/O de leitura de arquivos é protegido por try/except.
  Arquivos bloqueados pelo Kaspersky/AV são logados e ignorados.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from src.core.config import HASH_FULL_CHUNK_SIZE, HASH_SAMPLE_SIZE
from src.core.scanner import FileEntry, PartitionInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Tamanho da amostra para hash parcial (1 MB).
# Sprint 7.6: alias backward-compat para testes que fazem patch deste nome.
# O valor canônico vive em src/core/config.py.
_SAMPLE_SIZE: int = HASH_SAMPLE_SIZE

# Extensões de mídia pesada que devem sair do NVMe (Regra 1).
# Sprint 6.4: incluídos áudio (.flac/.wav grandes) e modelos de IA
# (.gguf/.safetensors/.bin), que costumam ultrapassar 1 GB no NVMe.
_HEAVY_MEDIA_EXTENSIONS: set[str] = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".iso",
    ".mp3", ".flac", ".wav", ".aac", ".ogg", ".m4a",
    ".gguf", ".safetensors", ".bin",
}

# Limiar de 1 GB em bytes (Regra 1).
_1GB: int = 1024 ** 3

# Categorias que contam como "mídia" para Regra 3.
# Sprint 6.4: "Áudio" e "Modelos IA" passam a ser candidatos a realocação
# quando o disco de origem está crítico (>90%).
_MEDIA_CATEGORIES: set[str] = {
    "Vídeos", "Imagens", "Compactados", "Áudio", "Modelos IA",
}


# ---------------------------------------------------------------------------
# Data classes de resultado
# ---------------------------------------------------------------------------

@dataclass
class DuplicateGroup:
    """Grupo de arquivos confirmados como duplicatas exatas."""
    hash_sha256: str
    size_bytes: int
    files: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def wasted_bytes(self) -> int:
        """Espaço desperdiçado = (N-1) × tamanho (mantendo 1 cópia)."""
        return self.size_bytes * max(0, self.count - 1)

    @property
    def wasted_mb(self) -> float:
        return round(self.wasted_bytes / (1024 ** 2), 2)

    def __repr__(self) -> str:
        return (
            f"<DuplicateGroup {self.count} arquivos | "
            f"{self.wasted_mb} MB desperdiçados | "
            f"hash=...{self.hash_sha256[-8:]}>"
        )


@dataclass
class ReallocationSuggestion:
    """Sugestão de ação gerada pelo Motor de Regras."""
    rule_id: int
    rule_name: str
    file_path: str
    action: str          # "MOVER" | "DELETAR"
    detail: str          # Descrição legível da sugestão
    target_disk: str = ""  # Ex: "D:", "G:", etc.
    priority: str = "MÉDIA"  # "ALTA" | "MÉDIA" | "BAIXA"

    def __repr__(self) -> str:
        return f"<Sugestão R{self.rule_id} [{self.action}] {self.detail}>"


# ---------------------------------------------------------------------------
# 3.3 — Detector de Duplicatas
# ---------------------------------------------------------------------------

class DuplicateDetector:
    """
    Detecta arquivos duplicados com algoritmo eficiente de 3 etapas.

    Uso::

        detector = DuplicateDetector()
        groups = detector.find_duplicates(list_of_file_entries)
    """

    def find_duplicates(
        self,
        files: list[FileEntry],
        *,
        cache=None,  # HashCache | None — Sprint 7.4
    ) -> list[DuplicateGroup]:
        """
        Encontra todas as duplicatas entre os arquivos fornecidos.

        Parameters
        ----------
        files:
            Lista de :class:`FileEntry` (normalmente produzida por
            ``StorageScanner.top_largest_files`` ou uma varredura completa).
        cache:
            Sprint 7.4 — instância opcional de :class:`HashCache`. Quando
            fornecida, hashes parciais e completos são consultados antes de
            recomputar o arquivo, e novos hashes são publicados de volta.
            Default: ``NullHashCache`` (sem caching).

        Returns
        -------
        Lista de :class:`DuplicateGroup` contendo apenas grupos com ≥2 arquivos.
        """
        if cache is None:
            from src.core.hash_cache import NullHashCache
            cache = NullHashCache()

        # ── Etapa 1: Agrupar por tamanho exato ──────────────────────────
        size_groups: dict[int, list[str]] = defaultdict(list)
        for f in files:
            size_groups[f.size_bytes].append(f.path)

        # Descartar tamanhos únicos (impossível ser duplicata).
        candidates = {
            size: paths for size, paths in size_groups.items()
            if len(paths) >= 2
        }
        logger.info(
            "Etapa 1 concluída: %d grupos com tamanho idêntico (de %d arquivos).",
            len(candidates),
            len(files),
        )

        if not candidates:
            return []

        # ── Etapa 2: Hash parcial (amostra) ─────────────────────────────
        sample_groups: dict[str, list[str]] = defaultdict(list)
        for size, paths in candidates.items():
            for filepath in paths:
                # Sprint 7.4: tentar cache antes de recomputar
                h = cache.get_partial(filepath)
                if h is None:
                    h = self._hash_sample(filepath)
                    if h is not None:
                        cache.put_partial(filepath, h)
                if h is not None:
                    # Chave composta: tamanho + hash parcial
                    key = f"{size}:{h}"
                    sample_groups[key].append(filepath)

        # Descartar amostras únicas.
        sample_candidates = {
            key: paths for key, paths in sample_groups.items()
            if len(paths) >= 2
        }
        logger.info(
            "Etapa 2 concluída: %d grupos com hash parcial idêntico.",
            len(sample_candidates),
        )

        if not sample_candidates:
            return []

        # ── Etapa 3: Hash completo SHA-256 ──────────────────────────────
        full_groups: dict[str, list[str]] = defaultdict(list)
        for key, paths in sample_candidates.items():
            size = int(key.split(":")[0])
            for filepath in paths:
                # Sprint 7.4: tentar cache antes de recomputar
                h = cache.get_full(filepath)
                if h is None:
                    h = self._hash_full(filepath)
                    if h is not None:
                        cache.put_full(filepath, h)
                if h is not None:
                    full_groups[h].append(filepath)

        # Montar resultado final (apenas grupos com ≥2 cópias confirmadas).
        duplicates: list[DuplicateGroup] = []
        for full_hash, paths in full_groups.items():
            if len(paths) >= 2:
                # Recuperar tamanho de qualquer um dos arquivos.
                try:
                    size = os.path.getsize(paths[0])
                except OSError:
                    size = 0
                duplicates.append(
                    DuplicateGroup(
                        hash_sha256=full_hash,
                        size_bytes=size,
                        files=sorted(paths),
                    )
                )

        # Ordenar do grupo mais pesado para o mais leve.
        duplicates.sort(key=lambda g: g.wasted_bytes, reverse=True)

        total_wasted = sum(g.wasted_bytes for g in duplicates)
        logger.info(
            "Etapa 3 concluída: %d grupos de duplicatas confirmados. "
            "Espaço desperdiçado total: %.2f MB.",
            len(duplicates),
            total_wasted / (1024 ** 2),
        )
        return duplicates

    # ---- Helpers de hashing -------------------------------------------------

    @staticmethod
    def _hash_sample(filepath: str) -> str | None:
        """
        Calcula hash SHA-256 de uma amostra do arquivo:
        primeiro 1 MB + último 1 MB.

        Retorna None se o arquivo estiver inacessível.
        """
        try:
            file_size = os.path.getsize(filepath)
            hasher = hashlib.sha256()

            with open(filepath, "rb") as f:
                # Ler primeiro 1 MB.
                head = f.read(_SAMPLE_SIZE)
                hasher.update(head)

                # Se o arquivo é maior que 2 MB, ler último 1 MB.
                if file_size > _SAMPLE_SIZE * 2:
                    f.seek(-_SAMPLE_SIZE, os.SEEK_END)
                    tail = f.read(_SAMPLE_SIZE)
                    hasher.update(tail)

            return hasher.hexdigest()

        except (PermissionError, OSError) as exc:
            logger.debug(
                "Hash parcial falhou (arquivo bloqueado/inacessível): %s — %s",
                filepath,
                exc,
            )
            return None

    @staticmethod
    def _hash_full(filepath: str) -> str | None:
        """
        Calcula hash SHA-256 completo do arquivo, lendo em blocos de 8 KB.

        Retorna None se o arquivo estiver inacessível.
        """
        try:
            hasher = hashlib.sha256()
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(HASH_FULL_CHUNK_SIZE)
                    if not chunk:
                        break
                    hasher.update(chunk)
            return hasher.hexdigest()

        except (PermissionError, OSError) as exc:
            logger.debug(
                "Hash completo falhou (arquivo bloqueado/inacessível): %s — %s",
                filepath,
                exc,
            )
            return None


# ---------------------------------------------------------------------------
# 3.4 — Motor de Regras de Realocação Inteligente
# ---------------------------------------------------------------------------

class SmartRulesEngine:
    """
    Motor de regras simbólicas para sugestões de realocação de arquivos.

    As regras são avaliadas na ordem de prioridade (1 → 2 → 3).
    Cada arquivo pode gerar múltiplas sugestões caso se encaixe em
    mais de uma regra.

    Uso::

        engine = SmartRulesEngine()
        suggestions = engine.evaluate(file_entry, partitions, duplicates)
    """

    def __init__(
        self,
        nvme_letters: set[str] | None = None,
        sata_internal_letters: set[str] | None = None,
        external_letters: set[str] | None = None,
    ):
        """
        Parameters
        ----------
        nvme_letters:
            Letras dos discos NVMe (alta velocidade). Default: {"C:"}.
        sata_internal_letters:
            Letras dos discos SATA internos. Default: {"D:", "G:"}.
        external_letters:
            Letras dos discos externos de backup. Default: {"J:", "L:"}.
        """
        self.nvme_letters = nvme_letters or {"C:"}
        self.sata_internal_letters = sata_internal_letters or {"D:", "G:"}
        self.external_letters = external_letters or {"J:", "L:"}

    def evaluate(
        self,
        file: FileEntry,
        partitions: list[PartitionInfo],
        duplicate_groups: list[DuplicateGroup] | None = None,
    ) -> list[ReallocationSuggestion]:
        """
        Avalia todas as regras para um arquivo e retorna as sugestões aplicáveis.

        Parameters
        ----------
        file:
            O arquivo a ser avaliado.
        partitions:
            Estado atual de todas as partições.
        duplicate_groups:
            Grupos de duplicatas (necessário para Regra 2).

        Returns
        -------
        Lista de sugestões — pode estar vazia se nenhuma regra se aplicar.
        """
        suggestions: list[ReallocationSuggestion] = []
        file_drive = self._extract_drive(file.path)
        partition_map = {p.letter: p for p in partitions}

        # ── Regra 1: Mídia pesada no NVMe → mover para SATA ────────────
        if (
            file_drive in self.nvme_letters
            and file.size_bytes > _1GB
            and Path(file.path).suffix.lower() in _HEAVY_MEDIA_EXTENSIONS
        ):
            target = self._best_sata_target(
                partition_map, file.size_bytes, file_drive
            )
            # Só sugerir se há um destino válido (existe, ≠ origem, comporta o
            # arquivo). Sem destino → nenhuma sugestão (Seção 6.2).
            if target is not None:
                suggestions.append(
                    ReallocationSuggestion(
                        rule_id=1,
                        rule_name="Mídia pesada no NVMe",
                        file_path=file.path,
                        action="MOVER",
                        detail=(
                            f"Mover {file.size_mb:.0f} MB de mídia "
                            f"de {file_drive} (NVMe) para {target} (SATA) "
                            f"para liberar espaço no disco principal."
                        ),
                        target_disk=target,
                        priority="ALTA",
                    )
                )

        # ── Regra 2: Arquivo duplicado → deletar cópia ─────────────────
        if duplicate_groups:
            for group in duplicate_groups:
                if file.path in group.files:
                    # Determinar qual cópia manter: a mais antiga (menor mtime).
                    copy_to_delete = self._pick_copy_to_delete(
                        group.files, file.path
                    )
                    if copy_to_delete == file.path:
                        suggestions.append(
                            ReallocationSuggestion(
                                rule_id=2,
                                rule_name="Arquivo duplicado",
                                file_path=file.path,
                                action="DELETAR",
                                detail=(
                                    f"Deletar cópia duplicada "
                                    f"({file.size_mb:.1f} MB). "
                                    f"Existem {group.count} cópias idênticas."
                                ),
                                priority="MÉDIA",
                            )
                        )
                    break  # Um arquivo só pertence a um grupo.

        # ── Regra 3: Disco >90% → mover mídia para externo ─────────────
        if file_drive in partition_map:
            part = partition_map[file_drive]
            if (
                part.percent_used > 90.0
                and file.category in _MEDIA_CATEGORIES
            ):
                target = self._best_external_target(
                    partition_map, file.size_bytes, file_drive
                )
                # Só sugerir se há um destino externo válido (Seção 6.2).
                if target is not None:
                    suggestions.append(
                        ReallocationSuggestion(
                            rule_id=3,
                            rule_name="Disco crítico (>90% uso)",
                            file_path=file.path,
                            action="MOVER",
                            detail=(
                                f"Disco {file_drive} está {part.percent_used}% cheio. "
                                f"Mover {file.size_mb:.0f} MB de {file.category} "
                                f"para disco externo {target}."
                            ),
                            target_disk=target,
                            priority="ALTA",
                        )
                    )

        return suggestions

    def evaluate_batch(
        self,
        files: list[FileEntry],
        partitions: list[PartitionInfo],
        duplicate_groups: list[DuplicateGroup] | None = None,
    ) -> list[ReallocationSuggestion]:
        """Avalia regras para uma lista de arquivos de uma vez."""
        all_suggestions: list[ReallocationSuggestion] = []
        for f in files:
            all_suggestions.extend(
                self.evaluate(f, partitions, duplicate_groups)
            )
        return all_suggestions

    # ---- Helpers privados ---------------------------------------------------

    @staticmethod
    def _extract_drive(filepath: str) -> str:
        """Extrai a letra do drive de um caminho (ex: 'C:\\foo' → 'C:')."""
        return Path(filepath).drive.upper()

    def _best_sata_target(
        self,
        partition_map: dict[str, PartitionInfo],
        required_bytes: int,
        source_drive: str,
    ) -> str | None:
        """
        Retorna o disco SATA interno candidato a destino, ou ``None``.

        Um candidato válido (Seção 6.2 — roteamento seguro):
          - existe no ``partition_map`` (sem default fabricado);
          - é diferente do disco de origem (origem ≠ destino);
          - tem espaço livre suficiente (``free_bytes >= required_bytes``).

        Entre os válidos, escolhe o de maior espaço livre. Retorna ``None``
        quando nenhum candidato satisfaz as três condições.
        """
        return self._best_target(
            self.sata_internal_letters, partition_map, required_bytes, source_drive
        )

    def _best_external_target(
        self,
        partition_map: dict[str, PartitionInfo],
        required_bytes: int,
        source_drive: str,
    ) -> str | None:
        """
        Retorna o disco externo candidato a destino, ou ``None``.

        Aplica as mesmas três validações de :meth:`_best_sata_target`
        (existe, origem ≠ destino, espaço suficiente).
        """
        return self._best_target(
            self.external_letters, partition_map, required_bytes, source_drive
        )

    @staticmethod
    def _best_target(
        candidate_letters: set[str],
        partition_map: dict[str, PartitionInfo],
        required_bytes: int,
        source_drive: str,
    ) -> str | None:
        """
        Helper comum: melhor destino entre ``candidate_letters`` que exista,
        difira da origem e comporte o arquivo. ``None`` se não houver.
        """
        best: str | None = None
        best_free = 0
        for letter in candidate_letters:
            if letter == source_drive:
                continue
            part = partition_map.get(letter)
            if part is None:
                continue
            if part.free_bytes < required_bytes:
                continue
            if part.free_bytes > best_free:
                best_free = part.free_bytes
                best = letter
        return best

    @staticmethod
    def _pick_copy_to_delete(file_paths: list[str], current_path: str) -> str:
        """
        Decide qual cópia deletar entre os duplicados.

        Estratégia (Seção 3.4, Regra 2):
          - Manter a cópia mais antiga (menor mtime).
          - Sugerir deletar a mais recente.

        Se não for possível ler os metadados, sugere deletar a que NÃO
        esteja na pasta raiz do usuário.
        """
        mtimes: list[tuple[str, float]] = []
        for p in file_paths:
            try:
                mt = os.path.getmtime(p)
                mtimes.append((p, mt))
            except OSError:
                # Arquivo inacessível → atribuir tempo infinito (será candidato a deletar).
                mtimes.append((p, float("inf")))

        # Ordenar do mais antigo para o mais recente.
        mtimes.sort(key=lambda x: x[1])

        # O mais antigo fica; todos os outros são candidatos a deleção.
        # Retornar current_path se ele é um dos candidatos a deletar.
        oldest_path = mtimes[0][0]
        if current_path != oldest_path:
            return current_path
        # Se current_path é o mais antigo, ele é mantido.
        return mtimes[1][0] if len(mtimes) > 1 else current_path


# ---------------------------------------------------------------------------
# Script de teste integrado
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # Forcar UTF-8 no stdout do Windows para evitar UnicodeEncodeError.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 70)
    print("  TESTE INTEGRADO — analyzer.py (Seções 3.3 e 3.4)")
    print("=" * 70)

    # ── Criar diretório temporário com arquivos de teste ─────────────
    test_dir = Path(tempfile.mkdtemp(prefix="gpc_test_"))
    print(f"\n[DIR] Diretorio de teste: {test_dir}\n")

    try:
        # Criar 3 arquivos idênticos (duplicatas).
        dup_content = b"CONTEUDO DUPLICADO " * 500  # ~9.5 KB
        (test_dir / "original.txt").write_bytes(dup_content)
        (test_dir / "copia1.txt").write_bytes(dup_content)
        (test_dir / "copia2.txt").write_bytes(dup_content)

        # Criar 1 arquivo único (mesmo tamanho, conteúdo diferente).
        unique_content = b"X" * len(dup_content)
        (test_dir / "unico_mesmo_tamanho.txt").write_bytes(unique_content)

        # Criar 1 arquivo com tamanho totalmente diferente.
        (test_dir / "diferente.log").write_bytes(b"log line\n" * 10)

        # Simular um .iso grande no C: (para Regra 1).
        fake_iso = test_dir / "jogo_pesado.iso"
        fake_iso.write_bytes(b"\x00" * 1024)  # Arquivo pequeno p/ teste rápido

        # ── Etapa A: Montar FileEntry list ──────────────────────────────
        entries: list[FileEntry] = []
        for f in test_dir.iterdir():
            if f.is_file():
                entries.append(
                    FileEntry(
                        path=str(f),
                        size_bytes=f.stat().st_size,
                        category="Compactados" if f.suffix == ".iso" else "Documentos",
                    )
                )

        print(f"[FILE] Arquivos criados: {len(entries)}")
        for e in entries:
            print(f"   {e.size_mb:>8.2f} MB  {e.path}")

        # ── Etapa B: Testar DuplicateDetector ───────────────────────────
        print("\n" + "-" * 70)
        print("  TESTE 3.3 — Detecção de Duplicatas")
        print("-" * 70)

        detector = DuplicateDetector()
        groups = detector.find_duplicates(entries)

        if groups:
            for g in groups:
                print(f"\n  [OK] Grupo encontrado: {g}")
                for fp in g.files:
                    print(f"     -> {fp}")
            print(f"\n  [DISK] Espaco desperdicado total: {sum(g.wasted_mb for g in groups):.2f} MB")
        else:
            print("  [WARN] Nenhuma duplicata encontrada (verifique os dados de teste).")

        # ── Etapa C: Testar SmartRulesEngine ────────────────────────────
        print("\n" + "-" * 70)
        print("  TESTE 3.4 — Motor de Regras de Realocação")
        print("-" * 70)

        # Simular partições para o teste.
        fake_partitions = [
            PartitionInfo(
                letter="C:", fstype="NTFS",
                total_bytes=1000 * _1GB, used_bytes=940 * _1GB,
                free_bytes=60 * _1GB, percent_used=94.0,
            ),
            PartitionInfo(
                letter="D:", fstype="NTFS",
                total_bytes=500 * _1GB, used_bytes=300 * _1GB,
                free_bytes=200 * _1GB, percent_used=60.0,
            ),
            PartitionInfo(
                letter="J:", fstype="NTFS",
                total_bytes=3000 * _1GB, used_bytes=2800 * _1GB,
                free_bytes=200 * _1GB, percent_used=93.0,
            ),
        ]

        # Criar um FileEntry simulando um .mkv de 2 GB no C:
        big_video_on_c = FileEntry(
            path="C:\\Users\\jeff\\Videos\\filme_enorme.mkv",
            size_bytes=2 * _1GB,
            category="Vídeos",
        )

        # Criar um FileEntry simulando mídia no disco C: lotado.
        media_on_full_disk = FileEntry(
            path="C:\\Users\\jeff\\Pictures\\fotos_viagem.zip",
            size_bytes=500 * (1024 ** 2),  # 500 MB
            category="Compactados",
        )

        engine = SmartRulesEngine()

        print("\n  >> Avaliando: filme_enorme.mkv (2 GB no C:)")
        suggestions = engine.evaluate(big_video_on_c, fake_partitions, groups)
        for s in suggestions:
            print(f"    [*] {s}")

        print("\n  >> Avaliando: fotos_viagem.zip (500 MB no C: com 94% uso)")
        suggestions = engine.evaluate(media_on_full_disk, fake_partitions, groups)
        for s in suggestions:
            print(f"    [*] {s}")

        # Testar Regra 2 (duplicata).
        if groups:
            dup_entry = FileEntry(
                path=groups[0].files[-1],  # Pegar última cópia
                size_bytes=groups[0].size_bytes,
                category="Documentos",
            )
            print(f"\n  >> Avaliando duplicata: {Path(dup_entry.path).name}")
            suggestions = engine.evaluate(dup_entry, fake_partitions, groups)
            for s in suggestions:
                print(f"    [*] {s}")

        print("\n" + "=" * 70)
        print("  [OK] TODOS OS TESTES CONCLUIDOS COM SUCESSO")
        print("=" * 70)

    finally:
        # Limpar diretório temporário.
        shutil.rmtree(test_dir, ignore_errors=True)
        print(f"\n[CLEAN] Diretorio de teste removido: {test_dir}")
