"""
ScanStatusPanel — Sprint 7.1.

Painel inline visível durante a varredura, mostrando o status de cada disco
(pendente / em curso / concluído) e o estágio global atual (mapeamento,
duplicatas, sugestões). Auto-oculta quando não há varredura em curso.

Layout:

    ┌──────────────────────────────────────────────────────────────┐
    │ STATUS DA VARREDURA                                  02:34    │
    ├──────────────────────────────────────────────────────────────┤
    │ ✓  C:  NVMe   Concluído                                       │
    │ ✓  D:  SSD    Concluído                                       │
    │ ⟳  L:  HDD    Analisando arquivos…                            │
    │ ○  G:  HDD    Pendente                                        │
    │ ○  J:  HDD    Pendente                                        │
    ├──────────────────────────────────────────────────────────────┤
    │ Estágio global: Comparando duplicatas (hash SHA-256)…         │
    └──────────────────────────────────────────────────────────────┘

Estados de disco:
    "pending"  → ○  (cinza)
    "scanning" → ⟳  (cyan, com label de estágio)
    "done"     → ✓  (verde)
    "error"    → ✗  (vermelho)

API pública:
    panel.begin_scan(partitions)             — cria linhas e mostra
    panel.update_disk(letter, status, stage) — atualiza um disco
    panel.set_global_stage(text)             — atualiza estágio global
    panel.end_scan()                         — para timer; chamador decide ocultar
    panel.reset()                            — limpa tudo e oculta
"""

from __future__ import annotations

import time
from typing import Iterable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.scanner import PartitionInfo
from src.gui.styles import Colors, Fonts


# Estados válidos
STATE_PENDING = "pending"
STATE_SCANNING = "scanning"
STATE_DONE = "done"
STATE_ERROR = "error"

VALID_STATES = frozenset({STATE_PENDING, STATE_SCANNING, STATE_DONE, STATE_ERROR})

# Símbolos por estado (Unicode — sem dependência de assets)
_ICON_BY_STATE = {
    STATE_PENDING: "○",
    STATE_SCANNING: "⟳",
    STATE_DONE: "✓",
    STATE_ERROR: "✗",
}

# Cor do ícone por estado
_ICON_COLOR = {
    STATE_PENDING: Colors.TEXT_DISABLED,
    STATE_SCANNING: Colors.ACCENT_CYAN,
    STATE_DONE: Colors.STATUS_GREEN,
    STATE_ERROR: Colors.STATUS_RED,
}

# Texto padrão por estado quando o stage é vazio
_DEFAULT_LABEL = {
    STATE_PENDING: "Pendente",
    STATE_SCANNING: "Em curso…",
    STATE_DONE: "Concluído",
    STATE_ERROR: "Falhou",
}


class _DiskRow(QWidget):
    """
    Linha compacta representando um disco no ScanStatusPanel.

    Layout horizontal: [ícone] [letra] [tipo de mídia] [stage label]
    """

    ROW_HEIGHT = 28

    def __init__(
        self, letter: str, media_type: str, parent: QWidget | None = None
    ):
        super().__init__(parent)
        self._letter = letter
        self._media_type = media_type or "Disco"

        self.setFixedHeight(self.ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(12)

        # Ícone de status — fonte maior para leitura
        self._icon = QLabel(_ICON_BY_STATE[STATE_PENDING])
        icon_font = QFont(Fonts.FAMILY)
        icon_font.setPointSize(Fonts.SIZE_BODY + 2)
        icon_font.setBold(True)
        self._icon.setFont(icon_font)
        self._icon.setFixedWidth(18)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon)

        # Letra do drive
        self._letter_label = QLabel(letter)
        letter_font = QFont(Fonts.FAMILY)
        letter_font.setPointSize(Fonts.SIZE_BODY)
        letter_font.setBold(True)
        self._letter_label.setFont(letter_font)
        self._letter_label.setFixedWidth(28)
        self._letter_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        layout.addWidget(self._letter_label)

        # Badge de tipo de mídia
        self._media_label = QLabel(self._media_type.upper())
        media_font = QFont(Fonts.FAMILY)
        media_font.setPointSize(Fonts.SIZE_TINY)
        media_font.setBold(True)
        self._media_label.setFont(media_font)
        self._media_label.setFixedWidth(56)
        self._media_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._media_label.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; "
            f"background-color: {Colors.BG_INPUT}; "
            f"border-radius: 3px; padding: 2px 6px;"
        )
        layout.addWidget(self._media_label)

        # Label de estágio (preenche espaço restante)
        self._stage_label = QLabel(_DEFAULT_LABEL[STATE_PENDING])
        stage_font = QFont(Fonts.FAMILY)
        stage_font.setPointSize(Fonts.SIZE_BODY)
        self._stage_label.setFont(stage_font)
        self._stage_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        layout.addWidget(self._stage_label, stretch=1)

        # Estado interno
        self._state = STATE_PENDING
        self._apply_visual_state()

    @property
    def letter(self) -> str:
        return self._letter

    @property
    def state(self) -> str:
        return self._state

    def set_state(self, state: str, stage_text: str = "") -> None:
        """
        Atualiza estado e texto do estágio. Estados inválidos são ignorados
        (silenciosamente — UI nunca crasha por inconsistência de signal).
        """
        if state not in VALID_STATES:
            return
        self._state = state
        text = stage_text.strip() or _DEFAULT_LABEL[state]
        self._stage_label.setText(text)
        self._apply_visual_state()

    def _apply_visual_state(self) -> None:
        self._icon.setText(_ICON_BY_STATE[self._state])
        self._icon.setStyleSheet(
            f"color: {_ICON_COLOR[self._state]}; font-weight: bold;"
        )


