"""
Design System — Tema visual inspirado no ASUS AI Suite 3.

Paleta de cores, tipografia e QSS (Qt Style Sheets) para toda a aplicação.
Referência: Seção 4 da spec 01-storage-manager.md.
"""

# ---------------------------------------------------------------------------
# Paleta de Cores
# ---------------------------------------------------------------------------

class Colors:
    """Constantes de cores do tema dark."""

    # Backgrounds
    BG_DARKEST = "#0A0A0A"      # Fundo mais profundo (barra de título custom)
    BG_PRIMARY = "#121212"       # Fundo principal da janela
    BG_SECONDARY = "#1E1E1E"    # Painéis, cards, abas
    BG_ELEVATED = "#252525"     # Elementos elevados (hover de cards)
    BG_INPUT = "#2A2A2A"        # Campos de input, tabelas

    # Accent
    ACCENT_CYAN = "#00A8FF"     # Destaque principal (botões, seleções, ícones)
    ACCENT_CYAN_HOVER = "#33BBFF"  # Hover do accent
    ACCENT_CYAN_PRESSED = "#0088CC"  # Pressed do accent
    ACCENT_CYAN_DIM = "rgba(0, 168, 255, 0.15)"  # Glow sutil

    # Status
    STATUS_GREEN = "#00E676"    # Sucesso / espaço livre saudável
    STATUS_YELLOW = "#FFD600"   # Atenção / uso moderado
    STATUS_ORANGE = "#FF9100"   # Alerta / uso alto
    STATUS_RED = "#FF1744"      # Crítico / disco quase cheio

    # Text
    TEXT_PRIMARY = "#EAEAEA"    # Texto principal
    TEXT_SECONDARY = "#9E9E9E"  # Texto secundário / labels
    TEXT_DISABLED = "#555555"   # Texto desabilitado
    TEXT_ON_ACCENT = "#FFFFFF"  # Texto sobre botões accent

    # Borders
    BORDER_SUBTLE = "#2C2C2C"   # Bordas suaves entre painéis
    BORDER_ACTIVE = "#00A8FF"   # Bordas de foco / seleção

    # Shadows
    SHADOW = "rgba(0, 0, 0, 0.5)"


class Fonts:
    """Configurações de tipografia."""
    FAMILY = "Segoe UI, Inter, Roboto, Arial"
    SIZE_TITLE = 22
    SIZE_HEADING = 16
    SIZE_BODY = 13
    SIZE_SMALL = 11
    SIZE_TINY = 10


# ---------------------------------------------------------------------------
# QSS — Stylesheet Global
# ---------------------------------------------------------------------------

