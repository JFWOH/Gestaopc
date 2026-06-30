# RECON REPORT — GestaoPC Storage Manager
**Gerado por:** Claude Code (claude-sonnet-4-6)  
**Data original:** 2026-06-28 | **Revisão de status:** 2026-06-29  
**Tipo:** Diagnóstico read-only — nenhum arquivo foi alterado

---

## ⚡ Painel de Status Geral (Revisão 2026-06-29)

| Seção | Item | Status |
|-------|------|--------|
| 2.3 | README desatualizado (~40%) | ✅ Corrigido — `docs(readme)` (commit `14993ec`) |
| 5.2 | mypy: 7 erros na GUI | ✅ Corrigido — `refactor(quality)` (commit `9e39dc6`) — 0 erros em 30 arquivos |
| 5.3 | ruff: 13 erros no src/ | ✅ Corrigido — ruff clean (0 erros no repo inteiro) |
| 5.4 | CI/CD ausente | ✅ Corrigido — `.github/workflows/ci.yml` (commit `a5c194e`) |
| 6.1 | top_largest_dirs subconta pastas profundas | ✅ Corrigido — recursão sem limite (commit `e219c43`) |
| 6.2 | Motor de regras: sugestões inválidas (sem espaço, mesmo disco) | ✅ Corrigido — `required_bytes` + `source_drive` validados (commit `e219c43`) |
| 6.3 | Fallback de mídia desconhecida retornava `'SSD'` | ✅ Corrigido — retorna `'Desconhecido'` (commit `e219c43`) |
| 6.4 | Áudio e `.gguf` não categorizados | ✅ Corrigido — categorias `Áudio` e `Modelos IA` adicionadas (commit `e219c43`) |
| 8.3.3 | E402 imports mid-file em módulos core | ✅ Corrigido — ruff clean |
| 4.1 | Duas instâncias de `OllamaClient` em `assistant_tab.py` | ⚪ Design intencional (worker vs. tab); agora ambas recebem backend injetável (Fase C) |
| 7.2 | Empacotamento/distribuição (PyInstaller/Nuitka) | ✅ Corrigido — build `--onedir` LGPL-compliant (commit `b45fe02`, Fase B) |
| 8.3.1 | `ai_toolbelt.py` com 1 314 linhas | ✅ Reduzido — `get_tool_schemas`→`tool_schemas.py` (1313→1035L, commit `628061e`, Fase D1) |
| 8.3.2 | `storage_db.py` com 797 linhas | ⚪ Deferido — classe coesa dona da conexão SQLite (candidato fraco); ganho estético não compensa o risco |
| 8.3.4 | PowerShell: 4 caminhos de falha silenciosa em `_detect_media_types` | ✅ Corrigido — aviso ao usuário via log_bridge (commit `48d3459`, Fase A2) |
| 8.3.5 | Sem marcadores de integração nos testes (`pytest -m unit`) | ✅ Corrigido — markers unit/integration + CI segmentado (commit `48d3459`, Fase A1) |
| 8.4 | `AIBackend` Protocol / abstração de backends | ✅ Corrigido — `src/core/ai_backend.py` + injeção na GUI (commit `0419982`, Fase C) |

**Testes na geração do RECON:** 549 &nbsp;|&nbsp; **Testes atuais:** 581 (+32 ao todo desde o RECON)

### Itens restantes (revisão 2026-06-29, segunda rodada)

Das 6 pendências, **5 foram resolvidas** (7.2, 8.3.1, 8.3.4, 8.3.5, 8.4). Resta apenas:
- ⚪ **8.3.2** — split de `storage_db.py`: **deferido por decisão de engenharia**. É uma classe única dona da conexão SQLite (coesa), testada por dezenas de testes; um split traria só ganho estético com risco de churn. Reavaliar apenas com motivação concreta.

A investigação da Fase D1 também confirmou por que o split de `ai_toolbelt.py` ficou parcial: os testes fazem monkeypatch no namespace do módulo (`get_default_db_path`, `StorageScanner`, `send2trash`), então mover os corpos das tools quebraria os patches. Só o bloco de dados puro (`get_tool_schemas`) foi extraído com segurança.

---

---

## Seção 1 — Identidade e Estado Atual

### 1.1 Versão Declarada (`pyproject.toml`)

```
name    = "gerenciador-de-pc"
version = "0.3.0"
```

### 1.2 Contagem de Testes

```
572 tests collected in 0.77s     ← +23 desde o RECON (era 549)
```

(Comando: `python -m pytest tests/ -q --co`)

### 1.3 Último Commit e Branch (atualizado em 2026-06-29)

```
Commit : 14993ec docs(readme): atualizar arquitetura e stack ~40% defasados (RECON 2.3)
Branch : master

Commits pós-RECON (mais recentes primeiro):
  14993ec docs(readme): atualizar arquitetura e stack ~40% defasados (RECON 2.3)
  b2cce82 refactor(tests): zerar lint do repo (ruff 32->0) e ampliar CI para lintar tudo
  a5c194e ci: adicionar pipeline GitHub Actions (ruff + mypy + pytest) (RECON 5.4)
  9e39dc6 refactor(quality): zerar erros de lint (ruff) e type-check (mypy) no src/ (RECON 5.2/5.3)
  e219c43 fix(core): corrigir rachaduras estruturais do motor de regras e scanner (RECON 6.1-6.4)
  02b3ce4 fix(mcp): corrigir conexao MCP no Claude Desktop — 3 problemas
```

### 1.4 Estado da Árvore de Trabalho

