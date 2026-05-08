"""
Cliente HTTP para o servidor Ollama local.

Suporta dois modos de operação:
  1. ``chat_stream()``    — streaming simples sem tool-calling (chat básico).
  2. ``chat_with_tools()`` — loop agente com tool-calling; itera até o modelo
                             retornar texto final ou atingir max_iterations.

O formato de tools segue o padrão OpenAI/Ollama function-calling, idêntico
ao retornado por ``ai_toolbelt.get_tool_schemas()``.
"""

import json
import logging
import urllib.request
import urllib.error
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)


class OllamaClient:
    """Cliente HTTP para o servidor Ollama local (padrão: localhost:11434)."""

    def __init__(self, host: str = "http://localhost:11434"):
        self.host = host

    # ─────────────────────────────────────────────────────────────────────────
    # Diagnóstico
    # ─────────────────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Verifica se o servidor Ollama está rodando e acessível."""
        try:
            req = urllib.request.Request(self.host)
            with urllib.request.urlopen(req, timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def get_models(self) -> list[str]:
        """Retorna lista com os nomes dos modelos instalados no Ollama."""
        try:
            req = urllib.request.Request(f"{self.host}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as response:
                data = json.loads(response.read().decode("utf-8"))
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.warning("Erro ao buscar modelos Ollama: %s", e)
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # Chat simples (streaming, sem tools)
    # ─────────────────────────────────────────────────────────────────────────

    def chat_stream(self, model: str, messages: list[dict]) -> Iterator[str]:
        """
        Chat com streaming de tokens, sem tool-calling.

        Mantido para compatibilidade e uso em contextos sem suporte a tools.
        Yields tokens de texto conforme chegam da API.
        """
        url = f"{self.host}/api/chat"
        payload = json.dumps({"model": model, "messages": messages}).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req) as response:
                for line in response:
                    if line:
                        try:
                            data = json.loads(line.decode("utf-8"))
                            yield data.get("message", {}).get("content", "")
                            if data.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error("Erro no chat_stream Ollama: %s", e)
            yield f"\n[Erro de conexão com '{model}': {e}]"

    # ─────────────────────────────────────────────────────────────────────────
    # Chat único não-streaming (base para o loop agente)
    # ─────────────────────────────────────────────────────────────────────────

    def chat_once(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        timeout: int = 120,
    ) -> dict | None:
        """
        Chamada única não-streaming à API /api/chat.

        Suporta tool-calling via o parâmetro ``tools`` (formato OpenAI/Ollama).
        Se o modelo não suportar tools, ignora o parâmetro e retorna texto.

        Args:
            model: Nome do modelo Ollama (ex: 'qwen2.5', 'llama3.1').
            messages: Histórico de mensagens no formato Ollama.
            tools: Lista de schemas de tools. Se None, chamada sem tools.
            timeout: Timeout em segundos (padrão 120s para modelos lentos).

        Returns:
            Dicionário com a resposta completa da API, ou None em caso de erro.
        """
        url = f"{self.host}/api/chat"
        payload_data: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload_data["tools"] = tools

        payload = json.dumps(payload_data).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as e:
            logger.error("Erro em chat_once Ollama: %s", e)
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Loop agente com tool-calling
    # ─────────────────────────────────────────────────────────────────────────

    def chat_with_tools(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: Callable[[str, dict], Any],
        max_iterations: int = 5,
    ) -> Iterator[dict]:
        """
        Executa loop agente com tool-calling até o modelo retornar texto final.

        Yields event dicts para que o chamador possa processar de forma reativa:

        .. code-block:: python

            {"type": "tool_call",   "name": str, "args": dict}
            {"type": "tool_result", "name": str, "result": object}
            {"type": "text",        "content": str}
            {"type": "error",       "message": str}

        Args:
            model: Nome do modelo Ollama.
            messages: Histórico de mensagens (copiado internamente, não mutado).
            tools: Schemas de tools no formato OpenAI/Ollama.
            tool_executor: callable(name, args) → result. Executa a tool pelo nome.
            max_iterations: Limite de rounds de tool-calling por segurança (padrão 5).
        """
        current_messages = list(messages)

        for _iteration in range(max_iterations):
            response = self.chat_once(model, current_messages, tools=tools)
            if response is None:
                yield {
                    "type": "error",
                    "message": "Sem resposta do Ollama. Verifique se o servidor está rodando.",
                }
                return

            msg = response.get("message", {})
            tool_calls: list[dict] = msg.get("tool_calls") or []

            if not tool_calls:
                # Modelo retornou texto final — encerra o loop
                content = msg.get("content", "")
                yield {"type": "text", "content": content}
                return

            # Adiciona mensagem do assistant (com tool_calls) ao histórico
            current_messages.append(msg)

            for tc in tool_calls:
                fn_info = tc.get("function", {})
                name: str = fn_info.get("name", "")
                args: Any = fn_info.get("arguments", {})

                # Alguns modelos retornam args como string JSON
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}

                yield {"type": "tool_call", "name": name, "args": args}

                try:
                    result = tool_executor(name, args)
                except Exception as exc:
                    result = {"error": "EXECUTOR_ERROR", "message": str(exc)}

                yield {"type": "tool_result", "name": name, "result": result}

                # Adiciona resultado da tool ao histórico
                current_messages.append({
                    "role": "tool",
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

        yield {
            "type": "error",
            "message": (
                f"Limite de {max_iterations} rounds de tool-calling atingido "
                "sem resposta final do modelo."
            ),
        }
