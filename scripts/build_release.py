"""
Build de release do GestaoPC (RECON 7.2).

Roda o PyInstaller com gestaopc.spec (--onedir, DLLs Qt soltas/substituíveis
conforme LGPL) e copia o README de distribuição para a pasta final, ao lado
do executável.

Pré-requisito:  pip install -e ".[packaging]"
Uso:            python scripts/build_release.py

Saída: dist/GestaoPC/GestaoPC.exe + dist/GestaoPC/_internal/ + README.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SPEC = _ROOT / "gestaopc.spec"
_DIST_DIR = _ROOT / "dist" / "GestaoPC"
_DIST_README_SRC = _ROOT / "packaging" / "README_DISTRIBUICAO.md"


def main() -> int:
    if not _SPEC.exists():
        print(f"ERRO: spec não encontrado em {_SPEC}", file=sys.stderr)
        return 1

    print("==> Rodando PyInstaller (--onedir via gestaopc.spec)...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(_SPEC)],
        cwd=str(_ROOT),
    )
    if result.returncode != 0:
        print("ERRO: build do PyInstaller falhou.", file=sys.stderr)
        return result.returncode

    if not _DIST_DIR.exists():
        print(f"ERRO: pasta de saída não encontrada em {_DIST_DIR}", file=sys.stderr)
        return 1

    if _DIST_README_SRC.exists():
        dest = _DIST_DIR / "README.md"
        shutil.copy2(_DIST_README_SRC, dest)
        print(f"==> README de distribuição copiado para {dest}")

    print(f"\nOK — release pronto em: {_DIST_DIR}")
    print("    Distribua a pasta GestaoPC/ inteira (NÃO só o .exe).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