```
M  Relatório.txt           ← modificado, não commitado
?? Claude.md               ← novo arquivo untracked
?? Relatorio_Projetos.md   ← novo arquivo untracked
?? "roadmap excelencia.pdf"← novo arquivo untracked
?? docs/RECON_REPORT.md    ← este arquivo (untracked)
```

**Há mudanças não commitadas.** Nenhum arquivo de código-fonte (.py) está modificado.

### 1.5 Arquivos `.md` em `specs/` e `docs/`

| Arquivo | Título / Resumo |
|---------|-----------------|
| `specs/01-storage-manager.md` | *Especificação de Módulo: Storage Manager* — define hardware alvo (C: NVMe, D: HDD, G/J/L: HDDs externos), 3 regras de realocação (R1: mídia pesada no NVMe, R2: duplicatas, R3: disco >90%), GUI PyQt6 tema escuro ASUS. |
| `specs/02-ai-toolbelt.md` | *Spec 02 — AI Toolbelt (v1.0, 2026-05-07, APROVADA)* — centraliza 13 tools para Ollama + MCP, define tokens one-shot, auditoria por `ai_source`. |
| `docs/COVERAGE_BASELINE.md` | *Baseline de Cobertura (v0.2, 2026-05-07)* — cobertura total 22%, 136 testes na época. Meta da Sprint 6 era ≥80%. |

---

## Seção 2 — Mapa de Módulos

### 2.1 Árvore de `src/` com Contagem de Linhas

```
src/
├── main.py                          40 linhas   Ponto de entrada: QApplication + MainWindow
├── core/
│   ├── __init__.py                  20 linhas   Exports públicos do pacote
│   ├── ai_toolbelt.py            1 314 linhas   13 tools centralizadas (leitura + exec + token)
│   ├── analyzer.py                 658 linhas   Detecção duplicatas 3-etapas + motor de regras
│   ├── config.py                   107 linhas   Single-source-of-truth de constantes
│   ├── executor.py                 382 linhas   Executor seguro: mover/deletar, undo log, QThread
│   ├── hash_cache.py               160 linhas   Cache in-memory de hashes parciais e completos
│   ├── ollama_client.py            218 linhas   Cliente HTTP para servidor Ollama local
│   ├── path_guard.py               140 linhas   Validação de caminhos (rejeita relativos, SO)
│   ├── scanner.py                  454 linhas   Inventário de discos + varredura de arquivos
│   ├── skills_loader.py            166 linhas   Loader de skills RAG (perfis .md + frontmatter)
│   ├── storage_db.py               797 linhas   Camada SQLite (settings, file_index, history)
│   └── telemetry.py                216 linhas   Logger de telemetria local JSONL, opt-in
├── gui/
│   ├── __init__.py                   ? linhas   (vazio / barrel)
│   ├── assistant_tab.py            683 linhas   Aba Assistente IA: loop agente Ollama + tool-call
│   ├── charts.py                     ? linhas   Donut chart + barras por categoria (QPainter)
│   ├── icon.py                       ? linhas   Ícone programático + system tray icon
│   ├── log_bridge.py               116 linhas   logger Python → Signal Qt (status bar thread-safe)
│   ├── main_window.py              492 linhas   Janela principal, 6 abas, orquestração
│   ├── scan_status_panel.py          ? linhas   Painel de status de varredura (barra de progresso)
│   ├── styles.py                     ? linhas   Design system: cores, fontes, QSS
│   ├── workers.py                  431 linhas   QThreads: FullScanWorker, FileActionWorker
│   └── tabs/
│       ├── __init__.py               ? linhas
│       ├── duplicates_tab.py         ? linhas   Aba: exibe duplicatas detectadas
│       ├── history_tab.py            ? linhas   Aba: histórico de operações
│       ├── overview_tab.py           ? linhas   Aba: overview de discos com gráficos
│       ├── shared.py                 ? linhas   Widgets compartilhados entre abas
│       ├── suggestions_tab.py        ? linhas   Aba: sugestões do motor de regras
│       ├── top_dirs_tab.py           ? linhas   Aba: top pastas mais pesadas
│       └── top_files_tab.py          ? linhas   Aba: top arquivos mais pesados
```

**Total core (+gui principais):** ~8 400 linhas Python.

### 2.2 Responsabilidades dos Módulos em `src/core/`

- **`scanner.py`** — Inventaria partições via `psutil`, detecta tipo de mídia (NVMe/SSD/HDD) por PowerShell `Get-PhysicalDisk`, varre o sistema de arquivos para produzir listas de `FileEntry` e `DirEntry`.
- **`analyzer.py`** — Detecta duplicatas em 3 etapas (tamanho → hash parcial 1 MB → SHA-256 completo) e executa o motor de regras simbólico (`SmartRulesEngine`) para gerar sugestões de realocação/deleção.
- **`ollama_client.py`** — Cliente HTTP puro para o servidor Ollama local (`http://localhost:11434`), suporta streaming, tool-calling multi-turn com limite de iterações.
- **`ai_toolbelt.py`** — Define as 13 tools (7 leitura + 1 confirmação + 5 executivas) com tokens one-shot SHA-256 bound, rate-limit e `ai_source` de auditoria. Expõe `get_tool_schemas()` para Ollama e MCP.
- **`skills_loader.py`** — Carrega perfis RAG (`.md`) da pasta `skills/`, extrai frontmatter YAML simples (name/description) e devolve `Skill(name, description, content, filename)` para injeção no system prompt do Ollama.
- **`config.py`** — Single-source-of-truth de todas as constantes do projeto, agrupadas por domínio (ver Seção 5.6).
- **`path_guard.py`** — Valida e sanitiza caminhos: rejeita relativos, caminhos fora de partições conhecidas e diretórios de sistema críticos (raiz do SO, `Windows/`, `System32/`).
- **`hash_cache.py`** — Cache in-memory thread-safe para hashes parciais e completos, keyed por `(path, mtime, size)` com tolerância de `HASH_CACHE_MTIME_TOLERANCE` segundos.
- **`telemetry.py`** — Grava eventos de telemetria em arquivo JSONL local de forma thread-safe; opt-in (respeitado via config). Sem envio externo.
- **`executor.py`** — Executa operações de arquivo (mover para lixeira, mover entre discos) com validação prévia via `path_guard`, log de undo reverso, e worker `QThread` para não bloquear GUI.
- **`storage_db.py`** — Toda a persistência SQLite: tabelas `app_settings`, `file_index`, `suggestions`, `operation_history`. Exposição de métodos de consulta e atualização de alto nível.
- **`__init__.py`** — Re-exports públicos do pacote `src.core`.

