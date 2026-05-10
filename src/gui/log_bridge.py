"""
Bridge entre o logging do Python e sinais Qt — Sprint 7.0.

Captura mensagens do logger (INFO+ por padrão) e re-emite como Signal,
permitindo exibição em tempo real na status bar sem qualquer modificação
no código de logging dos módulos core (scanner, analyzer, executor, etc.).

Motivação:
    Operações longas (ex.: hash completo SHA-256 em Etapa 3 de duplicatas)
    podem rodar 10+ minutos sem feedback visual, dando a impressão de
    travamento. Os módulos core já fazem `logger.info(...)` em pontos-chave
    (ex.: "Etapa 2 concluída: 523 grupos com hash parcial"); este bridge
    aproveita esses logs e os exibe na status bar automaticamente.

Uso típico:
    bridge = QtLogBridge()
    bridge.install()
    bridge.message.connect(status_bar.showMessage)

Thread-safety:
    Signal.emit() é thread-safe e usa Qt::QueuedConnection automaticamente
    quando emissor e receptor estão em threads diferentes — exatamente o
    cenário de QThread workers chamando logger no thread de trabalho.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from src.core.config import LOG_BRIDGE_MAX_MESSAGE_LENGTH


# Sprint 7.6: alias backward-compat — valor canônico em config.py
_MAX_MESSAGE_LENGTH: int = LOG_BRIDGE_MAX_MESSAGE_LENGTH


class QtLogBridge(QObject):
    """
    Re-emite mensagens de log como sinais Qt thread-safe.

    Parameters
    ----------
    level : int
        Nível mínimo de log a capturar (default: logging.INFO).
    parent : QObject | None
        Parent Qt opcional para gerenciamento de ciclo de vida.

    Signals
    -------
    message(str)
        Emitido para cada log record formatado, truncado a 200 chars.
    """

    message = Signal(str)

    def __init__(self, level: int = logging.INFO, parent: QObject | None = None):
        super().__init__(parent)
        self._handler = _SignalHandler(self, level=level)
        self._installed_logger: logging.Logger | None = None

    def install(self, logger_name: str | None = None) -> None:
        """
        Instala o handler no logger raiz (ou em logger específico).

        Parameters
        ----------
        logger_name : str | None
            Nome do logger alvo. None → logger raiz (captura tudo).
        """
        if self._installed_logger is not None:
            # Já instalado em algum logger — remover antes para evitar duplicação
            self.uninstall()
        target = (
            logging.getLogger(logger_name) if logger_name else logging.getLogger()
        )
        target.addHandler(self._handler)
        self._installed_logger = target

    def uninstall(self) -> None:
        """Remove o handler do logger onde foi instalado."""
        if self._installed_logger is not None:
            self._installed_logger.removeHandler(self._handler)
            self._installed_logger = None

    def set_level(self, level: int) -> None:
        """Ajusta o nível mínimo de captura."""
        self._handler.setLevel(level)

    @property
    def is_installed(self) -> bool:
        return self._installed_logger is not None


class _SignalHandler(logging.Handler):
    """
    Handler interno que dispara o Signal de QtLogBridge para cada record.

    Erros internos são silenciados via logging.Handler.handleError()
    para nunca interromper o fluxo do app por causa de telemetria de UI.
    """

    def __init__(self, bridge: QtLogBridge, level: int = logging.INFO):
        super().__init__(level=level)
        self._bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            if len(msg) > _MAX_MESSAGE_LENGTH:
                msg = msg[: _MAX_MESSAGE_LENGTH - 3] + "..."
            # Signal.emit é thread-safe (QueuedConnection automática)
            self._bridge.message.emit(msg)
        except Exception:
            self.handleError(record)
