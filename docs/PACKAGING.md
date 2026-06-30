# Empacotamento e Distribuição (RECON 7.2)

O GestaoPC é distribuído como uma pasta autônoma do Windows gerada pelo
**PyInstaller em modo `--onedir`**.

## Por que `--onedir` (e não `--onefile`)

`LICENSES/THIRD_PARTY_NOTICES.md` exige, por conformidade **LGPL v3** do
PySide6/Qt, que as DLLs do Qt sejam distribuídas como **arquivos soltos e
substituíveis**. O modo `--onefile` embute e comprime as DLLs num único
executável — o que violaria a LGPL. Por isso o build usa `--onedir`, sem UPX.

## Como buildar

```powershell
# 1. Instalar a dependência de empacotamento (só para release)
pip install -e ".[packaging]"

# 2. Buildar (wrapper que roda o spec e copia o README de distribuição)
python scripts/build_release.py

# Alternativa direta:
pyinstaller gestaopc.spec
```

Saída: `dist/GestaoPC/` contendo `GestaoPC.exe` e `_internal/` (DLLs, skills,
LICENSES). Distribua a **pasta inteira**.

## Arquivos relevantes

| Arquivo | Papel |
|---------|-------|
| `gestaopc.spec` | Spec do PyInstaller (`--onedir`, bundla `skills/` e `LICENSES/`) |
| `scripts/build_release.py` | Wrapper de build + cópia do README de distribuição |
| `packaging/README_DISTRIBUICAO.md` | README que viaja na pasta de release (inclui instruções de substituição de DLL para LGPL) |
| `[project.gui-scripts]` em `pyproject.toml` | Entry point `gestaopc = src.main:main` (instalável via `pip install -e .`) |

## Entry points

- Dev / instalado: `gestaopc` ou `gestaopc --auto-scan` (após `pip install -e .`).
- Script direto: `python run_gui.py` (shim fino para `src.main:main`).
- Build: o spec aponta para `run_gui.py`.