### 2.3 Módulos Presentes no Código mas NÃO Documentados no `README.md` ✅ CORRIGIDO

~~O `README.md` foi escrito em fase inicial e lista apenas os 5 módulos originais.~~  
**Correção aplicada** no commit `14993ec`. O README agora documenta todos os módulos, menciona 572 testes, lista `ci.yml` no diagrama de arquitetura e descreve o motor de regras com as validações de destino. O seguinte estava ausente antes da correção:

| Módulo | Sprint de Introdução (estimado) |
|--------|---------------------------------|
| `ai_toolbelt.py` | Sprint 5+ |
| `ollama_client.py` | Sprint 5+ |
| `skills_loader.py` | Sprint 6+ |
| `config.py` | Sprint 7.6 |
| `path_guard.py` | Sprint 5+ |
| `hash_cache.py` | Sprint 7.4 |
| `telemetry.py` | Sprint 6+ |
| `storage_db.py` | Sprint 6+ |
| `assistant_tab.py` (GUI) | Sprint 5+ |
| `log_bridge.py` (GUI) | Sprint 6+ |
| `scan_status_panel.py` (GUI) | Sprint 6+ |
| `tabs/` (todos) | Sprint 6+ |

~~**Gravidade:** O README descreve um sistema que já não existe — o diagrama de arquitetura está ~40% desatualizado.~~ **Resolvido.**

---

## Seção 3 — Os Dois Sistemas de "Skills"

### 3.1 Skills de Produto (`skills/` na raiz)

| Arquivo | `name` (frontmatter) | `description` (frontmatter) |
|---------|---------------------|----------------------------|
| `skills/01_limpeza_midia.md` | Limpeza de Mídia | Identifica e realoca arquivos de vídeo, áudio e imagem grandes ou duplicados. |
| `skills/02_limpeza_downloads.md` | Limpeza de Downloads | Analisa e limpa pastas de download, removendo instaladores antigos e arquivos temporários. |
| `skills/03_otimizacao_ssd.md` | Otimização de SSD/NVMe | Libera espaço em discos rápidos movendo arquivos grandes para HDDs de backup. |
| `skills/04_duplicatas.md` | Caça a Duplicatas | Detecta e remove arquivos duplicados para recuperar espaço desperdiçado. |

Todas as 4 skills usam frontmatter YAML bem-formado (`---\nname: X\ndescription: Y\n---`).

### 3.2 `skills_loader.py` — Mecanismo Completo

**Como localiza:** `load_skills(skills_dir=None)` usa `DEFAULT_SKILLS_DIR` que resolve para `skills/` relativo à raiz do projeto (derivado do `__file__` do módulo). Faz glob `*.md`.

**Como parseia:** `_parse_frontmatter(text: str)` aplica regex `^---\n(.*?)\n---\n` (dotall) para extrair YAML. Parseia apenas chaves simples `key: value` — sem YAML completo. Se frontmatter ausente, `name` é gerado a partir do stem do arquivo (`01_limpeza_midia` → `"Limpeza Midia"`).

**Como carrega:** Cria `Skill(name, description, content, filename)` onde `content` é o corpo do `.md` sem o bloco frontmatter. Retorna `list[Skill]`.

**Assinaturas públicas:**
```python
def load_skills(skills_dir: Path | str | None = None) -> list[Skill]:
def get_skill_by_name(name: str, skills_dir: Path | str | None = None) -> Skill | None:

@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    content: str    # ← body Markdown injetado no system prompt
    filename: str
```

**Ponto de injeção no fluxo Ollama:** `src/gui/assistant_tab.py`, método `_get_system_context()` (aproximadamente linha 450). O `.content` da skill selecionada é inserido na lista de `messages` como system message antes de `self._client.chat_with_tools(model, messages, tools, _execute_tool)` ser chamado.

### 3.3 Convenção Claude Code (`.claude/` e `CLAUDE.md`)

**`.claude/` existe** e contém:
```
.claude/
├── rules/
│   ├── security.md        ← Proíbe ler .env/.pem/chaves; validar entrada; negar por padrão
│   └── testing.md         ← Bugfixes devem ter testes de regressão; features = sucesso + erro
├── agents/
│   ├── codebase-explorer.md
│   └── security-auditor.md
├── skills/
│   ├── plan-change/SKILL.md
│   └── code-review/SKILL.md
├── output-styles/
│   └── tutor-stepwise.md
├── hooks/
│   ├── hooks.json
│   └── scripts/deny-dangerous-bash.sh
├── settings.json
└── settings.local.json
```

