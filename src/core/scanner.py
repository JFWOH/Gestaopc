"""
StorageScanner — Módulo de varredura de discos e análise de espaço.

Implementa as seções 3.1 (Mapeamento de Discos) e 3.2 (Análise de Espaço)
da especificação 01-storage-manager.md.

Princípios de resiliência (Seção 5 da spec):
  • Todo acesso a disco/arquivo é envolvido em try/except.
  • Pastas protegidas do sistema são ignoradas automaticamente.
  • Arquivos bloqueados pelo Kaspersky (ou qualquer AV) são registrados
    via logging e pulados — o scan nunca deve crashar.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import psutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Pastas que NUNCA devem ser varridas (Seção 5 da spec).
SYSTEM_EXCLUDED_DIRS: set[str] = {
    "Windows",
    "Program Files",
    "Program Files (x86)",
    "ProgramData",
    "$Recycle.Bin",
    "System Volume Information",
    "Recovery",
}

# Extensões agrupadas por categoria (Seção 3.2 da spec).
FILE_CATEGORIES: dict[str, set[str]] = {
    "Imagens": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".tiff", ".ico"},
    "Vídeos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
    "Documentos": {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".txt", ".csv", ".odt"},
    "Executáveis": {".exe", ".msi", ".bat", ".cmd", ".ps1", ".com"},
    "Compactados": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"},
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PartitionInfo:
    """Informações de uma partição montada."""
    letter: str
    fstype: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent_used: float
    mount_opts: str = ""
    media_type: str = "Desconhecido"  # "NVMe", "SSD", "HDD", "Desconhecido"

    @property
    def total_gb(self) -> float:
        return round(self.total_bytes / (1024 ** 3), 2)

    @property
    def free_gb(self) -> float:
        return round(self.free_bytes / (1024 ** 3), 2)

    def __repr__(self) -> str:
        return (
            f"<Partition {self.letter} [{self.media_type}]  "
            f"{self.total_gb} GB total | {self.free_gb} GB livre | "
            f"{self.percent_used}% usado>"
        )


@dataclass
class FileEntry:
    """Registro de um arquivo encontrado durante a varredura."""
    path: str
    size_bytes: int
    category: str = "Outros"
    modified_time: float = 0.0  # epoch seconds; 0.0 = desconhecido

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / (1024 ** 2), 2)


@dataclass
class DirEntry:
    """Registro de um diretório e seu consumo de espaço."""
    path: str
    total_size_bytes: int
    file_count: int

    @property
    def size_gb(self) -> float:
        return round(self.total_size_bytes / (1024 ** 3), 2)

    @property
    def size_mb(self) -> float:
        return round(self.total_size_bytes / (1024 ** 2), 2)

    def __repr__(self) -> str:
        return (
            f"<DirEntry {self.path}  "
            f"{self.size_gb} GB | {self.file_count} arquivos>"
        )


# ---------------------------------------------------------------------------
# Classe principal
# ---------------------------------------------------------------------------

class StorageScanner:
    """
    Scanner de armazenamento resiliente para Windows.

    Uso básico::

        scanner = StorageScanner()

        # 3.1 — Listar partições
        partitions = scanner.list_partitions()

        # 3.2 — Top 50 maiores arquivos de um diretório
        biggest = scanner.top_largest_files("D:\\Dados", n=50)
    """

    # ---- 3.1  Mapeamento de Discos -----------------------------------------

    def list_partitions(self) -> list[PartitionInfo]:
        """
        Retorna informações de todas as partições lógicas montadas.

        Partições inacessíveis (ex: leitor de CD vazio, volumes BitLocker
        trancados) são registradas em log e ignoradas — nunca lançam exceção.

        Inclui detecção automática do tipo de mídia (NVMe/SSD/HDD) via
        consulta PowerShell ao ``Get-PhysicalDisk``.
        """
        partitions: list[PartitionInfo] = []

        # Detectar tipos de mídia por letra de drive.
        media_map = self._detect_media_types()

        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except PermissionError:
                logger.warning(
                    "Sem permissão para acessar partição %s — ignorando.",
                    part.mountpoint,
                )
                continue
            except OSError as exc:
                # Dispositivos sem mídia (CD-ROM, leitor de cartão vazio).
                logger.info(
                    "Partição %s inacessível (%s) — ignorando.",
                    part.mountpoint,
                    exc,
                )
                continue

            letter = part.mountpoint.rstrip("\\")
            partitions.append(
                PartitionInfo(
                    letter=letter,
                    fstype=part.fstype,
                    total_bytes=usage.total,
                    used_bytes=usage.used,
                    free_bytes=usage.free,
                    percent_used=usage.percent,
                    mount_opts=part.opts,
                    media_type=media_map.get(letter.upper(), "Desconhecido"),
                )
            )

        logger.info("Partições mapeadas: %d encontradas.", len(partitions))
        return partitions

    # ---- 3.2  Top N maiores arquivos ----------------------------------------

    def top_largest_files(
        self,
        root_dir: str | os.PathLike,
        n: int = 50,
    ) -> list[FileEntry]:
        """
        Varre *root_dir* recursivamente e retorna os *n* maiores arquivos.

        Diretórios protegidos do sistema (C:\\Windows, etc.) são pulados
        automaticamente. Arquivos bloqueados pelo antivírus ou pelo SO
        são registrados em log e ignorados.

        Parameters
        ----------
        root_dir:
            Caminho absoluto do diretório a ser varrido.
        n:
            Quantidade de arquivos a retornar (default 50).

        Returns
        -------
        Lista de :class:`FileEntry` ordenada do maior para o menor.
        """
        root = Path(root_dir).resolve()

        if not root.exists():
            logger.error("Diretório raiz não encontrado: %s", root)
            return []

        entries: list[FileEntry] = []

        for dirpath, dirnames, filenames in os.walk(root):
            # ------ Podar diretórios protegidos do sistema (Seção 5) ------
            dirnames[:] = [
                d for d in dirnames
                if d not in SYSTEM_EXCLUDED_DIRS
            ]

            for fname in filenames:
                filepath = os.path.join(dirpath, fname)
                try:
                    st = os.stat(filepath)
                except (PermissionError, OSError) as exc:
                    # Arquivo bloqueado pelo Kaspersky, BitLocker, ou SYSTEM.
                    logger.debug(
                        "Arquivo inacessível (pulando): %s — %s",
                        filepath,
                        exc,
                    )
                    continue

                category = self._categorize(fname)
                entries.append(FileEntry(
                    path=filepath,
                    size_bytes=st.st_size,
                    category=category,
                    modified_time=st.st_mtime,
                ))

        # Ordenar do maior para o menor e retornar o top N.
        entries.sort(key=lambda e: e.size_bytes, reverse=True)
        top = entries[:n]

        logger.info(
            "Varredura de '%s' concluída: %d arquivos verificados, top %d retornados.",
            root,
            len(entries),
            len(top),
        )
        return top

    # ---- Helpers privados ---------------------------------------------------

    @staticmethod
    def _categorize(filename: str) -> str:
        """Classifica um arquivo por sua extensão conforme categorias da spec."""
        ext = Path(filename).suffix.lower()
        for category, extensions in FILE_CATEGORIES.items():
            if ext in extensions:
                return category
        return "Outros"

    # ---- 3.2  Top N maiores diretórios ----------------------------------------

    def top_largest_dirs(
        self,
        root_dir: str | os.PathLike,
        n: int = 20,
        max_depth: int = 2,
    ) -> list[DirEntry]:
        """
        Identifica os *n* diretórios que mais consomem espaço.

        Varre subdiretórios até *max_depth* níveis de profundidade,
        calculando o tamanho total (soma recursiva dos arquivos).
        Diretórios protegidos do sistema são ignorados.

        Parameters
        ----------
        root_dir:
            Caminho absoluto do diretório raíz.
        n:
            Quantidade de diretórios a retornar (default 20).
        max_depth:
            Profundidade máxima de subdiretórios a analisar.

        Returns
        -------
        Lista de :class:`DirEntry` ordenada do maior para o menor.
        """
        root = Path(root_dir).resolve()

        if not root.exists():
            logger.error("Diretório raíz não encontrado: %s", root)
            return []

        results: list[DirEntry] = []

        try:
            for entry in os.scandir(root):
                if not entry.is_dir(follow_symlinks=False):
                    continue
                if entry.name in SYSTEM_EXCLUDED_DIRS:
                    continue
                if entry.name.startswith("$"):
                    continue

                total_size, file_count = self._dir_size_recursive(
                    entry.path, max_depth=max_depth, current_depth=1
                )
                if total_size > 0:
                    results.append(
                        DirEntry(
                            path=entry.path,
                            total_size_bytes=total_size,
                            file_count=file_count,
                        )
                    )
        except (PermissionError, OSError) as exc:
            logger.debug("Erro ao listar %s: %s", root, exc)

        results.sort(key=lambda d: d.total_size_bytes, reverse=True)
        top = results[:n]

        logger.info(
            "Top dirs de '%s': %d diretórios analisados, top %d retornados.",
            root, len(results), len(top),
        )
        return top

    @staticmethod
    def _dir_size_recursive(
        dir_path: str,
        max_depth: int = 2,
        current_depth: int = 0,
    ) -> tuple[int, int]:
        """
        Calcula tamanho total e contagem de arquivos de um diretório recursivamente.

        Returns
        -------
        tuple[int, int]
            (total_size_bytes, file_count)
        """
        total_size = 0
        file_count = 0

        try:
            for entry in os.scandir(dir_path):
                try:
                    if entry.is_file(follow_symlinks=False):
                        total_size += entry.stat(follow_symlinks=False).st_size
                        file_count += 1
                    elif (
                        entry.is_dir(follow_symlinks=False)
                        and current_depth < max_depth
                        and entry.name not in SYSTEM_EXCLUDED_DIRS
                    ):
                        sub_size, sub_count = StorageScanner._dir_size_recursive(
                            entry.path, max_depth, current_depth + 1
                        )
                        total_size += sub_size
                        file_count += sub_count
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            pass

        return total_size, file_count

    @staticmethod
    def _detect_media_types() -> dict[str, str]:
        """
        Detecta o tipo de mídia física de cada drive via PowerShell.

        Consulta ``Get-PhysicalDisk`` + ``Get-Partition`` + ``Get-Volume``
        para mapear Letra → Tipo de mídia (NVMe, SSD, HDD).

        Returns
        -------
        dict[str, str]
            Mapa de letra do drive (ex: ``"C:"``) para tipo
            (``"NVMe"``, ``"SSD"``, ``"HDD"``, ``"Desconhecido"``).
        """
        # Script PowerShell que retorna JSON com o mapeamento.
        # Usa Get-Partition por DiskNumber (funciona sem elevação de admin).
        ps_script = """
