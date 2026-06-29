"""
MainWindow — Janela principal do Gerenciador de PC (Sprint 5: thin orchestrator).

Sprint 5 — Refatoração GUI:
    A lógica de UI de cada aba foi extraída para src/gui/tabs/.
    MainWindow orquestra:
      - Lifecycle (tray, close, quit)
      - Varredura completa via FullScanWorker
      - Execução de ações via FileActionWorker
      - Conexão de sinais entre abas e workers

Especificação: 01-storage-manager.md § 4 (GUI).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QFrame,
)

from src.gui.styles import Colors, Fonts
from src.gui.workers import FullScanWorker, ScanResult
from src.gui.log_bridge import QtLogBridge
from src.gui.scan_status_panel import ScanStatusPanel
from src.core.executor import (
    SafeFileExecutor,
    FileAction,
    FileActionWorker,
    OperationRecord,
)
from src.core.storage_db import StorageManagerDB, get_default_db_path
from src.gui.icon import create_app_icon, create_tray_icon
from src.gui.assistant_tab import AssistantTab

from src.gui.tabs import (
    OverviewTab,
    TopFilesTab,
    TopDirsTab,
    DuplicatesTab,
    SuggestionsTab,
    HistoryTab,
)

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Janela principal — thin orchestrator que delega UI para sub-widgets de aba."""

    WINDOW_TITLE = "Gerenciador de PC  —  Storage Manager"
    MIN_WIDTH = 1100
    MIN_HEIGHT = 720

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(self.WINDOW_TITLE)
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.resize(1280, 800)

        # ── Estado compartilhado ────────────────────────────────────────────
        self._scan_worker: FullScanWorker | None = None
        self._action_worker: FileActionWorker | None = None
        self._last_result: ScanResult | None = None

        self._db = StorageManagerDB(get_default_db_path())
        self._db.initialize()
        self._executor = SafeFileExecutor(db=self._db)

        # Timer de animação de pulso no botão de varredura
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(600)
        self._pulse_timer.timeout.connect(self._pulse_scan_button)
        self._pulse_state = False

        # ── Layout central ──────────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_header())
        root_layout.addWidget(self._make_separator())

        # ── Painel de status de varredura (Sprint 7.1) ─────────────────────
        # Inicialmente oculto; mostrado durante varredura, ocultado ao fim.
        self._scan_status_panel = ScanStatusPanel()
        scan_status_wrap = QWidget()
        scan_status_wrap_layout = QVBoxLayout(scan_status_wrap)
        scan_status_wrap_layout.setContentsMargins(16, 8, 16, 0)
        scan_status_wrap_layout.setSpacing(0)
        scan_status_wrap_layout.addWidget(self._scan_status_panel)
        root_layout.addWidget(scan_status_wrap)

        # ── Sub-widgets de aba ──────────────────────────────────────────────
        self._overview_tab = OverviewTab()
        self._top_files_tab = TopFilesTab()
        self._top_dirs_tab = TopDirsTab()
        self._duplicates_tab = DuplicatesTab()
        self._suggestions_tab = SuggestionsTab()
        self._history_tab = HistoryTab()
        self._assistant_tab = AssistantTab(self)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._overview_tab,    "  Visao Geral  ")
        self.tabs.addTab(self._top_files_tab,   "  Maiores Arquivos  ")
        self.tabs.addTab(self._top_dirs_tab,    "  Pastas  ")
        self.tabs.addTab(self._duplicates_tab,  "  Duplicatas  ")
        self.tabs.addTab(self._suggestions_tab, "  Sugestoes da IA  ")
        self.tabs.addTab(self._history_tab,     "  Historico  ")
        self.tabs.addTab(self._assistant_tab,   "  Assistente IA  ")
        root_layout.addWidget(self.tabs, stretch=1)

        # ── Status bar ──────────────────────────────────────────────────────
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.status_progress = QProgressBar()
        self.status_progress.setFixedWidth(200)
        self.status_progress.setFixedHeight(16)
        self.status_progress.setRange(0, 100)
        self.status_progress.setValue(0)
        self.status_progress.setVisible(False)
        self.status_bar.addPermanentWidget(self.status_progress)

        self.status_bar.showMessage(
            "Pronto. Clique 'Iniciar Varredura Completa' para comecar."
        )

        # ── Bridge logger → status bar (Sprint 7.0) ─────────────────────────
        # Captura mensagens de todos os módulos core e as exibe na status bar
        # automaticamente. Resolve o "fica em silêncio por 13 min" durante
        # a Etapa 3 do DuplicateDetector e similares.
        self._log_bridge = QtLogBridge(level=logging.INFO, parent=self)
        self._log_bridge.message.connect(self._show_log_in_status)
        self._log_bridge.install()

        # ── Ícone e tray ────────────────────────────────────────────────────
        self._app_icon = create_app_icon()
        self.setWindowIcon(self._app_icon)

        self._tray = create_tray_icon(
            parent=self,
            on_open=self._show_from_tray,
            on_scan=self._on_start_scan,
            on_quit=self._quit_app,
        )
        self._tray.show()
        self._minimize_to_tray = True

        # ── Conexão de sinais entre abas ────────────────────────────────────
        self._connect_tab_signals()

    def _connect_tab_signals(self) -> None:
        """Conecta os sinais emitidos pelas abas aos handlers da MainWindow."""
        # DuplicatesTab → deletar arquivos selecionados
        self._duplicates_tab.actions_requested.connect(
            lambda actions: self._run_actions(actions, "Deletando duplicatas...")
        )
        # DuplicatesTab → re-escanear
        self._duplicates_tab.rescan_requested.connect(self._on_start_scan)

        # SuggestionsTab → executar ação(ões) confirmada(s)
        self._suggestions_tab.actions_requested.connect(self._run_actions)

        # HistoryTab → undo / clear
        self._history_tab.undo_move_requested.connect(self._on_undo_last_move)
        self._history_tab.clear_history_requested.connect(self._on_clear_history)

        # AssistantTab → atualizar Histórico após tool executiva
        if hasattr(self._assistant_tab, "ai_action_executed"):
            self._assistant_tab.ai_action_executed.connect(
                lambda: self._history_tab.refresh(self._db, self._executor)
            )

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def closeEvent(self, event: QCloseEvent) -> None:
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

        # Encerramento real — parar workers em andamento
        if self._scan_worker and self._scan_worker.isRunning():
            logger.info("Encerrando — abortando worker de varredura...")
            self._scan_worker.abort()
            self._scan_worker.quit()
            self._scan_worker.wait(5000)
        if self._action_worker and self._action_worker.isRunning():
            self._action_worker.abort()
            self._action_worker.quit()
            self._action_worker.wait(5000)
        if hasattr(self, "_db"):
            self._db.close()
        # Desinstalar bridge de log para liberar logger raiz
        if hasattr(self, "_log_bridge"):
            self._log_bridge.uninstall()
        self._tray.hide()
        event.accept()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _quit_app(self) -> None:
        self._minimize_to_tray = False
        self.close()

    # =========================================================================
    # Header
    # =========================================================================

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setStyleSheet(f"background-color: {Colors.BG_DARKEST};")
        header.setFixedHeight(72)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(16)

        title = QLabel("GERENCIADOR DE PC")
        title.setStyleSheet(f"""
            color: {Colors.TEXT_PRIMARY};
            font-size: {Fonts.SIZE_TITLE}px;
            font-weight: 300;
            letter-spacing: 3px;
        """)
        layout.addWidget(title)

        subtitle = QLabel("STORAGE MANAGER v0.3-dev")
        subtitle.setStyleSheet(f"""
            color: {Colors.ACCENT_CYAN};
            font-size: {Fonts.SIZE_SMALL}px;
            font-weight: 600;
            letter-spacing: 1px;
        """)
        layout.addWidget(subtitle)

        layout.addStretch()

        self.btn_scan = QPushButton("  Iniciar Varredura Completa  ")
        self.btn_scan.setFixedHeight(40)
        self.btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan.clicked.connect(self._on_start_scan)
        layout.addWidget(self.btn_scan)

        return header

    @staticmethod
    def _make_separator() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(
            f"background-color: {Colors.BORDER_SUBTLE}; max-height: 1px;"
        )
        return sep

    # =========================================================================
    # Varredura (FullScanWorker)
    # =========================================================================

    def _on_start_scan(self) -> None:
        """Inicia a varredura completa em background."""
        if self._scan_worker and self._scan_worker.isRunning():
            self.status_bar.showMessage("Varredura ja em andamento...")
            return

        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("  Varrendo...  ")
        self.status_progress.setVisible(True)
        self.status_progress.setValue(0)
        self.status_bar.showMessage("Iniciando varredura completa...")

        self._pulse_state = False
        self._pulse_timer.start()

        self._scan_worker = FullScanWorker(self)
        self._scan_worker.progress.connect(self.status_bar.showMessage)
        self._scan_worker.progress_percent.connect(self.status_progress.setValue)
        self._scan_worker.progress_indeterminate.connect(
            self._set_progress_indeterminate
        )
        # Sprint 7.1: painel de status por disco
        self._scan_worker.partitions_detected.connect(
            self._scan_status_panel.begin_scan
        )
        self._scan_worker.disk_state_changed.connect(
            self._scan_status_panel.update_disk
        )
        self._scan_worker.global_stage_changed.connect(
            self._scan_status_panel.set_global_stage
        )
        self._scan_worker.finished_result.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_scan_finished(self, result: ScanResult) -> None:
        """Chamado quando a varredura termina — delega populate() a cada aba."""
        self._last_result = result

        self._pulse_timer.stop()
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("  Iniciar Varredura Completa  ")
        self.btn_scan.setStyleSheet("")
        # Garantir que a barra volte ao modo determinístico antes de esconder
        self._set_progress_indeterminate(False)
        self.status_progress.setVisible(False)
        # Sprint 7.1: parar cronômetro do painel e agendar ocultação
        self._scan_status_panel.end_scan()
        # Manter painel visível por 4s com sumário, depois ocultar via reset()
        QTimer.singleShot(4000, self._scan_status_panel.reset)

        if result.error:
            self.status_bar.showMessage(f"Erro na varredura: {result.error}")
            return

        self._overview_tab.populate(result)
        self._top_files_tab.populate(result)
        self._top_dirs_tab.populate(result)
        self._duplicates_tab.populate(result)
        self._suggestions_tab.populate(result)
        self._history_tab.refresh(self._db, self._executor)

        self.status_bar.showMessage(
            f"Varredura concluida em {result.elapsed_seconds:.1f}s  |  "
            f"{len(result.partitions)} discos  |  "
            f"{len(result.top_files)} maiores arquivos  |  "
            f"{len(result.top_dirs)} pastas  |  "
            f"{len(result.duplicates)} grupos de duplicatas  |  "
            f"{len(result.suggestions)} sugestoes"
        )
        self._scan_worker = None

    # =========================================================================
    # Execução de ações (FileActionWorker)
    # =========================================================================

    def _run_actions(
        self, actions: list[FileAction], status_msg: str = "Executando..."
    ) -> None:
        """Inicia execução de ações de arquivo em background."""
        if self._action_worker and self._action_worker.isRunning():
            self.status_bar.showMessage("Outra operacao ja em andamento...")
            return

        self.status_progress.setVisible(True)
        self.status_progress.setValue(0)
        self.status_bar.showMessage(status_msg)

        # `self` é o parent (QThread ownership), não o db. Passá-lo como db
        # (2º posicional) era um bug: SafeFileExecutor._persist_record chamaria
        # MainWindow.insert_operation(...) → AttributeError em runtime.
        self._action_worker = FileActionWorker(actions, parent=self)
        self._action_worker.progress.connect(self.status_bar.showMessage)
        self._action_worker.progress_percent.connect(self.status_progress.setValue)
        self._action_worker.finished_all.connect(self._on_actions_finished)
        self._action_worker.start()

    def _on_actions_finished(self, results: list[OperationRecord]) -> None:
        """Chamado quando todas as ações de arquivo terminam."""
        self.status_progress.setVisible(False)
        self._action_worker = None

        success = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)

        msg = f"Operacoes concluidas: {success} OK"
        if failed:
            msg += f", {failed} falhas"
            fail_details = "\n".join(
                f"• {r.source_path}: {r.error}"
                for r in results
                if not r.success
            )
            QMessageBox.warning(
                self,
                "Algumas operacoes falharam",
                f"{failed} operacao(oes) falharam:\n\n{fail_details}",
            )

        self.status_bar.showMessage(msg)
        self._history_tab.refresh(self._db, self._executor)

        # Re-escanear automaticamente após ações bem-sucedidas
        if success > 0:
            QTimer.singleShot(1000, self._on_start_scan)

    # =========================================================================
    # Ações do Histórico
    # =========================================================================

    def _on_undo_last_move(self) -> None:
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

        self._history_tab.refresh(self._db, self._executor)

    def _on_clear_history(self) -> None:
        """Limpa o histórico de operações."""
        self._executor.history.clear()
        if hasattr(self, "_db"):
            self._db.clear_operations()
        self._history_tab.refresh(self._db, self._executor)
        self.status_bar.showMessage("Historico limpo.")

    # =========================================================================
    # Utilitários
    # =========================================================================

    def _show_log_in_status(self, message: str) -> None:
        """
        Slot do QtLogBridge — exibe mensagem do logger na status bar.

        Sprint 7.0: durante varreduras longas (Etapa 3 do DuplicateDetector,
        que é silenciosa por design), os logs intermediários do core
        (ex.: "Etapa 2 concluída: 523 grupos") aparecem aqui em tempo real,
        eliminando a sensação de travamento.

        Não interfere com mensagens explícitas do worker — ambas usam
        showMessage com timeout zero (persistente até a próxima).
        """
        self.status_bar.showMessage(message)

    def _set_progress_indeterminate(self, busy: bool) -> None:
        """
        Alterna a barra de progresso entre modo determinístico e indeterminado.

        Sprint 7.0: durante a Etapa 3 (hash SHA-256 completo de duplicatas),
        que pode levar 10+ minutos sem progresso mensurável, a barra mostra
        animação contínua em vez de ficar parada em 65%.
        """
        if busy:
            # range(0, 0) ativa o modo "busy" do QProgressBar — animação contínua
            self.status_progress.setRange(0, 0)
        else:
            self.status_progress.setRange(0, 100)

    def _pulse_scan_button(self) -> None:
        """Alterna a cor do botão de varredura para efeito de pulso."""
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
