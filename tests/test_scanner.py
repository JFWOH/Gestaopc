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
    DirEntry,
    FileEntry,
    PartitionInfo,
    FILE_CATEGORIES,
    _MEDIA_TYPE_PS_SCRIPT,
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
        # Sprint 6.4: "Áudio" e "Modelos IA" adicionadas.
        expected = {
            "Imagens", "Vídeos", "Áudio", "Documentos",
            "Executáveis", "Compactados", "Modelos IA",
        }
        assert set(FILE_CATEGORIES.keys()) == expected

    @pytest.mark.parametrize("filename, expected_category", [
        # Áudio (6.4) — antes caía em "Outros"
        ("musica.mp3", "Áudio"),
        ("trilha.FLAC", "Áudio"),
        ("som.wav", "Áudio"),
        ("podcast.m4a", "Áudio"),
        ("audio.aac", "Áudio"),
        ("stream.ogg", "Áudio"),
        # Modelos de IA (6.4) — antes caía em "Outros"
        ("llama3.gguf", "Modelos IA"),
        ("model.SAFETENSORS", "Modelos IA"),
        ("weights.bin", "Modelos IA"),
    ])
    def test_categorize_audio_and_ai_models(self, filename: str, expected_category: str):
        """Regressão 6.4: áudio e modelos de IA não devem cair em 'Outros'."""
        assert self.scanner._categorize(filename) == expected_category


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
        (tmp_path / "blocked.dat").write_bytes(b"\x00" * 100)

        # Mock os.stat para lançar PermissionError em arquivos com "blocked"
        # (a implementação usa os.stat em uma única syscall para size+mtime).
        original_stat = os.stat

        def patched_stat(path, *args, **kwargs):
            if "blocked" in str(path):
                raise PermissionError("Bloqueado pelo AV")
            return original_stat(path, *args, **kwargs)

        with patch("os.stat", side_effect=patched_stat):
            files = scanner.top_largest_files(tmp_path, n=50)

        # Não deve crashar; deve retornar pelo menos o arquivo ok.txt
        names = [Path(f.path).name for f in files]
        assert "ok.txt" in names
        assert "blocked.dat" not in names

    def test_file_entry_has_modified_time(self, tmp_files_dir: Path):
        """Regressão: FileEntry deve trazer modified_time preenchido (epoch)."""
        scanner = StorageScanner()
        files = scanner.top_largest_files(tmp_files_dir, n=50)

        assert len(files) > 0
        for f in files:
            # Atributo deve existir e ser float positivo (timestamp Unix)
            assert hasattr(f, "modified_time"), (
                "FileEntry deve expor modified_time para persistência no DB"
            )
            assert isinstance(f.modified_time, float)
            assert f.modified_time > 0, (
                f"modified_time inválido: {f.modified_time} para {f.path}"
            )

    def test_heap_returns_the_n_largest(self, tmp_path: Path):
        """E2: com mais arquivos que N, retorna exatamente os N maiores."""
        scanner = StorageScanner()
        # 10 arquivos com tamanhos distintos 100, 200, ..., 1000 bytes.
        for i in range(1, 11):
            (tmp_path / f"f{i:02d}.bin").write_bytes(b"\x00" * (i * 100))

        files = scanner.top_largest_files(tmp_path, n=3)
        sizes = [f.size_bytes for f in files]
        assert sizes == [1000, 900, 800], "deve trazer só os 3 maiores, em ordem"

    def test_heap_n_zero_returns_empty(self, tmp_path: Path):
        """E2: n=0 não deve quebrar e retorna lista vazia."""
        scanner = StorageScanner()
        (tmp_path / "a.bin").write_bytes(b"\x00" * 100)
        assert scanner.top_largest_files(tmp_path, n=0) == []


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

    def test_warns_when_media_detection_fails(self, caplog):
        """RECON 8.3.4 — mapa de mídia vazio com partições presentes deve avisar."""
        scanner = StorageScanner()

        mock_part = MagicMock()
        mock_part.mountpoint = "C:\\"
        mock_part.fstype = "NTFS"
        mock_part.opts = ""

        mock_usage = MagicMock()
        mock_usage.total = 500_000_000_000
        mock_usage.used = 100_000_000_000
        mock_usage.free = 400_000_000_000
        mock_usage.percent = 20.0

        with patch("psutil.disk_partitions", return_value=[mock_part]), \
             patch("psutil.disk_usage", return_value=mock_usage), \
             patch.object(StorageScanner, "_detect_media_types", return_value={}), \
             caplog.at_level("WARNING"):

            partitions = scanner.list_partitions()

        assert len(partitions) == 1
        assert partitions[0].media_type == "Desconhecido"
        assert any(
            "Detecção de tipo de disco indisponível" in rec.message
            for rec in caplog.records
        )

    def test_no_warning_when_media_detected(self, caplog):
        """Mapa de mídia presente NÃO deve emitir o aviso de degradação."""
        scanner = StorageScanner()

        mock_part = MagicMock()
        mock_part.mountpoint = "C:\\"
        mock_part.fstype = "NTFS"
        mock_part.opts = ""

        mock_usage = MagicMock()
        mock_usage.total = 500_000_000_000
        mock_usage.used = 100_000_000_000
        mock_usage.free = 400_000_000_000
        mock_usage.percent = 20.0

        with patch("psutil.disk_partitions", return_value=[mock_part]), \
             patch("psutil.disk_usage", return_value=mock_usage), \
             patch.object(StorageScanner, "_detect_media_types", return_value={"C:": "NVMe"}), \
             caplog.at_level("WARNING"):

            scanner.list_partitions()

        assert not any(
            "Detecção de tipo de disco indisponível" in rec.message
            for rec in caplog.records
        )


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

    def test_modified_time_default_is_zero(self):
        """Se não informado, modified_time = 0.0 (desconhecido)."""
        f = FileEntry(path="C:\\file.txt", size_bytes=100)
        assert f.modified_time == 0.0

    def test_modified_time_explicit(self):
        """Aceita timestamp epoch como float."""
        ts = 1_700_000_000.5
        f = FileEntry(path="C:\\file.txt", size_bytes=100, modified_time=ts)
        assert f.modified_time == ts

    def test_db_persistence_signature_compat(self):
        """
        Regressão para o bug 'AttributeError: FileEntry has no attribute
        modified_time' que crashava workers.py após Etapa 3 da varredura.
        Garante que os 3 atributos lidos por workers.py existem.
        """
        f = FileEntry(
            path="C:\\file.txt",
            size_bytes=100,
            category="Outros",
            modified_time=123.0,
        )
        # Campos efetivamente lidos em workers.py linha ~265
        assert f.path == "C:\\file.txt"
        assert f.size_bytes == 100
        assert f.modified_time == 123.0
        assert f.category == "Outros"


