# Spec 02 — AI Toolbelt (Camada de Ferramentas de IA)

**Versão:** 1.0  
**Data:** 2026-05-07  
**Status:** APROVADA — referência para Sprint 1, 2 e 3  
**Módulo alvo:** `src/core/ai_toolbelt.py`

---

## 1. Objetivo

Centralizar **todas** as ações que podem ser invocadas por agentes de IA (Ollama local e clientes MCP externos) em um único módulo reutilizável. O MCP server e o AssistantTab serão wrappers finos sobre este módulo — sem lógica de negócio duplicada.

---

## 2. Princípios de Design

- **Single Source of Truth:** cada tool existe uma vez; MCP e Ollama importam do mesmo módulo.
- **Retorno sempre JSON-serializável:** nenhuma função retorna `Row` do sqlite3, objetos PyQt6 ou `str(dict)`. Sempre `dict | list[dict] | str`.
- **Classificação obrigatória:** toda tool tem `read_only: bool` e `requires_confirmation: bool`.
- **Auditoria embutida:** tools executivas registram em `operation_history` com `source = 'ai:ollama' | 'ai:mcp'`.
- **Falha explícita:** erros retornam `{"error": "mensagem descritiva"}` — nunca levantam exceções não tratadas para o agente.

---

## 3. Catálogo de Tools v1

### 3.1 Tools de Leitura (`read_only=True`, `requires_confirmation=False`)

---

#### `list_partitions`

**Descrição:** Lista todas as partições detectadas no sistema com espaço livre, total e tipo de mídia.

**Argumentos:** nenhum

**Retorno:**
```json
[
  {
    "letter": "C",
    "label": "Windows",
    "fstype": "NTFS",
    "media_type": "NVMe",
    "total_gb": 476.8,
    "free_gb": 120.4,
    "used_pct": 74.7
  }
]
```

---

#### `find_top_files`

**Descrição:** Retorna os N maiores arquivos encontrados no último scan, com categoria e caminho.

**Argumentos:**

| Nome | Tipo | Obrigatório | Padrão | Descrição |
|---|---|---|---|---|
| `limit` | `int` | Não | `50` | Quantos arquivos retornar (máx. 100) |
| `category` | `str` | Não | `null` | Filtrar por categoria: `"video"`, `"image"`, `"document"`, `"executable"`, `"compressed"`, `"other"` |
| `drive_letter` | `str` | Não | `null` | Filtrar por letra de disco (`"C"`, `"D"`, etc.) |

**Retorno:**
```json
[
  {
    "path": "D:\\Videos\\movie.mkv",
    "size_bytes": 15728640000,
    "size_human": "14.6 GB",
    "category": "video",
    "drive_letter": "D",
    "last_modified": "2024-11-15T14:32:00"
  }
]
```

---

#### `find_top_folders`

**Descrição:** Retorna as N pastas que mais consomem espaço no último scan.

**Argumentos:**

| Nome | Tipo | Obrigatório | Padrão | Descrição |
|---|---|---|---|---|
| `limit` | `int` | Não | `20` | Quantas pastas retornar (máx. 50) |
| `drive_letter` | `str` | Não | `null` | Filtrar por letra de disco |

**Retorno:**
```json
[
  {
    "path": "D:\\Downloads",
    "size_bytes": 42949672960,
    "size_human": "40.0 GB",
    "file_count": 1247,
    "drive_letter": "D"
  }
]
```

---

#### `find_duplicates`

**Descrição:** Retorna grupos de arquivos duplicados detectados no último scan, ordenados por desperdício de espaço.

**Argumentos:**

| Nome | Tipo | Obrigatório | Padrão | Descrição |
|---|---|---|---|---|
| `limit` | `int` | Não | `50` | Máximo de grupos retornados |
| `min_size_mb` | `float` | Não | `1.0` | Ignorar duplicatas menores que este tamanho |

**Retorno:**
```json
[
  {
    "hash": "abc123...",
    "file_count": 3,
    "size_each_bytes": 2097152000,
    "wasted_bytes": 4194304000,
    "wasted_human": "3.9 GB",
    "files": [
      {"path": "C:\\Users\\user\\Desktop\\backup.zip", "last_modified": "2024-01-10T08:00:00"},
      {"path": "D:\\Backup\\backup.zip", "last_modified": "2023-12-01T10:00:00"}
    ]
  }
]
```

---

#### `list_suggestions`

**Descrição:** Retorna as sugestões geradas pelo SmartRulesEngine após o último scan.