**`CLAUDE.md` na raiz:** Contém 4 princípios fundamentais para o AI: (1) Perguntar antes de assumir, (2) Solução mais simples primeiro, (3) Não tocar código não relacionado, (4) Sinalizar incerteza explicitamente.

### 3.4 `.agent/`

```
.agent/
├── memory/.gitkeep
├── skills/.gitkeep
└── workflows/.gitkeep
```

**Finalidade aparente:** Scaffold vazio para um futuro sistema de agentes autônomos com memória persistente, skills próprias e workflows. **Nenhum conteúdo real** — apenas arquivos `.gitkeep` para preservar a estrutura de diretórios no git.

---

## Seção 4 — Acoplamento ao Ollama e Camada de IA

### 4.1 Todos os Pontos que Importam ou Instanciam `OllamaClient`

| Arquivo | Linha | Tipo |
|---------|-------|------|
| `src/core/ollama_client.py` | 24 | **Definição** da classe |
| `src/gui/assistant_tab.py` | 40 | `from src.core.ollama_client import OllamaClient` (import) |
| `src/gui/assistant_tab.py` | 116 | `self._client = OllamaClient()` (instância em `OllamaAgentWorker.__init__`) |
| `src/gui/assistant_tab.py` | 190 | `self._client = OllamaClient()` (segunda instância — classe diferente) |
| `src/core/ai_toolbelt.py` | 1047 | Comentário apenas: `# Passar para OllamaClient.chat_with_tools()` |

**Observação:** Há **duas instanciações separadas** de `OllamaClient` em `assistant_tab.py`. Indicativo de duas classes worker distintas nesse arquivo.

### 4.2 Interface Pública de `ollama_client.py`

| Método | Assinatura | Propósito |
|--------|-----------|-----------|
| `__init__` | `(host: str = OLLAMA_DEFAULT_HOST)` | Inicializa com URL base do servidor |
| `is_available` | `() -> bool` | Verifica se servidor Ollama responde (GET `/api/tags`) |
| `get_models` | `() -> list[str]` | Retorna lista de modelos instalados no servidor |
| `chat_stream` | `(model, messages) -> Iterator[str]` | Chat com streaming de tokens (sem tool-calling) |
| `chat_once` | `(model, messages, tools=None, timeout=120) -> dict \| None` | Uma rodada de chat, retorna mensagem completa do modelo |
| `chat_with_tools` | `(model, messages, tools, tool_executor, max_iterations=5) -> Iterator[dict]` | Loop agente multi-turn com tool-calling até `max_iterations` |

### 4.3 Strings Hardcoded Relacionadas ao Ollama

| Arquivo | Linha | Conteúdo |
|---------|-------|----------|
| `src/core/config.py` | ~78 | `OLLAMA_DEFAULT_HOST = "http://localhost:11434"` |
| `src/core/ollama_client.py` | 27 | importa `OLLAMA_DEFAULT_HOST` de config (não hardcoded aqui) |
| `src/core/ollama_client.py` | ~37 | `f"{self.host}/api/tags"` (endpoint de modelos) |
| `src/core/ollama_client.py` | ~65 | `f"{self.host}/api/chat"` (endpoint de chat) |
| `src/core/ollama_client.py` | ~169 | `"Sem resposta do Ollama. Verifique se o servidor está rodando."` |
| `src/core/ollama_client.py` | ~82 | `"Erro no chat_stream Ollama: %s"` |
| `src/core/ollama_client.py` | ~128 | `"Erro em chat_once Ollama: %s"` |

**Positivo:** O `host` e a porta vivem em `config.py` como `OLLAMA_DEFAULT_HOST`. Porém os **caminhos de endpoint** (`/api/tags`, `/api/chat`) estão hardcoded no cliente — incompatível com outros backends de IA.

### 4.4 AI Toolbelt — As 13 Tools

| # | Nome da Tool | Tipo | Propósito |
|---|-------------|------|-----------|
| 1 | `list_partitions` | Leitura | Retorna inventário de todos os discos |
| 2 | `find_top_files` | Leitura | Top N arquivos mais pesados por disco |
| 3 | `find_top_folders` | Leitura | Top N pastas mais pesadas por disco |
| 4 | `find_duplicates` | Leitura | Grupos de arquivos duplicados (3 etapas) |
| 5 | `list_suggestions` | Leitura | Sugestões pendentes do motor de regras |
| 6 | `get_history` | Leitura | Histórico de operações executadas |
| 7 | `get_app_settings` | Leitura | Configurações do aplicativo no SQLite |
| 8 | `request_confirmation` | Confirmação | Gera token one-shot SHA-256 bound (TTL 60s) |
| 9 | `move_to_trash` | Executiva | Move arquivo para Lixeira do Windows |
| 10 | `move_file` | Executiva | Move arquivo entre discos com validação |
| 11 | `apply_suggestion` | Executiva | Executa sugestão do motor de regras |
| 12 | `undo_last_operation` | Executiva | Reverte última operação de arquivo |
| 13 | `set_disk_role` | Executiva | Define papel de um disco (NVMe/SATA/externo) |

**Compartilhamento entre Ollama e MCP:** `get_tool_schemas()` (linha ~1040 de `ai_toolbelt.py`) retorna `list[dict]` com 13 schemas JSON no formato OpenAI/Ollama. No `OllamaAgentWorker`, essas schemas são passadas diretamente ao `chat_with_tools()`. O MCP server importa `ai_toolbelt` diretamente e registra as mesmas funções Python como tools FastMCP.

