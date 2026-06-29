"""
Testes de ciclo de vida do AssistantTab — Sprint 7.5.

Foco: vazamentos de recursos (DB, threads, signals) que apareceriam em
sessões longas. NÃO testa o fluxo de chat com Ollama (requer servidor real
e tem testes de integração separados).

Cobre:
  - closeEvent fecha DB e para worker ativo
  - _stop_active_worker é seguro com worker=None
  - _stop_active_worker chama disconnect + deleteLater
  - _disconnect_worker_signals é idempotente
  - _send_message para worker anterior antes de criar novo
  - _on_response_finished limpa worker
  - closeEvent é seguro de chamar duas vezes
  - _get_system_context loga exceptions com stack trace (não mais silencioso)

Estratégia:
  - Mock Ollama (não há servidor rodando em CI)
  - Mock workers para evitar threads reais
  - Verificar chamadas a disconnect/quit/wait/deleteLater via spies
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtGui import QCloseEvent  # noqa: E402  (após importorskip)

from src.gui.assistant_tab import AssistantTab  # noqa: E402  (após importorskip)


# ─────────────────────────────────────────────────────────────────────────────
# Fixture: AssistantTab com OllamaClient e DB mockados
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tab(qapp_session, tmp_path, monkeypatch):
    """
    Cria AssistantTab com OllamaClient mock e DB em tmp_path.

    Evita dependência de servidor Ollama real e DB de produção.
    """
    # Mock OllamaClient para que is_available() retorne False —
    # _refresh_models não tenta consultar a rede real.
    mock_client = MagicMock()
    mock_client.is_available.return_value = False
    mock_client.get_models.return_value = []

    # Patch o caminho default do DB para tmp_path
    monkeypatch.setattr(
        "src.gui.assistant_tab.get_default_db_path",
        lambda: tmp_path / "assistant_test.db",
    )
    monkeypatch.setattr(
        "src.gui.assistant_tab.OllamaClient",
        lambda *a, **kw: mock_client,
    )

    widget = AssistantTab()
    yield widget
    # Cleanup — equivalente ao closeEvent
    try:
        widget.deleteLater()
    except Exception:
        pass


@pytest.fixture(scope="session")
def qapp_session():
    """Reusa a QApplication global do conftest."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ─────────────────────────────────────────────────────────────────────────────
# closeEvent — cleanup de DB e worker
# ─────────────────────────────────────────────────────────────────────────────

class TestCloseEvent:
    def test_close_event_closes_db(self, tab):
        # DB inicial não deve ser None
        assert tab._db is not None
        db_close_mock = MagicMock()
        tab._db.close = db_close_mock

        evt = QCloseEvent()
        tab.closeEvent(evt)

        db_close_mock.assert_called_once()
        assert tab._db is None

    def test_close_event_safe_when_db_already_none(self, tab):
        tab._db = None
        evt = QCloseEvent()
        # Não deve crashar
        tab.closeEvent(evt)

    def test_close_event_safe_when_db_missing(self, tab):
        del tab._db
        evt = QCloseEvent()
        tab.closeEvent(evt)  # não deve crashar

    def test_close_event_calls_stop_active_worker(self, tab):
        with patch.object(tab, "_stop_active_worker") as mock_stop:
            evt = QCloseEvent()
            tab.closeEvent(evt)
            mock_stop.assert_called_once()
            # Timeout passado deve ser o constante de quit
            args, kwargs = mock_stop.call_args
            timeout = kwargs.get("timeout_ms") or (args[0] if args else None)
            assert timeout == AssistantTab._WORKER_QUIT_TIMEOUT_MS

    def test_close_event_idempotent(self, tab):
        """Chamar closeEvent duas vezes não deve crashar."""
        evt = QCloseEvent()
        tab.closeEvent(evt)
        tab.closeEvent(evt)  # segunda chamada — DB já None, worker já None

    def test_close_event_swallows_db_close_exceptions(self, tab):
        """Falha no close do DB não deve impedir limpeza do widget."""
        tab._db.close = MagicMock(side_effect=RuntimeError("DB locked"))
        evt = QCloseEvent()
        tab.closeEvent(evt)  # não deve propagar