**Argumentos:**

| Nome | Tipo | Obrigatório | Padrão | Descrição |
|---|---|---|---|---|
| `include_dismissed` | `bool` | Não | `false` | Incluir sugestões já descartadas |
| `limit` | `int` | Não | `20` | Máximo de sugestões |

**Retorno:**
```json
[
  {
    "id": 42,
    "rule_id": "R1",
    "description": "Arquivo de vídeo 14.6 GB em NVMe C: — mover para HDD D:",
    "source_path": "C:\\Users\\user\\Videos\\movie.mkv",
    "target_path": "D:\\Videos\\movie.mkv",
    "size_bytes": 15728640000,
    "dismissed": false,
    "created_at": "2026-05-07T10:00:00"
  }
]
```

---

#### `get_history`

**Descrição:** Retorna as últimas N operações registradas (mover, deletar, undo).

**Argumentos:**

| Nome | Tipo | Obrigatório | Padrão | Descrição |
|---|---|---|---|---|
| `limit` | `int` | Não | `20` | Quantas operações retornar |
| `source` | `str` | Não | `null` | Filtrar por origem: `"ui"`, `"ai:ollama"`, `"ai:mcp"` |

**Retorno:**
```json
[
  {
    "id": 15,
    "timestamp": "2026-05-07T11:30:00",
    "operation": "move",
    "source_path": "C:\\movie.mkv",
    "target_path": "D:\\Videos\\movie.mkv",
    "success": true,
    "source": "ai:ollama"
  }
]
```

---

#### `get_app_settings`

**Descrição:** Retorna todas as configurações persistidas do aplicativo.

**Argumentos:** nenhum

**Retorno:**
```json
{
  "theme": "dark",
  "scan_depth": "3",
  "default_skill": "conservador"
}
```

---

### 3.2 Tools Executivas (`read_only=False`, `requires_confirmation=True`)

> ⚠️ Toda tool executiva exige token de confirmação válido (obtido via `request_confirmation`), registra em `operation_history` com `source` da camada chamante e valida o path contra lista negra antes de executar.

---

#### `request_confirmation`

**Descrição:** Gera um token one-shot para autorizar uma ação executiva. Token expira em 60s. Esta é a única tool executiva que **não requer** token prévio.

**Argumentos:**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `action` | `str` | Sim | Nome da tool a ser executada |
| `args` | `dict` | Sim | Argumentos que serão passados à tool |

**Retorno:**
```json
{
  "token": "a3f9c2...",
  "expires_at": "2026-05-07T11:31:00",
  "human_description": "Mover 'C:\\movie.mkv' (14.6 GB) para 'D:\\Videos\\movie.mkv'",
  "risk_level": "medium"
}
```

---

#### `move_to_trash`

**Descrição:** Envia um arquivo para a Lixeira do Windows (reversível). Registra em `operation_history`.

**Argumentos:**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `path` | `str` | Sim | Caminho absoluto do arquivo |
| `confirmation_token` | `str` | Sim | Token obtido via `request_confirmation` |

**Retorno:**
```json
{
  "success": true,
  "path": "C:\\file.mkv",
  "operation_id": 16,
  "message": "Arquivo enviado para Lixeira com sucesso."
}
```

---

#### `move_file`

**Descrição:** Move um arquivo de origem para destino. Cria a pasta de destino se não existir. Registra em `operation_history`.

**Argumentos:**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `source_path` | `str` | Sim | Caminho absoluto de origem |
| `target_path` | `str` | Sim | Caminho absoluto de destino |
| `confirmation_token` | `str` | Sim | Token obtido via `request_confirmation` |

**Retorno:**
```json
{
  "success": true,
  "source_path": "C:\\movie.mkv",
  "target_path": "D:\\Videos\\movie.mkv",
  "operation_id": 17,
  "message": "Arquivo movido com sucesso."
}
```

---

#### `apply_suggestion`

**Descrição:** Aplica uma sugestão específica do SmartRulesEngine pelo seu ID. Internamente delega a `move_file` ou `move_to_trash`.

**Argumentos:**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `suggestion_id` | `int` | Sim | ID da sugestão (obtido via `list_suggestions`) |
| `confirmation_token` | `str` | Sim | Token obtido via `request_confirmation` |

**Retorno:**
```json
{
  "success": true,
  "suggestion_id": 42,
  "operation_id": 18,
  "message": "Sugestão R1 aplicada: arquivo movido para D:\\Videos\\movie.mkv"
}
```

