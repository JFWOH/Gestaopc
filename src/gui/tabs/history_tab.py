"""
Aba — Histórico de Operações.

Exibe todas as operações de arquivo (mover/deletar) registradas no SQLite.
Emite sinais para desfazer última movimentação e limpar histórico.

API pública:
    refresh(db=None, executor=None)  — recarrega dados do banco ou do executor
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.gui.styles import Colors
from src.core.executor import OperationRecord
from src.gui.tabs.shared import make_label, make_separator


class HistoryTab(QWidget):
    """Aba — histórico persistido de operações de arquivo."""

    # Emitido quando o usuário clica em "Desfazer Última Movimentação"
    undo_move_requested = Signal()
    # Emitido quando o usuário clica em "Limpar Histórico"
    clear_history_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # ── Header ──────────────────────────────────────────────────────────
        header = QHBoxLayout()
        header.addWidget(make_label("Historico de Operacoes", "heading"))
        header.addStretch()
        self._info_lbl = make_label("Nenhuma operacao realizada", "subtext")
        header.addWidget(self._info_lbl)
        layout.addLayout(header)

        layout.addWidget(make_separator())

        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._btn_undo = QPushButton("Desfazer Ultima Movimentacao")
        self._btn_undo.setProperty("cssClass", "secondary")
        self._btn_undo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_undo.setEnabled(False)
        self._btn_undo.clicked.connect(self.undo_move_requested)
        toolbar.addWidget(self._btn_undo)

        toolbar.addStretch()

        btn_clear = QPushButton("Limpar Historico")
        btn_clear.setProperty("cssClass", "secondary")
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.clicked.connect(self.clear_history_requested)
        toolbar.addWidget(btn_clear)

        layout.addLayout(toolbar)

        # ── Tabela ───────────────────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)

        columns = ["Hora", "Acao", "Arquivo", "Destino", "Status", "Detalhe"]
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(0, 140)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(1, 80)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        h.resizeSection(4, 70)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.table, stretch=1)

    # ──────────────────────────────────────────────────────────────────────────
    # API pública
    # ──────────────────────────────────────────────────────────────────────────

    def refresh(self, db=None, executor=None) -> None:
        """
        Recarrega a tabela do histórico.

        Tenta primeiro o banco de dados (source of truth); cai para
        executor.history se o banco não tiver registros.
        """
        records: list[OperationRecord] = []

        if db is not None:
            try:
                db_rows = db.list_operations()
                if db_rows:
                    for row in db_rows:
                        records.append(
                            OperationRecord(
                                timestamp=row["timestamp"],
                                action=row["action"],
                                source_path=row["source_path"],
                                target_path=row["target_path"] or "",
                                success=bool(row["success"]),
                                error=row["error"] or "",
                                used_trash=bool(row["used_trash"]),
                            )
                        )
            except Exception:
                pass

        if not records and executor is not None:
            records = list(reversed(executor.history))

        self.table.setRowCount(0)

        if not records:
            self._info_lbl.setText("Nenhuma operacao realizada")
            self._btn_undo.setEnabled(False)
            return

        ok = sum(1 for r in records if r.success)
        fail = len(records) - ok
        self._info_lbl.setText(
            f"{len(records)} operacoes  |  {ok} OK  |  {fail} falhas"
        )

        has_moves = any(r.action == "MOVER" and r.success for r in records)
        self._btn_undo.setEnabled(has_moves)

        for idx, record in enumerate(records):
            self.table.insertRow(idx)

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

            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 1:
                    color = (
                        Colors.ACCENT_CYAN if val == "MOVER" else Colors.STATUS_RED
                    )
                    item.setForeground(QColor(color))
                elif col == 4:
                    item.setForeground(QColor(status_color))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(idx, col, item)

            self.table.setRowHeight(idx, 36)
