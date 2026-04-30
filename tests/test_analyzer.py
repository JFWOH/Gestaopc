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

import pytest

from src.core.scanner import FileEntry, PartitionInfo
from src.core.analyzer import (
    DuplicateDetector,
    DuplicateGroup,
    SmartRulesEngine,
    ReallocationSuggestion,
    _HEAVY_MEDIA_EXTENSIONS,
    _1GB,
    _MEDIA_CATEGORIES,
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
