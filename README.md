# Gerenciador de PC — Storage Manager

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41CD52?logo=qt&logoColor=white)
![Windows](https://img.shields.io/badge/OS-Windows%2011-0078D4?logo=windows&logoColor=white)
![Status](https://img.shields.io/badge/Status-Em%20Desenvolvimento-FFD600)

Sistema inteligente de gerenciamento de armazenamento para Windows 11, com interface gráfica inspirada no ASUS AI Suite 3. Analisa discos, detecta duplicatas, e sugere realocações inteligentes usando um motor de regras simbólico.

## ✨ Funcionalidades

- **Mapeamento de Discos** — Detecta automaticamente todas as partições, tipo de mídia (NVMe/SSD/HDD), espaço usado/livre
- **Top 50 Maiores Arquivos** — Varredura inteligente com categorização automática (Vídeos, Imagens, Documentos, Executáveis, Compactados)
- **Top 20 Pastas Mais Pesadas** — Identifica os diretórios que mais consomem espaço
- **Detecção de Duplicatas** — Algoritmo eficiente em 3 etapas (tamanho → hash parcial → hash SHA-256 completo)
- **Motor de Regras IA** — Sugestões de realocação baseadas em regras:
  - R1: Mídia pesada (>1GB) no NVMe → mover para SATA
  - R2: Arquivos duplicados → sugerir deleção da cópia mais recente
  - R3: Disco >90% cheio → mover mídia para discos externos
- **Execução Segura** — Movimentação/deleção via Lixeira, com undo e log completo
- **Gráficos Visuais** — Donut chart de uso de disco + barras por categoria
- **System Tray** — Minimiza para bandeja com acesso rápido

## 🏗️ Arquitetura

```
gestaopc/
├── src/
│   ├── core/                    # Lógica de negócio
│   │   ├── scanner.py           # Mapeamento de discos + varredura (3.1, 3.2)
│   │   ├── analyzer.py          # Duplicatas + motor de regras (3.3, 3.4)
│   │   └── executor.py          # Operações seguras de arquivo + QThread
│   ├── gui/                     # Interface gráfica PyQt6
│   │   ├── main_window.py       # Janela principal (6 abas)
│   │   ├── charts.py            # Gráficos donut + barras (QPainter)
│   │   ├── icon.py              # Ícone programático + system tray
│   │   ├── styles.py            # Design system (cores, fontes, QSS)
│   │   └── workers.py           # QThreads para I/O sem bloquear GUI
│   └── main.py                  # Ponto de entrada alternativo
├── tests/                       # Testes unitários (pytest)
│   ├── conftest.py              # Fixtures compartilhadas
│   ├── test_scanner.py          # Testes do scanner
│   ├── test_analyzer.py         # Testes de duplicatas + regras
│   └── test_executor.py         # Testes do executor
├── specs/                       # Especificações técnicas
│   └── 01-storage-manager.md    # Spec principal do módulo
├── run_gui.py                   # Launcher da GUI
└── pyproject.toml               # Configuração do projeto
```

## 🚀 Instalação

### Pré-requisitos
- Python 3.11+
- Windows 11

### Setup

```bash
# Clonar o repositório
git clone <url-do-repo>
cd gestaopc

# Criar ambiente virtual
python -m venv venv
venv\Scripts\activate

# Instalar dependências
pip install -e .

# Instalar dependências de desenvolvimento (testes)
pip install -e ".[dev]"
```

## ▶️ Uso

### Interface Gráfica

```bash
python run_gui.py
```

Com varredura automática ao iniciar:
```bash
python run_gui.py --auto-scan
```

### Testes

```bash
python -m pytest tests/ -v
```

### Self-test do módulo analyzer

```bash
python -m src.core.analyzer
```

## 🎨 Design

Interface inspirada no **ASUS AI Suite 3**:

- **Tema Dark** — Fundo `#121212`, painéis `#1E1E1E`
- **Destaque Ciano** — `#00A8FF` para botões, seleções e acentos
- **6 Abas** — Visão Geral, Maiores Arquivos, Pastas, Duplicatas, Sugestões IA, Histórico
- **Gráficos** — Donut chart de uso de disco, barras por categoria
- **System Tray** — Minimiza para bandeja com menu de contexto

## 🔒 Segurança

- Pastas do sistema (`C:\Windows`, `C:\Program Files`, etc.) são **sempre ignoradas**
- Deleção usa **Lixeira do Windows** por padrão (via `send2trash`)
- Erros de permissão (Kaspersky/AV) são tratados graciosamente — nunca trava
- Todas as operações são registradas em log com possibilidade de undo

## 🛠️ Tecnologias

| Componente | Tecnologia |
|---|---|
| Linguagem | Python 3.11+ |
| GUI | PyQt6 |
| Gráficos | QPainter (puro Qt, sem dependências) |
| Disco | psutil + PowerShell (Get-PhysicalDisk) |
| Deleção Segura | send2trash |
| Testes | pytest |
| Lint | ruff |

## 📋 Especificação

O projeto segue a metodologia **Spec-Driven Development**. A especificação completa está em [`specs/01-storage-manager.md`](specs/01-storage-manager.md).

## 📄 Licença

MIT