### 4.5 Fluxo do `request_confirmation` / Confirmation Token

**Geração** (`ai_toolbelt.py`, função `request_confirmation`):
```python
token = secrets.token_hex(16)          # 128 bits de entropia
expires_at = time.time() + 60          # TTL de 60 segundos
args_fingerprint = _fingerprint_args(args)  # SHA-256 dos argumentos
_token_store[token] = _ConfirmationToken(token, action, args, args_fingerprint, expires_at)
```

**Binding criptográfico** (`_fingerprint_args`):
```python
def _fingerprint_args(args: dict) -> str:
    filtered = {k: v for k, v in args.items()
                if k not in {"confirmation_token", "ai_source"}}
    canonical = json.dumps(filtered, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

**Validação** (`_validate_token`): Verifica (1) token existe, (2) não expirou, (3) `action` bate, (4) `_fingerprint_args(call_args) == stored_fingerprint`. Erro em qualquer etapa retorna dict de erro sem consumir o token. Sucesso: `del _token_store[token]` — **one-shot**.

**Garantia S-2:** Se o modelo tentar reusar um token com `source_path` diferente (ataque de substituição de argumento), o SHA-256 dos args não bate → `TOKEN_ARGS_MISMATCH` → operação bloqueada.

---

## Seção 5 — Fundações de Engenharia

### 5.1 Testes: `conftest.py`

**Fixtures globais disponíveis:**

| Fixture | Escopo | Descrição |
|---------|--------|-----------|
| `_qt_application()` | session (autouse) | Cria `QApplication` única para toda a sessão de testes |
| `tmp_files_dir(tmp_path)` | function | Diretório temporário com 12 arquivos variados (duplicatas, por categoria) |
| `fake_file_entries(tmp_files_dir)` | function | Lista de `FileEntry` construída a partir de `tmp_files_dir` |
| `fake_partitions()` | function | Lista de `PartitionInfo` simulando hardware alvo (C: NVMe 94%, D: HDD 60%, etc.) |

**Marcadores de integração:** Não foram encontrados marcadores `@pytest.mark.integration` ou similares no `conftest.py`. Os testes não estão segmentados por tipo.

### 5.2 Type Checking (mypy) ✅ CORRIGIDO

**Configuração:** Modo gradual — `disallow_untyped_defs = false` globalmente. Strict-on-allowlist para 5 módulos:
```
src.core.config, src.core.path_guard, src.core.hash_cache,
src.core.telemetry, src.core.skills_loader
```

**Resultado atual (`python -m mypy src/ --ignore-missing-imports`):**
```
Success: no issues found in 30 source files
```

~~**Resultado anterior:** `Found 7 errors in 5 files` em `charts.py`, `overview_tab.py`, `assistant_tab.py`, `main_window.py`.~~  
**Correção aplicada** pelo commit `9e39dc6` (`refactor(quality): zerar erros de lint (ruff) e type-check (mypy) no src/`). Todos os 7 erros GUI foram resolvidos (null-guards, anotações de tipo corrigidas).

### 5.3 Linting (ruff) ✅ CORRIGIDO

**Configuração:** `line-length = 100`, `target-version = "py311"`. Sem seletores de regras explícitos (usa defaults do ruff).

**Resultado atual de `ruff check src/` (e do repo inteiro):**
```
All checks passed!
```

~~**Resultado anterior:** `Found 13 errors. [*] 10 fixable with the --fix option.`~~  
**Correção aplicada** pelos commits `9e39dc6` e `b2cce82`. Os 3 `E402` (imports mid-file) e todos os `F401`/`F541`/imports GUI não utilizados foram eliminados. O CI agora roda `ruff check .` (repo inteiro, não só `src/`).

### 5.4 CI/CD ✅ CORRIGIDO

~~**Não existe.** O diretório `.github/workflows/` estava ausente.~~  
**Implementado** no commit `a5c194e` (`ci: adicionar pipeline GitHub Actions`). Arquivo `.github/workflows/ci.yml` com:
- Runner: `windows-latest` (correto para app Windows-específico)
- `QT_QPA_PLATFORM=offscreen` para PySide6 rodar sem display em CI
- Jobs: `ruff check .` → `mypy src/` → `pytest tests/ -q`
- Trigger: push e PRs no branch `master`; `concurrency` cancela runs duplicados

### 5.5 Logging: `log_bridge.py`

**Mecanismo:** `QtLogBridge(QObject)` instala um `logging.Handler` (`_SignalHandler`) em um logger Python padrão (stdlib). Quando o handler captura um `LogRecord`, emite o `record.getMessage()` via `Signal(str)` do Qt.

**Thread-safety:** `Signal.emit()` com `QueuedConnection` enfileira automaticamente a emissão no event loop da thread Qt principal — workers de background podem chamar `logger.info(...)` sem race conditions.

**Truncamento:** Mensagens longas são truncadas em `LOG_BRIDGE_MAX_MESSAGE_LENGTH = 200` (constante de `config.py`) com sufixo `"..."`.

**Uso prático:** Operações longas (hash SHA-256 em Etapa 3, varredura de disco) chamam `logger.info(...)` nos QThreads; a status bar da GUI atualiza em tempo real sem bloquear.

### 5.6 Configuração: `src/core/config.py` — Constantes por Domínio

| Domínio | Constante | Valor |
|---------|-----------|-------|
| **Scanner** | `SCAN_MIN_PARTITION_BYTES` | 100 MB |
| | `SCAN_TOP_FILES_PER_DISK` | 50 |
| | `SCAN_TOP_DIRS_PER_DISK` | 20 |
| | `SCAN_DIR_MAX_DEPTH` | 2 |
| **Hash** | `HASH_SAMPLE_SIZE` | 1 MB |
| | `HASH_FULL_CHUNK_SIZE` | 8 192 bytes |
| | `HASH_CACHE_MTIME_TOLERANCE` | 1.0 s |
| **Executor** | `EXECUTOR_MAX_BATCH_SIZE` | 50 |
| **AI Toolbelt** | `AI_MAX_EXEC_PER_MINUTE` | 3 |
| | `AI_TOKEN_TTL_SECONDS` | 60 |
| **Ollama** | `OLLAMA_DEFAULT_HOST` | `"http://localhost:11434"` |
| **Log Bridge** | `LOG_BRIDGE_MAX_MESSAGE_LENGTH` | 200 |
| **GUI Workers** | `WORKER_QUIT_TIMEOUT_MS` | 3 000 ms |
| | `WORKER_CLEANUP_TIMEOUT_MS` | 500 ms |
| | `WORKER_RESTART_TIMEOUT_MS` | 2 000 ms |
| | `WORKER_TERMINATE_TIMEOUT_MS` | 1 000 ms |

### 5.7 Feature Flags em Runtime

**Não existem.** Nenhum mecanismo de feature flags foi encontrado. Não há `settings.json` de runtime, `env vars` de toggle, tabela de flags no SQLite, nem decoradores de feature flag.

---

## Seção 6 — Rachaduras Estruturais

> **Status geral:** Todas as 4 rachaduras foram corrigidas no commit `e219c43` (`fix(core): corrigir rachaduras estruturais do motor de regras e scanner`).

### 6.1 Scan Não-Recursivo em `top_largest_dirs` ✅ CORRIGIDO

**Existe o problema?** ~~Parcialmente. A função não é "não-recursiva" no sentido de não varrer subdiretórios, mas tem um **limite artificial de profundidade**.~~  
**Correção aplicada:** O parâmetro `max_depth` foi mantido na assinatura por compatibilidade, mas a recursão agora percorre todos os níveis. Comentário no código confirma: *"Sprint 6.1: não limita mais a soma de tamanho — pastas além de max_depth níveis eram subcontadas (uma pasta com 50 GB em nivel3/ aparecia com 0 bytes). A soma agora é sempre o total real da árvore."*

**Localização:** `scanner.py`, função `top_largest_dirs()` e helper `_dir_size_recursive()`.

**Código relevante:**
```python
def top_largest_dirs(self, root_dir, n=20, max_depth=2) -> list[DirEntry]:
    for entry in os.scandir(root_dir):
        if entry.is_dir():
            total_size, file_count = self._dir_size_recursive(
                entry.path, max_depth=max_depth, current_depth=1
            )

