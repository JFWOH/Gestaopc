"""
Testes unitários do servidor MCP (scripts/mcp_server.py).

Verifica:
  - 13 tools registradas com os nomes corretos
  - 3 resources registrados
  - Cada tool delega corretamente para ai_toolbelt (sem lógica própria)
  - Tools executivas passam ai_source='ai:mcp' para auditoria correta
  - Resources chamam ai_toolbelt e serializam em JSON

Estratégia:
  - Importar `scripts.mcp_server` como módulo (instância FastMCP já criada)
  - Patchear `scripts.mcp_server.tb` (alias para ai_toolbelt no servidor)
  - Chamar `asyncio.run(MCP.call_tool(name, args))` para exercitar o caminho completo
  - Verificar chamadas via mock.assert_called_once_with()
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

import scripts.mcp_server as server_mod

# Referência à instância FastMCP criada no módulo do servidor
MCP = server_mod.mcp


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _call(tool_name: str, args: dict) -> object:
    """Executa uma tool MCP de forma síncrona e retorna o resultado bruto."""
    return asyncio.run(MCP.call_tool(tool_name, args))


# ─────────────────────────────────────────────────────────────────────────────
# Registro
# ─────────────────────────────────────────────────────────────────────────────

EXPECTED_TOOL_NAMES = {
    "list_partitions",
    "find_top_files",
    "find_top_folders",
    "find_duplicates",
    "list_suggestions",
    "get_history",
    "get_app_settings",
    "request_confirmation",
    "move_to_trash",
    "move_file",
    "apply_suggestion",
    "undo_last_operation",
    "set_disk_role",
}

EXPECTED_RESOURCE_URIS = {
    "sqlite://gestaopc/partitions",
    "sqlite://gestaopc/operations",
    "sqlite://gestaopc/suggestions",
}


class TestToolRegistration:
    def test_exactly_13_tools_registered(self):
        registered = set(MCP._tool_manager._tools.keys())
        assert len(registered) == 13, f"Esperado 13, encontrado {len(registered)}: {registered}"

    def test_all_expected_tool_names_present(self):
        registered = set(MCP._tool_manager._tools.keys())
        assert registered == EXPECTED_TOOL_NAMES

    def test_3_resources_registered(self):
        registered = set(MCP._resource_manager._resources.keys())
        assert registered == EXPECTED_RESOURCE_URIS


# ─────────────────────────────────────────────────────────────────────────────
# Tools de leitura
# ─────────────────────────────────────────────────────────────────────────────

class TestReadOnlyTools:
    """Cada tool de leitura deve delegar ao ai_toolbelt sem alterar args."""

    def test_list_partitions_delegates(self):
        sentinel = [{"letter": "C:", "total_gb": 500.0}]
        with patch.object(server_mod.tb, "list_partitions", return_value=sentinel) as mock:
            _call("list_partitions", {})
            mock.assert_called_once_with()

    def test_find_top_files_defaults(self):
        with patch.object(server_mod.tb, "find_top_files", return_value=[]) as mock:
            _call("find_top_files", {})
            mock.assert_called_once_with(limit=50, category=None, drive_letter=None)

    def test_find_top_files_with_params(self):
        with patch.object(server_mod.tb, "find_top_files", return_value=[]) as mock:
            _call("find_top_files", {"limit": 10, "category": "Vídeos", "drive_letter": "D:"})
            mock.assert_called_once_with(limit=10, category="Vídeos", drive_letter="D:")

    def test_find_top_folders_defaults(self):
        with patch.object(server_mod.tb, "find_top_folders", return_value=[]) as mock:
            _call("find_top_folders", {})
            mock.assert_called_once_with(limit=20, drive_letter=None)

    def test_find_top_folders_with_drive(self):
        with patch.object(server_mod.tb, "find_top_folders", return_value=[]) as mock:
            _call("find_top_folders", {"limit": 5, "drive_letter": "D"})
            mock.assert_called_once_with(limit=5, drive_letter="D")

    def test_find_duplicates_defaults(self):
        with patch.object(server_mod.tb, "find_duplicates", return_value=[]) as mock:
            _call("find_duplicates", {})
            mock.assert_called_once_with(limit=50, min_size_mb=1.0)

    def test_find_duplicates_with_params(self):
        with patch.object(server_mod.tb, "find_duplicates", return_value=[]) as mock:
            _call("find_duplicates", {"limit": 100, "min_size_mb": 10.0})
            mock.assert_called_once_with(limit=100, min_size_mb=10.0)

    def test_list_suggestions_defaults(self):
        with patch.object(server_mod.tb, "list_suggestions", return_value=[]) as mock:
            _call("list_suggestions", {})
            mock.assert_called_once_with(include_dismissed=False, limit=20)

    def test_list_suggestions_with_dismissed(self):
        with patch.object(server_mod.tb, "list_suggestions", return_value=[]) as mock:
            _call("list_suggestions", {"include_dismissed": True, "limit": 50})
            mock.assert_called_once_with(include_dismissed=True, limit=50)

    def test_get_history_defaults(self):
        with patch.object(server_mod.tb, "get_history", return_value=[]) as mock:
            _call("get_history", {})
            mock.assert_called_once_with(limit=20, source=None)

    def test_get_history_with_source_filter(self):
        with patch.object(server_mod.tb, "get_history", return_value=[]) as mock:
            _call("get_history", {"limit": 5, "source": "ai:mcp"})
            mock.assert_called_once_with(limit=5, source="ai:mcp")

    def test_get_app_settings_delegates(self):
        sentinel = {"scan_interval": "60", "theme": "dark"}
        with patch.object(server_mod.tb, "get_app_settings", return_value=sentinel) as mock:
            _call("get_app_settings", {})
            mock.assert_called_once_with()


# ─────────────────────────────────────────────────────────────────────────────
# Tool de confirmação
# ─────────────────────────────────────────────────────────────────────────────

class TestConfirmationTool:
    def test_request_confirmation_delegates(self):
        sentinel = {"token": "abc123", "expires_at": "2026-01-01T00:01:00"}
        with patch.object(server_mod.tb, "request_confirmation", return_value=sentinel) as mock:
            _call("request_confirmation", {"action": "move_file", "args": {}})
            mock.assert_called_once_with(action="move_file", args={})

    def test_request_confirmation_with_args(self):
        with patch.object(server_mod.tb, "request_confirmation", return_value={}) as mock:
            payload = {"source_path": "D:/big.mkv", "target_path": "E:/big.mkv"}
            _call("request_confirmation", {"action": "move_file", "args": payload})
            mock.assert_called_once_with(action="move_file", args=payload)

    def test_request_confirmation_for_trash(self):
        with patch.object(server_mod.tb, "request_confirmation", return_value={}) as mock:
            _call("request_confirmation", {"action": "move_to_trash", "args": {"path": "D:/old.iso"}})
            mock.assert_called_once_with(
                action="move_to_trash", args={"path": "D:/old.iso"}
            )


# ─────────────────────────────────────────────────────────────────────────────
# Tools executivas — verificar ai_source='ai:mcp'
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutiveToolsAiSource:
    """
    Tools executivas DEVEM passar ai_source='ai:mcp'.
    Garante que operações iniciadas pelo MCP são corretamente auditadas no DB.
    """

    def test_move_to_trash_passes_ai_mcp(self):
        with patch.object(server_mod.tb, "move_to_trash", return_value={"success": True}) as mock:
            _call("move_to_trash", {"path": "D:/old.mkv", "confirmation_token": "tok123"})
            mock.assert_called_once_with("D:/old.mkv", "tok123", ai_source="ai:mcp")

    def test_move_file_passes_ai_mcp(self):
        with patch.object(server_mod.tb, "move_file", return_value={"success": True}) as mock:
            _call(
                "move_file",
                {
                    "source_path": "D:/a.mkv",
                    "target_path": "E:/a.mkv",
                    "confirmation_token": "tok456",
                },
            )
            mock.assert_called_once_with("D:/a.mkv", "E:/a.mkv", "tok456", ai_source="ai:mcp")

    def test_apply_suggestion_passes_ai_mcp(self):
        with patch.object(server_mod.tb, "apply_suggestion", return_value={"success": True}) as mock:
            _call("apply_suggestion", {"suggestion_id": 7, "confirmation_token": "tok789"})
            mock.assert_called_once_with(7, "tok789", ai_source="ai:mcp")

    def test_undo_last_operation_passes_ai_mcp(self):
        with patch.object(
            server_mod.tb, "undo_last_operation", return_value={"success": True}
        ) as mock:
            _call("undo_last_operation", {"confirmation_token": "tokABC"})
            mock.assert_called_once_with("tokABC", operation_id=None, ai_source="ai:mcp")

    def test_undo_last_operation_with_id_passes_ai_mcp(self):
        with patch.object(
            server_mod.tb, "undo_last_operation", return_value={"success": True}
        ) as mock:
            _call("undo_last_operation", {"confirmation_token": "tokDEF", "operation_id": 42})
            mock.assert_called_once_with("tokDEF", operation_id=42, ai_source="ai:mcp")

    def test_set_disk_role_passes_ai_mcp(self):
        with patch.object(server_mod.tb, "set_disk_role", return_value={"success": True}) as mock:
            _call(
                "set_disk_role",
                {"drive_letter": "D", "role": "backup", "confirmation_token": "tokGHI"},
            )
            mock.assert_called_once_with("D", "backup", "tokGHI", ai_source="ai:mcp")


# ─────────────────────────────────────────────────────────────────────────────
# Nenhuma lógica de negócio no servidor
# ─────────────────────────────────────────────────────────────────────────────

class TestNoBusinessLogicInServer:
    """O servidor não deve conter lógica — deve apenas delegar ao ai_toolbelt.

    Nota sobre serialização FastMCP:
      - list[dict] → tuple(list[TextContent], meta); 1 TextContent por dict na lista
      - dict       → list[TextContent]; único TextContent com o JSON do dict
    """

    def test_list_partitions_returns_toolbelt_result_verbatim(self):
        # 2 itens: um TextContent por dict
        payload = [
            {"letter": "Z:", "total_gb": 999.9},
            {"letter": "D:", "total_gb": 200.0},
        ]
        with patch.object(server_mod.tb, "list_partitions", return_value=payload):
            result = _call("list_partitions", {})
            content_list = result[0]  # tuple: (list[TextContent], meta)
            assert len(content_list) == 2
            assert json.loads(content_list[0].text) == payload[0]
            assert json.loads(content_list[1].text) == payload[1]

    def test_find_duplicates_returns_toolbelt_result_verbatim(self):
        payload = [{"hash": "deadbeef", "file_count": 2, "wasted_bytes": 1024}]
        with patch.object(server_mod.tb, "find_duplicates", return_value=payload):
            result = _call("find_duplicates", {})
            content_list = result[0]  # tuple: (list[TextContent], meta)
            assert len(content_list) == 1
            assert json.loads(content_list[0].text) == payload[0]

    def test_get_app_settings_returns_toolbelt_result_verbatim(self):
        # dict return → list[TextContent] direto (sem meta)
        payload = {"theme": "dark", "scan_on_startup": "true"}
        with patch.object(server_mod.tb, "get_app_settings", return_value=payload):
            result = _call("get_app_settings", {})
            content_list = result[0] if isinstance(result, tuple) else result
            data = json.loads(content_list[0].text)
            assert data == payload


# ─────────────────────────────────────────────────────────────────────────────
# Resources
# ─────────────────────────────────────────────────────────────────────────────

class TestResources:
    """Resources devem chamar ai_toolbelt e retornar JSON válido."""

    def test_partitions_resource_calls_list_partitions(self):
        payload = [{"letter": "C:"}]
        with patch.object(server_mod.tb, "list_partitions", return_value=payload):
            result = asyncio.run(MCP.read_resource("sqlite://gestaopc/partitions"))
            # read_resource retorna lista de resource contents
            assert len(result) > 0

    def test_operations_resource_calls_get_history(self):
        payload = [{"id": 1, "operation": "MOVER"}]
        with patch.object(server_mod.tb, "get_history", return_value=payload) as mock:
            asyncio.run(MCP.read_resource("sqlite://gestaopc/operations"))
            mock.assert_called_once_with(limit=100)

    def test_suggestions_resource_calls_list_suggestions(self):
        payload = [{"id": 1, "rule_name": "MediaOnNVMe"}]
        with patch.object(server_mod.tb, "list_suggestions", return_value=payload) as mock:
            asyncio.run(MCP.read_resource("sqlite://gestaopc/suggestions"))
            mock.assert_called_once_with(include_dismissed=False, limit=50)

    def test_partitions_resource_returns_valid_json(self):
        payload = [{"letter": "C:", "free_gb": 100.0}]
        with patch.object(server_mod.tb, "list_partitions", return_value=payload):
            result = asyncio.run(MCP.read_resource("sqlite://gestaopc/partitions"))
            # Extrair texto do primeiro content
            text = result[0].text if hasattr(result[0], "text") else result[0].content
            parsed = json.loads(text)
            assert parsed == payload
