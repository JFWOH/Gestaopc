"""
Servidor MCP para o GestaoPC Storage Manager.

Wrapper fino sobre src.core.ai_toolbelt — expõe todas as 13 tools ao
Model Context Protocol (Claude Desktop, Cursor, agentes de IA externos).

Nenhuma lógica de negócio aqui. Toda execução delega ao ai_toolbelt.
Ações executivas passam ai_source='ai:mcp' para auditoria correta no DB.

Uso::

    # Linha de comando (stdin/stdout por padrão)
    python -m scripts.mcp_server

    # Configuração para Claude Desktop (claude_desktop_config.json):
    {
      "mcpServers": {
        "gestaopc": {
          "command": "python",
          "args": ["-m", "scripts.mcp_server"],
          "cwd": "/caminho/para/gestaopc"
        }
      }
    }
"""

import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Garantir raiz do projeto no sys.path quando executado como módulo
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import src.core.ai_toolbelt as tb  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Instância do servidor
# ─────────────────────────────────────────────────────────────────────────────

mcp = FastMCP("GestaoPC-StorageManager")


# ─────────────────────────────────────────────────────────────────────────────
# Resources (leitura passiva — snapshot em JSON, sem side-effects)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.resource("sqlite://gestaopc/partitions")
def resource_partitions() -> str:
    """Snapshot das partições do sistema em JSON."""
    return json.dumps(tb.list_partitions(), ensure_ascii=False)


@mcp.resource("sqlite://gestaopc/operations")
def resource_operations() -> str:
    """Histórico das últimas 100 operações (MOVER/DELETAR) em JSON."""
    return json.dumps(tb.get_history(limit=100), ensure_ascii=False)