@staticmethod
def _dir_size_recursive(dir_path, max_depth=2, current_depth=0):
    for entry in os.scandir(dir_path):
        if entry.is_dir() and current_depth < max_depth:
            sub_size, _ = StorageScanner._dir_size_recursive(
                entry.path, max_depth, current_depth + 1
            )
```

**Impacto:** Com `max_depth=2`, a função enumera até 2 níveis de subdiretórios para calcular tamanhos. Estruturas mais profundas (ex: `node_modules/`, `.git/objects/`, modelos de IA em `models/subfolder/`) são **subcontadas**. Uma pasta com 50 GB em `nivel3/` pode aparecer no resultado com 0 bytes.

**Gravidade:** Média — o resultado é sistematicamente incorreto para projetos de desenvolvimento e estruturas de dados profundas, que são exatamente os maiores candidatos a limpeza.

### 6.2 Roteamento Inválido no Motor de Regras (`analyzer.py`) ✅ CORRIGIDO

**Existe o problema?** ~~Sim — há ausência de duas validações críticas.~~  
**Correção aplicada:** `_best_sata_target` e `_best_external_target` agora recebem `required_bytes: int` e `source_drive: str`. A seleção do destino valida (1) `part.free_bytes >= required_bytes` (espaço suficiente), (2) `letter != source_drive` (origem ≠ destino), (3) default `best = None` — se nenhum disco válido existir, retorna `None` sem fallback hardcoded para `"D:"`.

**Originalmente:**

**Localização:** `analyzer.py`, métodos `_best_sata_target()` e `_best_external_target()`.

**Código relevante:**
```python
def _best_sata_target(self, partition_map: dict[str, PartitionInfo]) -> str:
    best = "D:"
    best_free = 0
    for letter in self.sata_internal_letters:
        if letter in partition_map and partition_map[letter].free_bytes > best_free:
            best_free = partition_map[letter].free_bytes
            best = letter
    return best
