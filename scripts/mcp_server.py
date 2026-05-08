"""
Servidor MCP para o GestaoPC.

Expõe ferramentas e dados do StorageManagerDB e StorageScanner 
para clientes compatíveis com o Model Context Protocol (ex: Claude Desktop, Cursor, agentes de IA).
"""

import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# Adicionar raiz do projeto ao sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.core.storage_db import StorageManagerDB, get_default_db_path
from src.core.scanner import StorageScanner

# Criar o servidor FastMCP
mcp = FastMCP("GestaoPC-StorageManager")

@mcp.resource("sqlite://gestaopc/operations")
def get_operations() -> str:
    """Retorna o histórico das últimas 100 operações realizadas (Mover/Deletar)."""
    db = StorageManagerDB(get_default_db_path())
    with db:
        ops = db.list_operations(limit=100)
    # Converter sqlite3.Row para dict e depois string
    return str([dict(op) for op in ops])

@mcp.resource("sqlite://gestaopc/suggestions")
def get_suggestions() -> str:
    """Retorna as sugestões ativas geradas pelo SmartRulesEngine."""
    db = StorageManagerDB(get_default_db_path())
    with db:
        suggs = db.list_suggestions(include_dismissed=False)
    return str([dict(s) for s in suggs])

@mcp.tool()
def scan_partitions() -> str:
    """
    Lista todas as partições do sistema.
    
    Returns:
        String formatada com as partições e seus respectivos espaços livre e total.
    """
    scanner = StorageScanner()
    parts = scanner.list_partitions()
    
    lines = ["== Partiçoes do Sistema =="]
    for p in parts:
        pct = (p.used_bytes / max(p.total_bytes, 1)) * 100
        lines.append(
            f"[{p.letter}] {p.file_system} | "
            f"Livre: {p.free_gb:.1f}GB / Total: {p.total_gb:.1f}GB "
            f"({pct:.1f}% usado)"
        )
    return "\n".join(lines)

@mcp.tool()
def read_app_settings() -> dict[str, str]:
    """
    Lê todas as configurações armazenadas da aplicação GestaoPC.
    
    Returns:
        Dicionário com chave e valor.
    """
    db = StorageManagerDB(get_default_db_path())
    with db:
        return db.list_settings()

if __name__ == "__main__":
    # Inicia o servidor usando transporte stdin/stdout por padrão
    mcp.run()
