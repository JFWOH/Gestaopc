"""
Aba — Arquivos Duplicados.

Detecta e exibe grupos de arquivos duplicados (verificados por SHA-256).
Emite `actions_requested` com a lista de FileAction quando o usuário confirma deleção.
Emite `rescan_requested` quando o botão Re-escanear é acionado.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.gui.styles import Colors
from src.gui.workers import ScanResult
from src.core.executor import FileAction
from src.gui.tabs.shared import make_label, make_separator

# Paleta de cores alternadas para grupos de duplicatas
_GROUP_COLORS = [
    "#1A2633", "#1A2820", "#25201A", "#201A26", "#1A2025", "#261A1A",
]


class DuplicatesTab(QWidget):
    """Aba — arquivos duplicados detectados pelo algoritmo de 3 etapas."""

    # Emite list[FileAction] quando o usuário confirma deleção de duplicatas
    actions_requested = Signal(list)
    # Emite quando o usuário clica em "Re-escanear"
    rescan_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # ── Header ──────────────────────────────────────────────────────────
        header = QHBoxLayout()
        header.addWidget(make_label("Arquivos Duplicados", "heading"))
        header.addStretch()
        self._info_lbl = make_label("Aguardando varredura...", "subtext")
        header.addWidget(self._info_lbl)
        layout.addLayout(header)

        layout.addWidget(make_separator())

        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._btn_select_all = QPushButton("Selecionar Todos")
        self._btn_select_all.setProperty("cssClass", "secondary")
        self._btn_select_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_select_all.clicked.connect(self._on_toggle_select_all)
        toolbar.addWidget(self._btn_select_all)

        self._btn_delete = QPushButton("Deletar Selecionados")
        self._btn_delete.setProperty("cssClass", "danger")
        self._btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_delete.setEnabled(False)
        self._btn_delete.clicked.connect(self._on_delete_selected)
        toolbar.addWidget(self._btn_delete)

        toolbar.addStretch()

        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Buscar arquivo ou hash...")
        self._search.setFixedHeight(34)
        self._search.setFixedWidth(280)
        self._search.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self._search)

        btn_rescan = QPushButton("Re-escanear")
        btn_rescan.setProperty("cssClass", "secondary")
        btn_rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_rescan.clicked.connect(self.rescan_requested)
        toolbar.addWidget(btn_rescan)

        layout.addLayout(toolbar)

        # ── Tabela ───────────────────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        columns = ["", "Arquivo", "Caminho", "Tamanho", "Hash (parcial)", "Grupo"]
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

        h = self.table.horizontalHeader()
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

        self._path_map: dict[int, str] = {}
        self._checkboxes: list[QCheckBox] = []

        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table, stretch=1)

    # ──────────────────────────────────────────────────────────────────────────
    # API pública
    # ──────────────────────────────────────────────────────────────────────────

    def populate(self, result: ScanResult) -> None:
        """Preenche a tabela com os grupos de duplicatas detectados."""
        self.table.setRowCount(0)
        self._path_map.clear()
        self._checkboxes.clear()

        if not result.duplicates:
            self._info_lbl.setText("Nenhuma duplicata encontrada")
            self._btn_delete.setEnabled(False)
            return

        total_groups = len(result.duplicates)
        total_wasted = sum(g.wasted_mb for g in result.duplicates)
        total_files = sum(g.count for g in result.duplicates)
        self._info_lbl.setText(
            f"{total_groups} grupos  |  {total_files} arquivos  |  "
            f"{total_wasted:.1f} MB desperdicados"
        )
        self._btn_delete.setEnabled(True)

        row_idx = 0
        for group_idx, group in enumerate(result.duplicates, start=1):
            row_bg = QColor(_GROUP_COLORS[(group_idx - 1) % len(_GROUP_COLORS)])

            for filepath in group.files:
                self.table.insertRow(row_idx)

                # Checkbox centralizado
                cb = QCheckBox()
                cb_widget = QWidget()
                cb_layout = QHBoxLayout(cb_widget)
                cb_layout.addWidget(cb)
                cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cb_layout.setContentsMargins(0, 0, 0, 0)
                self.table.setCellWidget(row_idx, 0, cb_widget)
                self._checkboxes.append(cb)
                self._path_map[row_idx] = filepath

                p = Path(filepath)
                size_mb = group.size_bytes / (1024 ** 2)
                size_str = (
                    f"{size_mb / 1024:.1f} GB"
                    if size_mb >= 1024
                    else f"{size_mb:.1f} MB"
                )
                hash_short = f"{group.hash_sha256[:6]}...{group.hash_sha256[-4:]}"

                for col_idx, val in enumerate(
                    [p.name, str(p.parent), size_str, hash_short, str(group_idx)],
                    start=1,
                ):
                    item = QTableWidgetItem(val)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setBackground(row_bg)
                    if col_idx == 3:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                    if col_idx == 5:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        item.setForeground(QColor(Colors.ACCENT_CYAN))
                    self.table.setItem(row_idx, col_idx, item)

                self.table.setRowHeight(row_idx, 42)
                row_idx += 1

    # ──────────────────────────────────────────────────────────────────────────
    # Slots privados
    # ──────────────────────────────────────────────────────────────────────────

    def _on_toggle_select_all(self) -> None:
        if not self._checkboxes:
            return
        all_checked = all(cb.isChecked() for cb in self._checkboxes)
        for cb in self._checkboxes:
            cb.setChecked(not all_checked)
        self._btn_select_all.setText(
            "Desmarcar Todos" if not all_checked else "Selecionar Todos"
        )

    def _on_delete_selected(self) -> None:
        selected = [
            self._path_map[i]
            for i, cb in enumerate(self._checkboxes)
            if cb.isChecked() and i in self._path_map
        ]
        if not selected:
            return

        reply = QMessageBox.warning(
            self,
            "Confirmar Deleção",
            f"Deseja enviar {len(selected)} arquivo(s) para a Lixeira?\n\n"
            "Esta ação pode ser desfeita restaurando da Lixeira do Windows.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            actions = [FileAction(action="DELETAR", source_path=p) for p in selected]
            self.actions_requested.emit(actions)

    def _apply_filter(self) -> None:
        """Filtra a tabela por texto em tempo real."""
        text = self._search.text().lower()
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 1)
            path_item = self.table.item(row, 2)
            hash_item = self.table.item(row, 4)

            name = name_item.text().lower() if name_item else ""
            path = path_item.text().lower() if path_item else ""
            hash_v = hash_item.text().lower() if hash_item else ""

            match = (not text) or (text in name) or (text in path) or (text in hash_v)
            self.table.setRowHidden(row, not match)

    def _show_context_menu(self, pos) -> None:
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
