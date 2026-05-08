"""
Testes unitários do OllamaClient (src.core.ollama_client).

Cobre:
  - is_available()   — conexão OK e falha de rede
  - get_models()     — parsing da resposta e tratamento de erro
  - chat_stream()    — geração de tokens e erro de conexão
  - chat_once()      — chamada simples e com tools; timeout; erro
  - chat_with_tools() — loop agente: sem tools (texto direto), 1 round de
                        tool-calling, múltiplos rounds, max_iterations,
                        erro de executor, args como string JSON

Estratégia:
  - Toda comunicação HTTP é mockada via unittest.mock.patch
  - urllib.request.urlopen é substituído por FakeResponse em memória
  - Nenhum servidor Ollama real é necessário
"""

from __future__ import annotations

import json
from io import BytesIO
from typing import Iterator
from unittest.mock import MagicMock, patch, call

import pytest

from src.core.ollama_client import OllamaClient


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fake_response(body: bytes, status: int = 200):
    """Simula um urllib response com corpo em bytes."""
    mock = MagicMock()
    mock.status = status
    mock.read.return_value = body
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    # Permite iteração linha a linha (para chat_stream)
    lines = body.splitlines(keepends=True)
    mock.__iter__ = lambda s: iter(lines)
    return mock


def _json_bytes(obj: object) -> bytes:
    return json.dumps(obj).encode("utf-8")


def _stream_lines(*chunks: dict) -> bytes:
    """Concatena múltiplos objetos JSON em linhas (formato Ollama streaming)."""
    return b"".join(json.dumps(c).encode() + b"\n" for c in chunks)


# ─────────────────────────────────────────────────────────────────────────────
# Fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    return OllamaClient(host="http://fake-ollama:11434")


# ─────────────────────────────────────────────────────────────────────────────
# is_available
# ─────────────────────────────────────────────────────────────────────────────

class TestIsAvailable:
    def test_returns_true_when_server_responds_200(self, client):
        fake = _fake_response(b"Ollama is running")
        with patch("urllib.request.urlopen", return_value=fake):
            assert client.is_available() is True

    def test_returns_false_on_connection_error(self, client):
        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            assert client.is_available() is False

    def test_returns_false_on_timeout(self, client):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            assert client.is_available() is False


# ─────────────────────────────────────────────────────────────────────────────
# get_models
# ─────────────────────────────────────────────────────────────────────────────

class TestGetModels:
    def test_parses_model_names(self, client):
        body = _json_bytes({
            "models": [
                {"name": "qwen2.5:7b"},
                {"name": "llama3.1:8b"},
            ]
        })
        fake = _fake_response(body)
        with patch("urllib.request.urlopen", return_value=fake):
            models = client.get_models()
        assert models == ["qwen2.5:7b", "llama3.1:8b"]

    def test_returns_empty_list_on_error(self, client):
        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            assert client.get_models() == []

    def test_returns_empty_list_when_no_models(self, client):
        body = _json_bytes({"models": []})
        fake = _fake_response(body)
        with patch("urllib.request.urlopen", return_value=fake):
            assert client.get_models() == []


# ─────────────────────────────────────────────────────────────────────────────
# chat_stream
# ─────────────────────────────────────────────────────────────────────────────

class TestChatStream:
    def test_yields_tokens_from_streaming_response(self, client):
        body = _stream_lines(
            {"message": {"content": "Hello"}, "done": False},
            {"message": {"content": " world"}, "done": True},
        )
        fake = _fake_response(body)
        with patch("urllib.request.urlopen", return_value=fake):
            tokens = list(client.chat_stream("qwen2.5", [{"role": "user", "content": "hi"}]))
        assert tokens == ["Hello", " world"]

    def test_stops_at_done_true(self, client):
        body = _stream_lines(
            {"message": {"content": "A"}, "done": False},
            {"message": {"content": "B"}, "done": True},
            {"message": {"content": "C"}, "done": False},  # nunca chegará
        )
        fake = _fake_response(body)
        with patch("urllib.request.urlopen", return_value=fake):
            tokens = list(client.chat_stream("m", []))
        # "C" não deve aparecer (já parou em done=True)
        assert "C" not in tokens

    def test_yields_error_message_on_connection_failure(self, client):
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            tokens = list(client.chat_stream("m", []))
        assert len(tokens) == 1
        assert "Erro" in tokens[0] or "down" in tokens[0]


