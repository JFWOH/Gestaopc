"""
AIBackend — abstração de backend de IA (RECON 8.4).

A GUI do Assistente (``src/gui/assistant_tab.py``) consumia ``OllamaClient``
diretamente, travando o app ao Ollama. Este Protocol descreve a superfície
mínima que a GUI realmente usa, permitindo trocar o backend (llama.cpp, API
remota compatível, etc.) sem tocar na GUI.

Convenção: segue o mesmo padrão de ``hash_cache.HashCache`` — ``typing.Protocol``
com tipagem estrutural (implementações NÃO precisam herdar). ``OllamaClient``
já satisfaz ``AIBackend`` como está, sem alterações.

Contrato de eventos de ``chat_with_tools`` (load-bearing — ``OllamaAgentWorker``
chaveia em ``event["type"]``)::

    {"type": "tool_call",   "name": str, "args": dict}
    {"type": "tool_result", "name": str, "result": object}
    {"type": "text",        "content": str}
    {"type": "error",       "message": str}

O formato de ``tools`` é o schema function-calling OpenAI/Ollama produzido por
``ai_toolbelt.get_tool_schemas()``. Um backend não-Ollama deve aceitar ou
traduzir esse formato.

Nota: ``chat_stream``/``chat_once`` do ``OllamaClient`` NÃO fazem parte do
Protocol — a GUI nunca os chama (``chat_once`` é interno de ``chat_with_tools``).
"""

from __future__ import annotations

from typing import Any, Callable, Iterator, Protocol, runtime_checkable


@runtime_checkable
class AIBackend(Protocol):
    """Superfície mínima de um backend de IA usada pela GUI do Assistente."""

    def is_available(self) -> bool:
        """Retorna True se o backend está acessível (servidor no ar, etc.)."""
        ...

    def get_models(self) -> list[str]:
        """Lista os identificadores de modelos selecionáveis (``[]`` se nenhum)."""
        ...

    def chat_with_tools(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: Callable[[str, dict], Any],
        max_iterations: int = 5,
    ) -> Iterator[dict]:
        """
        Loop agente com tool-calling. Faz yield de event dicts (ver docstring
        do módulo) até o modelo retornar texto final ou atingir max_iterations.
        Não deve mutar ``messages`` (trabalhe sobre uma cópia interna).
        """
        ...
