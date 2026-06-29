# GestaoPC Storage Manager — Distribuição

Esta pasta é uma distribuição autônoma do **GestaoPC Storage Manager** para
Windows 11. Não requer Python instalado.

## Como executar

Dê duplo-clique em **`GestaoPC.exe`** (ou rode pela linha de comando, com
`GestaoPC.exe --auto-scan` para já iniciar a varredura).

> **Importante:** distribua a **pasta inteira**, não apenas o `.exe`. Os
> arquivos de suporte (incluindo as DLLs do Qt) ficam em `_internal/`.

## Aviso de licença (LGPL — Qt / PySide6)

Este aplicativo é licenciado sob **MIT**, mas usa a biblioteca **PySide6 / Qt**,
licenciada sob **LGPL v3**. Em conformidade com a LGPL, as bibliotecas do Qt são
distribuídas como **arquivos DLL separados** (na pasta `_internal/`, soltos e
não comprimidos), de modo que você pode **substituí-las** por sua própria versão
compatível do PySide6/Qt.

### Como substituir as DLLs do Qt

1. Instale a versão desejada do PySide6 num ambiente Python:
   `pip install --upgrade "PySide6>=6.6,<7.0"`
2. Localize as DLLs `Qt6*.dll` e a pasta `PySide6/` no `site-packages` desse
   ambiente.
3. Substitua os arquivos correspondentes dentro de `_internal/` desta
   distribuição.

Os avisos completos de terceiros estão em `_internal/LICENSES/THIRD_PARTY_NOTICES.md`.

## Dados do aplicativo

O banco SQLite e os logs ficam em `%LOCALAPPDATA%\GestaoPC\` — fora desta pasta,
preservados entre atualizações da distribuição.
