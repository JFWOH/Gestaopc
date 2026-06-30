"""
Testes para src.core.analyzer — DuplicateDetector + SmartRulesEngine.

Cobre:
  - Detecção de duplicatas com 3 etapas (3.3)
  - Hash parcial vs hash completo
  - Motor de regras: Regra 1, 2, 3 isoladamente (3.4)
  - evaluate_batch()
  - Resiliência a arquivos inacessíveis
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch


from src.core.scanner import FileEntry, PartitionInfo
import src.core.analyzer as _analyzer_module
from src.core.analyzer import (
    DuplicateDetector,
    DuplicateGroup,
    SmartRulesEngine,
    ReallocationSuggestion,
    _1GB,
)


# ---------------------------------------------------------------------------
# DuplicateDetector
# ---------------------------------------------------------------------------

class TestDuplicateDetector:
    """Testa o algoritmo de 3 etapas para detecção de duplicatas."""

    def test_finds_duplicates(self, fake_file_entries: list[FileEntry]):
        """Deve encontrar o grupo de 3 arquivos duplicados (doc1/doc2/doc3)."""
        detector = DuplicateDetector()
        groups = detector.find_duplicates(fake_file_entries)

        assert len(groups) >= 1

        # O maior grupo deve conter exatamente 3 cópias
        biggest = groups[0]
        assert biggest.count == 3

        names = {Path(f).name for f in biggest.files}
        assert names == {"doc1.txt", "doc2.txt", "doc3.txt"}

    def test_no_false_positives_same_size(self, fake_file_entries: list[FileEntry]):
        """Arquivos com mesmo tamanho mas conteúdo diferente NÃO são duplicatas."""
        detector = DuplicateDetector()
        groups = detector.find_duplicates(fake_file_entries)

        all_dup_paths = {f for g in groups for f in g.files}
        unique_files = [
            e for e in fake_file_entries
            if "unico" in Path(e.path).name
        ]

        for uf in unique_files:
            assert uf.path not in all_dup_paths, \
                "Arquivo com conteúdo único não deve ser marcado como duplicata"

    def test_empty_input(self):
        detector = DuplicateDetector()
        groups = detector.find_duplicates([])
        assert groups == []

    def test_all_unique_files(self, tmp_path: Path):
        """Sem duplicatas quando todos os arquivos são únicos."""
        (tmp_path / "a.txt").write_bytes(b"conteudo A")
        (tmp_path / "b.txt").write_bytes(b"conteudo B diferente")
        (tmp_path / "c.txt").write_bytes(b"outro conteudo C totalmente diferente")

        entries = [
            FileEntry(path=str(f), size_bytes=f.stat().st_size)
            for f in tmp_path.iterdir() if f.is_file()
        ]

        detector = DuplicateDetector()
        groups = detector.find_duplicates(entries)
        assert groups == []

    def test_wasted_bytes_calculation(self, fake_file_entries: list[FileEntry]):
        """wasted_bytes = (N-1) × tamanho do arquivo."""
        detector = DuplicateDetector()
        groups = detector.find_duplicates(fake_file_entries)

        for g in groups:
            expected = g.size_bytes * (g.count - 1)
            assert g.wasted_bytes == expected

    def test_groups_sorted_by_wasted_space(self, tmp_path: Path):
        """Grupos devem ser ordenados do mais pesado para o mais leve."""
        # Criar 2 grupos de duplicatas com tamanhos diferentes
        small = b"small" * 100
        big = b"BIG CONTENT " * 1000

        (tmp_path / "small_a.txt").write_bytes(small)
        (tmp_path / "small_b.txt").write_bytes(small)
        (tmp_path / "big_a.dat").write_bytes(big)
        (tmp_path / "big_b.dat").write_bytes(big)

        entries = [
            FileEntry(path=str(f), size_bytes=f.stat().st_size)
            for f in tmp_path.iterdir() if f.is_file()
        ]

        detector = DuplicateDetector()
        groups = detector.find_duplicates(entries)

        assert len(groups) == 2
        assert groups[0].wasted_bytes >= groups[1].wasted_bytes

    def test_handles_inaccessible_files(self, tmp_path: Path):
        """Arquivos inacessíveis devem ser pulados sem crash."""
        content = b"duplicata" * 100
        (tmp_path / "ok1.txt").write_bytes(content)
        (tmp_path / "ok2.txt").write_bytes(content)

        entries = [
            FileEntry(path=str(tmp_path / "ok1.txt"), size_bytes=len(content)),
            FileEntry(path=str(tmp_path / "ok2.txt"), size_bytes=len(content)),
            FileEntry(path=str(tmp_path / "nao_existe.txt"), size_bytes=len(content)),
        ]

        detector = DuplicateDetector()
        # Não deve lançar exceção
        groups = detector.find_duplicates(entries)
        # Deve encontrar pelo menos as 2 acessíveis
        assert len(groups) >= 1


# ---------------------------------------------------------------------------
# DuplicateGroup dataclass
# ---------------------------------------------------------------------------

class TestDuplicateGroup:
    def test_count(self):
        g = DuplicateGroup(hash_sha256="abc123", size_bytes=1000, files=["a", "b", "c"])
        assert g.count == 3

    def test_wasted_bytes(self):
        g = DuplicateGroup(hash_sha256="abc123", size_bytes=1000, files=["a", "b"])
        assert g.wasted_bytes == 1000  # (2-1) * 1000

    def test_wasted_mb(self):
        g = DuplicateGroup(
            hash_sha256="abc123",
            size_bytes=1024 * 1024,  # 1 MB
            files=["a", "b", "c"],
        )
        assert g.wasted_mb == 2.0  # (3-1) * 1 MB

    def test_repr(self):
        g = DuplicateGroup(hash_sha256="abcdef1234567890", size_bytes=500, files=["a", "b"])
        r = repr(g)
        assert "2 arquivos" in r
        assert "34567890" in r  # últimos 8 chars do hash


# ---------------------------------------------------------------------------
# SmartRulesEngine — Regra 1: Mídia pesada no NVMe
# ---------------------------------------------------------------------------

class TestRule1:
    """Mídia pesada (>1GB, extensão de vídeo/iso) no C: → mover para SATA."""

    def test_triggers_for_large_mkv_on_c(self, fake_partitions: list[PartitionInfo]):
        engine = SmartRulesEngine()
        file = FileEntry(
            path="C:\\Users\\jeff\\Videos\\filme.mkv",
            size_bytes=2 * _1GB,
            category="Vídeos",
        )

        suggestions = engine.evaluate(file, fake_partitions)
        r1 = [s for s in suggestions if s.rule_id == 1]

        assert len(r1) == 1
        assert r1[0].action == "MOVER"
        assert r1[0].priority == "ALTA"
        assert r1[0].target_disk in {"D:", "G:"}

    def test_does_not_trigger_for_small_file(self, fake_partitions):
        engine = SmartRulesEngine()
        file = FileEntry(
            path="C:\\Users\\jeff\\Videos\\clip.mp4",
            size_bytes=500 * 1024 * 1024,  # 500 MB (< 1GB)
            category="Vídeos",
        )

        suggestions = engine.evaluate(file, fake_partitions)
        r1 = [s for s in suggestions if s.rule_id == 1]
        assert len(r1) == 0

    def test_does_not_trigger_for_non_media(self, fake_partitions):
        engine = SmartRulesEngine()
        file = FileEntry(
            path="C:\\Users\\jeff\\backup.db",
            size_bytes=5 * _1GB,
            category="Outros",
        )

        suggestions = engine.evaluate(file, fake_partitions)
        r1 = [s for s in suggestions if s.rule_id == 1]
        assert len(r1) == 0

    def test_does_not_trigger_on_sata_disk(self, fake_partitions):
        engine = SmartRulesEngine()
        file = FileEntry(
            path="D:\\Videos\\filme.mkv",
            size_bytes=2 * _1GB,
            category="Vídeos",
        )

        suggestions = engine.evaluate(file, fake_partitions)
        r1 = [s for s in suggestions if s.rule_id == 1]
        assert len(r1) == 0

    def test_picks_sata_with_most_free_space(self, fake_partitions):
        engine = SmartRulesEngine()
        file = FileEntry(
            path="C:\\Users\\jeff\\Videos\\filme.iso",
            size_bytes=2 * _1GB,
            category="Compactados",
        )

        suggestions = engine.evaluate(file, fake_partitions)
        r1 = [s for s in suggestions if s.rule_id == 1]

        # D: tem 800 GB livre, G: tem 550 GB → deve sugerir D:
        assert r1[0].target_disk == "D:"


# ---------------------------------------------------------------------------
# SmartRulesEngine — Regra 2: Arquivo duplicado
# ---------------------------------------------------------------------------

class TestRule2:
    """Arquivo duplicado → sugerir deletar a cópia mais recente."""

    def test_suggests_delete_for_duplicate(self, fake_partitions):
        engine = SmartRulesEngine()

        group = DuplicateGroup(
            hash_sha256="aabbccdd" * 8,
            size_bytes=5000,
            files=["C:\\doc1.txt", "C:\\doc2.txt"],
        )

        # Testar com o arquivo que seria candidato a deleção
        file = FileEntry(path="C:\\doc2.txt", size_bytes=5000, category="Documentos")

        # Mock os.path.getmtime para controlar qual é "mais antigo"
        def fake_mtime(p):
            if "doc1" in p:
                return 1000.0  # mais antigo
            return 2000.0  # mais recente

        with patch("os.path.getmtime", side_effect=fake_mtime):
            suggestions = engine.evaluate(file, fake_partitions, [group])

        r2 = [s for s in suggestions if s.rule_id == 2]
        assert len(r2) == 1
        assert r2[0].action == "DELETAR"

    def test_keeps_oldest_copy(self, fake_partitions):
        engine = SmartRulesEngine()

        group = DuplicateGroup(
            hash_sha256="aabbccdd" * 8,
            size_bytes=5000,
            files=["C:\\old.txt", "C:\\new.txt"],
        )

        # Testar com o arquivo MAIS ANTIGO — não deve sugerir deletá-lo
        file = FileEntry(path="C:\\old.txt", size_bytes=5000, category="Documentos")

        def fake_mtime(p):
            if "old" in p:
                return 1000.0
            return 2000.0

        with patch("os.path.getmtime", side_effect=fake_mtime):
            suggestions = engine.evaluate(file, fake_partitions, [group])

        r2 = [s for s in suggestions if s.rule_id == 2]
        # O mais antigo não é sugerido para deleção
        assert len(r2) == 0

    def test_no_duplicates_no_suggestion(self, fake_partitions):
        engine = SmartRulesEngine()
        file = FileEntry(path="C:\\unique.txt", size_bytes=5000, category="Documentos")

        suggestions = engine.evaluate(file, fake_partitions, [])
        r2 = [s for s in suggestions if s.rule_id == 2]
        assert len(r2) == 0


# ---------------------------------------------------------------------------
# SmartRulesEngine — Regra 3: Disco >90% → mover mídia
# ---------------------------------------------------------------------------

class TestRule3:
    """Disco >90% cheio + arquivo de mídia → mover para externo."""

    def test_triggers_for_media_on_full_disk(self, fake_partitions):
        engine = SmartRulesEngine()
        file = FileEntry(
            path="C:\\Users\\jeff\\Pictures\\fotos.zip",
            size_bytes=500 * 1024 * 1024,
            category="Compactados",  # Está em _MEDIA_CATEGORIES
        )

        suggestions = engine.evaluate(file, fake_partitions)
        r3 = [s for s in suggestions if s.rule_id == 3]

        assert len(r3) == 1
        assert r3[0].action == "MOVER"
        assert r3[0].priority == "ALTA"
        # Deve sugerir disco externo com mais espaço (J: tem 2100 GB)
        assert r3[0].target_disk == "J:"

    def test_does_not_trigger_for_healthy_disk(self, fake_partitions):
        engine = SmartRulesEngine()
        file = FileEntry(
            path="D:\\Videos\\filme.mp4",
            size_bytes=2 * _1GB,
            category="Vídeos",
        )

        suggestions = engine.evaluate(file, fake_partitions)
        r3 = [s for s in suggestions if s.rule_id == 3]
        assert len(r3) == 0  # D: está em 60%

    def test_does_not_trigger_for_non_media(self, fake_partitions):
        engine = SmartRulesEngine()
        file = FileEntry(
            path="C:\\Users\\jeff\\app.exe",
            size_bytes=100 * 1024 * 1024,
            category="Executáveis",
        )

        suggestions = engine.evaluate(file, fake_partitions)
        r3 = [s for s in suggestions if s.rule_id == 3]
        assert len(r3) == 0  # Executáveis não são mídia


# ---------------------------------------------------------------------------
# evaluate_batch()
# ---------------------------------------------------------------------------

class TestEvaluateBatch:
    """Testa avaliação em lote de múltiplos arquivos."""

    def test_processes_multiple_files(self, fake_partitions):
        engine = SmartRulesEngine()
        files = [
            FileEntry(path="C:\\filme.mkv", size_bytes=3 * _1GB, category="Vídeos"),
            FileEntry(path="C:\\fotos.zip", size_bytes=200 * 1024 * 1024, category="Compactados"),
            FileEntry(path="D:\\doc.txt", size_bytes=1024, category="Documentos"),
        ]

        suggestions = engine.evaluate_batch(files, fake_partitions)

        # filme.mkv deve disparar R1 e R3; fotos.zip deve disparar R3
        assert len(suggestions) >= 2

    def test_empty_files_returns_empty(self, fake_partitions):
        engine = SmartRulesEngine()
        suggestions = engine.evaluate_batch([], fake_partitions)
        assert suggestions == []


# ---------------------------------------------------------------------------
# ReallocationSuggestion dataclass
# ---------------------------------------------------------------------------

class TestReallocationSuggestion:
    def test_repr(self):
        s = ReallocationSuggestion(
            rule_id=1,
            rule_name="Teste",
            file_path="C:\\a.mkv",
            action="MOVER",
            detail="Mover para D:",
        )
        r = repr(s)
        assert "R1" in r
        assert "MOVER" in r


# ---------------------------------------------------------------------------
# DuplicateDetector — branches não cobertos
# ---------------------------------------------------------------------------

class TestDuplicateDetectorBranches:
    """Cobre branches específicos do algoritmo de 3 etapas."""

    def test_early_return_when_all_samples_unique(self, tmp_path: Path):
        """
        Etapa 2: arquivos com mesmo tamanho mas hashes de amostra distintos
        resultam em sample_candidates vazio → retorno antecipado de [].

        Garante cobertura da linha: `if not sample_candidates: return []`
        """
        size = 1_000
        (tmp_path / "file_a.bin").write_bytes(b"A" * size)
        (tmp_path / "file_b.bin").write_bytes(b"B" * size)

        entries = [
            FileEntry(path=str(tmp_path / "file_a.bin"), size_bytes=size),
            FileEntry(path=str(tmp_path / "file_b.bin"), size_bytes=size),
        ]

        detector = DuplicateDetector()
        groups = detector.find_duplicates(entries)
        assert groups == []

    def test_oserror_in_final_getsize_yields_size_zero(self, tmp_path: Path):
        """
        Etapa 3 — construção do resultado: se os.path.getsize(paths[0]) lançar
        OSError, size_bytes deve ser 0 (branch de fallback na linha ~192).
        """
        content = b"identical content " * 50
        f1 = tmp_path / "dup_a.bin"
        f2 = tmp_path / "dup_b.bin"
        f1.write_bytes(content)
        f2.write_bytes(content)

        entries = [
            FileEntry(path=str(f1), size_bytes=len(content)),
            FileEntry(path=str(f2), size_bytes=len(content)),
        ]

        real_getsize = os.path.getsize
        call_counts: dict[str, int] = {}

        def counting_getsize(path: str) -> int:
            key = str(path)
            call_counts[key] = call_counts.get(key, 0) + 1
            # As primeiras chamadas vêm do _hash_sample (uma por arquivo).
            # A 2ª chamada ao mesmo caminho vem da fase de resultado.
            if call_counts[key] >= 2:
                raise OSError("Arquivo sumiu")
            return real_getsize(path)

        detector = DuplicateDetector()
        with patch("os.path.getsize", side_effect=counting_getsize):
            groups = detector.find_duplicates(entries)

        assert len(groups) == 1
        assert groups[0].size_bytes == 0, "OSError em getsize deve resultar em size_bytes=0"

    def test_hash_sample_reads_tail_for_large_file(self, tmp_path: Path):
        """
        _hash_sample lê os últimos _SAMPLE_SIZE bytes quando o arquivo
        é maior que 2 × _SAMPLE_SIZE (branch L234-237).

        Estratégia: patch _SAMPLE_SIZE=5 so qualquer arquivo >10 bytes
        aciona a leitura do tail.
        """
        small_sample = 5
        # 30 bytes > 2*5=10 → branch de tail será ativado
        head = b"HEADX"         # 5 bytes — head lido
        middle = b"\x00" * 20  # 20 bytes de padding
        tail_a = b"TAILA"      # 5 bytes — tail do arquivo A
        tail_b = b"TAILB"      # 5 bytes — tail diferente

        fa = tmp_path / "file_a.bin"
        fb = tmp_path / "file_b.bin"
        fa.write_bytes(head + middle + tail_a)
        fb.write_bytes(head + middle + tail_b)

        with patch.object(_analyzer_module, "_SAMPLE_SIZE", small_sample):
            ha = DuplicateDetector._hash_sample(str(fa))
            hb = DuplicateDetector._hash_sample(str(fb))

        assert ha is not None
        assert hb is not None
        assert ha != hb, "Tails diferentes devem gerar hashes diferentes"

        # Verificar também que dois arquivos idênticos (inclusive o tail) geram hashes iguais
        fc = tmp_path / "file_c.bin"
        fc.write_bytes(head + middle + tail_a)  # cópia de fa

        with patch.object(_analyzer_module, "_SAMPLE_SIZE", small_sample):
            hc = DuplicateDetector._hash_sample(str(fc))

        assert hc == ha, "Conteúdo idêntico deve gerar hash idêntico"

    def test_hash_full_returns_none_on_permission_error(self, tmp_path: Path):
        """
        _hash_full deve retornar None quando open() lançar PermissionError
        (branch L266-272).
        """
        f = tmp_path / "locked.bin"
        f.write_bytes(b"algum conteudo")

        with patch("builtins.open", side_effect=PermissionError("Acesso negado")):
            result = DuplicateDetector._hash_full(str(f))

        assert result is None

    def test_hash_full_returns_none_on_oserror(self, tmp_path: Path):
        """
        _hash_full deve retornar None quando open() lançar OSError genérico.
        """
        f = tmp_path / "broken.bin"
        f.write_bytes(b"conteudo")

        with patch("builtins.open", side_effect=OSError("Disco com falha")):
            result = DuplicateDetector._hash_full(str(f))

        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Sprint 7.4 — DuplicateDetector + HashCache
# ─────────────────────────────────────────────────────────────────────────────

class TestDuplicateDetectorWithCache:
    """
    Garante que find_duplicates respeita um HashCache fornecido:
      - Lê hashes do cache antes de recomputar
      - Escreve hashes recém-computados de volta ao cache
      - Mantém comportamento idêntico ao default (NullHashCache)
    """

    def _two_duplicates(self, tmp_path: Path) -> list[FileEntry]:
        """Cria 2 arquivos idênticos e retorna FileEntry list."""
        content = b"identical content for cache tests " * 10
        f1 = tmp_path / "dup_a.bin"
        f2 = tmp_path / "dup_b.bin"
        f1.write_bytes(content)
        f2.write_bytes(content)
        return [
            FileEntry(path=str(f1), size_bytes=len(content)),
            FileEntry(path=str(f2), size_bytes=len(content)),
        ]

    def test_no_cache_arg_keeps_original_behavior(self, tmp_path: Path):
        """find_duplicates sem cache funciona como antes do Sprint 7.4."""
        entries = self._two_duplicates(tmp_path)
        detector = DuplicateDetector()
        groups = detector.find_duplicates(entries)
        assert len(groups) == 1
        assert groups[0].count == 2

    def test_writes_computed_hashes_to_cache(self, tmp_path: Path):
        """Após detecção, partial_writes e full_writes devem estar populados."""
        from src.core.hash_cache import InMemoryHashCache

        entries = self._two_duplicates(tmp_path)
        cache = InMemoryHashCache()

        detector = DuplicateDetector()
        groups = detector.find_duplicates(entries, cache=cache)

        assert len(groups) == 1
        # Ambos os arquivos devem ter hash parcial e completo no cache
        assert len(cache.partial_writes) == 2
        assert len(cache.full_writes) == 2
        for f in entries:
            assert cache.get_partial(f.path) is not None
            assert cache.get_full(f.path) is not None

    def test_seeded_cache_skips_recomputation(self, tmp_path: Path):
        """
        Cache pré-populado com hashes válidos deve impedir _hash_sample/full
        de ser chamado. Verificamos via patch.
        """
        from src.core.hash_cache import InMemoryHashCache

        entries = self._two_duplicates(tmp_path)
        cache = InMemoryHashCache()

        # Calcular hashes "verdadeiros" primeiro
        true_partial = DuplicateDetector._hash_sample(entries[0].path)
        true_full = DuplicateDetector._hash_full(entries[0].path)

        # Seedar cache para AMBOS os arquivos com os mesmos hashes
        # (eles são duplicatas, então hash deve ser igual)
        for f in entries:
            cache.seed_partial(f.path, true_partial)
            cache.seed_full(f.path, true_full)

        # Patch para detectar se _hash_* são chamados
        with patch.object(
            DuplicateDetector, "_hash_sample", wraps=DuplicateDetector._hash_sample
        ) as mock_sample, patch.object(
            DuplicateDetector, "_hash_full", wraps=DuplicateDetector._hash_full
        ) as mock_full:
            detector = DuplicateDetector()
            groups = detector.find_duplicates(entries, cache=cache)

        assert len(groups) == 1
        # Cache hit em ambas as etapas → sem chamadas a _hash_*
        assert mock_sample.call_count == 0, (
            f"_hash_sample não deveria ser chamado (chamadas: {mock_sample.call_count})"
        )
        assert mock_full.call_count == 0, (
            f"_hash_full não deveria ser chamado (chamadas: {mock_full.call_count})"
        )
        # Cache hits foram contabilizados, sem novos writes
        assert cache.partial_hits == 2
        assert cache.full_hits == 2
        assert len(cache.partial_writes) == 0
        assert len(cache.full_writes) == 0

    def test_partial_seed_only_skips_partial_recomputes_full(
        self, tmp_path: Path
    ):
        """Seed só de partial → partial reusado, full ainda computado."""
        from src.core.hash_cache import InMemoryHashCache

        entries = self._two_duplicates(tmp_path)
        cache = InMemoryHashCache()

        true_partial = DuplicateDetector._hash_sample(entries[0].path)
        for f in entries:
            cache.seed_partial(f.path, true_partial)
        # Note: NÃO seedamos full

        detector = DuplicateDetector()
        groups = detector.find_duplicates(entries, cache=cache)

        assert len(groups) == 1
        assert cache.partial_hits == 2
        assert len(cache.partial_writes) == 0
        # Full hash foi computado e cacheado
        assert len(cache.full_writes) == 2

    def test_null_cache_behaves_like_no_cache(self, tmp_path: Path):
        """NullHashCache é o default e não persiste nada."""
        from src.core.hash_cache import NullHashCache

        entries = self._two_duplicates(tmp_path)
        cache = NullHashCache()

        detector = DuplicateDetector()
        groups_no_arg = detector.find_duplicates(entries)
        groups_null = detector.find_duplicates(entries, cache=cache)

        # Mesmo resultado com e sem cache
        assert len(groups_no_arg) == len(groups_null) == 1

    def test_stale_cache_entry_recomputes(self, tmp_path: Path):
        """
        Se o cache tem hash 'errado' (ex: arquivo modificado mas seed não
        atualizado), o detector vai produzir resultado incorreto. Esta
        situação É responsabilidade do chamador (workers.py) — o detector
        confia no cache. Este teste documenta o contrato.
        """
        from src.core.hash_cache import InMemoryHashCache

        entries = self._two_duplicates(tmp_path)
        cache = InMemoryHashCache()

        # Seedar com hashes deliberadamente DIFERENTES entre os dois arquivos
        cache.seed_partial(entries[0].path, "hash_A_fake")
        cache.seed_partial(entries[1].path, "hash_B_fake")
        # Sem seed do full

        detector = DuplicateDetector()
        groups = detector.find_duplicates(entries, cache=cache)

        # Como os partial hashes diferem (no cache), Etapa 2 separa em grupos
        # de 1 arquivo cada → sample_candidates vazio → return [] cedo
        assert groups == []


# ---------------------------------------------------------------------------
# Testes de REGRESSÃO — Bug de gravidade ALTA em _best_sata_target e
# _best_external_target (routing-target-validation).
#
# ESTES TESTES DEVEM FALHAR com o código atual — são a rede de segurança
# para a correção que virá na próxima sessão.
#
# Três bugs codificados aqui:
#   A) helper sugere disco sem espaço suficiente para o arquivo
#   B) helper sugere o mesmo disco de origem como destino
#   C) helper retorna default hardcoded ("D:" / "J:") quando disco não existe
# ---------------------------------------------------------------------------

_1GB_REG = 1024 ** 3  # alias local para não depender do import do módulo


class TestRoutingTargetValidation:
    """
    Regressão: _best_sata_target e _best_external_target devem validar
    (a) espaço disponível, (b) que destino ≠ origem, (c) que destino existe.
    """

    # ── Teste A: não sugere disco que não comporta o arquivo ─────────────────

    def test_no_routing_suggestion_when_no_target_has_enough_space(self):
        """
        Bug A — Regra 1: se o único disco SATA tem menos espaço livre do que
        o tamanho do arquivo, o motor NÃO deve emitir sugestão de MOVER.

        Comportamento atual (ERRADO): _best_sata_target escolhe D: (maior
        free_bytes entre os candidatos) e o motor emite a sugestão mesmo com
        D: tendo só 200 MB livres para um arquivo de 2 GB.
        """
        _200MB = 200 * 1024 * 1024
        file_size = 2 * _1GB_REG  # 2 GB — não cabe em 200 MB

        partitions = [
            PartitionInfo(
                letter="C:", fstype="NTFS",
                total_bytes=1000 * _1GB_REG, used_bytes=940 * _1GB_REG,
                free_bytes=60 * _1GB_REG, percent_used=94.0,
            ),
            PartitionInfo(
                letter="D:", fstype="NTFS",
                total_bytes=500 * _1GB_REG,
                used_bytes=500 * _1GB_REG - _200MB,
                free_bytes=_200MB,
                percent_used=99.9,
            ),
        ]
        engine = SmartRulesEngine(
            nvme_letters={"C:"},
            sata_internal_letters={"D:"},
            external_letters=set(),
        )
        file = FileEntry(
            path="C:\\Users\\jeff\\filme.mkv",
            size_bytes=file_size,
            category="Vídeos",
        )

        suggestions = engine.evaluate(file, partitions)
        r1 = [s for s in suggestions if s.rule_id == 1]

        # DEVE ser vazio: nenhum SATA comporta 2 GB
        assert len(r1) == 0, (
            f"Não deve sugerir mover {file_size // _1GB_REG} GB para D: "
            f"com apenas {_200MB // (1024 ** 2)} MB livres. "
            f"Sugestões geradas: {r1}"
        )

    def test_no_routing_suggestion_when_external_target_has_no_space(self):
        """
        Bug A — Regra 3: se o único disco externo tem menos espaço livre do
        que o arquivo, o motor NÃO deve emitir sugestão de MOVER.

        Comportamento atual (ERRADO): _best_external_target retorna J: (único
        candidato) e o motor emite sugestão com destino insuficiente.
        """
        _50MB = 50 * 1024 * 1024
        file_size = 500 * 1024 * 1024  # 500 MB — não cabe em 50 MB

        partitions = [
            PartitionInfo(
                letter="C:", fstype="NTFS",
                total_bytes=1000 * _1GB_REG, used_bytes=940 * _1GB_REG,
                free_bytes=60 * _1GB_REG, percent_used=94.0,
            ),
            PartitionInfo(
                letter="J:", fstype="NTFS",
                total_bytes=3000 * _1GB_REG,
                used_bytes=3000 * _1GB_REG - _50MB,
                free_bytes=_50MB,
                percent_used=99.9,
            ),
        ]
        engine = SmartRulesEngine(
            nvme_letters={"C:"},
            sata_internal_letters=set(),
            external_letters={"J:"},
        )
        file = FileEntry(
            path="C:\\fotos.zip",
            size_bytes=file_size,
            category="Compactados",
        )

        suggestions = engine.evaluate(file, partitions)
        r3 = [s for s in suggestions if s.rule_id == 3]

        assert len(r3) == 0, (
            f"Não deve sugerir mover {file_size // (1024 ** 2)} MB para J: "
            f"com apenas {_50MB // (1024 ** 2)} MB livres. "
            f"Sugestões geradas: {r3}"
        )

    # ── Teste B: não sugere o mesmo disco de origem como destino ─────────────

    def test_no_routing_suggestion_when_target_equals_source_disk(self):
        """
        Bug B — Regra 3: quando o único disco externo disponível É o mesmo
        disco de origem (cheio), o motor NÃO deve sugerir mover para ele mesmo.

        Cenário: arquivo em J: (93% cheio, categoria Vídeos). Único candidato
        externo é J:. _best_external_target devolve "J:" como destino.

        Comportamento atual (ERRADO): ReallocationSuggestion é emitida com
        target_disk="J:" == file_drive="J:".
        """
        partitions = [
            PartitionInfo(
                letter="J:", fstype="NTFS",
                total_bytes=3000 * _1GB_REG,
                used_bytes=2790 * _1GB_REG,
                free_bytes=210 * _1GB_REG,
                percent_used=93.0,
            ),
        ]
        engine = SmartRulesEngine(
            nvme_letters=set(),
            sata_internal_letters=set(),
            external_letters={"J:"},
        )
        file = FileEntry(
            path="J:\\series\\temporada.mkv",
            size_bytes=100 * 1024 * 1024,
            category="Vídeos",
        )

        suggestions = engine.evaluate(file, partitions)
        r3 = [s for s in suggestions if s.rule_id == 3]

        # Nenhuma sugestão OU (se houver) o destino não pode ser J:
        same_disk_suggestions = [s for s in r3 if s.target_disk == "J:"]
        assert len(same_disk_suggestions) == 0, (
            "Não deve sugerir mover de J: para J: (origem == destino). "
            f"Sugestões geradas: {r3}"
        )

    # ── Teste C: não retorna disco inexistente (default hardcoded) ────────────

    def test_no_routing_suggestion_when_sata_target_does_not_exist(self):
        """
        Bug C — Regra 1: quando nenhum disco de sata_internal_letters existe
        no partition_map, o motor NÃO deve emitir sugestão com target_disk
        fabricado (ex: "D:").

        Comportamento atual (ERRADO): _best_sata_target inicializa best="D:"
        e retorna "D:" mesmo sem D: no partition_map. O motor emite sugestão
        com um destino que não existe.
        """
        # partition_map sem D: nem G: — apenas C: e J:
        partitions = [
            PartitionInfo(
                letter="C:", fstype="NTFS",
                total_bytes=1000 * _1GB_REG, used_bytes=940 * _1GB_REG,
                free_bytes=60 * _1GB_REG, percent_used=94.0,
            ),
            PartitionInfo(
                letter="J:", fstype="NTFS",
                total_bytes=3000 * _1GB_REG, used_bytes=900 * _1GB_REG,
                free_bytes=2100 * _1GB_REG, percent_used=30.0,
            ),
        ]
        engine = SmartRulesEngine(
            nvme_letters={"C:"},
            sata_internal_letters={"D:", "G:"},  # nem D: nem G: existem
            external_letters={"J:"},
        )
        file = FileEntry(
            path="C:\\Users\\jeff\\filme.mkv",
            size_bytes=2 * _1GB_REG,
            category="Vídeos",
        )

        suggestions = engine.evaluate(file, partitions)
        r1 = [s for s in suggestions if s.rule_id == 1]

        assert len(r1) == 0, (
            "Não deve emitir sugestão quando nenhum disco SATA candidato "
            f"existe no partition_map. target_disk gerado: "
            f"{[s.target_disk for s in r1]}"
        )

    def test_no_routing_suggestion_when_external_target_does_not_exist(self):
        """
        Bug C — Regra 3: quando nenhum disco de external_letters existe no
        partition_map, o motor NÃO deve emitir sugestão com "J:" fabricado.

        Comportamento atual (ERRADO): _best_external_target retorna "J:" mesmo
        sem J: ou L: no partition_map.
        """
        # Apenas C: — sem nenhum disco externo montado
        partitions = [
            PartitionInfo(
                letter="C:", fstype="NTFS",
                total_bytes=1000 * _1GB_REG, used_bytes=940 * _1GB_REG,
                free_bytes=60 * _1GB_REG, percent_used=94.0,
            ),
        ]
        engine = SmartRulesEngine(
            nvme_letters={"C:"},
            sata_internal_letters=set(),
            external_letters={"J:", "L:"},  # nem J: nem L: existem
        )
        file = FileEntry(
            path="C:\\fotos.zip",
            size_bytes=500 * 1024 * 1024,
            category="Compactados",
        )

        suggestions = engine.evaluate(file, partitions)
        r3 = [s for s in suggestions if s.rule_id == 3]

        assert len(r3) == 0, (
            "Não deve emitir sugestão quando nenhum disco externo candidato "
            f"existe no partition_map. target_disk gerado: "
            f"{[s.target_disk for s in r3]}"
        )


# ---------------------------------------------------------------------------
# Sprint 6.4 — Áudio e Modelos de IA passam pelas regras R1 e R3
# ---------------------------------------------------------------------------

class TestRule1AudioAndAIModels:
    """R1 (mídia pesada >1GB no NVMe) agora cobre áudio e modelos de IA."""

    def test_triggers_for_large_gguf_on_c(self, fake_partitions):
        engine = SmartRulesEngine()
        file = FileEntry(
            path="C:\\Users\\jeff\\models\\llama3-70b.gguf",
            size_bytes=40 * _1GB,
            category="Modelos IA",
        )
        suggestions = engine.evaluate(file, fake_partitions)
        r1 = [s for s in suggestions if s.rule_id == 1]

        assert len(r1) == 1
        assert r1[0].action == "MOVER"
        assert r1[0].target_disk in {"D:", "G:"}

    def test_triggers_for_large_flac_on_c(self, fake_partitions):
        engine = SmartRulesEngine()
        file = FileEntry(
            path="C:\\Users\\jeff\\Music\\album-lossless.flac",
            size_bytes=2 * _1GB,
            category="Áudio",
        )
        suggestions = engine.evaluate(file, fake_partitions)
        r1 = [s for s in suggestions if s.rule_id == 1]
        assert len(r1) == 1

    def test_small_audio_does_not_trigger(self, fake_partitions):
        engine = SmartRulesEngine()
        file = FileEntry(
            path="C:\\Users\\jeff\\Music\\musica.mp3",
            size_bytes=8 * 1024 * 1024,  # 8 MB < 1 GB
            category="Áudio",
        )
        suggestions = engine.evaluate(file, fake_partitions)
        r1 = [s for s in suggestions if s.rule_id == 1]
        assert len(r1) == 0


class TestRule3AudioAndAIModels:
    """R3 (disco >90% + mídia) agora cobre as categorias Áudio e Modelos IA."""

    def test_triggers_for_audio_on_full_disk(self, fake_partitions):
        engine = SmartRulesEngine()
        file = FileEntry(
            path="C:\\Users\\jeff\\Music\\set.wav",
            size_bytes=300 * 1024 * 1024,
            category="Áudio",
        )
        suggestions = engine.evaluate(file, fake_partitions)
        r3 = [s for s in suggestions if s.rule_id == 3]

        assert len(r3) == 1
        assert r3[0].target_disk == "J:"  # externo com mais espaço

    def test_triggers_for_ai_model_on_full_disk(self, fake_partitions):
        engine = SmartRulesEngine()
        file = FileEntry(
            path="C:\\models\\mistral.safetensors",
            size_bytes=15 * _1GB,
            category="Modelos IA",
        )
        suggestions = engine.evaluate(file, fake_partitions)
        r3 = [s for s in suggestions if s.rule_id == 3]

        assert len(r3) == 1
        assert r3[0].target_disk == "J:"