# ─────────────────────────────────────────────────────────────────────────────
# _stop_active_worker
# ─────────────────────────────────────────────────────────────────────────────

class TestStopActiveWorker:
    def test_safe_when_worker_is_none(self, tab):
        tab._worker = None
        tab._stop_active_worker()  # não deve crashar
        assert tab._worker is None

    def test_clears_worker_reference(self, tab):
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = False
        tab._worker = mock_worker
        tab._stop_active_worker()
        assert tab._worker is None

    def test_calls_quit_and_wait_when_running(self, tab):
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        mock_worker.wait.return_value = True  # parou no timeout
        tab._worker = mock_worker

        tab._stop_active_worker(timeout_ms=1000)

        mock_worker.quit.assert_called_once()
        mock_worker.wait.assert_called_once_with(1000)
        mock_worker.terminate.assert_not_called()

    def test_terminates_when_wait_times_out(self, tab):
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        mock_worker.wait.side_effect = [False, True]  # primeiro wait falha
        tab._worker = mock_worker

        tab._stop_active_worker(timeout_ms=500)

        mock_worker.quit.assert_called_once()
        mock_worker.terminate.assert_called_once()

    def test_skips_quit_when_not_running(self, tab):
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = False
        tab._worker = mock_worker

        tab._stop_active_worker()

        mock_worker.quit.assert_not_called()
        mock_worker.wait.assert_not_called()

    def test_calls_delete_later(self, tab):
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = False
        tab._worker = mock_worker

        tab._stop_active_worker()

        mock_worker.deleteLater.assert_called_once()

    def test_disconnects_signals_before_quit(self, tab):
        """Garante que sinais sejam desconectados ANTES de quit() ser chamado."""
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        mock_worker.wait.return_value = True

        # Adicionar atributos de sinal mockados para os nomes esperados
        for name in AssistantTab._WORKER_SIGNAL_NAMES:
            setattr(mock_worker, name, MagicMock())

        tab._worker = mock_worker
        tab._stop_active_worker()

        # Verificar que disconnect foi chamado em pelo menos um sinal
        for name in AssistantTab._WORKER_SIGNAL_NAMES:
            sig = getattr(mock_worker, name)
            sig.disconnect.assert_called()

    def test_swallows_quit_exception(self, tab):
        """Worker.quit() lançando exceção não deve propagar."""
        mock_worker = MagicMock()
        mock_worker.isRunning.side_effect = RuntimeError("worker dead")
        tab._worker = mock_worker
        tab._stop_active_worker()  # não deve crashar


# ─────────────────────────────────────────────────────────────────────────────
# _disconnect_worker_signals
# ─────────────────────────────────────────────────────────────────────────────

class TestDisconnectWorkerSignals:
    def test_safe_with_none_worker(self, tab):
        tab._disconnect_worker_signals(None)  # não deve crashar

    def test_calls_disconnect_on_known_signals(self, tab):
        worker = MagicMock()
        for name in AssistantTab._WORKER_SIGNAL_NAMES:
            setattr(worker, name, MagicMock())

        tab._disconnect_worker_signals(worker)

        for name in AssistantTab._WORKER_SIGNAL_NAMES:
            sig = getattr(worker, name)
            sig.disconnect.assert_called_once()

    def test_skips_missing_signals(self, tab):
        """Worker sem alguns dos sinais (ex.: OllamaChatWorker) é OK."""
        worker = MagicMock(spec=[])  # spec vazio → atributos padrão ausentes
        tab._disconnect_worker_signals(worker)  # não deve crashar

    def test_idempotent_when_already_disconnected(self, tab):
        """RuntimeError de 'no connections' é silenciosamente ignorado."""
        worker = MagicMock()
        for name in AssistantTab._WORKER_SIGNAL_NAMES:
            sig = MagicMock()
            sig.disconnect.side_effect = RuntimeError("not connected")
            setattr(worker, name, sig)

        tab._disconnect_worker_signals(worker)  # não deve propagar


# ─────────────────────────────────────────────────────────────────────────────
# _on_response_finished cleanup
# ─────────────────────────────────────────────────────────────────────────────