# ─────────────────────────────────────────────────────────────────────────────
# chat_once
# ─────────────────────────────────────────────────────────────────────────────

class TestChatOnce:
    def _text_response(self, content: str) -> bytes:
        return _json_bytes({
            "model": "test",
            "message": {"role": "assistant", "content": content, "tool_calls": []},
            "done": True,
            "done_reason": "stop",
        })

    def test_returns_response_dict_on_success(self, client):
        body = self._text_response("Olá!")
        fake = _fake_response(body)
        with patch("urllib.request.urlopen", return_value=fake):
            result = client.chat_once("m", [{"role": "user", "content": "oi"}])
        assert isinstance(result, dict)
        assert result["message"]["content"] == "Olá!"

    def test_returns_none_on_connection_error(self, client):
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            assert client.chat_once("m", []) is None

    def test_includes_tools_in_payload_when_provided(self, client):
        body = self._text_response("ok")
        fake = _fake_response(body)
        tools = [{"type": "function", "function": {"name": "list_partitions"}}]

        captured_payload: list[dict] = []

        def fake_urlopen(req, timeout=None):
            data = json.loads(req.data.decode())
            captured_payload.append(data)
            return fake

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.chat_once("m", [], tools=tools)

        assert "tools" in captured_payload[0]
        assert captured_payload[0]["tools"] == tools

    def test_does_not_include_tools_key_when_none(self, client):
        body = self._text_response("ok")
        fake = _fake_response(body)
        captured: list[dict] = []

        def fake_urlopen(req, timeout=None):
            captured.append(json.loads(req.data.decode()))
            return fake

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.chat_once("m", [], tools=None)

        assert "tools" not in captured[0]

    def test_stream_false_in_payload(self, client):
        body = self._text_response("ok")
        fake = _fake_response(body)
        captured: list[dict] = []

        def fake_urlopen(req, timeout=None):
            captured.append(json.loads(req.data.decode()))
            return fake

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.chat_once("m", [])

        assert captured[0]["stream"] is False


# ─────────────────────────────────────────────────────────────────────────────
# chat_with_tools
# ─────────────────────────────────────────────────────────────────────────────

def _make_text_resp(content: str) -> dict:
    return {
        "message": {
            "role": "assistant",
            "content": content,
            "tool_calls": [],
        },
    }


def _make_tool_resp(tool_name: str, args: dict) -> dict:
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": tool_name, "arguments": args}}
            ],
        },
    }


