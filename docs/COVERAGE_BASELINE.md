# Baseline de Cobertura de Testes — GestaoPC

**Data:** 2026-05-07  
**Versão:** 0.2  
**Ferramenta:** pytest-cov  
**Comando:** `python -m pytest tests/ --cov=src --cov=scripts --cov-report=term-missing -q`

---

## Resultado Geral

| Métrica | Valor |
|---|---|
| Testes coletados | 136 |
| Testes aprovados | 136 |
| Testes reprovados | 0 |
| **Cobertura total** | **22%** |
| Meta Sprint 6 | ≥ 80% |

---

## Cobertura por Módulo

### ✅ Cobertura Boa (≥ 80%)

| Módulo | Stmts | Miss | Cobertura |
|---|---|---|---|
| `src/core/storage_db.py` | 153 | 4 | **97%** |
| `scripts/__init__.py` | 0 | 0 | **100%** |
| `src/core/__init__.py` | 5 | 0 | **100%** |

### ⚠️ Cobertura Parcial (50%–79%)

| Módulo | Stmts | Miss | Cobertura | Linhas descobertas |
|---|---|---|---|---|
| `src/core/analyzer.py` | 238 | 74 | **69%** | 174, 192-193, 235-237, 266-272, 471-473, 492-630 |
| `src/core/executor.py` | 156 | 48 | **69%** | 35-37, 94, 150-158, 194-197, 203-211, 286-289, 293, 297-318, 322 |
| `src/core/scanner.py` | 159 | 61 | **62%** | 106, 110, 113, 297-335, 351-375, 393-448 |

### ❌ Cobertura Zero (0%) — Prioridade de melhoria

| Módulo | Stmts | Contexto |
|---|---|---|
| `src/core/ollama_client.py` | 43 | Módulo de IA — crítico para Sprint 3 |
| `src/gui/assistant_tab.py` | 139 | Aba de IA — crítico para Sprint 3 |
| `scripts/mcp_server.py` | 38 | Servidor MCP — crítico para Sprint 2 |
| `src/gui/main_window.py` | 968 | GUI principal — cobrir via pytest-qt (Sprint 5) |
| `src/gui/workers.py` | 141 | QThreads — mockar em Sprint 5 |
| `src/gui/charts.py` | 164 | Gráficos — smoke test via QPainter mock |
| `src/gui/icon.py` | 65 | Ícone/tray — baixa prioridade |
| `src/gui/styles.py` | 29 | Constantes CSS — baixa prioridade |
| `src/gui/__init__.py` | 3 | Init — trivial |
| `src/main.py` | 18 | Entry point alternativo — baixa prioridade |
| `scripts/capture_gui.py` | 17 | Utilitário de screenshot — fora de escopo |
| `scripts/test_media_detect.py` | 8 | Script ad-hoc — fora de escopo |

---

## Problemas Encontrados Durante a Execução

| Severidade | Arquivo | Linha | Descrição |
|---|---|---|---|
| ⚠️ Warning | `src/core/storage_db.py` | 66 | `DeprecationWarning`: sequência de escape inválida (`\`` em docstring) |

---

## Módulos com Cobertura < 50% — Ações Requeridas

Módulos a cobrir por Sprint:

- **Sprint 2:** `scripts/mcp_server.py` (via FastMCP TestClient)
- **Sprint 3:** `src/core/ollama_client.py` (mock urllib), `src/gui/assistant_tab.py` (mock OllamaClient)
- **Sprint 5:** `src/gui/main_window.py`, `src/gui/workers.py` (via pytest-qt + `QT_QPA_PLATFORM=offscreen`)

---

## Como Reproduzir

```bash
# Instalar dependência
pip install pytest-cov

# Rodar com cobertura
python -m pytest tests/ --cov=src --cov=scripts --cov-report=term-missing -q

# Relatório HTML (opcional)
python -m pytest tests/ --cov=src --cov=scripts --cov-report=html
# Abrir htmlcov/index.html
```
