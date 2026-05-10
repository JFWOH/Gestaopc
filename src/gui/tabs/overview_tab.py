"""
Aba 1 — Visão Geral dos Discos.

Exibe barras de uso por disco, donut chart e estatísticas de rodapé.
Responsabilidade: apenas UI, nenhuma lógica de negócio.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.gui.styles import Colors
from src.gui.workers import ScanResult
from src.gui.charts import DonutChartWithLegend, DonutSegment
from src.gui.tabs.shared import DiskUsageBar, make_label, make_separator


class OverviewTab(QWidget):
    """Aba de Visão Geral — mapas de uso dos discos físicos e lógicos."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # ── Header ──────────────────────────────────────────────────────────
        header = QHBoxLayout()
        header.addWidget(make_label("Uso de Armazenamento", "heading"))
        header.addStretch()
        self._disk_count_lbl = make_label("Aguardando varredura...", "subtext")
        header.addWidget(self._disk_count_lbl)
        layout.addLayout(header)

        layout.addWidget(make_separator())

        # ── Scroll area com barras de disco ─────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)

        _container = QWidget()
        _clayout = QVBoxLayout(_container)
        _clayout.setContentsMargins(0, 0, 0, 0)
        _clayout.setSpacing(4)

        placeholder = make_label(
            "Nenhum dado disponivel. Inicie uma varredura para ver o uso dos discos.",
            "subtext",
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet(f"color: {Colors.TEXT_DISABLED}; padding: 60px;")
        _clayout.addWidget(placeholder)
        _clayout.addStretch()

        self._scroll.setWidget(_container)
        layout.addWidget(self._scroll, stretch=1)

        # ── Gráfico donut ────────────────────────────────────────────────────
        self._donut = DonutChartWithLegend()
        layout.addWidget(self._donut)

        # ── Rodapé com estatísticas ──────────────────────────────────────────
        footer = QHBoxLayout()
        footer.setSpacing(32)

        self._stat_total = self._make_stat("--", "Espaco Total", Colors.TEXT_PRIMARY)
        self._stat_used = self._make_stat("--", "Em Uso", Colors.STATUS_ORANGE)
        self._stat_free = self._make_stat("--", "Livre", Colors.STATUS_GREEN)
        self._stat_critical = self._make_stat(
            "--", "Discos Criticos (>90%)", Colors.STATUS_RED
        )

        for s in (self._stat_total, self._stat_used, self._stat_free, self._stat_critical):
            footer.addLayout(s)

        layout.addLayout(footer)

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers privados
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _make_stat(value: str, label: str, color: str) -> QVBoxLayout:
        """Cria bloco valor+label para o rodapé de estatísticas."""
        box = QVBoxLayout()
        box.setSpacing(2)
        lbl_val = QLabel(value)
        lbl_val.setStyleSheet(
            f"color: {color}; font-size: 20px; font-weight: 700;"
        )
        lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(lbl_val)
        lbl_desc = make_label(label, "subtext")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(lbl_desc)
        return box

    @staticmethod
    def _set_stat(stat_layout: QVBoxLayout, value: str) -> None:
        """Atualiza o valor de um bloco de estatística."""
        widget = stat_layout.itemAt(0).widget()
        if isinstance(widget, QLabel):
            widget.setText(value)

    # ──────────────────────────────────────────────────────────────────────────
    # API pública
    # ──────────────────────────────────────────────────────────────────────────

    def populate(self, result: ScanResult) -> None:
        """Reconstrói a aba com os dados da varredura mais recente."""
        # Barras de disco
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
            new_layout.addWidget(make_separator())

        new_layout.addStretch()
        self._scroll.setWidget(new_container)

        # Contador de discos
        self._disk_count_lbl.setText(
            f"Total monitorado: {len(result.partitions)} discos"
        )

        # Estatísticas de rodapé
        total_gb = sum(p.total_gb for p in result.partitions)
        free_gb = sum(p.free_gb for p in result.partitions)
        used_gb = total_gb - free_gb
        critical = sum(1 for p in result.partitions if p.percent_used > 90)

        self._set_stat(self._stat_total, f"{total_gb / 1024:.2f} TB")
        self._set_stat(self._stat_used, f"{used_gb / 1024:.2f} TB")
        self._set_stat(self._stat_free, f"{free_gb / 1024:.2f} TB")
        self._set_stat(self._stat_critical, str(critical))

        # Donut chart
        media_colors = {
            "NVMe": Colors.ACCENT_CYAN,
            "SSD": Colors.STATUS_GREEN,
            "HDD": Colors.STATUS_YELLOW,
            "Desconhecido": Colors.TEXT_DISABLED,
        }
        segments = [
            DonutSegment(
                label=f"{p.letter} ({p.media_type})",
                value=round((p.total_bytes - p.free_bytes) / (1024 ** 3), 1),
                color=media_colors.get(p.media_type, Colors.TEXT_DISABLED),
            )
            for p in result.partitions
        ]
        self._donut.set_data(
            segments,
            center_label=f"Total\n{total_gb / 1024:.1f} TB",
        )
