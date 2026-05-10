"""
Testes para src.gui.log_bridge — Sprint 7.0.

Cobre:
  - _SignalHandler.emit() formata e envia mensagens
  - Truncamento de mensagens longas (> 200 chars)
  - QtLogBridge.install() / uninstall() — adiciona e remove handler
  - install() em logger nomeado vs raiz
  - install() chamado duas vezes não duplica handler
  - set_level() ajusta o nível do handler
  - Tratamento silencioso de erros em emit() (handleError)

Estratégia:
  - Testar _SignalHandler isoladamente com um Signal mock
    (objeto com método .emit que coleta strings) — evita necessidade
    de QApplication para a maior parte dos testes.
  - Onde QtLogBridge é exercitado, usar instância sem precisar de
    event loop Qt rodando, já que apenas Signal.emit() é chamado
    e a entrega acontece via direct connection no mesmo thread.
"""

from __future__ import annotations

import logging

import pytest

# Pular todos os testes deste arquivo se PyQt6 não estiver disponível
PySide6 = pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication

from src.gui.log_bridge import QtLogBridge, _SignalHandler


# ─────────────────────────────────────────────────────────────────────────────
# Fixture: garantir QCoreApplication existe (para QObject + Signal)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qapp():
    """Garante uma única QCoreApplication para todos os testes do módulo."""
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


# ─────────────────────────────────────────────────────────────────────────────
# _SignalHandler — comportamento básico
# ─────────────────────────────────────────────────────────────────────────────

class _MockBridge:
    """Stub mínimo de QtLogBridge expondo apenas .message.emit()."""

    def __init__(self):
        self.received: list[str] = []

        class _Sig:
            def emit(_self, msg: str) -> None:
                self.received.append(msg)

        self.message = _Sig()


class TestSignalHandlerBasics:
    def test_emit_forwards_message(self):
        bridge = _MockBridge()
        handler = _SignalHandler(bridge, level=logging.INFO)
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__,
            lineno=10, msg="hello world", args=(), exc_info=None,
        )
        handler.emit(record)
        assert bridge.received == ["hello world"]

    def test_emit_formats_args(self):
        bridge = _MockBridge()
        handler = _SignalHandler(bridge, level=logging.INFO)
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__,
            lineno=10, msg="counted %d items", args=(42,), exc_info=None,
        )
        handler.emit(record)
        assert bridge.received == ["counted 42 items"]

    def test_emit_truncates_long_message(self):
        bridge = _MockBridge()
        handler = _SignalHandler(bridge, level=logging.INFO)
        long_msg = "X" * 500
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__,
            lineno=10, msg=long_msg, args=(), exc_info=None,
        )
        handler.emit(record)
        assert len(bridge.received) == 1
        delivered = bridge.received[0]
        assert len(delivered) <= 200
        assert delivered.endswith("...")

    def test_short_message_not_truncated(self):
        bridge = _MockBridge()
        handler = _SignalHandler(bridge, level=logging.INFO)
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__,
            lineno=10, msg="short", args=(), exc_info=None,
        )
        handler.emit(record)
        assert bridge.received == ["short"]

    def test_emit_handles_exception_silently(self, monkeypatch):
        """Se algo falhar dentro de emit(), handleError é chamado, sem propagar."""
        bridge = _MockBridge()
        handler = _SignalHandler(bridge, level=logging.INFO)

        # Forçar exceção em getMessage() via record corrompido
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__,
            lineno=10, msg="fmt %s", args=(object(),),  # args inválidos para %s? — sempre OK
            exc_info=None,
        )

        # Patch handleError para detectar invocação
        called: list[bool] = []
        monkeypatch.setattr(
            handler, "handleError", lambda r: called.append(True)
        )
        # Patch o emit do signal para lançar
        original_emit = bridge.message.emit

        def boom(_msg):
            raise RuntimeError("Qt indisponivel")

        bridge.message.emit = boom

        # Não deve propagar
        handler.emit(record)
        assert called == [True]

        bridge.message.emit = original_emit


# ─────────────────────────────────────────────────────────────────────────────
# QtLogBridge — install / uninstall
# ─────────────────────────────────────────────────────────────────────────────

class TestQtLogBridgeInstall:
    def test_install_adds_handler_to_root_logger(self, qapp):
        bridge = QtLogBridge()
        before = len(logging.getLogger().handlers)
        bridge.install()
        try:
            after = len(logging.getLogger().handlers)
            assert after == before + 1
            assert bridge.is_installed
        finally:
            bridge.uninstall()

    def test_uninstall_removes_handler(self, qapp):
        bridge = QtLogBridge()
        bridge.install()
        before = len(logging.getLogger().handlers)
        bridge.uninstall()
        after = len(logging.getLogger().handlers)
        assert after == before - 1
        assert not bridge.is_installed

    def test_uninstall_without_install_is_safe(self, qapp):
        bridge = QtLogBridge()
        bridge.uninstall()  # não deve lançar
        assert not bridge.is_installed

    def test_install_twice_does_not_duplicate(self, qapp):
        bridge = QtLogBridge()
        bridge.install()
        try:
            count_after_first = len(logging.getLogger().handlers)
            bridge.install()  # segunda chamada — deve remover antes
            count_after_second = len(logging.getLogger().handlers)
            assert count_after_second == count_after_first
        finally:
            bridge.uninstall()

    def test_install_on_named_logger(self, qapp):
        bridge = QtLogBridge()
        named_logger = logging.getLogger("test.named.logger")
        before = len(named_logger.handlers)
        bridge.install(logger_name="test.named.logger")
        try:
            after = len(named_logger.handlers)
            assert after == before + 1
        finally:
            bridge.uninstall()

    def test_set_level_changes_handler_level(self, qapp):
        bridge = QtLogBridge(level=logging.INFO)
        bridge.set_level(logging.WARNING)
        assert bridge._handler.level == logging.WARNING

    def test_default_level_is_info(self, qapp):
        bridge = QtLogBridge()
        assert bridge._handler.level == logging.INFO


# ─────────────────────────────────────────────────────────────────────────────
# Integração: log emitido → recebido via signal
# ─────────────────────────────────────────────────────────────────────────────

class TestEndToEnd:
    def test_logger_info_reaches_signal(self, qapp):
        """Mensagem real do logger.info() é entregue via Signal."""
        bridge = QtLogBridge()
        received: list[str] = []
        bridge.message.connect(received.append)
        bridge.install()
        try:
            test_logger = logging.getLogger("test.e2e.bridge")
            # Garantir que o logger propaga para o root onde está o handler
            test_logger.setLevel(logging.INFO)
            test_logger.info("varredura concluida em 12.5s")
            QCoreApplication.processEvents()  # flush queued connections
            assert any("varredura concluida" in m for m in received)
        finally:
            bridge.uninstall()

    def test_debug_below_threshold_not_delivered(self, qapp):
        """Mensagens DEBUG não são entregues quando nível é INFO."""
        bridge = QtLogBridge(level=logging.INFO)
        received: list[str] = []
        bridge.message.connect(received.append)
        bridge.install()
        try:
            test_logger = logging.getLogger("test.threshold.bridge")
            test_logger.setLevel(logging.DEBUG)
            test_logger.debug("isto eh debug, nao deve aparecer")
            test_logger.info("isto eh info, deve aparecer")
            QCoreApplication.processEvents()
            assert any("info" in m for m in received)
            assert not any("debug" in m for m in received)
        finally:
            bridge.uninstall()