# ---------------------------------------------------------------------------
# DirEntry properties
# ---------------------------------------------------------------------------

class TestDirEntryProperties:
    """Testa propriedades calculadas de DirEntry."""

    def test_size_gb(self):
        d = DirEntry(
            path="D:\\Filmes",
            total_size_bytes=2 * 1024 ** 3,
            file_count=5,
        )
        assert d.size_gb == 2.0

    def test_size_mb(self):
        d = DirEntry(
            path="D:\\Downloads",
            total_size_bytes=512 * 1024 ** 2,
            file_count=10,
        )
        assert d.size_mb == 512.0

    def test_repr_contains_path(self):
        d = DirEntry(path="E:\\Backup", total_size_bytes=1024, file_count=2)
        r = repr(d)
        assert "E:\\Backup" in r
        assert "arquivos" in r


# ---------------------------------------------------------------------------
# top_dirs()
# ---------------------------------------------------------------------------

class TestTopDirs:
    """Testa varredura e ranking dos maiores diretórios."""

    def test_returns_empty_for_nonexistent_dir(self):
        scanner = StorageScanner()
        result = scanner.top_largest_dirs("Z:\\diretorio_que_nao_existe_mesmo", n=10)
        assert result == []

    def test_returns_dirs_sorted_by_size(self, tmp_path: Path):
        scanner = StorageScanner()
        big = tmp_path / "big_dir"
        big.mkdir()
        (big / "file.bin").write_bytes(b"\x00" * 10_000)

        small = tmp_path / "small_dir"
        small.mkdir()
        (small / "file.bin").write_bytes(b"\x00" * 100)

        results = scanner.top_largest_dirs(str(tmp_path), n=10)
        assert len(results) >= 2
        sizes = [d.total_size_bytes for d in results]
        assert sizes == sorted(sizes, reverse=True), "Deve estar em ordem decrescente"

    def test_respects_n_limit(self, tmp_path: Path):
        scanner = StorageScanner()
        for i in range(5):
            d = tmp_path / f"dir_{i}"
            d.mkdir()
            (d / "f.bin").write_bytes(b"\x00" * (1_000 * (i + 1)))

        results = scanner.top_largest_dirs(str(tmp_path), n=3)
        assert len(results) <= 3

    def test_skips_system_excluded_dirs(self, tmp_path: Path):
        scanner = StorageScanner()
        sys_dir = tmp_path / "Windows"
        sys_dir.mkdir()
        (sys_dir / "file.sys").write_bytes(b"\x00" * 5_000)

        normal = tmp_path / "meus_arquivos"
        normal.mkdir()
        (normal / "file.bin").write_bytes(b"\x00" * 3_000)

        results = scanner.top_largest_dirs(str(tmp_path), n=10)
        paths = [d.path for d in results]
        assert not any("Windows" in p for p in paths), "Dir do sistema deve ser ignorado"
        assert any("meus_arquivos" in p for p in paths)

    def test_skips_dollar_sign_dirs(self, tmp_path: Path):
        scanner = StorageScanner()
        dollar_dir = tmp_path / "$RECYCLE.BIN"
        dollar_dir.mkdir()
        (dollar_dir / "trash.bin").write_bytes(b"\x00" * 5_000)

        normal = tmp_path / "normal"
        normal.mkdir()
        (normal / "file.txt").write_bytes(b"\x00" * 1_000)

        results = scanner.top_largest_dirs(str(tmp_path), n=10)
        paths = [d.path for d in results]
        assert not any("$RECYCLE" in p for p in paths), "Diretório $ deve ser ignorado"

    def test_excludes_empty_dirs(self, tmp_path: Path):
        scanner = StorageScanner()
        empty = tmp_path / "vazio"
        empty.mkdir()
        # Nenhum arquivo criado dentro

        results = scanner.top_largest_dirs(str(tmp_path), n=10)
        paths = [d.path for d in results]
        assert not any("vazio" in p for p in paths), "Diretório vazio (0 bytes) deve ser excluído"

    def test_dir_entry_has_correct_size_and_count(self, tmp_path: Path):
        scanner = StorageScanner()
        d = tmp_path / "my_dir"
        d.mkdir()
        (d / "a.txt").write_bytes(b"\x00" * 1_024)
        (d / "b.txt").write_bytes(b"\x00" * 2_048)

        results = scanner.top_largest_dirs(str(tmp_path), n=10)
        assert len(results) == 1
        entry = results[0]
        assert entry.total_size_bytes == 3_072
        assert entry.file_count == 2
        assert "my_dir" in entry.path

    def test_returns_dir_entry_instances(self, tmp_path: Path):
        scanner = StorageScanner()
        d = tmp_path / "dir_teste"
        d.mkdir()
        (d / "file.bin").write_bytes(b"\x00" * 512)

        results = scanner.top_largest_dirs(str(tmp_path), n=10)
        assert len(results) == 1
        assert isinstance(results[0], DirEntry)


