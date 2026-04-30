"""Core — módulos de lógica de negócio do Gerenciador de PC."""

from src.core.scanner import StorageScanner, FileEntry, PartitionInfo, DirEntry
from src.core.analyzer import DuplicateDetector, SmartRulesEngine
from src.core.executor import SafeFileExecutor, FileActionWorker, FileAction

__all__ = [
    "StorageScanner",
    "FileEntry",
    "PartitionInfo",
    "DirEntry",
    "DuplicateDetector",
    "SmartRulesEngine",
    "SafeFileExecutor",
    "FileActionWorker",
    "FileAction",
]
