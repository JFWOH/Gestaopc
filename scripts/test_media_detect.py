"""Quick test of the media type detection."""
import sys
sys.path.insert(0, ".")
from src.core.scanner import StorageScanner

media_map = StorageScanner._detect_media_types()
print("Media type map:", media_map)

parts = StorageScanner().list_partitions()
for p in parts:
    print(p)
