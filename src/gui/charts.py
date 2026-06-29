"""
Charts — Gráficos visuais renderizados com QPainter.

Implementa os gráficos solicitados na Seção 4 da spec:
  - DonutChart: gráfico donut de uso de disco
  - CategoryBarChart: barras horizontais por categoria de arquivo
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QLinearGradient,
)
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy

from src.gui.styles import Colors, Fonts


# ---------------------------------------------------------------------------
# Data classes de entrada
# ---------------------------------------------------------------------------

@dataclass
class DonutSegment:
    """Um segmento do gráfico donut."""
    label: str
    value: float       # Valor absoluto (ex: GB usados)
    color: str         # Cor hex


@dataclass
class BarEntry:
    """Uma barra do gráfico de barras."""
    label: str
    value: float       # Valor numérico
    color: str
    suffix: str = ""   # Ex: " GB", " arquivos"


# ---------------------------------------------------------------------------
# DonutChart
# ---------------------------------------------------------------------------

class DonutChart(QWidget):
    """
    Gráfico Donut (pizza com buraco central) renderizado com QPainter.

    Mostra segmentos proporcionais com legenda integrada.
    O centro exibe um label (ex: "Total: 8.5 TB").

    Uso::

        chart = DonutChart(
            segments=[
                DonutSegment("C:", 940, "#00A8FF"),
                DonutSegment("D:", 1200, "#00E676"),
            ],
            center_label="Total\\n8.5 TB",
        )
    """

    def __init__(
        self,
        segments: list[DonutSegment] | None = None,
        center_label: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._segments = segments or []
        self._center_label = center_label
        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, segments: list[DonutSegment], center_label: str = ""):
        self._segments = segments
        self._center_label = center_label
        self.update()

    def paintEvent(self, event):
        if not self._segments:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        side = min(w, h) - 20
        donut_thickness = side * 0.22

        # Centralizar
        cx = w / 2
        cy = h / 2

        outer_rect = QRectF(cx - side / 2, cy - side / 2, side, side)
        inner_radius = side / 2 - donut_thickness

        total = sum(s.value for s in self._segments)
        if total <= 0:
            painter.end()
            return

        # Desenhar segmentos
        start_angle = 90 * 16  # Começar do topo (Qt usa 1/16 graus)

        for seg in self._segments:
            span_angle = int((seg.value / total) * 360 * 16)
            if span_angle == 0:
                continue

            color = QColor(seg.color)

            # Gradiente suave
            gradient = QConicalGradient(cx, cy, -(start_angle / 16 - 90))
            gradient.setColorAt(0.0, color)
            gradient.setColorAt(0.5, color.lighter(115))
            gradient.setColorAt(1.0, color)

            # Desenhar arco externo
            path = QPainterPath()
            path.arcMoveTo(outer_rect, start_angle / 16)
            path.arcTo(outer_rect, start_angle / 16, span_angle / 16)

            # Arco interno (buraco)
            inner_rect = QRectF(
                cx - inner_radius, cy - inner_radius,
                inner_radius * 2, inner_radius * 2,
            )
            end_angle = start_angle + span_angle
            path.arcTo(inner_rect, end_angle / 16, -span_angle / 16)
            path.closeSubpath()

            painter.setPen(QPen(QColor(Colors.BG_PRIMARY), 2))
            painter.setBrush(color)
            painter.drawPath(path)

            start_angle += span_angle

        # Centro — fundo escuro + label
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(Colors.BG_PRIMARY))
        inner_rect_bg = QRectF(
            cx - inner_radius + 2, cy - inner_radius + 2,
            (inner_radius - 2) * 2, (inner_radius - 2) * 2,
        )
        painter.drawEllipse(inner_rect_bg)

        if self._center_label:
            painter.setPen(QColor(Colors.TEXT_PRIMARY))
            font = QFont(Fonts.FAMILY, 11)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(inner_rect_bg, Qt.AlignmentFlag.AlignCenter, self._center_label)

        painter.end()


class DonutChartWithLegend(QWidget):
    """
    DonutChart + legenda lateral.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self._chart = DonutChart()
        self._chart.setFixedSize(200, 200)
        layout.addWidget(self._chart)

        self._legend_layout = QVBoxLayout()
        self._legend_layout.setSpacing(6)
        self._legend_layout.addStretch()
        layout.addLayout(self._legend_layout)
        layout.addStretch()

    def set_data(self, segments: list[DonutSegment], center_label: str = ""):
        self._chart.set_data(segments, center_label)

        # Reconstruir legenda
        while self._legend_layout.count() > 1:
            item = self._legend_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        for seg in segments:
            row = QHBoxLayout()
            row.setSpacing(8)

            dot = QLabel("●")
            dot.setStyleSheet(f"color: {seg.color}; font-size: 14px;")
            dot.setFixedWidth(18)
            row.addWidget(dot)

            text = QLabel(f"{seg.label}  {seg.value:.0f} GB")
            text.setStyleSheet(f"""
                color: {Colors.TEXT_SECONDARY};
                font-size: {Fonts.SIZE_SMALL}px;
            """)
            row.addWidget(text)
            row.addStretch()

            container = QWidget()
            container.setLayout(row)
            self._legend_layout.insertWidget(
                self._legend_layout.count() - 1, container
            )


