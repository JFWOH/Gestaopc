"""
HashCache — Sprint 7.4.

Permite que `DuplicateDetector.find_duplicates` reaproveite hashes calculados
em varreduras anteriores, transformando re-scans de 13+ minutos (hash SHA-256
completo de 500+ grupos) em segundos quando os arquivos não mudaram.

Design:
    A cache é uma camada thin entre o detector e o DB. O detector chama
    `cache.get_partial(path)` antes de computar hash; se o cache devolve
    um valor, o detector usa-o sem ler o arquivo. Caso contrário, computa
    e devolve via `cache.put_partial(path, hash)`.

    A staleness lógica (size/mtime mudaram?) NÃO vive aqui — fica no
    chamador (workers.py), que filtra entradas obsoletas do DB antes de
    popular o cache. Assim, este módulo permanece testável em isolamento.

Implementações fornecidas:
    NullHashCache       — no-op; usar quando não há cache (default).
    InMemoryHashCache   — backed por dicts; carrier entre DB e detector.

Não há "SqliteHashCache" — o ciclo read-from-DB → in-memory → write-to-DB
é orquestrado em workers.py para tornar a operação atômica e tracejável.
"""

from __future__ import annotations

from typing import Protocol


class HashCache(Protocol):
    """
    Interface mínima de cache de hash usada por DuplicateDetector.

    Todas as operações são síncronas e devem ser baratas (idealmente O(1)).
    """

    def get_partial(self, path: str) -> str | None:
        """Retorna hash parcial cacheado ou None se ausente."""
        ...

    def put_partial(self, path: str, hash_hex: str) -> None:
        """Armazena hash parcial recém-computado."""
        ...

    def get_full(self, path: str) -> str | None:
        """Retorna hash completo cacheado ou None se ausente."""
        ...

    def put_full(self, path: str, hash_hex: str) -> None:
        """Armazena hash completo recém-computado."""
        ...


class NullHashCache:
    """Cache no-op — usado como default quando nenhum cache é desejado."""

    def get_partial(self, path: str) -> str | None:
        return None

    def put_partial(self, path: str, hash_hex: str) -> None:
        return None

    def get_full(self, path: str) -> str | None:
        return None

    def put_full(self, path: str, hash_hex: str) -> None:
        return None


class InMemoryHashCache:
    """
    Cache backed por dois dicts in-memory.

    Rastreia separadamente quais hashes vieram pré-populados (`seed_*`) versus
    quais foram computados durante a varredura atual (`_*_writes`). Isso
    permite ao chamador persistir apenas as deltas no DB ao final, sem
    re-escrever o mundo inteiro.

    Uso típico (em workers.py):
        cache = InMemoryHashCache()
        # 1) Pré-popular com dados do DB cujo size/mtime ainda batem:
        for path, partial in known_partial_hashes:
            cache.seed_partial(path, partial)
        for path, full in known_full_hashes:
            cache.seed_full(path, full)

        # 2) Passar ao detector — Stage 2 e 3 podem reaproveitar:
        groups = detector.find_duplicates(files, cache=cache)

        # 3) Persistir só o que foi computado (não o que já estava cacheado):
        for path, h in cache.partial_writes.items():
            db.upsert_file_index(..., partial_hash=h, ...)
    """

    def __init__(self) -> None:
        self._partial: dict[str, str] = {}
        self._full: dict[str, str] = {}
        self._partial_writes: dict[str, str] = {}
        self._full_writes: dict[str, str] = {}

    # ── HashCache Protocol ─────────────────────────────────────────────────

    def get_partial(self, path: str) -> str | None:
        return self._partial.get(path)

    def put_partial(self, path: str, hash_hex: str) -> None:
        self._partial[path] = hash_hex
        self._partial_writes[path] = hash_hex

    def get_full(self, path: str) -> str | None:
        return self._full.get(path)

    def put_full(self, path: str, hash_hex: str) -> None:
        self._full[path] = hash_hex
        self._full_writes[path] = hash_hex

    # ── API de seeding (não é parte do Protocol) ───────────────────────────

    def seed_partial(self, path: str, hash_hex: str) -> None:
        """
        Pré-popula um hash parcial sem marcá-lo como write.

        Use ao carregar do DB no início de uma varredura.
        """
        self._partial[path] = hash_hex

    def seed_full(self, path: str, hash_hex: str) -> None:
        """Pré-popula um hash completo sem marcá-lo como write."""
        self._full[path] = hash_hex

    # ── Inspeção ───────────────────────────────────────────────────────────

    @property
    def partial_writes(self) -> dict[str, str]:
        """Hashes parciais computados durante a varredura (não os seedados)."""
        return dict(self._partial_writes)

    @property
    def full_writes(self) -> dict[str, str]:
        """Hashes completos computados durante a varredura."""
        return dict(self._full_writes)

    @property
    def partial_count(self) -> int:
        """Total de hashes parciais conhecidos (seedados + computados)."""
        return len(self._partial)

    @property
    def full_count(self) -> int:
        return len(self._full)

    @property
    def partial_hits(self) -> int:
        """Hashes parciais reaproveitados do seed (não recomputados)."""
        return len(self._partial) - len(self._partial_writes)

    @property
    def full_hits(self) -> int:
        return len(self._full) - len(self._full_writes)