GLOBAL_STYLESHEET = f"""

/* ===== BASE ===== */
QMainWindow, QWidget {{
    background-color: {Colors.BG_PRIMARY};
    color: {Colors.TEXT_PRIMARY};
    font-family: {Fonts.FAMILY};
    font-size: {Fonts.SIZE_BODY}px;
}}

/* ===== SCROLL BARS ===== */
QScrollBar:vertical {{
    background: {Colors.BG_SECONDARY};
    width: 8px;
    margin: 0;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {Colors.TEXT_DISABLED};
    min-height: 30px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: {Colors.TEXT_SECONDARY};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {Colors.BG_SECONDARY};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {Colors.TEXT_DISABLED};
    min-width: 30px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {Colors.TEXT_SECONDARY};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ===== TAB WIDGET ===== */
QTabWidget::pane {{
    border: 1px solid {Colors.BORDER_SUBTLE};
    border-radius: 6px;
    background: {Colors.BG_SECONDARY};
    top: -1px;
}}
QTabBar::tab {{
    background: {Colors.BG_PRIMARY};
    color: {Colors.TEXT_SECONDARY};
    border: 1px solid {Colors.BORDER_SUBTLE};
    border-bottom: none;
    padding: 10px 24px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-size: {Fonts.SIZE_BODY}px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background: {Colors.BG_SECONDARY};
    color: {Colors.ACCENT_CYAN};
    border-bottom: 2px solid {Colors.ACCENT_CYAN};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    background: {Colors.BG_ELEVATED};
    color: {Colors.TEXT_PRIMARY};
}}

/* ===== BOTÕES PRIMÁRIOS ===== */
QPushButton {{
    background-color: {Colors.ACCENT_CYAN};
    color: {Colors.TEXT_ON_ACCENT};
    border: none;
    border-radius: 6px;
    padding: 10px 24px;
    font-size: {Fonts.SIZE_BODY}px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {Colors.ACCENT_CYAN_HOVER};
}}
QPushButton:pressed {{
    background-color: {Colors.ACCENT_CYAN_PRESSED};
}}
QPushButton:disabled {{
    background-color: {Colors.BG_ELEVATED};
    color: {Colors.TEXT_DISABLED};
}}

/* ===== BOTÕES SECUNDÁRIOS (classe .secondary) ===== */
QPushButton[cssClass="secondary"] {{
    background-color: transparent;
    color: {Colors.ACCENT_CYAN};
    border: 1px solid {Colors.ACCENT_CYAN};
}}
QPushButton[cssClass="secondary"]:hover {{
    background-color: {Colors.ACCENT_CYAN_DIM};
}}

/* ===== BOTÕES DANGER ===== */
QPushButton[cssClass="danger"] {{
    background-color: {Colors.STATUS_RED};
    color: {Colors.TEXT_ON_ACCENT};
    border: none;
}}
QPushButton[cssClass="danger"]:hover {{
    background-color: #FF4466;
}}

/* ===== TABELAS ===== */
QTableWidget {{
    background-color: {Colors.BG_INPUT};
    alternate-background-color: {Colors.BG_SECONDARY};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER_SUBTLE};
    border-radius: 6px;
    gridline-color: {Colors.BORDER_SUBTLE};
    selection-background-color: {Colors.ACCENT_CYAN_DIM};
    selection-color: {Colors.ACCENT_CYAN};
    font-size: {Fonts.SIZE_SMALL}px;
}}
QTableWidget::item {{
    padding: 6px 10px;
    border-bottom: 1px solid {Colors.BORDER_SUBTLE};
}}
QTableWidget::item:selected {{
    background-color: {Colors.ACCENT_CYAN_DIM};
    color: {Colors.ACCENT_CYAN};
}}
QHeaderView::section {{
    background-color: {Colors.BG_SECONDARY};
    color: {Colors.ACCENT_CYAN};
    border: none;
    border-bottom: 2px solid {Colors.ACCENT_CYAN};
    padding: 8px 10px;
    font-weight: 600;
    font-size: {Fonts.SIZE_SMALL}px;
}}

/* ===== CHECKBOXES ===== */
QCheckBox {{
    color: {Colors.TEXT_PRIMARY};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 2px solid {Colors.TEXT_SECONDARY};
    border-radius: 4px;
    background: {Colors.BG_INPUT};
}}
QCheckBox::indicator:checked {{
    background-color: {Colors.ACCENT_CYAN};
    border-color: {Colors.ACCENT_CYAN};
}}
QCheckBox::indicator:hover {{
    border-color: {Colors.ACCENT_CYAN};
}}

/* ===== LABELS ===== */
QLabel {{
    color: {Colors.TEXT_PRIMARY};
}}
QLabel[cssClass="heading"] {{
    font-size: {Fonts.SIZE_HEADING}px;
    font-weight: 700;
    color: {Colors.TEXT_PRIMARY};
}}
QLabel[cssClass="subtext"] {{
    font-size: {Fonts.SIZE_SMALL}px;
    color: {Colors.TEXT_SECONDARY};
}}
QLabel[cssClass="accent"] {{
    color: {Colors.ACCENT_CYAN};
    font-weight: 600;
}}

/* ===== PROGRESS BAR ===== */
QProgressBar {{
    background-color: {Colors.BG_INPUT};
    border: none;
    border-radius: 4px;
    text-align: center;
    color: {Colors.TEXT_PRIMARY};
    font-size: {Fonts.SIZE_TINY}px;
    height: 12px;
}}
QProgressBar::chunk {{
    border-radius: 4px;
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {Colors.ACCENT_CYAN},
        stop:1 {Colors.ACCENT_CYAN_HOVER}
    );
}}

/* ===== TOOLTIPS ===== */
QToolTip {{
    background-color: {Colors.BG_ELEVATED};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER_SUBTLE};
    border-radius: 4px;
    padding: 6px 10px;
    font-size: {Fonts.SIZE_SMALL}px;
}}

/* ===== SCROLL AREA ===== */
QScrollArea {{
    border: none;
    background: transparent;
}}

/* ===== GROUP BOX (for cards) ===== */
QGroupBox {{
    background-color: {Colors.BG_SECONDARY};
    border: 1px solid {Colors.BORDER_SUBTLE};
    border-radius: 8px;
    margin-top: 8px;
    padding: 16px;
    font-size: {Fonts.SIZE_BODY}px;
    color: {Colors.TEXT_PRIMARY};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 12px;
    color: {Colors.ACCENT_CYAN};
    font-weight: 600;
}}

/* ===== STATUS BAR ===== */
QStatusBar {{
    background-color: {Colors.BG_DARKEST};
    color: {Colors.TEXT_SECONDARY};
    border-top: 1px solid {Colors.BORDER_SUBTLE};
    font-size: {Fonts.SIZE_SMALL}px;
    padding: 4px;
}}
"""
