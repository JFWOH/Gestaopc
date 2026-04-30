"""
Ícone e System Tray — Branding visual do Gerenciador de PC.

Gera um ícone programático (SVG → QIcon) e fornece um QSystemTrayIcon
com menu de contexto para acesso rápido.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from src.gui.styles import Colors


def create_app_icon(size: int = 128) -> QIcon:
    """
    Gera um QIcon programático para a aplicação.

    Design: disco estilizado com gradiente ciano sobre fundo escuro,
    com uma letra "G" central.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = size * 0.08
    rect_size = size - margin * 2

    # Fundo circular escuro
    painter.setPen(Qt.PenStyle.NoPen)
    bg_gradient = QLinearGradient(0, 0, size, size)
    bg_gradient.setColorAt(0.0, QColor("#1A1A2E"))
    bg_gradient.setColorAt(1.0, QColor("#0A0A1A"))
    painter.setBrush(bg_gradient)
    painter.drawEllipse(int(margin), int(margin), int(rect_size), int(rect_size))

    # Anel externo ciano
    pen = QPen(QColor(Colors.ACCENT_CYAN))
    pen.setWidth(max(2, int(size * 0.03)))
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    ring_margin = size * 0.12
    ring_size = size - ring_margin * 2
    painter.drawEllipse(int(ring_margin), int(ring_margin), int(ring_size), int(ring_size))

    # Arco decorativo (parcial)
    arc_pen = QPen(QColor(Colors.ACCENT_CYAN_HOVER))
    arc_pen.setWidth(max(3, int(size * 0.04)))
    arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(arc_pen)
    arc_margin = size * 0.18
    arc_size = size - arc_margin * 2
    from PyQt6.QtCore import QRectF
    arc_rect = QRectF(arc_margin, arc_margin, arc_size, arc_size)
    painter.drawArc(arc_rect, 45 * 16, 90 * 16)  # Arco de 90° no topo-direita

    # Letra "G" central
    painter.setPen(QColor(Colors.ACCENT_CYAN))
    font = QFont("Segoe UI", int(size * 0.35))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(
        pixmap.rect(),
        Qt.AlignmentFlag.AlignCenter,
        "G",
    )

    painter.end()

    icon = QIcon()
    # Gerar múltiplos tamanhos
    for s in [16, 24, 32, 48, 64, 128, 256]:
        scaled = pixmap.scaled(
            s, s,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        icon.addPixmap(scaled)

    return icon


def create_tray_icon(
    parent: QWidget,
    on_open=None,
    on_scan=None,
    on_quit=None,
) -> QSystemTrayIcon:
    """
    Cria um QSystemTrayIcon com menu de contexto.

    Parameters
    ----------
    parent:
        Widget pai.
    on_open:
        Callback para "Abrir Gerenciador".
    on_scan:
        Callback para "Varredura Rápida".
    on_quit:
        Callback para "Sair".

    Returns
    -------
    QSystemTrayIcon configurado e pronto para .show().
    """
    tray = QSystemTrayIcon(parent)
    tray.setIcon(create_app_icon(64))
    tray.setToolTip("Gerenciador de PC — Storage Manager")

    menu = QMenu()
    menu.setStyleSheet(f"""
        QMenu {{
            background-color: {Colors.BG_SECONDARY};
            color: {Colors.TEXT_PRIMARY};
            border: 1px solid {Colors.BORDER_SUBTLE};
            border-radius: 6px;
            padding: 4px;
        }}
        QMenu::item {{
            padding: 8px 24px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            background-color: {Colors.ACCENT_CYAN_DIM};
            color: {Colors.ACCENT_CYAN};
        }}
    """)

    act_open = menu.addAction("Abrir Gerenciador")
    if on_open:
        act_open.triggered.connect(on_open)

    act_scan = menu.addAction("Varredura Rapida")
    if on_scan:
        act_scan.triggered.connect(on_scan)

    menu.addSeparator()

    act_quit = menu.addAction("Sair")
    if on_quit:
        act_quit.triggered.connect(on_quit)

    tray.setContextMenu(menu)

    # Duplo clique abre a janela
    if on_open:
        tray.activated.connect(
            lambda reason: on_open()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )

    return tray
