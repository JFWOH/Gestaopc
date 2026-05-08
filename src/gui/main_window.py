"""
MainWindow — Janela principal do Gerenciador de PC.

Layout inspirado no ASUS AI Suite 3: tema dark, painéis limpos,
destaque em ciano (#00A8FF).

Implementa a Seção 4 da spec 01-storage-manager.md.
Integração com backend via QThread (workers.py) — Seção 6.4.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QFont, QIcon, QColor, QPalette, QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QStatusBar,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.gui.styles import Colors, Fonts
from src.gui.workers import FullScanWorker, ScanResult
from src.gui.charts import (
    DonutChartWithLegend,
    DonutSegment,
    CategoryBarChart,
    BarEntry,
)
from src.core.executor import (
    SafeFileExecutor,
    FileAction,
    FileActionWorker,
    OperationRecord,
)
from src.core.storage_db import StorageManagerDB, get_default_db_path
from src.gui.icon import create_app_icon, create_tray_icon
from src.gui.assistant_tab import AssistantTab

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers de UI
# ---------------------------------------------------------------------------

def _make_label(text: str, css_class: str = "", font_size: int = 0) -> QLabel:
    """Cria um QLabel estilizado."""
    lbl = QLabel(text)
    if css_class:
        lbl.setProperty("cssClass", css_class)
    if font_size:
        f = lbl.font()
        f.setPointSize(font_size)
        lbl.setFont(f)
    return lbl


def _make_separator() -> QFrame:
    """Linha horizontal fina para separar seções."""
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(f"background-color: {Colors.BORDER_SUBTLE}; max-height: 1px;")
    return sep


# ---------------------------------------------------------------------------
# Widgets reutilizáveis
# ---------------------------------------------------------------------------

class DiskUsageBar(QWidget):
    """
    Barra visual de uso de disco individual.
    Mostra: [Letra]  [barra de progresso]  [XX% | livre: YY GB]
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

        # ---- Header row: letter + label + stats
        header = QHBoxLayout()
        header.setSpacing(10)

        lbl_letter = _make_label(letter, "accent")
        lbl_letter.setFixedWidth(30)
        f = lbl_letter.font()
        f.setPointSize(Fonts.SIZE_HEADING)
        f.setBold(True)
        lbl_letter.setFont(f)
        header.addWidget(lbl_letter)

        # Tipo de disco (NVMe / SSD / HDD)
        media_colors = {
            "NVMe": Colors.ACCENT_CYAN,
            "SSD": Colors.STATUS_GREEN,
            "HDD": Colors.STATUS_YELLOW,
        }
        m_color = media_colors.get(media_type, Colors.TEXT_DISABLED)
        lbl_media = QLabel(f"  {media_type}  ")
        lbl_media.setStyleSheet(f"""
            background-color: {m_color}22;
            color: {m_color};
            border: 1px solid {m_color}44;
            border-radius: 3px;
            font-size: 10px;
            font-weight: 700;
            padding: 2px 6px;
        """)
        lbl_media.setFixedHeight(20)
        header.addWidget(lbl_media)

        lbl_name = _make_label(label, "subtext")
        header.addWidget(lbl_name)

        header.addStretch()

        # Cor baseada no uso
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

        lbl_stats = _make_label(
            f"{percent:.1f}% usado  |  {free_gb:.1f} GB livre de {total_gb:.0f} GB",
            "subtext",
        )
        header.addWidget(lbl_stats)

        lbl_status = _make_label(status_txt)
        lbl_status.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 11px;")
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


