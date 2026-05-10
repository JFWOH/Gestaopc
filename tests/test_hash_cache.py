"""
Testes para src.core.hash_cache — Sprint 7.4.

Cobre:
  - NullHashCache: todos os métodos retornam None / no-op
  - InMemoryHashCache: get/put/seed, separação seed vs writes, contadores
  - Protocol HashCache: ambas implementações cumprem a interface
"""

from __future__ import annotations

from src.core.hash_cache import (
    HashCache,
    InMemoryHashCache,
    NullHashCache,
)


# ─────────────────────────────────────────────────────────────────────────────
# NullHashCache
# ─────────────────────────────────────────────────────────────────────────────

class TestNullHashCache:
    def test_get_partial_returns_none(self):
        cache = NullHashCache()
        assert cache.get_partial("C:\\file.txt") is None

    def test_get_full_returns_none(self):
        cache = NullHashCache()
        assert cache.get_full("C:\\file.txt") is None

    def test_put_partial_is_silent(self):
        cache = NullHashCache()
        cache.put_partial("C:\\file.txt", "abc123")  # não deve crashar
        assert cache.get_partial("C:\\file.txt") is None

    def test_put_full_is_silent(self):
        cache = NullHashCache()
        cache.put_full("C:\\file.txt", "def456")
        assert cache.get_full("C:\\file.txt") is None

    def test_protocol_compliance(self):
        """NullHashCache satisfaz o Protocol HashCache (duck-typing)."""
        cache: HashCache = NullHashCache()
        assert hasattr(cache, "get_partial")
        assert hasattr(cache, "put_partial")
        assert hasattr(cache, "get_full")
        assert hasattr(cache, "put_full")


# ─────────────────────────────────────────────────────────────────────────────
# InMemoryHashCache — operações básicas
# ─────────────────────────────────────────────────────────────────────────────

class TestInMemoryHashCacheBasics:
    def test_starts_empty(self):
        cache = InMemoryHashCache()
        assert cache.partial_count == 0
        assert cache.full_count == 0
        assert cache.partial_writes == {}
        assert cache.full_writes == {}

    def test_put_then_get_partial(self):
        cache = InMemoryHashCache()
        cache.put_partial("C:\\a.bin", "hash1")
        assert cache.get_partial("C:\\a.bin") == "hash1"

    def test_put_then_get_full(self):
        cache = InMemoryHashCache()
        cache.put_full("C:\\a.bin", "fullhash")
        assert cache.get_full("C:\\a.bin") == "fullhash"

    def test_get_unknown_path_returns_none(self):
        cache = InMemoryHashCache()
        assert cache.get_partial("X:\\nope.bin") is None
        assert cache.get_full("X:\\nope.bin") is None

    def test_partial_and_full_are_independent(self):
        cache = InMemoryHashCache()
        cache.put_partial("C:\\a.bin", "p")
        assert cache.get_partial("C:\\a.bin") == "p"
        assert cache.get_full("C:\\a.bin") is None

    def test_put_overwrites_previous_value(self):
        cache = InMemoryHashCache()
        cache.put_partial("C:\\a.bin", "old")
        cache.put_partial("C:\\a.bin", "new")
        assert cache.get_partial("C:\\a.bin") == "new"


# ─────────────────────────────────────────────────────────────────────────────
# InMemoryHashCache — diferenciação seed vs writes
# ─────────────────────────────────────────────────────────────────────────────

class TestInMemoryHashCacheSeeding:
    def test_seed_partial_does_not_count_as_write(self):
        cache = InMemoryHashCache()
        cache.seed_partial("C:\\a.bin", "seeded")
        assert cache.get_partial("C:\\a.bin") == "seeded"
        assert cache.partial_writes == {}, "seed não deve aparecer em writes"
        assert cache.partial_count == 1

    def test_seed_full_does_not_count_as_write(self):
        cache = InMemoryHashCache()
        cache.seed_full("C:\\a.bin", "seeded_full")
        assert cache.get_full("C:\\a.bin") == "seeded_full"
        assert cache.full_writes == {}
        assert cache.full_count == 1

    def test_put_after_seed_marks_as_write(self):
        cache = InMemoryHashCache()
        cache.seed_partial("C:\\a.bin", "old")
        cache.put_partial("C:\\a.bin", "new")
        assert cache.get_partial("C:\\a.bin") == "new"
        assert cache.partial_writes == {"C:\\a.bin": "new"}

    def test_writes_tracks_only_put_calls(self):
        cache = InMemoryHashCache()
        cache.seed_partial("C:\\seed1.bin", "s1")
        cache.seed_partial("C:\\seed2.bin", "s2")
        cache.put_partial("C:\\write1.bin", "w1")
        cache.put_partial("C:\\write2.bin", "w2")

        assert cache.partial_count == 4
        assert set(cache.partial_writes.keys()) == {"C:\\write1.bin", "C:\\write2.bin"}

    def test_writes_returns_independent_copy(self):
        """Mutar o dict retornado não afeta o estado interno."""
        cache = InMemoryHashCache()
        cache.put_partial("C:\\a.bin", "p")
        snap = cache.partial_writes
        snap.clear()  # tentativa de mutação externa
        assert cache.get_partial("C:\\a.bin") == "p"
        assert cache.partial_writes == {"C:\\a.bin": "p"}


# ─────────────────────────────────────────────────────────────────────────────
# InMemoryHashCache — contadores hits/writes
# ─────────────────────────────────────────────────────────────────────────────

class TestInMemoryHashCacheMetrics:
    def test_partial_hits_when_seeded(self):
        cache = InMemoryHashCache()
        cache.seed_partial("C:\\a.bin", "h1")
        cache.seed_partial("C:\\b.bin", "h2")
        assert cache.partial_hits == 2

    def test_partial_hits_zero_when_only_writes(self):
        cache = InMemoryHashCache()
        cache.put_partial("C:\\a.bin", "h1")
        cache.put_partial("C:\\b.bin", "h2")
        assert cache.partial_hits == 0
        assert len(cache.partial_writes) == 2

    def test_partial_hits_with_mixed_seed_and_write(self):
        cache = InMemoryHashCache()
        cache.seed_partial("C:\\seeded.bin", "s")
        cache.put_partial("C:\\new.bin", "n")
        assert cache.partial_hits == 1
        assert len(cache.partial_writes) == 1
        assert cache.partial_count == 2

    def test_full_metrics_independent_from_partial(self):
        cache = InMemoryHashCache()
        cache.seed_partial("C:\\a.bin", "p")
        cache.put_full("C:\\a.bin", "f")
        assert cache.partial_hits == 1
        assert cache.full_hits == 0
        assert len(cache.partial_writes) == 0
        assert len(cache.full_writes) == 1


# ─────────────────────────────────────────────────────────────────────────────
# InMemoryHashCache — Protocol compliance
# ─────────────────────────────────────────────────────────────────────────────

class TestInMemoryProtocol:
    def test_satisfies_hash_cache_protocol(self):
        cache: HashCache = InMemoryHashCache()
        # Operações básicas do Protocol funcionam
        assert cache.get_partial("X") is None
        cache.put_partial("X", "h")
        assert cache.get_partial("X") == "h"
