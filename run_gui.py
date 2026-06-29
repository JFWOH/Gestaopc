"""
Launcher fino da GUI do Gerenciador de PC.

Fonte única do entry point é ``src/main.py:main`` — este arquivo apenas delega,
preservando o uso histórico ``python run_gui.py [--auto-scan]`` (RECON 7.2 —
elimina a duplicação byte-a-byte que existia com src/main.py).

Uso:
    python run_gui.py
    python run_gui.py --auto-scan    (inicia varredura automaticamente)
"""

from src.main import main

if __name__ == "__main__":
    main()