@mcp.resource("sqlite://gestaopc/suggestions")
def resource_suggestions() -> str:
    """Sugestões ativas do SmartRulesEngine em JSON."""
    return json.dumps(
        tb.list_suggestions(include_dismissed=False, limit=50), ensure_ascii=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tools de leitura (sem side-effects, sem token necessário)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_partitions() -> list[dict]:
    """
    Lista todas as partições do sistema.

    Retorna: letra, filesystem, tipo de mídia (NVMe/SSD/HDD),
    espaço total, livre e percentual de uso.
    """
    return tb.list_partitions()


@mcp.tool()
def find_top_files(
    limit: int = 50,
    category: str | None = None,
    drive_letter: str | None = None,
) -> list[dict]:
    """
    Retorna os N maiores arquivos do índice persistido (último scan).

    Se o índice estiver vazio, orienta a executar varredura via interface gráfica.

    Args:
        limit: Máximo de arquivos (1–100, padrão 50).
        category: Filtrar por categoria: 'Vídeos', 'Imagens', 'Documentos',
                  'Executáveis', 'Compactados' ou 'Outros'.
        drive_letter: Filtrar por letra de disco, ex: 'C' ou 'D:'.
    """
    return tb.find_top_files(limit=limit, category=category, drive_letter=drive_letter)


@mcp.tool()
def find_top_folders(
    limit: int = 20,
    drive_letter: str | None = None,
) -> list[dict]:
    """
    Varre diretórios ao vivo e retorna os N que mais consomem espaço.

    Pode levar alguns segundos dependendo do tamanho do disco.

    Args:
        limit: Máximo de pastas (1–50, padrão 20).
        drive_letter: Varrer apenas este disco, ex: 'C' ou 'D:'.
                      Omitir para varrer todas as partições.
    """
    return tb.find_top_folders(limit=limit, drive_letter=drive_letter)


@mcp.tool()
def find_duplicates(
    limit: int = 50,
    min_size_mb: float = 1.0,
) -> list[dict]:
    """
    Retorna grupos de arquivos duplicados detectados no índice (hash SHA-256).

    Retorna hash, contagem, tamanho e lista de caminhos de cada grupo.

    Args:
        limit: Máximo de grupos (1–200, padrão 50).
        min_size_mb: Ignorar duplicatas menores que este tamanho em MB (padrão 1.0).
    """
    return tb.find_duplicates(limit=limit, min_size_mb=min_size_mb)


@mcp.tool()
def list_suggestions(
    include_dismissed: bool = False,
    limit: int = 20,
) -> list[dict]:
    """
    Retorna sugestões de otimização do SmartRulesEngine do último scan.

    Cada sugestão contém ID, regra, arquivo, ação recomendada e prioridade.

    Args:
        include_dismissed: Incluir sugestões já descartadas (padrão False).
        limit: Máximo de sugestões (1–100, padrão 20).
    """
    return tb.list_suggestions(include_dismissed=include_dismissed, limit=limit)


@mcp.tool()
def get_history(
    limit: int = 20,
    source: str | None = None,
) -> list[dict]:
    """
    Retorna o histórico de operações realizadas (mover, deletar, desfazer).

    Args:
        limit: Máximo de operações (1–200, padrão 20).
        source: Filtrar por origem: 'ui', 'ai:ollama' ou 'ai:mcp'.
    """
    return tb.get_history(limit=limit, source=source)


@mcp.tool()
def get_app_settings() -> dict:
    """
    Retorna todas as configurações persistidas da aplicação como dicionário chave/valor.
    """
    return tb.get_app_settings()


# ─────────────────────────────────────────────────────────────────────────────
# Tool de confirmação (obrigatória antes de qualquer ação executiva)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def request_confirmation(action: str, args: dict) -> dict:
    """
    Gera token one-shot (válido 60s) para autorizar ação executiva.

    SEMPRE chame esta tool antes de: move_to_trash, move_file, apply_suggestion,
    undo_last_operation ou set_disk_role. Passe o 'token' retornado no próximo call.

    Args:
        action: Ação a autorizar — 'move_to_trash', 'move_file', 'apply_suggestion',
                'undo_last_operation' ou 'set_disk_role'.
        args: Argumentos que serão passados à ação (para descrição humana legível).
    """
    return tb.request_confirmation(action=action, args=args)


# ─────────────────────────────────────────────────────────────────────────────
# Tools executivas (exigem confirmation_token; auditadas como 'ai:mcp' no DB)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def move_to_trash(path: str, confirmation_token: str) -> dict:
    """
    Envia arquivo para a Lixeira do Windows (operação reversível).

    Requer token obtido via request_confirmation com action='move_to_trash'.
    Limitado a 3 ações executivas por minuto. Caminhos do SO são bloqueados.

    Args:
        path: Caminho absoluto do arquivo a enviar para Lixeira.
        confirmation_token: Token one-shot obtido via request_confirmation.
    """
    return tb.move_to_trash(path, confirmation_token, ai_source="ai:mcp")


@mcp.tool()
def move_file(source_path: str, target_path: str, confirmation_token: str) -> dict:
    """
    Move arquivo de origem para destino. Cria pastas intermediárias automaticamente.

    Se o destino já existir, adiciona sufixo numérico para evitar sobrescrita.
    Requer token obtido via request_confirmation com action='move_file'.

    Args:
        source_path: Caminho absoluto do arquivo de origem.
        target_path: Caminho absoluto de destino (incluindo nome do arquivo).
        confirmation_token: Token one-shot obtido via request_confirmation.
    """
    return tb.move_file(source_path, target_path, confirmation_token, ai_source="ai:mcp")


@mcp.tool()
def apply_suggestion(suggestion_id: int, confirmation_token: str) -> dict:
    """
    Aplica sugestão do SmartRulesEngine pelo ID (MOVER ou DELETAR conforme a regra).

    Requer token obtido via request_confirmation com action='apply_suggestion'.
    Use list_suggestions para obter IDs disponíveis.

    Args:
        suggestion_id: ID da sugestão (obtido via list_suggestions).
        confirmation_token: Token one-shot obtido via request_confirmation.
    """
    return tb.apply_suggestion(suggestion_id, confirmation_token, ai_source="ai:mcp")


@mcp.tool()
def undo_last_operation(
    confirmation_token: str,
    operation_id: int | None = None,
) -> dict:
    """
    Desfaz a última operação de MOVER registrada (ou operação específica por ID).

    Apenas operações MOVER podem ser desfeitas automaticamente. Para operações de
    Lixeira, o usuário deve recuperar manualmente via Windows Explorer.

    Args:
        confirmation_token: Token one-shot obtido via request_confirmation com
                            action='undo_last_operation'.
        operation_id: ID específico da operação a desfazer (padrão: última MOVER).
    """
    return tb.undo_last_operation(
        confirmation_token, operation_id=operation_id, ai_source="ai:mcp"
    )


@mcp.tool()
def set_disk_role(drive_letter: str, role: str, confirmation_token: str) -> dict:
    """
    Atribui papel lógico ao disco, influenciando sugestões do SmartRulesEngine.

    Requer token obtido via request_confirmation com action='set_disk_role'.

    Args:
        drive_letter: Letra do disco, ex: 'C', 'D' ou 'D:'.
        role: Papel — 'primary', 'media', 'backup', 'external' ou 'none'.
        confirmation_token: Token one-shot obtido via request_confirmation.
    """
    return tb.set_disk_role(drive_letter, role, confirmation_token, ai_source="ai:mcp")


if __name__ == "__main__":
    # Inicia o servidor usando transporte stdin/stdout (padrão MCP)
    mcp.run()