class ScanStatusPanel(QFrame):
    """
    Painel inline de status da varredura.

    Não emite sinais — é puramente um receptor de updates do FullScanWorker
    via slots públicos (begin_scan, update_disk, set_global_stage, end_scan).
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ScanStatusPanel")
        self.setStyleSheet(f"""
            QFrame#ScanStatusPanel {{
                background-color: {Colors.BG_SECONDARY};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 6px;
            }}
        """)

        self._rows: dict[str, _DiskRow] = {}
        self._start_time: float | None = None

        # Layout principal
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        # ── Cabeçalho: título + cronômetro ─────────────────────
        header = QHBoxLayout()
        header.setSpacing(12)

        title = QLabel("STATUS DA VARREDURA")
        title_font = QFont(Fonts.FAMILY)
        title_font.setPointSize(Fonts.SIZE_SMALL)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(
            f"color: {Colors.ACCENT_CYAN}; letter-spacing: 1px;"
        )
        header.addWidget(title)

        header.addStretch()

        self._elapsed_label = QLabel("00:00")
        elapsed_font = QFont("Consolas", Fonts.SIZE_BODY)
        elapsed_font.setBold(True)
        self._elapsed_label.setFont(elapsed_font)
        self._elapsed_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        header.addWidget(self._elapsed_label)

        outer.addLayout(header)

        # ── Container para linhas de disco ─────────────────────
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        outer.addLayout(self._rows_layout)

        # ── Estágio global ─────────────────────────────────────
        self._global_label = QLabel("")
        global_font = QFont(Fonts.FAMILY)
        global_font.setPointSize(Fonts.SIZE_BODY)
        global_font.setItalic(True)
        self._global_label.setFont(global_font)
        self._global_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        self._global_label.setVisible(False)
        outer.addWidget(self._global_label)

        # Cronômetro
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick_elapsed)

        self.hide()

    # =========================================================================
    # API pública
    # =========================================================================

    def begin_scan(self, partitions: Iterable[PartitionInfo]) -> None:
        """Inicia o painel com a lista de discos a serem varridos."""
        self.reset()
        self._start_time = time.perf_counter()
        self._tick_elapsed()  # exibe 00:00 imediatamente
        self._timer.start()

        for p in partitions:
            row = _DiskRow(p.letter, p.media_type or "Disco")
            self._rows[p.letter] = row
            self._rows_layout.addWidget(row)

        if self._rows:
            self.show()

    def update_disk(self, letter: str, status: str, stage: str = "") -> None:
        """Atualiza estado e texto de um disco. Letras desconhecidas são ignoradas."""
        row = self._rows.get(letter)
        if row is not None:
            row.set_state(status, stage)

    def set_global_stage(self, text: str) -> None:
        """Mostra ou oculta o estágio global na parte inferior."""
        text = text.strip()
        if text:
            self._global_label.setText(text)
            self._global_label.setVisible(True)
        else:
            self._global_label.clear()
            self._global_label.setVisible(False)

    def end_scan(self) -> None:
        """Para o cronômetro. O chamador decide quando ocultar (via reset())."""
        self._timer.stop()

    def reset(self) -> None:
        """Limpa todas as linhas, para timer e oculta painel."""
        self._timer.stop()
        self._start_time = None
        for row in list(self._rows.values()):
            self._rows_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()
        self._elapsed_label.setText("00:00")
        self.set_global_stage("")
        self.hide()

    # =========================================================================
    # Internos
    # =========================================================================

    def _tick_elapsed(self) -> None:
        if self._start_time is None:
            return
        delta = int(time.perf_counter() - self._start_time)
        mins, secs = divmod(delta, 60)
        if mins >= 60:
            hours, mins = divmod(mins, 60)
            self._elapsed_label.setText(f"{hours:02d}:{mins:02d}:{secs:02d}")
        else:
            self._elapsed_label.setText(f"{mins:02d}:{secs:02d}")

    # ---- Acesso para testes (não é API pública) ----------------------------

    def _disk_count(self) -> int:
        return len(self._rows)

    def _disk_state(self, letter: str) -> str | None:
        row = self._rows.get(letter)
        return row.state if row else None
