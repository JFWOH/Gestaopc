"""
Aba 2 — Top 50 Maiores Arquivos.

Exibe tabela, filtros de busca/categoria, gráfico de barras por categoria.
Context menu: Abrir no Explorer / Copiar caminho.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.gui.styles import Colors
from src.gui.workers import ScanResult
from src.gui.charts import CategoryBarChart, BarEntry
from src.gui.tabs.shared import make_label, make_separator

# Paleta de cores por categoria de arquivo
_CAT_COLORS: dict[str, str] = {
    "Vídeos": Colors.ACCENT_CYAN,
    "Imagens": Colors.STATUS_GREEN,
    "Documentos": Colors.STATUS_YELLOW,
    "Executáveis": Colors.STATUS_ORANGE,
    "Compactados": Colors.STATUS_RED,
    "Outros": Colors.TEXT_SECONDARY,
}


class TopFilesTab(QWidget):
    """Aba — Top 50 maiores arquivos do sistema."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # ── Header ──────────────────────────────────────────────────────────
        header = QHBoxLayout()
        header.addWidget(make_label("Top 50 Maiores Arquivos", "heading"))
        header.addStretch()
        self._info_lbl = make_label("Aguardando varredura...", "subtext")
        header.addWidget(self._info_lbl)
        layout.addLayout(header)

        layout.addWidget(make_separator())

        # ── Toolbar: busca + filtro de categoria ────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Buscar arquivo ou caminho...")
        self._search.setFixedHeight(34)
        self._search.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self._search, stretch=1)

        self._cat_filter = QComboBox()
        self._cat_filter.addItems([
            "Todas as categorias", "Vídeos", "Imagens",
            "Documentos", "Executáveis", "Compactados", "Outros",
        ])
        self._cat_filter.setFixedHeight(34)
        self._cat_filter.currentTextChanged.connect(self._apply_filter)
        toolbar.addWidget(self._cat_filter)

        layout.addLayout(toolbar)

        # ── Tabela ───────────────────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        columns = ["#", "Arquivo", "Caminho", "Tamanho", "Categoria", "Disco"]
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

        h = self.table.horizontalHeader()
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

        self._path_map: dict[int, str] = {}
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table, stretch=1)

        # ── Gráfico de categorias ─────────────────────────────────────────────
        self._chart = CategoryBarChart()
        self._chart.setFixedHeight(180)
        layout.addWidget(self._chart)

        # ── Rodapé ───────────────────────────────────────────────────────────
        footer = QHBoxLayout()
        self._total_lbl = make_label("", "subtext")
        footer.addWidget(self._total_lbl)
        footer.addStretch()
        layout.addLayout(footer)

    # ──────────────────────────────────────────────────────────────────────────
    # API pública
    # ──────────────────────────────────────────────────────────────────────────

    def populate(self, result: ScanResult) -> None:
        """Preenche a tabela com os maiores arquivos da varredura."""
        self.table.setRowCount(0)
        self._path_map.clear()

        if not result.top_files:
            self._info_lbl.setText("Nenhum arquivo encontrado")
            self._total_lbl.setText("")
            return

        total_size = sum(f.size_bytes for f in result.top_files)
        self._info_lbl.setText(
            f"{len(result.top_files)} arquivos  |  "
            f"{total_size / (1024 ** 3):.1f} GB no total"
        )

        for idx, fe in enumerate(result.top_files):
            self.table.insertRow(idx)
            p = Path(fe.path)
            size_mb = fe.size_bytes / (1024 ** 2)
            size_str = (
                f"{size_mb / 1024:.1f} GB" if size_mb >= 1024 else f"{size_mb:.1f} MB"
            )

            values = [
                str(idx + 1),
                p.name,
                str(p.parent),
                size_str,
                fe.category,
                p.drive.upper(),
            ]

            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif col == 3:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                elif col == 5:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif col == 4:
                    item.setForeground(
                        QColor(_CAT_COLORS.get(val, Colors.TEXT_SECONDARY))
                    )
                self.table.setItem(idx, col, item)

            self.table.setRowHeight(idx, 38)
            self._path_map[idx] = fe.path

        # Rodapé resumo por categoria
        categories: dict[str, int] = {}
        cat_sizes: dict[str, float] = {}
        for f in result.top_files:
            categories[f.category] = categories.get(f.category, 0) + 1
            cat_sizes[f.category] = (
                cat_sizes.get(f.category, 0.0) + f.size_bytes / (1024 ** 3)
            )

        cat_summary = "  |  ".join(
            f"{cat}: {n}" for cat, n in sorted(categories.items())
        )
        self._total_lbl.setText(f"Por categoria:  {cat_summary}")

        bar_entries = [
            BarEntry(
                label=cat,
                value=round(size, 2),
                color=_CAT_COLORS.get(cat, Colors.TEXT_SECONDARY),
                suffix=" GB",
            )
            for cat, size in cat_sizes.items()
            if size > 0
        ]
        self._chart.set_data(bar_entries)

    # ──────────────────────────────────────────────────────────────────────────
    # Slots privados
    # ──────────────────────────────────────────────────────────────────────────

    def _apply_filter(self) -> None:
        """Filtra a tabela por texto e/ou categoria em tempo real."""
        text = self._search.text().lower()
        cat_filter = self._cat_filter.currentText()
        use_cat = cat_filter != "Todas as categorias"

        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 1)
            path_item = self.table.item(row, 2)
            cat_item = self.table.item(row, 4)

            name = name_item.text().lower() if name_item else ""
            path = path_item.text().lower() if path_item else ""
            cat = cat_item.text() if cat_item else ""

            match_text = (not text) or (text in name) or (text in path)
            match_cat = (not use_cat) or (cat == cat_filter)
            self.table.setRowHidden(row, not (match_text and match_cat))

    def _show_context_menu(self, pos) -> None:
        """Exibe menu de contexto com opções Explorer e copiar caminho."""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        filepath = self._path_map.get(row, "")
        if not filepath:
            return

        menu = QMenu(self)
        act_open = menu.addAction("📂  Abrir pasta no Explorer")
        act_copy = menu.addAction("📋  Copiar caminho")
        menu.addSeparator()
        act_info = menu.addAction(Path(filepath).name)
        act_info.setEnabled(False)

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == act_open:
            self._open_in_explorer(filepath)
        elif action == act_copy:
            QApplication.clipboard().setText(filepath)

    @staticmethod
    def _open_in_explorer(filepath: str) -> None:
        try:
            p = Path(filepath)
            if p.is_file():
                subprocess.run(["explorer", "/select,", str(p)], check=False)
            elif p.is_dir():
                subprocess.run(["explorer", str(p)], check=False)
        except Exception:
            pass