# ---------------------------------------------------------------------------
# _dir_size_recursive()
# ---------------------------------------------------------------------------

class TestDirSizeRecursive:
    """Testa o cálculo recursivo de tamanho de diretórios."""

    def test_sums_files_in_flat_dir(self, tmp_path: Path):
        (tmp_path / "a.txt").write_bytes(b"\x00" * 1_000)
        (tmp_path / "b.txt").write_bytes(b"\x00" * 2_000)

        size, count = StorageScanner._dir_size_recursive(str(tmp_path))
        assert size == 3_000
        assert count == 2

    def test_empty_dir_returns_zeros(self, tmp_path: Path):
        size, count = StorageScanner._dir_size_recursive(str(tmp_path))
        assert size == 0
        assert count == 0

    def test_recurses_into_subdirs(self, tmp_path: Path):
        (tmp_path / "root.txt").write_bytes(b"\x00" * 500)
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "nested.txt").write_bytes(b"\x00" * 300)

        size, count = StorageScanner._dir_size_recursive(str(tmp_path), max_depth=2)
        assert size == 800
        assert count == 2

    def test_sums_all_levels_ignoring_max_depth(self, tmp_path: Path):
        """
        Regressão 6.1: a soma agora percorre TODA a árvore, independentemente
        de max_depth. Antes, com max_depth=1, deep.txt (nível 2) era excluído
        e a pasta era subcontada.
        """
        # depth 0: root file
        (tmp_path / "root.txt").write_bytes(b"\x00" * 1_000)
        # depth 1: sub
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "sub.txt").write_bytes(b"\x00" * 500)
        # depth 2: deep — antes era excluído com max_depth=1; agora deve contar
        deep = sub / "deep"
        deep.mkdir()
        (deep / "deep.txt").write_bytes(b"\x00" * 200)

        # max_depth=1 não limita mais a soma: todos os 3 arquivos contam.
        size, count = StorageScanner._dir_size_recursive(
            str(tmp_path), max_depth=1, current_depth=0
        )
        assert size == 1_700   # root.txt + sub.txt + deep.txt
        assert count == 3

    def test_deep_nesting_fully_counted(self, tmp_path: Path):
        """
        Regressão 6.1: estrutura de 5 níveis (ex: node_modules, .git/objects)
        deve ter o tamanho somado por completo, não subcontado.
        """
        current = tmp_path
        # Cria nivel1/.../nivel5, cada um com um arquivo de 100 bytes.
        for level in range(1, 6):
            current = current / f"nivel{level}"
            current.mkdir()
            (current / f"f{level}.bin").write_bytes(b"\x00" * 100)

        size, count = StorageScanner._dir_size_recursive(str(tmp_path), max_depth=2)
        assert size == 500   # 5 arquivos × 100 bytes, todos os níveis
        assert count == 5

    def test_handles_permission_error_on_subdir(self, tmp_path: Path):
        (tmp_path / "ok.txt").write_bytes(b"\x00" * 100)
        blocked = tmp_path / "blocked_sub"
        blocked.mkdir()
        (blocked / "secret.txt").write_bytes(b"\x00" * 1_000)

        original_scandir = os.scandir

        def patched_scandir(path):
            if "blocked_sub" in str(path):
                raise PermissionError("Acesso negado")
            return original_scandir(path)

        with patch("os.scandir", side_effect=patched_scandir):
            size, count = StorageScanner._dir_size_recursive(
                str(tmp_path), max_depth=2
            )

        # Apenas ok.txt deve ser contado
        assert size == 100
        assert count == 1

    def test_skips_system_excluded_subdirs_during_recursion(self, tmp_path: Path):
        (tmp_path / "normal.txt").write_bytes(b"\x00" * 500)
        windows_dir = tmp_path / "Windows"
        windows_dir.mkdir()
        (windows_dir / "system.dll").write_bytes(b"\x00" * 5_000)

        # "Windows" está em SYSTEM_EXCLUDED_DIRS → deve ser ignorado na recursão
        size, count = StorageScanner._dir_size_recursive(str(tmp_path), max_depth=2)
        assert size == 500
        assert count == 1

    def test_skips_entry_when_stat_raises_permission_error(self, tmp_path: Path):
        """Erro de stat() em um entry específico não deve crashar; entry é silenciosamente ignorado."""
        from unittest.mock import MagicMock

        # Criar entradas falsas para simular um arquivo cujo stat() falha
        good_entry = MagicMock()
        good_entry.name = "ok.txt"
        good_entry.path = str(tmp_path / "ok.txt")
        good_entry.is_file.return_value = True
        good_entry.is_dir.return_value = False
        stat_result = MagicMock()
        stat_result.st_size = 300
        good_entry.stat.return_value = stat_result

        bad_entry = MagicMock()
        bad_entry.name = "locked.txt"
        bad_entry.path = str(tmp_path / "locked.txt")
        bad_entry.is_file.return_value = True
        bad_entry.is_dir.return_value = False
        bad_entry.stat.side_effect = PermissionError("Acesso negado ao stat()")

        with patch("os.scandir", return_value=iter([good_entry, bad_entry])):
            size, count = StorageScanner._dir_size_recursive(str(tmp_path), max_depth=2)

        # Apenas o entry válido deve ser contado
        assert size == 300
        assert count == 1


