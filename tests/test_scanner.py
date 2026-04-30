"""
Testes para src.core.scanner — StorageScanner.

Cobre:
  - Categorização de arquivos por extensão (3.2)
  - top_largest_files() com diretório real (3.2)
  - Exclusão de pastas do sistema (Seção 5)
  - list_partitions() via mock do psutil (3.1)
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.core.scanner import (
    StorageScanner,
    FileEntry,
    PartitionInfo,
    FILE_CATEGORIES,
    SYSTEM_EXCLUDED_DIRS,
)


# ---------------------------------------------------------------------------
# _categorize()
# ---------------------------------------------------------------------------

class TestCategorize:
    """Testa classificação de arquivos por extensão."""

    scanner = StorageScanner()

    @pytest.mark.parametrize("filename, expected_category", [
        ("video.mp4", "Vídeos"),
        ("video.MKV", "Vídeos"),
        ("video.avi", "Vídeos"),
        ("foto.jpg", "Imagens"),
        ("foto.JPEG", "Imagens"),
        ("foto.png", "Imagens"),
        ("foto.webp", "Imagens"),
        ("relatorio.pdf", "Documentos"),
        ("planilha.xlsx", "Documentos"),
        ("texto.txt", "Documentos"),
        ("dados.csv", "Documentos"),
        ("setup.exe", "Executáveis"),
        ("installer.msi", "Executáveis"),
        ("script.bat", "Executáveis"),
        ("backup.zip", "Compactados"),
        ("arquivo.rar", "Compactados"),
        ("pacote.7z", "Compactados"),
        ("imagem.iso", "Compactados"),
        ("arquivo.tar", "Compactados"),
        # Arquivos sem categoria definida → "Outros"
        ("dados.db", "Outros"),
        ("sem_extensao", "Outros"),
        ("config.ini", "Outros"),
        (".gitignore", "Outros"),
    ])
    def test_categorize_by_extension(self, filename: str, expected_category: str):
        assert self.scanner._categorize(filename) == expected_category

    def test_all_spec_categories_have_entries(self):
        """Garante que todas as categorias da spec são testáveis."""
        expected = {"Imagens", "Vídeos", "Documentos", "Executáveis", "Compactados"}
        assert set(FILE_CATEGORIES.keys()) == expected


# ---------------------------------------------------------------------------
# top_largest_files()
# ---------------------------------------------------------------------------

class TestTopLargestFiles:
    """Testa varredura e ranking de maiores arquivos."""

    def test_returns_sorted_by_size(self, tmp_files_dir: Path):
        scanner = StorageScanner()
        files = scanner.top_largest_files(tmp_files_dir, n=50)

        assert len(files) > 0
        sizes = [f.size_bytes for f in files]
        assert sizes == sorted(sizes, reverse=True), "Deve estar em ordem decrescente"

    def test_respects_n_limit(self, tmp_files_dir: Path):
        scanner = StorageScanner()
        files = scanner.top_largest_files(tmp_files_dir, n=3)

        assert len(files) == 3

    def test_returns_empty_for_nonexistent_dir(self):
        scanner = StorageScanner()
        files = scanner.top_largest_files("Z:\\dir_que_nao_existe", n=10)

        assert files == []

    def test_includes_nested_files(self, tmp_files_dir: Path):
        scanner = StorageScanner()
        files = scanner.top_largest_files(tmp_files_dir, n=50)

        paths = [f.path for f in files]
        nested = [p for p in paths if "subdir" in p]
        assert len(nested) >= 1, "Deve incluir arquivos de subdiretórios"

    def test_assigns_correct_categories(self, tmp_files_dir: Path):
        scanner = StorageScanner()
        files = scanner.top_largest_files(tmp_files_dir, n=50)

        by_name = {Path(f.path).name: f.category for f in files}

        assert by_name.get("video.mp4") == "Vídeos"
        assert by_name.get("foto.jpg") == "Imagens"
        assert by_name.get("planilha.xlsx") == "Documentos"
        assert by_name.get("app.exe") == "Executáveis"
        assert by_name.get("backup.zip") == "Compactados"

    def test_excludes_system_dirs(self, tmp_path: Path):
        """Pastas protegidas do sistema devem ser puladas (Seção 5)."""
        scanner = StorageScanner()

        # Criar uma pasta com nome de sistema + arquivo dentro
        system_dir = tmp_path / "Windows"
        system_dir.mkdir()
        (system_dir / "system_file.dll").write_bytes(b"\x00" * 10000)

        # Criar um arquivo normal fora
        (tmp_path / "normal.txt").write_bytes(b"conteudo normal\n")

        files = scanner.top_largest_files(tmp_path, n=50)
        paths = [f.path for f in files]

        # O arquivo dentro de "Windows" não deve aparecer
        system_files = [p for p in paths if "Windows" in p]
        assert len(system_files) == 0, "Pastas do sistema devem ser excluídas"

        # O arquivo normal deve aparecer
        normal_files = [p for p in paths if "normal.txt" in p]
        assert len(normal_files) == 1

    def test_handles_permission_error_gracefully(self, tmp_path: Path):
        """Arquivos inacessíveis devem ser pulados sem crash."""
        scanner = StorageScanner()
        (tmp_path / "ok.txt").write_bytes(b"acessivel\n")

        # Mock os.path.getsize para lançar PermissionError em 1 arquivo
        original_getsize = os.path.getsize

        def patched_getsize(path):
            if "blocked" in str(path):
                raise PermissionError("Bloqueado pelo AV")
            return original_getsize(path)

        (tmp_path / "blocked.dat").write_bytes(b"\x00" * 100)

        with patch("os.path.getsize", side_effect=patched_getsize):
            files = scanner.top_largest_files(tmp_path, n=50)

        # Não deve crashar; deve retornar pelo menos o arquivo ok.txt
        names = [Path(f.path).name for f in files]
        assert "ok.txt" in names
        assert "blocked.dat" not in names


# ---------------------------------------------------------------------------
# list_partitions() — com mock do psutil
# ---------------------------------------------------------------------------

class TestListPartitions:
    """Testa mapeamento de partições com psutil mockado."""

    def test_returns_partition_info_list(self):
        scanner = StorageScanner()

        mock_part = MagicMock()
        mock_part.mountpoint = "C:\\"
        mock_part.fstype = "NTFS"
        mock_part.opts = "rw,compress"

        mock_usage = MagicMock()
        mock_usage.total = 1_000_000_000_000
        mock_usage.used = 800_000_000_000
        mock_usage.free = 200_000_000_000
        mock_usage.percent = 80.0

        with patch("psutil.disk_partitions", return_value=[mock_part]), \
             patch("psutil.disk_usage", return_value=mock_usage), \
             patch.object(StorageScanner, "_detect_media_types", return_value={"C:": "NVMe"}):

            partitions = scanner.list_partitions()

        assert len(partitions) == 1
        p = partitions[0]
        assert p.letter == "C:"
        assert p.fstype == "NTFS"
        assert p.percent_used == 80.0
        assert p.media_type == "NVMe"

    def test_skips_inaccessible_partitions(self):
        scanner = StorageScanner()

        mock_part = MagicMock()
        mock_part.mountpoint = "E:\\"
        mock_part.fstype = "CDFS"
        mock_part.opts = ""

        with patch("psutil.disk_partitions", return_value=[mock_part]), \
             patch("psutil.disk_usage", side_effect=OSError("No media")), \
             patch.object(StorageScanner, "_detect_media_types", return_value={}):

            partitions = scanner.list_partitions()

        assert len(partitions) == 0

    def test_skips_permission_denied(self):
        scanner = StorageScanner()

        mock_part = MagicMock()
        mock_part.mountpoint = "F:\\"
        mock_part.fstype = "NTFS"
        mock_part.opts = ""

        with patch("psutil.disk_partitions", return_value=[mock_part]), \
             patch("psutil.disk_usage", side_effect=PermissionError("Acesso negado")), \
             patch.object(StorageScanner, "_detect_media_types", return_value={}):

            partitions = scanner.list_partitions()

        assert len(partitions) == 0


# ---------------------------------------------------------------------------
# PartitionInfo properties
# ---------------------------------------------------------------------------

class TestPartitionInfoProperties:
    """Testa propriedades calculadas de PartitionInfo."""

    def test_total_gb(self):
        p = PartitionInfo(
            letter="D:", fstype="NTFS",
            total_bytes=2_000_000_000_000,
            used_bytes=1_000_000_000_000,
            free_bytes=1_000_000_000_000,
            percent_used=50.0,
        )
        assert abs(p.total_gb - 1862.65) < 1  # ~1.86 TB ≈ 1862 GB

    def test_free_gb(self):
        p = PartitionInfo(
            letter="C:", fstype="NTFS",
            total_bytes=1_000_000_000_000,
            used_bytes=900_000_000_000,
            free_bytes=100_000_000_000,
            percent_used=90.0,
        )
        assert abs(p.free_gb - 93.13) < 1

    def test_repr_contains_letter(self):
        p = PartitionInfo(
            letter="G:", fstype="NTFS",
            total_bytes=500_000_000_000,
            used_bytes=250_000_000_000,
            free_bytes=250_000_000_000,
            percent_used=50.0,
            media_type="HDD",
        )
        r = repr(p)
        assert "G:" in r
        assert "HDD" in r


# ---------------------------------------------------------------------------
# FileEntry properties
# ---------------------------------------------------------------------------

class TestFileEntryProperties:
    """Testa propriedades calculadas de FileEntry."""

    def test_size_mb(self):
        f = FileEntry(path="C:\\file.txt", size_bytes=10_485_760)  # 10 MB
        assert f.size_mb == 10.0

    def test_size_mb_small(self):
        f = FileEntry(path="C:\\small.txt", size_bytes=1024)
        assert f.size_mb == pytest.approx(0.001, abs=0.01)