class TestChatWithTools:
    """Loop agente via chat_with_tools()."""

    TOOLS = [{"type": "function", "function": {"name": "list_partitions"}}]

    def _collect_events(
        self, client: OllamaClient, responses: list[dict | None]
    ) -> list[dict]:
        """Coleta todos os eventos do loop agente mockando chat_once."""
        idx = iter(responses)
        executor = MagicMock(return_value={"data": "ok"})

        with patch.object(client, "chat_once", side_effect=lambda *a, **kw: next(idx)):
            events = list(
                client.chat_with_tools("m", [], self.TOOLS, executor)
            )
        return events, executor

    def test_text_response_emits_text_event(self, client):
        events, _ = self._collect_events(
            client, [_make_text_resp("Tudo bem!")]
        )
        text_events = [e for e in events if e["type"] == "text"]
        assert len(text_events) == 1
        assert text_events[0]["content"] == "Tudo bem!"

    def test_no_tool_call_yields_only_text_event(self, client):
        events, executor = self._collect_events(
            client, [_make_text_resp("Pronto.")]
        )
        assert all(e["type"] in ("text",) for e in events)
        executor.assert_not_called()

    def test_one_tool_call_then_text(self, client):
        events, executor = self._collect_events(
            client,
            [
                _make_tool_resp("list_partitions", {}),
                _make_text_resp("Partições listadas."),
            ],
        )
        types = [e["type"] for e in events]
        assert "tool_call" in types
        assert "tool_result" in types
        assert "text" in types
        executor.assert_called_once_with("list_partitions", {})

    def test_tool_call_emits_name_and_args(self, client):
        events, _ = self._collect_events(
            client,
            [
                _make_tool_resp("find_top_files", {"limit": 10}),
                _make_text_resp("OK"),
            ],
        )
        tc = next(e for e in events if e["type"] == "tool_call")
        assert tc["name"] == "find_top_files"
        assert tc["args"] == {"limit": 10}

    def test_tool_result_contains_executor_output(self, client):
        idx = [_make_tool_resp("get_app_settings", {}), _make_text_resp("ok")]
        executor = MagicMock(return_value={"theme": "dark"})

        with patch.object(client, "chat_once", side_effect=lambda *a, **kw: next(iter(idx))):
            # Re-iterate properly
            pass

        # Use proper iteration
        responses = iter([
            _make_tool_resp("get_app_settings", {}),
            _make_text_resp("Done."),
        ])
        executor2 = MagicMock(return_value={"theme": "dark"})
        with patch.object(client, "chat_once", side_effect=lambda *a, **kw: next(responses)):
            events = list(client.chat_with_tools("m", [], self.TOOLS, executor2))

        tr = next(e for e in events if e["type"] == "tool_result")
        assert tr["result"] == {"theme": "dark"}

    def test_multiple_tool_calls_before_text(self, client):
        responses = iter([
            _make_tool_resp("list_partitions", {}),
            _make_tool_resp("list_suggestions", {}),
            _make_text_resp("Feito."),
        ])
        executor = MagicMock(return_value={"ok": True})
        with patch.object(client, "chat_once", side_effect=lambda *a, **kw: next(responses)):
            events = list(client.chat_with_tools("m", [], self.TOOLS, executor))

        tool_calls = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_calls) == 2
        assert executor.call_count == 2

    def test_max_iterations_emits_error(self, client):
        # Sempre retorna tool_call — nunca chega em texto
        executor = MagicMock(return_value={"ok": True})
        with patch.object(
            client,
            "chat_once",
            return_value=_make_tool_resp("list_partitions", {}),
        ):
            events = list(
                client.chat_with_tools(
                    "m", [], self.TOOLS, executor, max_iterations=3
                )
            )

        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1
        assert "3" in error_events[0]["message"]

    def test_none_response_emits_error(self, client):
        with patch.object(client, "chat_once", return_value=None):
            events = list(client.chat_with_tools("m", [], self.TOOLS, MagicMock()))

        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1

    def test_executor_exception_captured_as_tool_result_error(self, client):
        responses = iter([
            _make_tool_resp("bad_tool", {}),
            _make_text_resp("Continua."),
        ])
        executor = MagicMock(side_effect=RuntimeError("boom"))
        with patch.object(client, "chat_once", side_effect=lambda *a, **kw: next(responses)):
            events = list(client.chat_with_tools("m", [], self.TOOLS, executor))

        tr = next(e for e in events if e["type"] == "tool_result")
        assert tr["result"]["error"] == "EXECUTOR_ERROR"
        assert "boom" in tr["result"]["message"]

    def test_args_as_json_string_are_parsed(self, client):
        """Alguns modelos retornam arguments como string JSON em vez de dict."""
        resp_with_str_args = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "find_top_files",
                            "arguments": '{"limit": 5}',  # string JSON
                        }
                    }
                ],
            }
        }
        responses = iter([resp_with_str_args, _make_text_resp("ok")])
        executor = MagicMock(return_value={"files": []})
        with patch.object(client, "chat_once", side_effect=lambda *a, **kw: next(responses)):
            events = list(client.chat_with_tools("m", [], self.TOOLS, executor))

        tc = next(e for e in events if e["type"] == "tool_call")
        assert tc["args"] == {"limit": 5}  # deve ter sido parseado para dict
        executor.assert_called_once_with("find_top_files", {"limit": 5})

    def test_tool_result_added_to_messages_for_next_round(self, client):
        """Verifica que o resultado da tool é incluído no histórico da próxima chamada."""
        captured_messages: list[list[dict]] = []

        def fake_once(model, messages, **kwargs):
            captured_messages.append(list(messages))
            if len(captured_messages) == 1:
                return _make_tool_resp("list_partitions", {})
            return _make_text_resp("ok")

        executor = MagicMock(return_value={"letter": "C:"})
        with patch.object(client, "chat_once", side_effect=fake_once):
            list(client.chat_with_tools("m", [], self.TOOLS, executor))

        # Na segunda chamada, o histórico deve conter a mensagem "tool" com resultado
        second_call_messages = captured_messages[1]
        roles = [m["role"] for m in second_call_messages]
        assert "tool" in roles