$result = @{}
try {
    $disks = Get-PhysicalDisk -ErrorAction Stop
    $parts = Get-Partition -ErrorAction SilentlyContinue | Where-Object { $_.DriveLetter }
    foreach ($p in $parts) {
        $letter = "$($p.DriveLetter):"
        $disk = $disks | Where-Object { $_.DeviceId -eq [string]$p.DiskNumber }
        if ($disk) {
            $busType = $disk.BusType
            $mediaType = $disk.MediaType
            if ($busType -eq 'NVMe') {
                $result[$letter] = 'NVMe'
            } elseif ($mediaType -eq 'SSD') {
                $result[$letter] = 'SSD'
            } elseif ($mediaType -eq 'HDD') {
                $result[$letter] = 'HDD'
            } elseif ($busType -eq 'USB') {
                $result[$letter] = 'HDD'
            } else {
                $result[$letter] = 'SSD'
            }
        }
    }
} catch {}
$result | ConvertTo-Json -Compress
"""
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                raw = proc.stdout.strip()
                data = json.loads(raw)
                # PowerShell pode retornar um dict simples ou um objeto.
                if isinstance(data, dict):
                    logger.info("Tipos de mídia detectados: %s", data)
                    return {k.upper(): v for k, v in data.items()}
            logger.warning(
                "PowerShell retornou código %d para detecção de disco.",
                proc.returncode,
            )
        except FileNotFoundError:
            logger.warning("PowerShell não encontrado — detecção de tipo de disco desabilitada.")
        except subprocess.TimeoutExpired:
            logger.warning("Timeout ao detectar tipo de disco via PowerShell.")
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Erro ao parsear resposta de Get-PhysicalDisk: %s", exc)
        except Exception as exc:
            logger.warning("Erro inesperado na detecção de tipo de disco: %s", exc)

        return {}
