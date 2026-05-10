"""
Aba — Top 20 Pastas Mais Pesadas.

Exibe tabela com os diretórios de maior tamanho encontrados na varredura.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.gui.workers import ScanResult
from src.gui.tabs.shared import make_label, make_separator


class TopDirsTab(QWidget):
    """Aba — Top 20 pastas mais pesadas do sistema."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # ── Header ──────────────────────────────────────────────────────────
        header = QHBoxLayout()
        header.addWidget(make_label("Top 20 Pastas Mais Pesadas", "heading"))
        header.addStretch()
        self._info_lbl = make_label("Aguardando varredura...", "subtext")
        header.addWidget(self._info_lbl)
        layout.addLayout(header)

        layout.addWidget(make_separator())

        # ── Tabela ───────────────────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)

        columns = ["#", "Pasta", "Caminho Completo", "Tamanho", "Arquivos", "Disco"]
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
        h.resizeSection(4, 90)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(5, 60)

        layout.addWidget(self.table, stretch=1)

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
        """Preenche a tabela com os diretórios mais pesados da varredura."""
        self.table.setRowCount(0)

        if not result.top_dirs:
            self._info_lbl.setText("Nenhuma pasta encontrada")
            self._total_lbl.setText("")
            return

        total_size = sum(d.total_size_bytes for d in result.top_dirs)
        self._info_lbl.setText(
            f"{len(result.top_dirs)} pastas  |  "
            f"{total_size / (1024 ** 3):.1f} GB no total"
        )

        for idx, de in enumerate(result.top_dirs):
            self.table.insertRow(idx)
            p = Path(de.path)
            size_gb = de.total_size_bytes / (1024 ** 3)
            size_str = (
                f"{size_gb:.1f} GB"
                if size_gb >= 1
                else f"{de.total_size_bytes / (1024 ** 2):.1f} MB"
            )
            drive = p.drive.upper()

            values = [
                str(idx + 1),
                p.name,
                str(p),
                size_str,
                f"{de.file_count:,}",
                drive,
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
                elif col in (4, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(idx, col, item)

            self.table.setRowHeight(idx, 38)

        total_files = sum(d.file_count for d in result.top_dirs)
        self._total_lbl.setText(
            f"Total: {total_files:,} arquivos em {len(result.top_dirs)} pastas"
        )
