"""
Fixtures compartilhadas para os testes do GestaoPC.

Fornece diretórios temporários pré-populados, PartitionInfo mock
e listas de FileEntry prontas para uso.
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path

from src.core.scanner import FileEntry, PartitionInfo


# ---------------------------------------------------------------------------
# Segmentação de testes — RECON 8.3.5
# ---------------------------------------------------------------------------
# Classificação single-source-of-truth: cada arquivo de teste é marcado
# automaticamente como `unit` ou `integration` por este hook, evitando
# espalhar `pytestmark` (e o risco de E402 após importorskip) por 16 arquivos.
#
#   unit         → mocks/tmp_path puro, sem I/O pesado, subprocess ou Qt widgets
#   integration  → real I/O, SQLite em disco, Qt widgets, threads, hashing SHA-256
#
# `pytest -m unit` dá feedback rápido; `pytest -m integration` roda o resto.
# Os markers estão registrados em pyproject.toml ([tool.pytest.ini_options]).

_UNIT_TEST_FILES = frozenset({
    "test_config.py",
    "test_path_guard.py",
    "test_hash_cache.py",
    "test_skills_loader.py",
    "test_ollama_client.py",   # HTTP totalmente mockado
    "test_mcp_server.py",      # patches tb, sem rede
    "test_ai_toolbelt.py",
    "test_ai_backend.py",      # conformidade estrutural do Protocol (Fase C)
})

_INTEGRATION_TEST_FILES = frozenset({
    "test_executor.py",
    "test_scanner.py",
    "test_analyzer.py",
    "test_scan_status_panel.py",
    "test_assistant_tab_lifecycle.py",
    "test_telemetry.py",
    "test_storage_db.py",
    "test_workers_signals.py",
    "test_log_bridge.py",
})


def pytest_collection_modifyitems(config, items):
    """Aplica os markers unit/integration por arquivo de origem do teste."""
    for item in items:
        filename = os.path.basename(str(item.fspath))
        if filename in _UNIT_TEST_FILES:
            item.add_marker(pytest.mark.unit)
        elif filename in _INTEGRATION_TEST_FILES:
            item.add_marker(pytest.mark.integration)


# ---------------------------------------------------------------------------
# QApplication — fixture de sessão única (Sprint 7.3.1)
# ---------------------------------------------------------------------------
# PySide6 (e Qt em geral) só permite UMA instância de QCoreApplication-derived
# por processo. Como temos arquivos de teste que precisam só de QCoreApplication
# (log_bridge, workers_signals — sem widgets) e outros que precisam de
# QApplication completa (scan_status_panel — com QFrame/QWidget), criar a
# QCoreApplication primeiro impede que QApplication seja criada depois.
#
# A fixture session-scoped abaixo cria QApplication uma única vez (que É-UMA
# QCoreApplication), atendendo ambos os casos. Os arquivos individuais que
# tinham `qapp` local agora podem reusar esta — mas mantemos as deles para
# não quebrar imports; a session-scoped é importada automaticamente pelo
# pytest e garante que QApplication existe antes de qualquer teste rodar.

@pytest.fixture(scope="session", autouse=True)
def _qt_application():
    """
    Cria a QApplication na primeira invocação e a mantém viva pela sessão.

    autouse=True garante que existe ANTES de qualquer fixture qapp local
    tentar `QCoreApplication.instance() or QCoreApplication([])` — neste caso
    instance() já retorna a QApplication, satisfazendo ambos os tipos.
    """
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        # PySide6 não instalado — pulamos silenciosamente. Testes Qt vão pular
        # via pytest.importorskip("PySide6") nos arquivos individuais.
        yield None
        return

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
    # Não chamamos app.quit() — deixar o GC do Python encerrar limpa.


# ---------------------------------------------------------------------------
# Constantes de teste
# ---------------------------------------------------------------------------

_1GB = 1024 ** 3
_DUP_CONTENT = b"CONTEUDO DUPLICADO PARA TESTES " * 500   # ~15 KB
_UNIQUE_CONTENT = b"CONTEUDO UNICO DIFERENTE " * 500       # ~12.5 KB


# ---------------------------------------------------------------------------
# Fixtures de diretório
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_files_dir(tmp_path: Path) -> Path:
    """
    Cria um diretório temporário com arquivos variados para teste:

      tmp_path/
        doc1.txt          (duplicata A)
        doc2.txt          (duplicata B — conteúdo idêntico a doc1)
        doc3.txt          (duplicata C — conteúdo idêntico a doc1)
        unico.txt         (conteúdo diferente, mesmo tamanho de doc1)
        diferente.log     (tamanho completamente diferente)
        video.mp4         (arquivo pequeno, extensão de vídeo)
        foto.jpg          (arquivo pequeno, extensão de imagem)
        planilha.xlsx     (arquivo pequeno, extensão de documento)
        app.exe           (arquivo pequeno, extensão de executável)
        backup.zip        (arquivo pequeno, extensão de compactado)
        sem_ext           (sem extensão)
        subdir/
          nested.txt      (arquivo em subdiretório)
    """
    # Duplicatas
    (tmp_path / "doc1.txt").write_bytes(_DUP_CONTENT)
    (tmp_path / "doc2.txt").write_bytes(_DUP_CONTENT)
    (tmp_path / "doc3.txt").write_bytes(_DUP_CONTENT)

    # Mesmo tamanho, conteúdo diferente (NÃO é duplicata)
    unique = b"X" * len(_DUP_CONTENT)
    (tmp_path / "unico.txt").write_bytes(unique)

    # Tamanho diferente
    (tmp_path / "diferente.log").write_bytes(b"log line\n" * 10)

    # Arquivos por categoria
    (tmp_path / "video.mp4").write_bytes(b"\x00" * 256)
    (tmp_path / "foto.jpg").write_bytes(b"\xFF\xD8\xFF" + b"\x00" * 128)
    (tmp_path / "planilha.xlsx").write_bytes(b"PK" + b"\x00" * 64)
    (tmp_path / "app.exe").write_bytes(b"MZ" + b"\x00" * 128)
    (tmp_path / "backup.zip").write_bytes(b"PK\x03\x04" + b"\x00" * 100)
    (tmp_path / "sem_ext").write_bytes(b"sem extensao\n")

    # Subdiretório
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "nested.txt").write_bytes(b"arquivo aninhado\n" * 20)

    return tmp_path


@pytest.fixture
def fake_file_entries(tmp_files_dir: Path) -> list[FileEntry]:
    """
    Lista de FileEntry construída a partir de tmp_files_dir.
    Inclui categorias atribuídas corretamente.
    """
    from src.core.scanner import StorageScanner

    scanner = StorageScanner()
    entries: list[FileEntry] = []

    for root, _dirs, files in os.walk(tmp_files_dir):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                size = os.path.getsize(fpath)
            except OSError:
                continue
            category = scanner._categorize(fname)
            entries.append(FileEntry(path=fpath, size_bytes=size, category=category))

    return entries


# ---------------------------------------------------------------------------
# Fixtures de partições
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_partitions() -> list[PartitionInfo]:
    """
    Lista de PartitionInfo simulando o cenário do hardware alvo (spec seção 2).

    - C: NVMe 1TB, 94% cheio (CRÍTICO)
    - D: HDD SATA 2TB, 60% cheio
    - G: HDD SATA 1TB, 45% cheio
    - J: HDD Externo 3TB, 30% cheio
    - L: HDD Externo 3TB, 85% cheio
    """
    return [
        PartitionInfo(
            letter="C:", fstype="NTFS",
            total_bytes=1000 * _1GB, used_bytes=940 * _1GB,
            free_bytes=60 * _1GB, percent_used=94.0,
            media_type="NVMe",
        ),
        PartitionInfo(
            letter="D:", fstype="NTFS",
            total_bytes=2000 * _1GB, used_bytes=1200 * _1GB,
            free_bytes=800 * _1GB, percent_used=60.0,
            media_type="HDD",
        ),
        PartitionInfo(
            letter="G:", fstype="NTFS",
            total_bytes=1000 * _1GB, used_bytes=450 * _1GB,
            free_bytes=550 * _1GB, percent_used=45.0,
            media_type="HDD",
        ),
        PartitionInfo(
            letter="J:", fstype="NTFS",
            total_bytes=3000 * _1GB, used_bytes=900 * _1GB,
            free_bytes=2100 * _1GB, percent_used=30.0,
            media_type="HDD",
        ),
        PartitionInfo(
            letter="L:", fstype="NTFS",
            total_bytes=3000 * _1GB, used_bytes=2550 * _1GB,
            free_bytes=450 * _1GB, percent_used=85.0,
            media_type="HDD",
        ),
    ]