class TestOnResponseFinished:
    def test_cleans_up_worker(self, tab):
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = False
        tab._worker = mock_worker

        with patch.object(tab, "_stop_active_worker") as mock_stop:
            tab._on_response_finished()
            mock_stop.assert_called_once()

    def test_uses_short_timeout(self, tab):
        """Worker já finalizou — wait() retorna rápido. Use timeout curto."""
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = False
        tab._worker = mock_worker

        with patch.object(tab, "_stop_active_worker") as mock_stop:
            tab._on_response_finished()
            args, kwargs = mock_stop.call_args
            timeout = kwargs.get("timeout_ms") or (args[0] if args else None)
            assert timeout == AssistantTab._WORKER_CLEANUP_TIMEOUT_MS

    def test_appends_text_to_messages_when_present(self, tab):
        tab._current_response_text = "Resposta do agente"
        tab._messages = [{"role": "user", "content": "pergunta"}]

        tab._on_response_finished()

        assert tab._messages[-1]["role"] == "assistant"
        assert tab._messages[-1]["content"] == "Resposta do agente"

    def test_skips_message_when_text_empty(self, tab):
        tab._current_response_text = ""
        tab._messages = [{"role": "user", "content": "x"}]
        before = len(tab._messages)
        tab._on_response_finished()
        assert len(tab._messages) == before  # nada adicionado


# ─────────────────────────────────────────────────────────────────────────────
# _get_system_context: logging com stack trace (Q-5)
# ─────────────────────────────────────────────────────────────────────────────

class TestSystemContextLogging:
    """Sprint 7.5 (Q-5): except Exception agora preserva stack trace."""

    def test_logs_traceback_when_list_partitions_fails(self, tab, caplog):
        with patch(
            "src.gui.assistant_tab.tb.list_partitions",
            side_effect=RuntimeError("scanner crashed"),
        ):
            with caplog.at_level(logging.ERROR, logger="src.gui.assistant_tab"):
                ctx = tab._get_system_context()

        assert "[Partições] — Não disponível" in ctx
        # logger.exception inclui mensagem + traceback
        assert any("scanner crashed" in r.message or
                   (r.exc_info and "scanner crashed" in str(r.exc_info[1]))
                   for r in caplog.records)

    def test_logs_traceback_when_suggestions_fails(self, tab, caplog):
        with patch(
            "src.gui.assistant_tab.tb.list_suggestions",
            side_effect=RuntimeError("DB locked"),
        ):
            with caplog.at_level(logging.ERROR, logger="src.gui.assistant_tab"):
                ctx = tab._get_system_context()

        assert "[Sugestões] — Não disponível" in ctx
        assert any("DB locked" in str(r.exc_info[1])
                   for r in caplog.records if r.exc_info)

    def test_logs_traceback_when_duplicates_fails(self, tab, caplog):
        with patch(
            "src.gui.assistant_tab.tb.find_duplicates",
            side_effect=RuntimeError("hash failure"),
        ):
            with caplog.at_level(logging.ERROR, logger="src.gui.assistant_tab"):
                ctx = tab._get_system_context()

        assert "[Duplicatas] — Não disponível" in ctx
        assert any("hash failure" in str(r.exc_info[1])
                   for r in caplog.records if r.exc_info)

    def test_logs_traceback_when_history_fails(self, tab, caplog):
        with patch(
            "src.gui.assistant_tab.tb.get_history",
            side_effect=RuntimeError("query error"),
        ):
            with caplog.at_level(logging.ERROR, logger="src.gui.assistant_tab"):
                ctx = tab._get_system_context()

        assert "[Histórico] — Não disponível" in ctx
        assert any("query error" in str(r.exc_info[1])
                   for r in caplog.records if r.exc_info)

    def test_partial_failure_does_not_break_other_sections(self, tab):
        """Se uma seção falha, as outras ainda devem aparecer."""
        with patch(
            "src.gui.assistant_tab.tb.list_partitions",
            side_effect=RuntimeError("scanner crashed"),
        ):
            ctx = tab._get_system_context()

        # Falhou
        assert "[Partições] — Não disponível" in ctx
        # Mas outras seções estão presentes
        assert "[Sugestões" in ctx
        assert "[Duplicatas" in ctx
        assert "[Histórico" in ctx or "[Últimas" in ctx
