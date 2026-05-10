"""
Aba — Sugestões da IA (Motor de Regras).

Exibe cards com as recomendações geradas pelo SmartRulesEngine após cada varredura.
Emite `actions_requested(list[FileAction], status_msg)` quando o usuário confirma execução.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.gui.styles import Colors
from src.gui.workers import ScanResult
from src.core.executor import FileAction
from src.gui.tabs.shared import SuggestionCard, make_label, make_separator


def _clear_layout(layout) -> None:
    """Remove todos os widgets de um layout."""
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()


class SuggestionsTab(QWidget):
    """Aba — sugestões geradas pelo Motor de Regras Inteligentes."""

    # Emite (list[FileAction], status_msg) quando o usuário confirma ação
    actions_requested = Signal(list, str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._current_suggestions: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # ── Header ──────────────────────────────────────────────────────────
        header = QHBoxLayout()
        header.addWidget(make_label("Sugestoes da IA  --  Motor de Regras", "heading"))
        header.addStretch()
        self._count_lbl = make_label("Aguardando varredura...", "subtext")
        header.addWidget(self._count_lbl)
        layout.addLayout(header)

        layout.addWidget(make_separator())

        # ── Pills de resumo por regra (conteúdo dinâmico) ───────────────────
        self._rules_layout = QHBoxLayout()
        self._rules_layout.setSpacing(16)
        self._rules_layout.addStretch()
        layout.addLayout(self._rules_layout)

        # ── Scroll area com cards ─────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)

        sug_container = QWidget()
        sug_layout = QVBoxLayout(sug_container)
        sug_layout.setContentsMargins(0, 8, 0, 8)
        sug_layout.setSpacing(10)

        placeholder = make_label(
            "Nenhuma sugestao disponivel. Inicie uma varredura para ativar o motor de regras.",
            "subtext",
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet(f"color: {Colors.TEXT_DISABLED}; padding: 60px;")
        sug_layout.addWidget(placeholder)
        sug_layout.addStretch()

        self._scroll.setWidget(sug_container)
        layout.addWidget(self._scroll, stretch=1)

        # ── Footer com ações em massa ─────────────────────────────────────────
        footer = QHBoxLayout()
        footer.setSpacing(12)
        footer.addStretch()

        self._btn_exec_all = QPushButton("  Executar Todas as Sugestoes  ")
        self._btn_exec_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_exec_all.setFixedHeight(40)
        self._btn_exec_all.setEnabled(False)
        self._btn_exec_all.clicked.connect(self._on_exec_all)
        footer.addWidget(self._btn_exec_all)

        btn_dismiss = QPushButton("Dispensar Todas")
        btn_dismiss.setProperty("cssClass", "secondary")
        btn_dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_dismiss.setFixedHeight(40)
        btn_dismiss.clicked.connect(self._on_dismiss_all)
        footer.addWidget(btn_dismiss)

        layout.addLayout(footer)

    # ──────────────────────────────────────────────────────────────────────────
    # API pública
    # ──────────────────────────────────────────────────────────────────────────

    def populate(self, result: ScanResult) -> None:
        """Reconstrói a aba com as sugestões da varredura mais recente."""
        count = len(result.suggestions)
        self._count_lbl.setText(
            f"{count} sugestoes ativas" if count else "Nenhuma sugestao"
        )

        # Reconstruir pills de resumo de regras
        _clear_layout(self._rules_layout)

        if result.suggestions:
            rule_counts: dict[int, int] = {}
            for s in result.suggestions:
                rule_counts[s.rule_id] = rule_counts.get(s.rule_id, 0) + 1

            rule_meta = {
                1: ("Midia pesada no NVMe", Colors.ACCENT_CYAN),
                2: ("Duplicatas", Colors.STATUS_YELLOW),
                3: ("Disco critico (>90%)", Colors.STATUS_RED),
            }

            for rule_id, cnt in sorted(rule_counts.items()):
                desc, color = rule_meta.get(
                    rule_id, (f"Regra {rule_id}", Colors.TEXT_SECONDARY)
                )
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
                # inserir antes do stretch final
                self._rules_layout.insertWidget(
                    self._rules_layout.count() - 1, pill
                )

        self._current_suggestions = list(result.suggestions) if result.suggestions else []

        # Reconstruir container de cards
        new_container = QWidget()
        new_layout = QVBoxLayout(new_container)
        new_layout.setContentsMargins(0, 8, 0, 8)
        new_layout.setSpacing(10)

        if result.suggestions:
            self._btn_exec_all.setEnabled(True)
            for sug in result.suggestions:
                card = SuggestionCard(
                    rule_id=sug.rule_id,
                    rule_name=sug.rule_name,
                    action=sug.action,
                    detail=sug.detail,
                    priority=sug.priority,
                    file_path=sug.file_path,
                    target_disk=sug.target_disk,
                    on_execute=lambda checked, s=sug: self._on_exec_single(s),
                )
                new_layout.addWidget(card)
        else:
            self._btn_exec_all.setEnabled(False)
            lbl = make_label(
                "Nenhuma sugestao gerada. Todos os discos parecem bem organizados.",
                "subtext",
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"color: {Colors.STATUS_GREEN}; padding: 60px;")
            new_layout.addWidget(lbl)

        new_layout.addStretch()
        self._scroll.setWidget(new_container)

    # ──────────────────────────────────────────────────────────────────────────
    # Slots privados
    # ──────────────────────────────────────────────────────────────────────────

    def _on_exec_single(self, suggestion) -> None:
        """Executa uma sugestão individual do Motor de Regras."""
        if suggestion.action == "MOVER":
            file_name = Path(suggestion.file_path).name
            target = str(Path(suggestion.target_disk + "\\") / file_name)
            reply = QMessageBox.question(
                self,
                "Confirmar Movimentacao",
                f"Mover arquivo?\n\nDe: {suggestion.file_path}\nPara: {target}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            actions = [
                FileAction(
                    action="MOVER",
                    source_path=suggestion.file_path,
                    target_path=target,
                )
            ]

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

        self.actions_requested.emit(actions, f"Executando R{suggestion.rule_id}...")

    def _on_exec_all(self) -> None:
        """Executa todas as sugestões ativas de uma vez."""
        if not self._current_suggestions:
            return

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

        actions: list[FileAction] = []
        for sug in self._current_suggestions:
            if sug.action == "MOVER":
                file_name = Path(sug.file_path).name
                target = str(Path(sug.target_disk + "\\") / file_name)
                actions.append(
                    FileAction(
                        action="MOVER",
                        source_path=sug.file_path,
                        target_path=target,
                    )
                )
            elif sug.action == "DELETAR":
                actions.append(
                    FileAction(action="DELETAR", source_path=sug.file_path)
                )

        self.actions_requested.emit(actions, "Executando todas as sugestoes...")

    def _on_dismiss_all(self) -> None:
        """Descarta todas as sugestões visualmente (sem executar nada)."""
        self._current_suggestions = []
        self._count_lbl.setText("Nenhuma sugestao")
        self._btn_exec_all.setEnabled(False)
        _clear_layout(self._rules_layout)

        new_container = QWidget()
        new_layout = QVBoxLayout(new_container)
        new_layout.setContentsMargins(0, 8, 0, 8)

        lbl = make_label("Todas as sugestoes foram dispensadas.", "subtext")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(f"color: {Colors.TEXT_DISABLED}; padding: 60px;")
        new_layout.addWidget(lbl)
        new_layout.addStretch()

        self._scroll.setWidget(new_container)