class TestTopLargestDirsEdgeCases:
    """Cobre branches de erro em top_largest_dirs não atingidos pelos testes principais."""

    def test_handles_permission_error_on_scandir(self, tmp_path: Path):
        """PermissionError no os.scandir() de top_largest_dirs deve retornar lista vazia."""
        scanner = StorageScanner()

        with patch("os.scandir", side_effect=PermissionError("Acesso negado")):
            results = scanner.top_largest_dirs(str(tmp_path), n=10)

        assert results == []

    def test_ignores_files_at_root_level(self, tmp_path: Path):
        """Entradas não-diretório na raiz devem ser ignoradas (branch L308: continue)."""
        scanner = StorageScanner()
        # Arquivo diretamente na raiz — não é diretório, deve ser ignorado
        (tmp_path / "root_file.txt").write_bytes(b"\x00" * 100)
        # Diretório com conteúdo — deve aparecer nos resultados
        d = tmp_path / "valid_dir"
        d.mkdir()
        (d / "file.bin").write_bytes(b"\x00" * 200)

        results = scanner.top_largest_dirs(str(tmp_path), n=10)

        assert len(results) == 1
        assert "valid_dir" in results[0].path


class TestMediaTypeDetectionFallback:
    """
    Regressão 6.3: o script PowerShell de detecção de tipo de mídia NÃO deve
    classificar silenciosamente bus/mídia desconhecidos como 'SSD'. O fallback
    correto é 'Desconhecido' (honesto, e bate com o default de PartitionInfo).
    """

    def test_unknown_bus_fallback_is_desconhecido_not_ssd(self):
        # O branch 'else' final (bus/mídia desconhecidos) atribui 'Desconhecido'.
        assert "$result[$letter] = 'Desconhecido'" in _MEDIA_TYPE_PS_SCRIPT

    def test_no_silent_ssd_default(self):
        # 'SSD' só pode ser atribuído via o teste explícito de MediaType — uma
        # única atribuição. Se alguém reintroduzir o fallback silencioso 'SSD',
        # haverá 2 atribuições e este teste falha.
        assert _MEDIA_TYPE_PS_SCRIPT.count("$result[$letter] = 'SSD'") == 1

    def test_legitimate_media_branches_preserved(self):
        # As classificações reais continuam presentes.
        for assignment in (
            "$result[$letter] = 'NVMe'",
            "$result[$letter] = 'SSD'",
            "$result[$letter] = 'HDD'",
        ):
            assert assignment in _MEDIA_TYPE_PS_SCRIPT
