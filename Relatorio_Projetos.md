# Relatório de Estado e Tecnologias

Este relatório fornece um panorama completo e detalhado do status atual de desenvolvimento, infraestrutura e capacidades técnicas dos dois projetos principais presentes no seu espaço de trabalho: **Gestão PC** e **Biblioteca Pessoal**.

Ambos os projetos compartilham um padrão rigoroso de arquitetura: **Linguagem Python 3.11+, Interface Desktop PyQt6** e separação de responsabilidades no padrão MVC (Model-View-Controller) com alta dependência do **SQLite3** e execução massiva de concorrência com **QThreads** para assegurar estabilidade visual.

---

## 1. Gestão PC (Storage Manager & Assistant)
**Status:** Em Desenvolvimento Ativo  
**Objetivo:** Um gerenciador inteligente de armazenamento para Windows 11 (estilo *ASUS AI Suite 3*) com análise de discos, sugestões algorítmicas de deleção e assistente de IA local para otimização de partições.

### 🛠️ Módulos e Tecnologias Core Implementadas:
*   **Varredura & Análise de I/O (`scanner.py`, `analyzer.py`)**
    *   Uso de `psutil` e chamadas silenciosas ao `PowerShell` para extrair topologias exatas de discos (identificando NVMe, SSD SATA e HDD).
    *   Algoritmos rápidos (via `os.scandir`) para ranquear os **Top 50 Maiores Arquivos** e **Top 20 Pastas Mais Pesadas**.
    *   Deteção avançada de duplicatas num processo de 3 steps: *Filtro de Tamanho > Hash Parcial Rápido > Hash SHA-256 Completo*.
*   **Segurança e Execução (`executor.py`, `path_guard.py`)**
    *   Deleção delegada ao pacote `send2trash`, movendo com segurança as ocorrências para a Lixeira.
    *   Guard rail contra diretórios do sistema Windows (garante que bibliotecas de OS, Program Files e AppData não sofram mutações inadvertidas).
*   **Persistência Analítica (`storage_db.py`)**
    *   Cache SQLite para histórico de logs de limpezas e varreduras pesadas, minimizando I/O de disco repetido durante múltiplas re-aberturas.
*   **Inteligência Artificial Autônoma (`ollama_client.py`, `ai_toolbelt.py`)**
    *   Implementação inovadora acoplada à CLI do **Ollama**. Um cliente assíncrono consome modelos de linguagem locais fornecendo "conhecimento sistêmico" da máquina via prompts embutidos e entrega sugestões dinâmicas (ex: *"Mover mídia pesada do disco de Boot para um HDD Secundário"*).
*   **Apresentação Gráfica (GUI)**
    *   Tema Cyber/Dark, englobando Gráficos customizados renderizados via `QPainter` (Donut charts de ocupação e barras de top-down sizes).

---

## 2. Biblioteca Pessoal (Library Manager)
**Status:** Sistema Maduro / Funcionalidades Finais de Refinamento  
**Objetivo:** Solução definitiva e rica para categorização, busca e leitura imersiva de e-books, quadrinhos, relatórios e textos de estudo.

### 🛠️ Módulos e Tecnologias Core Implementadas:
*   **Motor Universal de Leitura (`Reader Factory`)**
    *   **PyMuPDF (`fitz`):** Abre, recorta capas e processa PDF fluídamente num `QScrollArea`.
    *   **ebooklib & BeautifulSoup:** Trata arquivos `.epub` removendo nós obsoletos e injetando na engine de Webview.
    *   **PyQt6-WebEngine:** Renderiza texto massivo (como HTML/EPUB/DOCX) paginando dinamicamente via execução injetada de JavaScript na runtime da tela para emular pulos de capítulo com cliques e roda do mouse.
*   **Base de Dados Ultra Rápida (`database.py`)**
    *   SQLite ajustado com modo **WAL** ativo e engine nativa **FTS5 (Full Text Search)** para permitir pesquisas granulares (por *string*, autor, tag) sobre milhares de instâncias instantaneamente.
*   **Ecossistema em Background (`workers/*.py`)**
    *   **MetadataFetcher:** Um `QThread` assíncrono engatado na API do *Google Books* (via `httpx`). Escaneia e busca em paralalelo o ISBN, sinopse, e descarrega bytes de imagens para as capas do livro dinamicamente na UI após solicitação do usuário.
    *   **Directory Watcher:** O serviço de vigília local que monitora se o usuário jogou e-books em uma pasta Windows para auto-catalogação na biblioteca.
*   **Local Cloud Streaming (`opds_server.py`)**
    *   Embutimento de um servidor **FastAPI** assíncrono guiado pelo *Uvicorn* rodando perfeitamente paralelizado na GUI, gerando catálogo XML Atom (padrão OPDS 1.2) que permite aos dispositivos Mobile pareados na rede do computador baixar os e-books remotamente via Wi-Fi.

---

### Conclusão e Resumo Arquitetural
Atualmente, ambos os repositórios cumprem à risca normativas profissionais: **Interface livre de engasgos (freeze-free UI)** através da alocação de pesados trabalhos em threads desacoplados com sinalização `pyqtSignal`, testabilidade de rotinas essenciais asseguradas por quase **100 suítes no Pytest**, e código fracamente acoplado propício à expansibilidade horizontal.