# ---------------------------------------------------------------------------
# CategoryBarChart
# ---------------------------------------------------------------------------

class CategoryBarChart(QWidget):
    """
    Gráfico de barras horizontais para distribuição por categoria.

    Cada barra mostra: [label] [barra proporcional] [valor]

    Uso::

        chart = CategoryBarChart()
        chart.set_data([
            BarEntry("Vídeos", 150.5, Colors.ACCENT_CYAN, " GB"),
            BarEntry("Imagens", 45.2, Colors.STATUS_GREEN, " GB"),
        ])
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._entries: list[BarEntry] = []
        self._bar_height = 22
        self._bar_spacing = 10
        self._label_width = 110
        self._value_width = 80
        self.setMinimumHeight(50)

    def set_data(self, entries: list[BarEntry]):
        self._entries = sorted(entries, key=lambda e: e.value, reverse=True)
        height = max(
            len(self._entries) * (self._bar_height + self._bar_spacing) + 20,
            50,
        )
        self.setMinimumHeight(height)
        self.update()

    def paintEvent(self, event):
        if not self._entries:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        max_val = max(e.value for e in self._entries) if self._entries else 1
        bar_area_width = w - self._label_width - self._value_width - 20

        y = 10
        for entry in self._entries:
            color = QColor(entry.color)

            # Label (à esquerda)
            painter.setPen(QColor(Colors.TEXT_SECONDARY))
            label_font = QFont(Fonts.FAMILY, Fonts.SIZE_SMALL)
            label_font.setWeight(QFont.Weight.Medium)
            painter.setFont(label_font)
            label_rect = QRectF(0, y, self._label_width, self._bar_height)
            painter.drawText(
                label_rect,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                entry.label,
            )

            # Barra
            bar_x = self._label_width + 10
            bar_width = max(
                (entry.value / max_val) * bar_area_width if max_val > 0 else 0,
                4,
            )

            # Fundo da barra
            bg_rect = QRectF(bar_x, y + 2, bar_area_width, self._bar_height - 4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(Colors.BG_INPUT))
            painter.drawRoundedRect(bg_rect, 4, 4)

            # Barra preenchida com gradiente
            bar_rect = QRectF(bar_x, y + 2, bar_width, self._bar_height - 4)
            gradient = QLinearGradient(bar_rect.topLeft(), bar_rect.topRight())
            gradient.setColorAt(0.0, color)
            gradient.setColorAt(1.0, color.lighter(130))
            painter.setBrush(gradient)
            painter.drawRoundedRect(bar_rect, 4, 4)

            # Valor (à direita)
            painter.setPen(QColor(Colors.TEXT_PRIMARY))
            value_font = QFont(Fonts.FAMILY, Fonts.SIZE_SMALL)
            value_font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(value_font)
            value_rect = QRectF(
                bar_x + bar_area_width + 6, y,
                self._value_width, self._bar_height,
            )
            val_text = f"{entry.value:.1f}{entry.suffix}"
            painter.drawText(
                value_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                val_text,
            )

            y += self._bar_height + self._bar_spacing

        painter.end()