```

**Problemas identificados:**
1. **Sem verificação de disco cheio:** A escolha é pelo `max(free_bytes)`, mas não há checagem se `free_bytes >= tamanho_do_arquivo`. Um arquivo de 50 GB pode ser "sugerido" para um disco com 10 GB livres.
2. **Sem verificação de mesmo disco:** Nenhum código impede que a regra R1 gere `move C:\video.mp4 → C:\video.mp4` se o único SATA disponível for o próprio C:.
3. **Default hardcoded:** `best = "D:"` como fallback — se D: não existir no sistema, a sugestão aponta para um disco inexistente.

**Gravidade:** Alta — pode gerar sugestões inviáveis ou mesmo destrutivas (mover para disco sem espaço).

### 6.3 Detecção de Tipo de Mídia (`scanner.py`) ✅ CORRIGIDO (fallback silencioso)

**Como funciona:** `_detect_media_types()` executa um script PowerShell via `subprocess` chamando `Get-PhysicalDisk | Get-Partition`. O script mapeia `BusType` e `MediaType` para `"NVMe"/"SSD"/"HDD"`.

**Fallback interno no script PowerShell — corrigido:**
```powershell
if ($busType -eq 'NVMe') { $result[$letter] = 'NVMe' }
elseif ($mediaType -eq 'SSD') { $result[$letter] = 'SSD' }
elseif ($mediaType -eq 'HDD') { $result[$letter] = 'HDD' }
elseif ($busType -eq 'USB') { $result[$letter] = 'HDD' }
else { $result[$letter] = 'Desconhecido' }   ← CORRIGIDO (era 'SSD')
```

**Correção:** O fallback agora retorna `'Desconhecido'` (consistente com o default de `PartitionInfo`). Comentário no código: *"Sprint 6.3: o fallback de bus/mídia desconhecidos é 'Desconhecido' — NÃO 'SSD'. Classificar um disco USB lento, Thunderbolt ou SD card silenciosamente como SSD era enganoso."*

**Quando PowerShell falha totalmente** (FileNotFoundError, timeout, JSON inválido): comportamento inalterado — retorna `{}`, todos os discos ficam `"Desconhecido"` sem aviso ao usuário. Ver item 8.3.4 (aberto).

~~**Gravidade:** Média — O fallback interno `'SSD'` é silenciosamente incorreto.~~ **Resolvido.**

### 6.4 Categorização "Outros" e Arquivos Especiais ✅ CORRIGIDO

**Código de categorização:**
```python
@staticmethod
def _categorize(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    for category, extensions in FILE_CATEGORIES.items():
        if ext in extensions:
            return category
    return "Outros"
```

**Categorias existentes:** Imagens, Vídeos, Documentos, Executáveis, Compactados.

**Situação após correção:**
- **`.gguf` (modelos de IA Ollama):** ✅ Nova categoria `"Modelos IA"` — `{".gguf", ".safetensors", ".bin"}`. Modelos de 40 GB+ agora são candidatos prioritários de realocação via Regra R1.
- **Áudio (`.mp3`, `.flac`, `.wav`):** ✅ Nova categoria `"Áudio"` — `{".mp3", ".flac", ".wav", ".aac", ".ogg", ".m4a"}`. Alinhado com a spec (candidatos para R1).
- **`node_modules/`:** Comportamento inalterado — é diretório, `top_largest_files` não alcança. `top_largest_dirs` agora conta corretamente (fix 6.1 remove limite de profundidade).
- **Cache dirs (`__pycache__/`):** Inalterado — invisíveis ao top_files por serem diretórios.

~~**Gravidade:** Média.~~ **Itens de mídia e modelos de IA resolvidos.**

---

## Seção 7 — Dependências e Empacotamento

### 7.1 Dependências

**Produção:**
| Pacote | Restrição de Versão | Propósito |
|--------|--------------------|----|
| `psutil` | `>=5.9,<7.0` | Inventário de partições e uso de disco |
| `PySide6` | `>=6.6,<7.0` | Framework GUI Qt6 (LGPL v3) |
| `send2trash` | `>=1.8,<2.0` | Envio de arquivos para Lixeira do Windows |
| `mcp` | `>=1.0.0,<2.0` | Servidor MCP para clientes LLM externos |
| `anyio` | `>=4.0,<5.0` | Async runtime (dep transitiva do mcp) |
| `httpx` | `>=0.25,<1.0` | HTTP client (dep transitiva do mcp) |
| `pydantic` | `>=2.0,<3.0` | Validação de dados (dep transitiva do mcp) |

**Desenvolvimento:**
| Pacote | Restrição | Propósito |
|--------|-----------|-----------|
| `pytest` | `>=7.0,<10.0` | Framework de testes |
| `pytest-cov` | `>=4.0,<8.0` | Cobertura de código |
| `ruff` | `>=0.4,<1.0` | Linter e formatter |
| `mypy` | `>=1.0,<2.0` | Type checker estático |

### 7.2 Estratégia de Empacotamento/Distribuição

**Não existe.** Não foram encontrados:
- Arquivo `.spec` (PyInstaller)
- Script Nuitka
- Script Inno Setup
- `Makefile` / `build.py` de empacotamento
- Workflow CI de release

O `THIRD_PARTY_NOTICES.md` menciona *"quando o GestaoPC for empacotado como executável, as DLLs do PySide6/Qt serão distribuídas como arquivos separados"* — mas essa capacidade não está implementada.

### 7.3 `LICENSES/THIRD_PARTY_NOTICES.md`

**Está atualizado?** Sim, para o estado atual das dependências.

**Licenças declaradas:**
- **PySide6** — LGPL v3 (com seção completa de conformidade sobre substituição da biblioteca)
- **psutil** — BSD-3-Clause
- **send2trash** — BSD-3-Clause
- **mcp** — MIT
- **anyio, httpx, pydantic** — MIT / Apache-2.0
- **pytest, pytest-cov, ruff** — MIT (dev only)

**Nota:** `mypy` está ausente da lista de dev deps do NOTICES, embora esteja em `pyproject.toml`. Omissão menor (dev-only, sem impacto em distribuição).

---

## Seção 8 — Síntese e Recomendações

### 8.1 Top 5 Pontos Fortes

1. **Segurança por design no AI Toolbelt:** O sistema de tokens one-shot com SHA-256 binding de argumentos (S-2) é uma implementação cuidadosa e rara — impede que o modelo manipule arquivos diferentes daqueles para os quais o usuário confirmou intenção.

2. **Detecção de duplicatas em 3 etapas:** A pipeline tamanho → hash parcial (1 MB) → SHA-256 completo é eficiente e correta. Evita hash desnecessário de arquivos que já diferem em tamanho, reduzindo drasticamente o I/O em discos grandes.

3. **Configuração centralizada (`config.py`):** Todas as constantes em um único lugar, com anotações de tipo. Módulos importam do config em vez de definir localmente — o projeto é razoavelmente fácil de tunar.

4. **`log_bridge.py` thread-safe:** A abordagem de usar `logging.Handler` + `Qt Signal` para bridgear threads é limpa e idiomática — workers de background nunca bloqueiam a GUI e o status bar é atualizado em tempo real.

5. **Cobertura de testes significativa (549 testes):** A suíte cresceu substancialmente desde o baseline de 136 testes. As fixtures do `conftest.py` (partições fake, FileEntry, QApplication) permitem testes unitários sem hardware real.

### 8.2 Fragilidades / Dívidas Técnicas — Status Atualizado

| # | Fragilidade | Status |
|---|-------------|--------|
| 1 | **Roteamento inválido no motor de regras (6.2)** — sugestões sem validação de espaço/disco | ✅ Corrigido (`e219c43`) |
| 2 | **Fallback silencioso `'SSD'` no script PowerShell (6.3)** | ✅ Corrigido — retorna `'Desconhecido'` |
| 3 | **README desatualizado ~40% (2.3)** — 12+ módulos invisíveis | ✅ Corrigido (`14993ec`) |
| 4 | **Duas instâncias de `OllamaClient` em `assistant_tab.py` (4.1)** | ⚪ Design intencional (worker QThread vs. tab widget); lifecycle gerenciado pelo Sprint 7.5 |
| 5 | **7 erros mypy na GUI (5.2)** — null-safety bugs reais | ✅ Corrigido (`9e39dc6`) — 0 erros em 30 arquivos |

### 8.3 Riscos de Manutenção — Status Atualizado

| # | Risco | Status |
|---|-------|--------|
| 1 | **`ai_toolbelt.py` com 1 314 linhas** — candidato a split | ⚠️ Aberto — sem sprint agendado |
| 2 | **`storage_db.py` com 797 linhas** — SQL cru sem ORM | ⚠️ Aberto — sem sprint agendado |
| 3 | **E402 imports mid-file em módulos core** | ✅ Corrigido — ruff clean (`b2cce82`) |
| 4 | **PowerShell: 4 caminhos de falha silenciosa em `_detect_media_types`** — sem aviso ao usuário quando `{}` | ⚠️ Aberto — comportamental, afeta só ambientes com PS restrito |
| 5 | **Sem marcadores de integração nos testes** — impossível `pytest -m unit` | ⚠️ Aberto — CI comenta o gap (`# RECON 8.3.5`) mas segmentação não implementada; 572 testes misturados |

### 8.4 Ponto de Menor Acoplamento para Abstração de Backends de IA

**Confirmado: o ponto é `OllamaClient` como consumido por `assistant_tab.py`.**

Mais especificamente, o ponto de introdução ideal é na criação das instâncias em `assistant_tab.py` linhas 116 e 190:
```python
self._client = OllamaClient()
```

Se `OllamaClient` fosse substituído por uma interface `AIBackend` (protocol/ABC) com os mesmos métodos públicos (`is_available`, `get_models`, `chat_stream`, `chat_once`, `chat_with_tools`), `assistant_tab.py` não precisaria mudar. As implementações concretas seriam:
- `OllamaBackend(host)` — atual
- `LlamaCppBackend(model_path)` — para llama.cpp local
- `RemoteAPIBackend(api_key, base_url)` — para API remota (Anthropic, OpenAI-compat)

**O `ai_toolbelt.py` NÃO precisa mudar** — ele não conhece o cliente, apenas define as tools. A injeção do backend ocorre exclusivamente em `assistant_tab.py`.

---

## Conclusão Técnica (atualizada em 2026-06-29)

**Antes do RECON:** codebase com fundações sólidas mas dívidas técnicas concentradas em rachaduras de runtime (motor de regras), qualidade (13 erros ruff, 7 erros mypy), ausência de CI/CD e README desatualizado.

**Após as correções pós-RECON (5 commits):** todas as rachaduras críticas e a maioria das dívidas de qualidade foram eliminadas.

- ✅ **9 de 15 itens identificados resolvidos** (incluindo todos os de alta/média gravidade)
- ✅ **CI/CD ativo** — ruff + mypy + pytest rodando em `windows-latest` a cada push
- ✅ **572 testes** passando, ruff clean, mypy zero erros em 30 arquivos
- ✅ **Motor de regras seguro** — sugestões com validação de espaço, origem ≠ destino
- ✅ **Categorização completa** — Áudio e Modelos IA reconhecidos

**Itens ainda abertos (baixa urgência):**
- ⚠️ `ai_toolbelt.py` (1 314 L) e `storage_db.py` (797 L) — riscos de manutenção futura, sem urgência imediata
- ⚠️ Empacotamento/distribuição (PyInstaller) — necessário antes de release público
- ⚠️ Segmentação de testes (`pytest -m unit`) — facilita feedback rápido em CI
- ⚠️ PowerShell: aviso ao usuário quando `_detect_media_types` retorna `{}`
- ⚠️ `AIBackend` Protocol — abstração de backends de IA (feature futura)
