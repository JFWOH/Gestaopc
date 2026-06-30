"""
Testes do Protocol AIBackend — RECON 8.4.

Cobre:
  - OllamaClient satisfaz AIBackend (conformidade estrutural, isinstance via
    runtime_checkable)
  - Um backend fake mínimo também satisfaz o Protocol e é aceito como AIBackend
  - O contrato de eventos de chat_with_tools é preservável por um backend
    alternativo (sem depender de Ollama real)
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

from src.core.ai_backend import AIBackend
from src.core.ollama_client import OllamaClient


# ─────────────────────────────────────────────────────────────────────────────
# Conformidade do OllamaClient
# ─────────────────────────────────────────────────────────────────────────────

class TestOllamaClientConformance:
    def test_ollama_client_is_aibackend(self):
        """OllamaClient satisfaz AIBackend sem herdar (tipagem estrutural)."""
        client: AIBackend = OllamaClient()
        assert isinstance(client, AIBackend)

    def test_has_required_methods(self):
        client = OllamaClient()
        assert hasattr(client, "is_available")
        assert hasattr(client, "get_models")
        assert hasattr(client, "chat_with_tools")


# ─────────────────────────────────────────────────────────────────────────────
# Backend alternativo mínimo
# ─────────────────────────────────────────────────────────────────────────────

class _FakeBackend:
    """Backend de teste que satisfaz AIBackend sem nenhuma dependência externa."""

    def __init__(self, models: list[str] | None = None, available: bool = True):
        self._models = models or ["fake-model"]
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def get_models(self) -> list[str]:
        return list(self._models)

    def chat_with_tools(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: Callable[[str, dict], Any],
        max_iterations: int = 5,
    ) -> Iterator[dict]:
        # Emite um texto final no formato do contrato de eventos.
        yield {"type": "text", "content": f"resposta de {model}"}


class TestAlternativeBackend:
    def test_fake_backend_is_aibackend(self):
        backend: AIBackend = _FakeBackend()
        assert isinstance(backend, AIBackend)

    def test_fake_backend_event_contract(self):
        backend = _FakeBackend()
        events = list(
            backend.chat_with_tools("m", [], [], lambda name, args: None)
        )
        assert events == [{"type": "text", "content": "resposta de m"}]

    def test_fake_backend_diagnostics(self):
        backend = _FakeBackend(models=["a", "b"], available=False)
        assert backend.is_available() is False
        assert backend.get_models() == ["a", "b"]


# ─────────────────────────────────────────────────────────────────────────────
# Injeção no AssistantTab / OllamaAgentWorker
# ─────────────────────────────────────────────────────────────────────────────

class TestBackendInjection:
    def test_worker_uses_injected_backend(self):
        """OllamaAgentWorker deve usar o backend injetado, não criar um Ollama."""
        import pytest
        pytest.importorskip("PySide6")

        from src.gui.assistant_tab import OllamaAgentWorker

        fake = _FakeBackend()
        worker = OllamaAgentWorker("m", [], [], backend=fake)
        assert worker._client is fake

    def test_worker_defaults_to_ollama(self):
        import pytest
        pytest.importorskip("PySide6")

        from src.gui.assistant_tab import OllamaAgentWorker

        worker = OllamaAgentWorker("m", [], [])
        assert isinstance(worker._client, OllamaClient)
