"""
Componentes visuais compartilhados entre as abas da GUI.

Exporta:
    make_label(text, css_class, font_size) -> QLabel
    make_separator()                        -> QFrame
    DiskUsageBar(QWidget)
    SuggestionCard(QWidget)
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.gui.styles import Colors, Fonts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_label(text: str, css_class: str = "", font_size: int = 0) -> QLabel:
    """Cria um QLabel com classe CSS e tamanho de fonte opcionais."""
    lbl = QLabel(text)
    if css_class:
        lbl.setProperty("cssClass", css_class)
    if font_size:
        f = lbl.font()
        f.setPointSize(font_size)
        lbl.setFont(f)
    return lbl


def make_separator() -> QFrame:
    """Linha horizontal fina para separar seções."""
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(f"background-color: {Colors.BORDER_SUBTLE}; max-height: 1px;")
    return sep


# ---------------------------------------------------------------------------
# DiskUsageBar
# ---------------------------------------------------------------------------

class DiskUsageBar(QWidget):
    """
    Barra visual de uso de disco individual.
    Mostra: [Letra]  [tipo]  [barra de progresso]  [XX% | livre: YY GB]
    """

    def __init__(
        self,
        letter: str = "C:",
        label: str = "Disco",
        percent: float = 0.0,
        total_gb: float = 0.0,
        free_gb: float = 0.0,
        media_type: str = "Desconhecido",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        # ---- Header row
        header = QHBoxLayout()
        header.setSpacing(10)

        lbl_letter = make_label(letter, "accent")
        lbl_letter.setFixedWidth(30)
        f = lbl_letter.font()
        f.setPointSize(Fonts.SIZE_HEADING)
        f.setBold(True)
        lbl_letter.setFont(f)
        header.addWidget(lbl_letter)

        media_colors = {
            "NVMe": Colors.ACCENT_CYAN,
            "SSD": Colors.STATUS_GREEN,
            "HDD": Colors.STATUS_YELLOW,
        }
        m_color = media_colors.get(media_type, Colors.TEXT_DISABLED)
        lbl_media = QLabel(f"  {media_type}  ")
        lbl_media.setStyleSheet(
            f"background-color: {m_color}22; color: {m_color}; "
            f"border: 1px solid {m_color}44; border-radius: 3px; "
            f"font-size: 10px; font-weight: 700; padding: 2px 6px;"
        )
        lbl_media.setFixedHeight(20)
        header.addWidget(lbl_media)

        lbl_name = make_label(label, "subtext")
        header.addWidget(lbl_name)
        header.addStretch()

        # Cor conforme uso
        if percent >= 90:
            color = Colors.STATUS_RED
            status_txt = "CRITICO"
        elif percent >= 75:
            color = Colors.STATUS_ORANGE
            status_txt = "ALTO"
        elif percent >= 50:
            color = Colors.STATUS_YELLOW
            status_txt = "MODERADO"
        else:
            color = Colors.STATUS_GREEN
            status_txt = "SAUDAVEL"

        lbl_stats = make_label(
            f"{percent:.1f}% usado  |  {free_gb:.1f} GB livre de {total_gb:.0f} GB",
            "subtext",
        )
        header.addWidget(lbl_stats)

        lbl_status = make_label(status_txt)
        lbl_status.setStyleSheet(
            f"color: {color}; font-weight: 700; font-size: 11px;"
        )
        lbl_status.setFixedWidth(80)
        lbl_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(lbl_status)
        layout.addLayout(header)

        # ---- Progress bar
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(percent))
        bar.setTextVisible(False)
        bar.setFixedHeight(10)
        bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {Colors.BG_INPUT};
                border: none;
                border-radius: 5px;
            }}
            QProgressBar::chunk {{
                border-radius: 5px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {color},
                    stop:1 {color}88
                );
            }}
        """)
        layout.addWidget(bar)


# ---------------------------------------------------------------------------
# SuggestionCard
# ---------------------------------------------------------------------------

class SuggestionCard(QWidget):
    """
    Card visual para uma sugestão do Motor de Regras.
    Mostra: [Badge R#]  [Título + prioridade]  [Detalhe]  [Botão]
    """

    def __init__(
        self,
        rule_id: int = 1,
        rule_name: str = "Regra",
        action: str = "MOVER",
        detail: str = "Descricao da sugestao",
        priority: str = "MEDIA",
        file_path: str = "",
        target_disk: str = "",
        on_execute=None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("suggestionCard")

        self.file_path = file_path
        self.target_disk = target_disk
        self.action_type = action

        # Cores conforme prioridade e ação
        if priority == "ALTA":
            badge_color = Colors.STATUS_RED
        elif priority in ("MEDIA", "MÉDIA"):
            badge_color = Colors.STATUS_YELLOW
        else:
            badge_color = Colors.STATUS_GREEN

        action_color = Colors.STATUS_RED if action == "DELETAR" else Colors.ACCENT_CYAN

        self.setStyleSheet(f"""
            QWidget#suggestionCard {{
                background-color: {Colors.BG_SECONDARY};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-left: 3px solid {action_color};
                border-radius: 8px;
            }}
            QWidget#suggestionCard:hover {{
                background-color: {Colors.BG_ELEVATED};
                border-color: {action_color};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        # Badge de regra
        badge = QLabel(f"R{rule_id}")
        badge.setFixedSize(36, 36)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background-color: {action_color}22; color: {action_color}; "
            f"border-radius: 18px; font-weight: 800; font-size: 13px;"
        )
        layout.addWidget(badge)

        # Texto
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        title_row = QHBoxLayout()
        lbl_rule = make_label(rule_name)
        lbl_rule.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-weight: 600; font-size: 13px;"
        )
        title_row.addWidget(lbl_rule)

        lbl_priority = QLabel(f"  {priority}  ")
        lbl_priority.setStyleSheet(
            f"background-color: {badge_color}33; color: {badge_color}; "
            f"border-radius: 3px; font-size: 10px; font-weight: 700; padding: 2px 6px;"
        )
        lbl_priority.setFixedHeight(20)
        title_row.addWidget(lbl_priority)
        title_row.addStretch()
        text_layout.addLayout(title_row)

        lbl_detail = make_label(detail, "subtext")
        lbl_detail.setWordWrap(True)
        text_layout.addWidget(lbl_detail)

        layout.addLayout(text_layout, stretch=1)

        # Botão de ação
        btn_label = "Executar" if action == "MOVER" else "Deletar"
        btn_css = "danger" if action == "DELETAR" else ""
        self.btn_action = QPushButton(btn_label)
        self.btn_action.setFixedSize(100, 36)
        self.btn_action.setCursor(Qt.CursorShape.PointingHandCursor)
        if btn_css:
            self.btn_action.setProperty("cssClass", btn_css)
        if on_execute:
            self.btn_action.clicked.connect(on_execute)
        layout.addWidget(self.btn_action)