class SuggestionCard(QWidget):
    """
    Card visual para uma sugestão do Motor de Regras.
    Mostra: [Ícone regra]  [Descrição]  [Botão Executar]
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

        # Cor do badge conforme prioridade
        if priority == "ALTA":
            badge_color = Colors.STATUS_RED
        elif priority in ("MEDIA", "MÉDIA"):
            badge_color = Colors.STATUS_YELLOW
        else:
            badge_color = Colors.STATUS_GREEN

        # Cor do ícone conforme ação
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

        # ---- Badge de regra
        badge = QLabel(f"R{rule_id}")
        badge.setFixedSize(36, 36)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(f"""
            background-color: {action_color}22;
            color: {action_color};
            border-radius: 18px;
            font-weight: 800;
            font-size: 13px;
        """)
        layout.addWidget(badge)

        # ---- Texto
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        title_row = QHBoxLayout()
        lbl_rule = _make_label(rule_name)
        lbl_rule.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: 600; font-size: 13px;")
        title_row.addWidget(lbl_rule)

        lbl_priority = QLabel(f"  {priority}  ")
        lbl_priority.setStyleSheet(f"""
            background-color: {badge_color}33;
            color: {badge_color};
            border-radius: 3px;
            font-size: 10px;
            font-weight: 700;
            padding: 2px 6px;
        """)
        lbl_priority.setFixedHeight(20)
        title_row.addWidget(lbl_priority)
        title_row.addStretch()
        text_layout.addLayout(title_row)

        lbl_detail = _make_label(detail, "subtext")
        lbl_detail.setWordWrap(True)
        text_layout.addWidget(lbl_detail)

        layout.addLayout(text_layout, stretch=1)

        # ---- Botão de ação
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


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Janela principal do Gerenciador de PC."""

    WINDOW_TITLE = "Gerenciador de PC  —  Storage Manager"
    MIN_WIDTH = 1100
    MIN_HEIGHT = 720

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(self.WINDOW_TITLE)
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.resize(1280, 800)

        # Estado do worker
        self._scan_worker: FullScanWorker | None = None
        self._action_worker: FileActionWorker | None = None
        self._last_result: ScanResult | None = None
        
        self._db = StorageManagerDB(get_default_db_path())
        self._db.initialize()
        self._executor = SafeFileExecutor(db=self._db)

        # Timer para animação de pulso no botão de varredura
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(600)
        self._pulse_timer.timeout.connect(self._pulse_scan_button)
        self._pulse_state = False

        # Container central
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ---- Header / Toolbar
        root_layout.addWidget(self._build_header())
        root_layout.addWidget(_make_separator())

        # ---- Tabs (conteúdo principal)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_tab_overview(), "  Visao Geral  ")
        self.tabs.addTab(self._build_tab_top_files(), "  Maiores Arquivos  ")
        self.tabs.addTab(self._build_tab_top_dirs(), "  Pastas  ")
        self.tabs.addTab(self._build_tab_duplicates(), "  Duplicatas  ")
        self.tabs.addTab(self._build_tab_suggestions(), "  Sugestoes da IA  ")
        self.tabs.addTab(self._build_tab_history(), "  Historico  ")
        self.tabs.addTab(AssistantTab(self), "  Assistente IA  ")
        root_layout.addWidget(self.tabs, stretch=1)

        # ---- Status bar com progress bar embutida
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.status_progress = QProgressBar()
        self.status_progress.setFixedWidth(200)
        self.status_progress.setFixedHeight(16)
        self.status_progress.setRange(0, 100)
        self.status_progress.setValue(0)
        self.status_progress.setVisible(False)
        self.status_bar.addPermanentWidget(self.status_progress)

        self.status_bar.showMessage("Pronto. Clique 'Iniciar Varredura Completa' para comecar.")

        # Ícone da aplicação
        self._app_icon = create_app_icon()
        self.setWindowIcon(self._app_icon)

        # System Tray
        self._tray = create_tray_icon(
            parent=self,
            on_open=self._show_from_tray,
            on_scan=self._on_start_scan,
            on_quit=self._quit_app,
        )
        self._tray.show()
        self._minimize_to_tray = True  # Minimizar ao fechar

    # ===================================================================
    # Lifecycle — Encerrar thread ao fechar janela
    # ===================================================================

    def closeEvent(self, event: QCloseEvent):
        """Minimiza para o tray ao fechar, ou encerra se solicitado."""
        if self._minimize_to_tray and self._tray.isVisible():
            self.hide()
            self._tray.showMessage(
                "Gerenciador de PC",
                "Minimizado para a bandeja. Clique duplo para reabrir.",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
            event.ignore()
            return

        # Encerramento real
        if self._scan_worker and self._scan_worker.isRunning():
            logger.info("Janela fechada — abortando worker de varredura...")
            self._scan_worker.abort()
            self._scan_worker.quit()
            self._scan_worker.wait(5000)
        if self._action_worker and self._action_worker.isRunning():
            self._action_worker.abort()
            self._action_worker.quit()
            self._action_worker.wait(5000)
        if hasattr(self, '_db'):
            self._db.close()
        self._tray.hide()
        event.accept()

    def _show_from_tray(self):
        """Restaura a janela a partir do tray."""
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _quit_app(self):
        """Encerra a aplicação de verdade."""
        self._minimize_to_tray = False
        self.close()

    # ===================================================================
    # Header
    # ===================================================================

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setStyleSheet(f"background-color: {Colors.BG_DARKEST};")
        header.setFixedHeight(72)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(16)

        # Logo / título
        title = QLabel("GERENCIADOR DE PC")
        title.setStyleSheet(f"""
            color: {Colors.TEXT_PRIMARY};
            font-size: {Fonts.SIZE_TITLE}px;
            font-weight: 300;
            letter-spacing: 3px;
        """)
        layout.addWidget(title)

        subtitle = QLabel("STORAGE MANAGER v0.2")
        subtitle.setStyleSheet(f"""
            color: {Colors.ACCENT_CYAN};
            font-size: {Fonts.SIZE_SMALL}px;
            font-weight: 600;
            letter-spacing: 1px;
        """)
        layout.addWidget(subtitle)

        layout.addStretch()

        # Botão principal — conectado ao worker
        self.btn_scan = QPushButton("  Iniciar Varredura Completa  ")
        self.btn_scan.setFixedHeight(40)
        self.btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan.clicked.connect(self._on_start_scan)
        layout.addWidget(self.btn_scan)

        return header

    # ===================================================================
    # Aba 1 — Visão Geral (Discos) — Dinâmica
    # ===================================================================

    def _build_tab_overview(self) -> QWidget:
        page = QWidget()
        self._overview_page = page
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # Título da seção
        header = QHBoxLayout()
        lbl = _make_label("Uso de Armazenamento", "heading")
        header.addWidget(lbl)
        header.addStretch()
        self._overview_disk_count = _make_label("Aguardando varredura...", "subtext")
        header.addWidget(self._overview_disk_count)
        layout.addLayout(header)

        layout.addWidget(_make_separator())

        # Scroll area para as barras de disco (conteúdo dinâmico)
        self._overview_scroll = QScrollArea()
        self._overview_scroll.setWidgetResizable(True)

        self._overview_container = QWidget()
        self._overview_layout = QVBoxLayout(self._overview_container)
        self._overview_layout.setContentsMargins(0, 0, 0, 0)
        self._overview_layout.setSpacing(4)

        # Placeholder inicial
        placeholder = _make_label(
            "Nenhum dado disponivel. Inicie uma varredura para ver o uso dos discos.",
            "subtext",
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet(f"color: {Colors.TEXT_DISABLED}; padding: 60px;")
        self._overview_layout.addWidget(placeholder)
        self._overview_layout.addStretch()

        self._overview_scroll.setWidget(self._overview_container)
        layout.addWidget(self._overview_scroll, stretch=1)

        # Gráfico donut de uso total
        self._overview_donut = DonutChartWithLegend()
        layout.addWidget(self._overview_donut)

        # Rodapé resumo (será preenchido dinamicamente)
        self._overview_footer = QHBoxLayout()
        self._overview_footer.setSpacing(32)

        self._stat_total = self._make_stat_widget("--", "Espaco Total", Colors.TEXT_PRIMARY)
        self._stat_used = self._make_stat_widget("--", "Em Uso", Colors.STATUS_ORANGE)
        self._stat_free = self._make_stat_widget("--", "Livre", Colors.STATUS_GREEN)
        self._stat_critical = self._make_stat_widget("--", "Discos Criticos (>90%)", Colors.STATUS_RED)

        self._overview_footer.addLayout(self._stat_total)
        self._overview_footer.addLayout(self._stat_used)
        self._overview_footer.addLayout(self._stat_free)
        self._overview_footer.addLayout(self._stat_critical)
        layout.addLayout(self._overview_footer)

        return page

    def _make_stat_widget(self, value: str, label: str, color: str) -> QVBoxLayout:
        """Cria um widget de estatística de rodapé (valor + label)."""
        stat = QVBoxLayout()
        stat.setSpacing(2)
        lbl_val = QLabel(value)
        lbl_val.setObjectName(f"stat_val_{label.replace(' ', '_')}")
        lbl_val.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: 700;")
        lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stat.addWidget(lbl_val)
        lbl_desc = _make_label(label, "subtext")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stat.addWidget(lbl_desc)
        return stat

    # ===================================================================
    # Aba 2 — Maiores Arquivos (Top 50)
    # ===================================================================

    def _build_tab_top_files(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        lbl = _make_label("Top 50 Maiores Arquivos", "heading")
        header.addWidget(lbl)
        header.addStretch()

        self._top_files_info = _make_label("Aguardando varredura...", "subtext")
        header.addWidget(self._top_files_info)
        layout.addLayout(header)

        layout.addWidget(_make_separator())

        # Toolbar: busca + filtro de categoria
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        self._top_files_search = QLineEdit()
        self._top_files_search.setPlaceholderText("🔍  Buscar arquivo ou caminho...")
        self._top_files_search.setFixedHeight(34)
        self._top_files_search.textChanged.connect(self._filter_top_files_table)
        toolbar.addWidget(self._top_files_search, stretch=1)

        self._top_files_cat_filter = QComboBox()
        self._top_files_cat_filter.addItems([
            "Todas as categorias", "Vídeos", "Imagens",
            "Documentos", "Executáveis", "Compactados", "Outros",
        ])
        self._top_files_cat_filter.setFixedHeight(34)
        self._top_files_cat_filter.currentTextChanged.connect(self._filter_top_files_table)
        toolbar.addWidget(self._top_files_cat_filter)

        layout.addLayout(toolbar)

        # Tabela
        self.table_top_files = QTableWidget()
        self.table_top_files.setAlternatingRowColors(True)
        self.table_top_files.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table_top_files.verticalHeader().setVisible(False)
        self.table_top_files.setShowGrid(False)
        self.table_top_files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        columns = ["#", "Arquivo", "Caminho", "Tamanho", "Categoria", "Disco"]
        self.table_top_files.setColumnCount(len(columns))
        self.table_top_files.setHorizontalHeaderLabels(columns)

        h = self.table_top_files.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(0, 40)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(3, 110)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(4, 110)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(5, 60)

        # Mapa de caminho por linha para o context menu
        self._top_files_path_map: dict[int, str] = {}
        self.table_top_files.customContextMenuRequested.connect(
            lambda pos: self._show_table_context_menu(
                self.table_top_files, self._top_files_path_map, pos
            )
        )

        layout.addWidget(self.table_top_files, stretch=1)

        # Gráfico de categorias
        self._category_chart = CategoryBarChart()
        self._category_chart.setFixedHeight(180)
        layout.addWidget(self._category_chart)

        # Rodapé resumo
        footer = QHBoxLayout()
        footer.setSpacing(16)
        self._top_files_total_label = _make_label("", "subtext")
        footer.addWidget(self._top_files_total_label)
        footer.addStretch()
        layout.addLayout(footer)

        return page


    # ===================================================================
    # Aba — Pastas (Top Diretórios)
    # ===================================================================

    def _build_tab_top_dirs(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        lbl = _make_label("Top 20 Pastas Mais Pesadas", "heading")
        header.addWidget(lbl)
        header.addStretch()

        self._top_dirs_info = _make_label("Aguardando varredura...", "subtext")
        header.addWidget(self._top_dirs_info)
        layout.addLayout(header)

        layout.addWidget(_make_separator())

        # Tabela
        self.table_top_dirs = QTableWidget()
        self.table_top_dirs.setAlternatingRowColors(True)
        self.table_top_dirs.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table_top_dirs.verticalHeader().setVisible(False)
        self.table_top_dirs.setShowGrid(False)

        columns = ["#", "Pasta", "Caminho Completo", "Tamanho", "Arquivos", "Disco"]
        self.table_top_dirs.setColumnCount(len(columns))
        self.table_top_dirs.setHorizontalHeaderLabels(columns)

        h = self.table_top_dirs.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(0, 40)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(3, 110)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(4, 90)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(5, 60)

        layout.addWidget(self.table_top_dirs, stretch=1)

        # Rodapé resumo
        footer = QHBoxLayout()
        footer.setSpacing(16)
        self._top_dirs_total_label = _make_label("", "subtext")
        footer.addWidget(self._top_dirs_total_label)
        footer.addStretch()
        layout.addLayout(footer)

        return page

    # ===================================================================
    # Aba 3 — Duplicatas
    # ===================================================================

    def _build_tab_duplicates(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        lbl = _make_label("Arquivos Duplicados", "heading")
        header.addWidget(lbl)
        header.addStretch()

        self._dup_info_label = _make_label("Aguardando varredura...", "subtext")
        header.addWidget(self._dup_info_label)
        layout.addLayout(header)

        layout.addWidget(_make_separator())

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._btn_select_all = QPushButton("Selecionar Todos")
        self._btn_select_all.setProperty("cssClass", "secondary")
        self._btn_select_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_select_all.clicked.connect(self._on_toggle_select_all_dups)
        toolbar.addWidget(self._btn_select_all)

        self._btn_delete_selected = QPushButton("Deletar Selecionados")
        self._btn_delete_selected.setProperty("cssClass", "danger")
        self._btn_delete_selected.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_delete_selected.setEnabled(False)
        self._btn_delete_selected.clicked.connect(self._on_delete_selected_dups)
        toolbar.addWidget(self._btn_delete_selected)

        toolbar.addStretch()

        # Barra de busca nas duplicatas
        self._dup_search = QLineEdit()
        self._dup_search.setPlaceholderText("🔍  Buscar arquivo ou hash...")
        self._dup_search.setFixedHeight(34)
        self._dup_search.setFixedWidth(280)
        self._dup_search.textChanged.connect(self._filter_duplicates_table)
        toolbar.addWidget(self._dup_search)

        btn_rescan = QPushButton("Re-escanear")
        btn_rescan.setProperty("cssClass", "secondary")
        btn_rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_rescan.clicked.connect(self._on_start_scan)
        toolbar.addWidget(btn_rescan)

        layout.addLayout(toolbar)

        # Tabela de duplicatas (começa vazia)
        self.table_duplicates = QTableWidget()
        self.table_duplicates.setAlternatingRowColors(True)
        self.table_duplicates.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table_duplicates.verticalHeader().setVisible(False)
        self.table_duplicates.setShowGrid(False)
        self.table_duplicates.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        columns = ["", "Arquivo", "Caminho", "Tamanho", "Hash (parcial)", "Grupo"]
        self.table_duplicates.setColumnCount(len(columns))
        self.table_duplicates.setHorizontalHeaderLabels(columns)

        h = self.table_duplicates.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(0, 40)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(3, 100)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(4, 130)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(5, 70)

        layout.addWidget(self.table_duplicates, stretch=1)

        # Armazenar caminhos das duplicatas por linha
        self._dup_file_paths: dict[int, str] = {}
        self._dup_checkboxes: list[QCheckBox] = []

        self.table_duplicates.customContextMenuRequested.connect(
            lambda pos: self._show_table_context_menu(
                self.table_duplicates, self._dup_file_paths, pos
            )
        )

        return page


    # ===================================================================
    # Aba 4 — Sugestões da IA — Dinâmica
    # ===================================================================

    def _build_tab_suggestions(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        lbl = _make_label("Sugestoes da IA  --  Motor de Regras", "heading")
        header.addWidget(lbl)
        header.addStretch()

        self._sug_count_label = _make_label("Aguardando varredura...", "subtext")
        header.addWidget(self._sug_count_label)
        layout.addLayout(header)

        layout.addWidget(_make_separator())

        # Resumo de regras ativas (atualizado dinamicamente)
        self._rules_summary_layout = QHBoxLayout()
        self._rules_summary_layout.setSpacing(16)
        self._rules_summary_layout.addStretch()
        layout.addLayout(self._rules_summary_layout)

        # Scroll area com cards de sugestão (conteúdo dinâmico)
        self._sug_scroll = QScrollArea()
        self._sug_scroll.setWidgetResizable(True)

        self._sug_container = QWidget()
        self._sug_layout = QVBoxLayout(self._sug_container)
        self._sug_layout.setContentsMargins(0, 8, 0, 8)
        self._sug_layout.setSpacing(10)

        # Placeholder
        placeholder = _make_label(
            "Nenhuma sugestao disponivel. Inicie uma varredura para ativar o motor de regras.",
            "subtext",
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet(f"color: {Colors.TEXT_DISABLED}; padding: 60px;")
        self._sug_layout.addWidget(placeholder)
        self._sug_layout.addStretch()

        self._sug_scroll.setWidget(self._sug_container)
        layout.addWidget(self._sug_scroll, stretch=1)

        # Footer com ações em massa
        footer = QHBoxLayout()
        footer.setSpacing(12)
        footer.addStretch()

        self._btn_exec_all = QPushButton("  Executar Todas as Sugestoes  ")
        self._btn_exec_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_exec_all.setFixedHeight(40)
        self._btn_exec_all.setEnabled(False)
        self._btn_exec_all.clicked.connect(self._on_exec_all_suggestions)
        footer.addWidget(self._btn_exec_all)

        btn_dismiss = QPushButton("Dispensar Todas")
        btn_dismiss.setProperty("cssClass", "secondary")
        btn_dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_dismiss.setFixedHeight(40)
        btn_dismiss.clicked.connect(self._on_dismiss_all_suggestions)
        footer.addWidget(btn_dismiss)

        layout.addLayout(footer)

        return page

    # ===================================================================
    # Aba — Histórico de Operações
    # ===================================================================

    def _build_tab_history(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        lbl = _make_label("Historico de Operacoes", "heading")
        header.addWidget(lbl)
        header.addStretch()

        self._history_info = _make_label("Nenhuma operacao realizada", "subtext")
        header.addWidget(self._history_info)
        layout.addLayout(header)

        layout.addWidget(_make_separator())

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._btn_undo = QPushButton("Desfazer Ultima Movimentacao")
        self._btn_undo.setProperty("cssClass", "secondary")
        self._btn_undo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_undo.setEnabled(False)
        self._btn_undo.clicked.connect(self._on_undo_last_move)
        toolbar.addWidget(self._btn_undo)

        toolbar.addStretch()

        btn_clear = QPushButton("Limpar Historico")
        btn_clear.setProperty("cssClass", "secondary")
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.clicked.connect(self._on_clear_history)
        toolbar.addWidget(btn_clear)

        layout.addLayout(toolbar)

        # Tabela
        self.table_history = QTableWidget()
        self.table_history.setAlternatingRowColors(True)
        self.table_history.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table_history.verticalHeader().setVisible(False)
        self.table_history.setShowGrid(False)

        columns = ["Hora", "Acao", "Arquivo", "Destino", "Status", "Detalhe"]
        self.table_history.setColumnCount(len(columns))
        self.table_history.setHorizontalHeaderLabels(columns)

        h = self.table_history.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(0, 140)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(1, 80)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(4, 70)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.table_history, stretch=1)

        return page

    def _refresh_history_tab(self):
        """Atualiza a tabela de histórico com os dados do executor."""
        db_rows = self._db.list_operations() if hasattr(self, '_db') else []
        
        records = []
        if db_rows:
            for row in db_rows:
                records.append(OperationRecord(
                    timestamp=row["timestamp"],
                    action=row["action"],
                    source_path=row["source_path"],
                    target_path=row["target_path"] or "",
                    success=bool(row["success"]),
                    error=row["error"] or "",
                    used_trash=bool(row["used_trash"])
                ))
        else:
            records = list(reversed(self._executor.history))

        self.table_history.setRowCount(0)

        if not records:
            self._history_info.setText("Nenhuma operacao realizada")
            self._btn_undo.setEnabled(False)
            return

        ok = sum(1 for r in records if r.success)
        fail = sum(1 for r in records if not r.success)
        self._history_info.setText(
            f"{len(records)} operacoes  |  {ok} OK  |  {fail} falhas"
        )

        has_moves = any(r.action == "MOVER" and r.success for r in records)
        self._btn_undo.setEnabled(has_moves)

        for idx, record in enumerate(records):  # Mais recente primeiro
            self.table_history.insertRow(idx)

            status = "OK" if record.success else "FALHA"
            status_color = Colors.STATUS_GREEN if record.success else Colors.STATUS_RED

            dst = Path(record.target_path).name if record.target_path else ""
            if record.used_trash:
                dst = "Lixeira"

            values = [
                record.timestamp_str,
                record.action,
                Path(record.source_path).name,
                dst,
                status,
                record.error or "—",
            ]

            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                if col_idx == 1:
                    color = Colors.ACCENT_CYAN if value == "MOVER" else Colors.STATUS_RED
                    item.setForeground(QColor(color))
                elif col_idx == 4:
                    item.setForeground(QColor(status_color))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                self.table_history.setItem(idx, col_idx, item)

            self.table_history.setRowHeight(idx, 36)

    def _on_undo_last_move(self):
        """Desfaz a última operação de MOVER."""
        reply = QMessageBox.question(
            self,
            "Desfazer Movimentacao",
            "Deseja desfazer a ultima movimentacao de arquivo?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        result = self._executor.undo_last_move()
        if result and result.success:
            self.status_bar.showMessage("Movimentacao desfeita com sucesso.")
        elif result:
            self.status_bar.showMessage(f"Falha ao desfazer: {result.error}")
        else:
            self.status_bar.showMessage("Nenhuma movimentacao para desfazer.")

        self._refresh_history_tab()

    def _on_clear_history(self):
        """Limpa o histórico de operações."""
        self._executor.history.clear()
        if hasattr(self, '_db'):
            self._db.clear_operations()
        self._refresh_history_tab()
        self.status_bar.showMessage("Historico limpo.")

    # ===================================================================
    # Lógica de Varredura (QThread)
    # ===================================================================

    def _on_start_scan(self):
        """Inicia a varredura completa em background."""
        if self._scan_worker and self._scan_worker.isRunning():
            self.status_bar.showMessage("Varredura ja em andamento...")
            return

        # UI → estado de loading
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("  Varrendo...  ")
        self.status_progress.setVisible(True)
        self.status_progress.setValue(0)
        self.status_bar.showMessage("Iniciando varredura completa...")

        # Iniciar animação de pulso
        self._pulse_state = False
        self._pulse_timer.start()

        # Criar e iniciar worker
        self._scan_worker = FullScanWorker(self)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.progress_percent.connect(self._on_scan_percent)
        self._scan_worker.finished_result.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_scan_progress(self, message: str):
        """Atualiza a mensagem de status."""
        self.status_bar.showMessage(message)

    def _on_scan_percent(self, percent: int):
        """Atualiza a barra de progresso."""
        self.status_progress.setValue(percent)

    def _on_scan_finished(self, result: ScanResult):
        """Chamado quando a varredura termina — atualiza todas as abas."""
        self._last_result = result

        # Parar animação e restaurar botão
        self._pulse_timer.stop()
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("  Iniciar Varredura Completa  ")
        self.btn_scan.setStyleSheet("")  # Resetar estilo de pulso
        self.status_progress.setVisible(False)

        if result.error:
            self.status_bar.showMessage(f"Erro na varredura: {result.error}")
            return

        # Atualizar as 5 abas com dados reais
        self._populate_overview(result)
        self._populate_top_files(result)
        self._populate_top_dirs(result)
        self._populate_duplicates(result)
        self._populate_suggestions(result)

        elapsed = f"{result.elapsed_seconds:.1f}s"
        self.status_bar.showMessage(
            f"Varredura concluida em {elapsed}  |  "
            f"{len(result.partitions)} discos  |  "
            f"{len(result.top_files)} maiores arquivos  |  "
            f"{len(result.top_dirs)} pastas  |  "
            f"{len(result.duplicates)} grupos de duplicatas  |  "
            f"{len(result.suggestions)} sugestoes"
        )

        # Limpar referência do worker
        self._scan_worker = None

    # ===================================================================
    # Populadores — Preencher UI com dados reais
    # ===================================================================

    def _populate_overview(self, result: ScanResult):
        """Reconstrói a aba Visão Geral com dados reais das partições."""
        # Recriar container de barras
        new_container = QWidget()
        new_layout = QVBoxLayout(new_container)
        new_layout.setContentsMargins(0, 0, 0, 0)
        new_layout.setSpacing(4)

        for part in result.partitions:
            bar = DiskUsageBar(
                letter=part.letter,
                label=part.fstype,
                percent=part.percent_used,
                total_gb=part.total_gb,
                free_gb=part.free_gb,
                media_type=part.media_type,
            )
            new_layout.addWidget(bar)
            new_layout.addWidget(_make_separator())

        new_layout.addStretch()
        self._overview_scroll.setWidget(new_container)

        # Atualizar contador de discos
        self._overview_disk_count.setText(f"Total monitorado: {len(result.partitions)} discos")

        # Atualizar rodapé
        total_gb = sum(p.total_gb for p in result.partitions)
        free_gb = sum(p.free_gb for p in result.partitions)
        used_gb = total_gb - free_gb
        critical = sum(1 for p in result.partitions if p.percent_used > 90)

        self._update_stat(self._stat_total, f"{total_gb / 1024:.2f} TB")
        self._update_stat(self._stat_used, f"{used_gb / 1024:.2f} TB")
        self._update_stat(self._stat_free, f"{free_gb / 1024:.2f} TB")
        self._update_stat(self._stat_critical, str(critical))

        # Atualizar donut chart
        media_colors = {
            "NVMe": Colors.ACCENT_CYAN,
            "SSD": Colors.STATUS_GREEN,
            "HDD": Colors.STATUS_YELLOW,
            "Desconhecido": Colors.TEXT_DISABLED,
        }
        donut_segments = [
            DonutSegment(
                label=f"{p.letter} ({p.media_type})",
                value=round((p.total_bytes - p.free_bytes) / (1024 ** 3), 1),
                color=media_colors.get(p.media_type, Colors.TEXT_DISABLED),
            )
            for p in result.partitions
        ]
        self._overview_donut.set_data(
            donut_segments,
            center_label=f"Total\n{total_gb / 1024:.1f} TB",
        )

    def _populate_top_files(self, result: ScanResult):
        """Preenche a aba Top 50 Maiores Arquivos com dados reais."""
        self.table_top_files.setRowCount(0)

        if not result.top_files:
            self._top_files_info.setText("Nenhum arquivo encontrado")
            self._top_files_total_label.setText("")
            return

        total_size = sum(f.size_bytes for f in result.top_files)
        self._top_files_info.setText(
            f"{len(result.top_files)} arquivos  |  "
            f"{total_size / (1024 ** 3):.1f} GB no total"
        )

        max_size = result.top_files[0].size_bytes if result.top_files else 1

        # Cores por categoria
        cat_colors = {
            "Vídeos": Colors.ACCENT_CYAN,
            "Imagens": Colors.STATUS_GREEN,
            "Documentos": Colors.STATUS_YELLOW,
            "Executáveis": Colors.STATUS_ORANGE,
            "Compactados": Colors.STATUS_RED,
            "Outros": Colors.TEXT_SECONDARY,
        }

        for idx, file_entry in enumerate(result.top_files):
            self.table_top_files.insertRow(idx)

            p = Path(file_entry.path)

            # Tamanho formatado
            size_mb = file_entry.size_bytes / (1024 ** 2)
            if size_mb >= 1024:
                size_str = f"{size_mb / 1024:.1f} GB"
            else:
                size_str = f"{size_mb:.1f} MB"

            # Drive letter
            drive = p.drive.upper()

            values = [
                str(idx + 1),
                p.name,
                str(p.parent),
                size_str,
                file_entry.category,
                drive,
            ]

            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                # Alinhar número central
                if col_idx == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                # Alinhar tamanho à direita
                elif col_idx == 3:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                # Alinhar disco central
                elif col_idx == 5:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                # Colorir categoria
                elif col_idx == 4:
                    cat_color = cat_colors.get(value, Colors.TEXT_SECONDARY)
                    item.setForeground(QColor(cat_color))

                self.table_top_files.setItem(idx, col_idx, item)

            self.table_top_files.setRowHeight(idx, 38)
            # Guardar path para context menu
            self._top_files_path_map[idx] = file_entry.path

        # Resumo no rodapé
        categories = {}
        cat_sizes: dict[str, float] = {}
        for f in result.top_files:
            categories[f.category] = categories.get(f.category, 0) + 1
            cat_sizes[f.category] = cat_sizes.get(f.category, 0.0) + f.size_bytes / (1024 ** 3)
        cat_summary = "  |  ".join(f"{cat}: {n}" for cat, n in sorted(categories.items()))
        self._top_files_total_label.setText(f"Por categoria:  {cat_summary}")

        # Atualizar gráfico de categorias
        cat_colors_map = {
            "Vídeos": Colors.ACCENT_CYAN,
            "Imagens": Colors.STATUS_GREEN,
            "Documentos": Colors.STATUS_YELLOW,
            "Executáveis": Colors.STATUS_ORANGE,
            "Compactados": Colors.STATUS_RED,
            "Outros": Colors.TEXT_SECONDARY,
        }
        bar_entries = [
            BarEntry(
                label=cat,
                value=round(size_gb, 2),
                color=cat_colors_map.get(cat, Colors.TEXT_SECONDARY),
                suffix=" GB",
            )
            for cat, size_gb in cat_sizes.items()
            if size_gb > 0
        ]
        self._category_chart.set_data(bar_entries)

    def _populate_top_dirs(self, result: ScanResult):
        """Preenche a aba Pastas com os diretórios mais pesados."""
        self.table_top_dirs.setRowCount(0)

        if not result.top_dirs:
            self._top_dirs_info.setText("Nenhuma pasta encontrada")
            self._top_dirs_total_label.setText("")
            return

        total_size = sum(d.total_size_bytes for d in result.top_dirs)
        self._top_dirs_info.setText(
            f"{len(result.top_dirs)} pastas  |  "
            f"{total_size / (1024 ** 3):.1f} GB no total"
        )

        for idx, dir_entry in enumerate(result.top_dirs):
            self.table_top_dirs.insertRow(idx)

            p = Path(dir_entry.path)

            # Tamanho formatado
            size_gb = dir_entry.total_size_bytes / (1024 ** 3)
            if size_gb >= 1:
                size_str = f"{size_gb:.1f} GB"
            else:
                size_str = f"{dir_entry.total_size_bytes / (1024 ** 2):.1f} MB"

            drive = p.drive.upper()

            values = [
                str(idx + 1),
                p.name,
                str(p),
                size_str,
                f"{dir_entry.file_count:,}",
                drive,
            ]

            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                if col_idx == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif col_idx == 3:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                elif col_idx == 4:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif col_idx == 5:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                self.table_top_dirs.setItem(idx, col_idx, item)

            self.table_top_dirs.setRowHeight(idx, 38)

        # Resumo no rodapé
        total_files = sum(d.file_count for d in result.top_dirs)
        self._top_dirs_total_label.setText(
            f"Total: {total_files:,} arquivos em {len(result.top_dirs)} pastas"
        )

    def _populate_duplicates(self, result: ScanResult):
        """Preenche a tabela de duplicatas com dados reais."""
        self.table_duplicates.setRowCount(0)
        self._dup_file_paths.clear()
        self._dup_checkboxes.clear()

        if not result.duplicates:
            self._dup_info_label.setText("Nenhuma duplicata encontrada")
            self._btn_delete_selected.setEnabled(False)
            return

        total_groups = len(result.duplicates)
        total_wasted = sum(g.wasted_mb for g in result.duplicates)
        total_files = sum(g.count for g in result.duplicates)
        self._dup_info_label.setText(
            f"{total_groups} grupos  |  {total_files} arquivos  |  "
            f"{total_wasted:.1f} MB desperdicados"
        )
        self._btn_delete_selected.setEnabled(True)

        # Paleta de cores para grupos alternados (6 tons)
        _GROUP_COLORS = [
            "#1A2633", "#1A2820", "#25201A", "#201A26", "#1A2025", "#261A1A",
        ]

        row_idx = 0
        for group_idx, group in enumerate(result.duplicates, start=1):
            row_bg = QColor(_GROUP_COLORS[(group_idx - 1) % len(_GROUP_COLORS)])
            for filepath in group.files:
                self.table_duplicates.insertRow(row_idx)

                # Checkbox
                cb = QCheckBox()
                cb_widget = QWidget()
                cb_layout = QHBoxLayout(cb_widget)
                cb_layout.addWidget(cb)
                cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cb_layout.setContentsMargins(0, 0, 0, 0)
                self.table_duplicates.setCellWidget(row_idx, 0, cb_widget)
                self._dup_checkboxes.append(cb)

                # Armazenar caminho por linha
                self._dup_file_paths[row_idx] = filepath

                # Dados
                p = Path(filepath)
                name = p.name
                folder = str(p.parent)
                size_mb = group.size_bytes / (1024 ** 2)
                if size_mb >= 1024:
                    size_str = f"{size_mb / 1024:.1f} GB"
                else:
                    size_str = f"{size_mb:.1f} MB"
                hash_short = f"{group.hash_sha256[:6]}...{group.hash_sha256[-4:]}"

                for col_idx, value in enumerate(
                    [name, folder, size_str, hash_short, str(group_idx)], start=1
                ):
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setBackground(row_bg)
                    if col_idx == 3:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                    if col_idx == 5:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        item.setForeground(QColor(Colors.ACCENT_CYAN))
                    self.table_duplicates.setItem(row_idx, col_idx, item)

                self.table_duplicates.setRowHeight(row_idx, 42)
                row_idx += 1

    def _populate_suggestions(self, result: ScanResult):
        """Reconstrói a aba Sugestões com os resultados do motor de regras."""
        # Atualizar contador
        count = len(result.suggestions)
        self._sug_count_label.setText(
            f"{count} sugestoes ativas" if count else "Nenhuma sugestao"
        )

        # Limpar e recriar pills de resumo de regras
        self._clear_layout(self._rules_summary_layout)

        if result.suggestions:
            # Contar por regra
            rule_counts: dict[int, int] = {}
            for s in result.suggestions:
                rule_counts[s.rule_id] = rule_counts.get(s.rule_id, 0) + 1

            rule_meta = {
                1: ("Midia pesada no NVMe", Colors.ACCENT_CYAN),
                2: ("Duplicatas", Colors.STATUS_YELLOW),
                3: ("Disco critico (>90%)", Colors.STATUS_RED),
            }

            for rule_id, cnt in sorted(rule_counts.items()):
                desc, color = rule_meta.get(rule_id, (f"Regra {rule_id}", Colors.TEXT_SECONDARY))
                pill = QLabel(f"  R{rule_id}: {desc} ({cnt})  ")
                pill.setStyleSheet(f"""
                    background-color: {color}22;
                    color: {color};
                    border: 1px solid {color}44;
                    border-radius: 12px;
                    padding: 6px 14px;
                    font-size: 11px;
                    font-weight: 600;
                """)
                self._rules_summary_layout.insertWidget(
                    self._rules_summary_layout.count() - 1, pill  # antes do stretch
                )

        # Guardar sugestões para ações em batch
        self._current_suggestions = result.suggestions if result.suggestions else []

        # Recriar container de cards
        new_container = QWidget()
        new_layout = QVBoxLayout(new_container)
        new_layout.setContentsMargins(0, 8, 0, 8)
        new_layout.setSpacing(10)

        if result.suggestions:
            self._btn_exec_all.setEnabled(True)
            for idx, sug in enumerate(result.suggestions):
                card = SuggestionCard(
                    rule_id=sug.rule_id,
                    rule_name=sug.rule_name,
                    action=sug.action,
                    detail=sug.detail,
                    priority=sug.priority,
                    file_path=sug.file_path,
                    target_disk=sug.target_disk,
                    on_execute=lambda checked, s=sug: self._on_exec_single_suggestion(s),
                )
                new_layout.addWidget(card)
        else:
            self._btn_exec_all.setEnabled(False)
            lbl = _make_label("Nenhuma sugestao gerada. Todos os discos parecem bem organizados.",
                              "subtext")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"color: {Colors.STATUS_GREEN}; padding: 60px;")
            new_layout.addWidget(lbl)

        new_layout.addStretch()
        self._sug_scroll.setWidget(new_container)

    # ===================================================================
    # Ações de Duplicatas
    # ===================================================================

    def _on_toggle_select_all_dups(self):
        """Alterna seleção de todos os checkboxes na aba Duplicatas."""
        if not self._dup_checkboxes:
            return

        # Se todos estão selecionados → desmarcar todos, senão → marcar todos.
        all_checked = all(cb.isChecked() for cb in self._dup_checkboxes)
        for cb in self._dup_checkboxes:
            cb.setChecked(not all_checked)

        self._btn_select_all.setText(
            "Desmarcar Todos" if not all_checked else "Selecionar Todos"
        )

    def _on_delete_selected_dups(self):
        """Deleta os arquivos duplicados selecionados (via Lixeira)."""
        selected_paths = []
        for row_idx, cb in enumerate(self._dup_checkboxes):
            if cb.isChecked() and row_idx in self._dup_file_paths:
                selected_paths.append(self._dup_file_paths[row_idx])

        if not selected_paths:
            self.status_bar.showMessage("Nenhum arquivo selecionado para deletar.")
            return

        # Diálogo de confirmação
        reply = QMessageBox.warning(
            self,
            "Confirmar Deleção",
            f"Deseja enviar {len(selected_paths)} arquivo(s) para a Lixeira?\n\n"
            "Esta ação pode ser desfeita restaurando da Lixeira do Windows.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Criar ações e executar via worker
        actions = [FileAction(action="DELETAR", source_path=p) for p in selected_paths]
        self._run_actions(actions, "Deletando duplicatas...")

    # ===================================================================
    # Ações de Sugestões
    # ===================================================================

    def _on_exec_single_suggestion(self, suggestion):
        """Executa uma sugestão individual do Motor de Regras."""
        if suggestion.action == "MOVER":
            # Construir caminho de destino mantendo o nome do arquivo.
            file_name = Path(suggestion.file_path).name
            target = str(Path(suggestion.target_disk + "\\") / file_name)

            reply = QMessageBox.question(
                self,
                "Confirmar Movimentacao",
                f"Mover arquivo?\n\n"
                f"De: {suggestion.file_path}\n"
                f"Para: {target}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

            actions = [FileAction(action="MOVER", source_path=suggestion.file_path, target_path=target)]

        elif suggestion.action == "DELETAR":
            reply = QMessageBox.warning(
                self,
                "Confirmar Deleção",
                f"Enviar para a Lixeira?\n\n{suggestion.file_path}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

            actions = [FileAction(action="DELETAR", source_path=suggestion.file_path)]

        else:
            return

        self._run_actions(actions, f"Executando R{suggestion.rule_id}...")

    def _on_exec_all_suggestions(self):
        """Executa todas as sugestões ativas."""
        if not hasattr(self, '_current_suggestions') or not self._current_suggestions:
            return

        # Contar ações
        n_move = sum(1 for s in self._current_suggestions if s.action == "MOVER")
        n_del = sum(1 for s in self._current_suggestions if s.action == "DELETAR")

        reply = QMessageBox.warning(
            self,
            "Executar Todas as Sugestoes",
            f"Executar todas as {len(self._current_suggestions)} sugestoes?\n\n"
            f"• {n_move} arquivo(s) serao movidos\n"
            f"• {n_del} arquivo(s) serao enviados a Lixeira\n\n"
            "Deseja continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        actions = []
        for sug in self._current_suggestions:
            if sug.action == "MOVER":
                file_name = Path(sug.file_path).name
                target = str(Path(sug.target_disk + "\\") / file_name)
                actions.append(FileAction(action="MOVER", source_path=sug.file_path, target_path=target))
            elif sug.action == "DELETAR":
                actions.append(FileAction(action="DELETAR", source_path=sug.file_path))

        self._run_actions(actions, "Executando todas as sugestoes...")

    def _on_dismiss_all_suggestions(self):
        """Dispensa todas as sugestões visuais."""
        self._current_suggestions = []
        self._sug_count_label.setText("Nenhuma sugestao")
        self._btn_exec_all.setEnabled(False)

        # Limpar pills
        self._clear_layout(self._rules_summary_layout)

        # Limpar cards
        new_container = QWidget()
        new_layout = QVBoxLayout(new_container)
        new_layout.setContentsMargins(0, 8, 0, 8)
        lbl = _make_label("Todas as sugestoes foram dispensadas.", "subtext")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(f"color: {Colors.TEXT_DISABLED}; padding: 60px;")
        new_layout.addWidget(lbl)
        new_layout.addStretch()
        self._sug_scroll.setWidget(new_container)

        self.status_bar.showMessage("Sugestoes dispensadas.")

    # ===================================================================
    # Execução em background (FileActionWorker)
    # ===================================================================

    def _run_actions(self, actions: list[FileAction], status_msg: str):
        """Inicia execução de ações de arquivo em background."""
        if self._action_worker and self._action_worker.isRunning():
            self.status_bar.showMessage("Outra operacao ja em andamento...")
            return

        self.status_progress.setVisible(True)
        self.status_progress.setValue(0)
        self.status_bar.showMessage(status_msg)

        self._action_worker = FileActionWorker(actions, self)
        self._action_worker.progress.connect(self._on_scan_progress)
        self._action_worker.progress_percent.connect(self._on_scan_percent)
        self._action_worker.finished_all.connect(self._on_actions_finished)
        self._action_worker.start()

    def _on_actions_finished(self, results: list[OperationRecord]):
        """Chamado quando todas as ações terminam."""
        self.status_progress.setVisible(False)
        self._action_worker = None

        success = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)

        msg = f"Operacoes concluidas: {success} OK"
        if failed:
            msg += f", {failed} falhas"
            # Exibir detalhes das falhas
            fail_details = "\n".join(
                f"• {r.source_path}: {r.error}"
                for r in results if not r.success
            )
            QMessageBox.warning(
                self,
                "Algumas operacoes falharam",
                f"{failed} operacao(oes) falharam:\n\n{fail_details}",
            )

        self.status_bar.showMessage(msg)

        # Atualizar aba Histórico
        self._refresh_history_tab()

        # Após ações executadas, re-escanear automaticamente.
        if success > 0:
            QTimer.singleShot(1000, self._on_start_scan)

    # ===================================================================
    # Filtros de Tabela (em tempo real)
    # ===================================================================

    def _filter_top_files_table(self):
        """Filtra a tabela de Maiores Arquivos por texto e/ou categoria."""
        text = self._top_files_search.text().lower()
        cat_filter = self._top_files_cat_filter.currentText()
        use_cat = cat_filter != "Todas as categorias"

        for row in range(self.table_top_files.rowCount()):
            name_item = self.table_top_files.item(row, 1)
            path_item = self.table_top_files.item(row, 2)
            cat_item = self.table_top_files.item(row, 4)

            name = name_item.text().lower() if name_item else ""
            path = path_item.text().lower() if path_item else ""
            cat = cat_item.text() if cat_item else ""

            match_text = (not text) or (text in name) or (text in path)
            match_cat = (not use_cat) or (cat == cat_filter)

            self.table_top_files.setRowHidden(row, not (match_text and match_cat))

    def _filter_duplicates_table(self):
        """Filtra a tabela de Duplicatas pelo texto da barra de busca."""
        text = self._dup_search.text().lower()
        for row in range(self.table_duplicates.rowCount()):
            name_item = self.table_duplicates.item(row, 1)
            path_item = self.table_duplicates.item(row, 2)
            hash_item = self.table_duplicates.item(row, 4)

            name = name_item.text().lower() if name_item else ""
            path = path_item.text().lower() if path_item else ""
            hash_val = hash_item.text().lower() if hash_item else ""

            match = (not text) or (text in name) or (text in path) or (text in hash_val)
            self.table_duplicates.setRowHidden(row, not match)

    # ===================================================================
    # Utilitários
    # ===================================================================

    def _pulse_scan_button(self):
        """Alterna a cor do botão de varredura para criar efeito de pulso."""
        from src.gui.styles import Colors
        self._pulse_state = not self._pulse_state
        if self._pulse_state:
            self.btn_scan.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Colors.ACCENT_CYAN_HOVER};
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 10px 24px;
                    font-size: 13px;
                    font-weight: 700;
                }}
            """)
        else:
            self.btn_scan.setStyleSheet("")

    @staticmethod
    def _open_in_explorer(filepath: str):
        """Abre o Explorador de Arquivos com o arquivo selecionado."""
        try:
            path = Path(filepath)
            if path.is_file():
                subprocess.run(["explorer", "/select,", str(path)], check=False)
            elif path.is_dir():
                subprocess.run(["explorer", str(path)], check=False)
        except Exception as exc:
            logger.warning("Falha ao abrir Explorer: %s", exc)

    def _show_table_context_menu(self, table: QTableWidget, filepath_map: dict[int, str], pos):
        """Exibe menu de contexto para uma linha de tabela."""
        row = table.rowAt(pos.y())
        if row < 0:
            return
        filepath = filepath_map.get(row, "")
        if not filepath:
            return

        menu = QMenu(self)
        act_open = menu.addAction("📂  Abrir pasta no Explorer")
        act_copy = menu.addAction("📋  Copiar caminho")
        menu.addSeparator()
        act_info = menu.addAction(Path(filepath).name)
        act_info.setEnabled(False)

        action = menu.exec(table.viewport().mapToGlobal(pos))
        if action == act_open:
            self._open_in_explorer(filepath)
        elif action == act_copy:
            QApplication.clipboard().setText(filepath)
            self.status_bar.showMessage(f"Caminho copiado: {filepath}")

    @staticmethod
    def _update_stat(stat_layout: QVBoxLayout, value: str):
        """Atualiza o valor de um widget de estatística do rodapé."""
        value_widget = stat_layout.itemAt(0).widget()
        if isinstance(value_widget, QLabel):
            value_widget.setText(value)

    @staticmethod
    def _clear_layout(layout: QHBoxLayout | QVBoxLayout):
        """Remove todos os widgets de um layout (exceto stretches)."""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
