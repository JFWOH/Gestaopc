"""
Schemas JSON das tools de IA (formato OpenAI/Ollama function-calling).

Extraído de ``ai_toolbelt`` (RECON 8.3.1) — bloco de dados puro, sem estado de
módulo nem dependências, separado da lógica de execução/segurança para reduzir
o tamanho do módulo principal. ``ai_toolbelt`` re-exporta ``get_tool_schemas``,
então ``ai_toolbelt.get_tool_schemas()`` continua válido para MCP e Ollama.
"""

from __future__ import annotations


def get_tool_schemas() -> list[dict]:
    """
    Retorna schemas JSON de todas as 13 tools no formato OpenAI/Ollama.

    Uso::

        schemas = get_tool_schemas()
        # Passar para OllamaClient.chat_with_tools() ou ao FastMCP
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "list_partitions",
                "description": "Lista todas as partições do sistema com espaço livre, total e tipo de mídia (NVMe/SSD/HDD).",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_top_files",
                "description": "Retorna os N maiores arquivos do índice do último scan, com categoria e caminho.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Quantos arquivos retornar (1–100, padrão 50).",
                        },
                        "category": {
                            "type": "string",
                            "description": "Filtrar por categoria: 'Vídeos', 'Imagens', 'Documentos', 'Executáveis', 'Compactados', 'Outros'.",
                        },
                        "drive_letter": {
                            "type": "string",
                            "description": "Filtrar por letra de disco, ex: 'C' ou 'D:'.",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_top_folders",
                "description": "Varre diretórios e retorna os N que mais consomem espaço.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Quantas pastas retornar (1–50, padrão 20).",
                        },
                        "drive_letter": {
                            "type": "string",
                            "description": "Varrer apenas este disco, ex: 'C' ou 'D:'. Omitir para varrer todos.",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_duplicates",
                "description": "Retorna grupos de arquivos duplicados do índice, ordenados por espaço desperdiçado.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Máximo de grupos (1–200, padrão 50).",
                        },
                        "min_size_mb": {
                            "type": "number",
                            "description": "Ignorar duplicatas menores que este tamanho em MB (padrão 1.0).",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_suggestions",
                "description": "Retorna sugestões de otimização geradas pelo Motor de Regras no último scan.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "include_dismissed": {
                            "type": "boolean",
                            "description": "Incluir sugestões já descartadas (padrão false).",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Máximo de sugestões (1–100, padrão 20).",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_history",
                "description": "Retorna o histórico de operações realizadas (mover, deletar, desfazer).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Máximo de operações (1–200, padrão 20).",
                        },
                        "source": {
                            "type": "string",
                            "description": "Filtrar por origem: 'ui', 'ai:ollama' ou 'ai:mcp'.",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_app_settings",
                "description": "Retorna todas as configurações persistidas da aplicação como dicionário chave/valor.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "request_confirmation",
                "description": (
                    "Gera um token one-shot (válido por 60s) para autorizar uma ação executiva. "
                    "SEMPRE chame esta tool antes de qualquer ação executiva (move_to_trash, "
                    "move_file, apply_suggestion, undo_last_operation, set_disk_role). "
                    "Use o token retornado no campo 'confirmation_token' da próxima chamada."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "Nome da ação a autorizar: 'move_to_trash', 'move_file', 'apply_suggestion', 'undo_last_operation' ou 'set_disk_role'.",
                        },
                        "args": {
                            "type": "object",
                            "description": "Argumentos que serão passados à ação (para geração da descrição humana).",
                        },
                    },
                    "required": ["action", "args"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "move_to_trash",
                "description": "Envia um arquivo para a Lixeira do Windows (operação reversível). Requer token de confirmação.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Caminho absoluto do arquivo a enviar para Lixeira.",
                        },
                        "confirmation_token": {
                            "type": "string",
                            "description": "Token obtido via request_confirmation com action='move_to_trash'.",
                        },
                    },
                    "required": ["path", "confirmation_token"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "move_file",
                "description": "Move um arquivo de origem para destino. Requer token de confirmação.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_path": {
                            "type": "string",
                            "description": "Caminho absoluto do arquivo de origem.",
                        },
                        "target_path": {
                            "type": "string",
                            "description": "Caminho absoluto de destino (incluindo nome do arquivo).",
                        },
                        "confirmation_token": {
                            "type": "string",
                            "description": "Token obtido via request_confirmation com action='move_file'.",
                        },
                    },
                    "required": ["source_path", "target_path", "confirmation_token"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "apply_suggestion",
                "description": "Aplica uma sugestão do Motor de Regras pelo ID. Requer token de confirmação.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "suggestion_id": {
                            "type": "integer",
                            "description": "ID da sugestão (obtido via list_suggestions).",
                        },
                        "confirmation_token": {
                            "type": "string",
                            "description": "Token obtido via request_confirmation com action='apply_suggestion'.",
                        },
                    },
                    "required": ["suggestion_id", "confirmation_token"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "undo_last_operation",
                "description": "Desfaz a última operação de mover (ou uma específica por ID). Requer token de confirmação.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "confirmation_token": {
                            "type": "string",
                            "description": "Token obtido via request_confirmation com action='undo_last_operation'.",
                        },
                        "operation_id": {
                            "type": "integer",
                            "description": "ID específico da operação a desfazer (padrão: última MOVER bem-sucedida).",
                        },
                    },
                    "required": ["confirmation_token"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "set_disk_role",
                "description": "Atribui papel lógico a um disco, influenciando sugestões do Motor de Regras. Requer token.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "drive_letter": {
                            "type": "string",
                            "description": "Letra do disco, ex: 'C', 'D' ou 'D:'.",
                        },
                        "role": {
                            "type": "string",
                            "description": "Papel: 'primary', 'media', 'backup', 'external' ou 'none'.",
                        },
                        "confirmation_token": {
                            "type": "string",
                            "description": "Token obtido via request_confirmation com action='set_disk_role'.",
                        },
                    },
                    "required": ["drive_letter", "role", "confirmation_token"],
                },
            },
        },
    ]