---

#### `undo_last_operation`

**Descrição:** Desfaz a última operação registrada em `operation_history`. Só funciona para operações de `move_file` (restaura o arquivo). Operações `move_to_trash` devem ser desfeitas manualmente via Lixeira do Windows.

**Argumentos:**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `operation_id` | `int` | Não | ID específico (padrão: última operação da sessão) |
| `confirmation_token` | `str` | Sim | Token obtido via `request_confirmation` |

**Retorno:**
```json
{
  "success": true,
  "undone_operation_id": 17,
  "message": "Arquivo restaurado para 'C:\\movie.mkv'."
}
```

---

#### `set_disk_role`

**Descrição:** Atribui um papel lógico a um disco (ex: `"backup"`, `"primary"`, `"media"`). Influencia as regras do SmartRulesEngine.

**Argumentos:**

| Nome | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `drive_letter` | `str` | Sim | Letra do disco (`"D"`, `"E"`, etc.) |
| `role` | `str` | Sim | Papel: `"primary"`, `"media"`, `"backup"`, `"external"`, `"none"` |
| `confirmation_token` | `str` | Sim | Token obtido via `request_confirmation` |

**Retorno:**
```json
{
  "success": true,
  "drive_letter": "D",
  "role": "media",
  "message": "Disco D: definido como 'media'."
}
```

---

## 4. Lista Negra de Proteção (Hardcoded)

Nenhuma tool executiva pode operar sobre paths que contenham os seguintes prefixos ou nomes:

```python
PROTECTED_PATHS = [
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
    "C:\\ProgramData",
    "C:\\System Volume Information",
    "C:\\$Recycle.Bin",
]

PROTECTED_FILENAMES = [
    "pagefile.sys",
    "swapfile.sys",
    "hiberfil.sys",
    "ntldr",
    "bootmgr",
]
```

Tentativa de operar sobre path protegido retorna:
```json
{"error": "PROTECTED_PATH: operação negada — caminho é parte do sistema operacional."}
```

---

## 5. Limites de Execução

| Limite | Valor | Onde aplicado |
|---|---|---|
| Max tool calls por turno | 5 | Loop do agente (Ollama e MCP) |
| Timeout por tool | 30s | `ai_toolbelt` via `threading.Timer` |
| Ações executivas por minuto | 3 | Rate limiter por sessão |
| Token de confirmação TTL | 60s | `request_confirmation` |
| Max arquivos por operação em lote | 50 | `apply_suggestion` em modo bulk (futuro) |

---

## 6. Schema JSON das Tools (para function-calling)

O módulo deve exportar `get_tool_schemas() -> list[dict]` retornando lista de schemas compatíveis com o formato OpenAI/Ollama:

```python
{
    "type": "function",
    "function": {
        "name": "move_file",
        "description": "Move um arquivo de origem para destino...",
        "parameters": {
            "type": "object",
            "properties": {
                "source_path": {"type": "string", "description": "Caminho absoluto de origem"},
                "target_path":  {"type": "string", "description": "Caminho absoluto de destino"},
                "confirmation_token": {"type": "string", "description": "Token obtido via request_confirmation"}
            },
            "required": ["source_path", "target_path", "confirmation_token"]
        }
    }
}
```

---

## 7. Auditoria — Campo `source`

A tabela `operation_history` deve ser estendida com coluna `source TEXT DEFAULT 'ui'`. Valores válidos:

| Valor | Descrição |
|---|---|
| `"ui"` | Ação iniciada pelo usuário via interface gráfica |
| `"ai:ollama"` | Ação iniciada pelo assistente Ollama local |
| `"ai:mcp"` | Ação iniciada por cliente MCP externo (ex: Claude Desktop) |

---

## 8. Critérios de Aceite da Implementação

- [ ] Módulo `src/core/ai_toolbelt.py` importável sem dependências de PyQt6.
- [ ] Todas as 12 tools implementadas com assinaturas conformes a esta spec.
- [ ] `get_tool_schemas()` retorna lista validável com `jsonschema`.
- [ ] Tools executivas rejeitam paths protegidos com erro estruturado.
- [ ] Rate limiter funciona em testes com mock de tempo.
- [ ] Cobertura de `ai_toolbelt.py` ≥ 90% em `tests/test_ai_toolbelt.py`.
- [ ] MCP server importa tools do toolbelt (zero lógica duplicada).
- [ ] `OllamaClient.chat_with_tools()` usa schemas de `get_tool_schemas()`.
