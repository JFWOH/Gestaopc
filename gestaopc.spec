# -*- mode: python ; coding: utf-8 -*-
#
# gestaopc.spec — build de release do GestaoPC Storage Manager (RECON 7.2).
#
# Modo --onedir (COLLECT abaixo): as DLLs do PySide6/Qt ficam SOLTAS em
# dist/GestaoPC/_internal/, substituíveis pelo usuário final. Isto é uma
# EXIGÊNCIA de compliance LGPL do LICENSES/THIRD_PARTY_NOTICES.md — NÃO migrar
# para --onefile (que embute/comprime as DLLs e violaria a LGPL).
#
# Build:  pyinstaller gestaopc.spec          (ou: python scripts/build_release.py)
# Saída:  dist/GestaoPC/GestaoPC.exe + dist/GestaoPC/_internal/

block_cipher = None

a = Analysis(
    ["run_gui.py"],
    pathex=["."],
    binaries=[],
    datas=[
        # Perfis RAG carregados em runtime por skills_loader.DEFAULT_SKILLS_DIR
        # (aritmética de __file__ resolve para _internal/skills no bundle onedir).
        ("skills", "skills"),
        # Avisos de licença de terceiros viajam junto do binário.
        ("LICENSES", "LICENSES"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,      # onedir: binários ficam soltos no COLLECT
    name="GestaoPC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # NÃO comprimir — preserva DLLs Qt substituíveis (LGPL)
    console=False,              # app GUI — sem janela de console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,                  # idem — DLLs soltas e substituíveis
    upx_exclude=[],
    name="GestaoPC",
)
