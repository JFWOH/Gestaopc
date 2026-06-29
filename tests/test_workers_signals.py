"""
Testes para os sinais Qt expostos por src.gui.workers — Sprint 7.0.

Cobre apenas a superfície de sinais (sem rodar varreduras reais):
  - FullScanWorker.progress_indeterminate existe e é Signal(bool)
  - Sinais são definidos como atributos de classe (nível Qt correto)

Não testa o fluxo run() completo porque requer FS real e leva minutos —
isso é validado manualmente na GUI durante a execução do app.
"""

from __future__ import annotations

import pytest

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication  # noqa: E402  (após importorskip)

from src.gui.workers import FullScanWorker  # noqa: E402  (após importorskip)


# Sprint 7.3.1: usamos duck-typing em vez de isinstance(sig, pyqtBoundSignal)
# para que os testes sobrevivam à troca PyQt6→PySide6 (cuja classe equivalente
# é SignalInstance) e a qualquer futuro binding alternativo.
def _is_signal_like(obj) -> bool:
    """True se o objeto tem a interface mínima de um Qt bound signal."""
    return hasattr(obj, "emit") and callable(obj.emit) \
        and hasattr(obj, "connect") and callable(obj.connect)


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


class TestFullScanWorkerSignals:
    def test_progress_indeterminate_exists(self, qapp):
        worker = FullScanWorker()
        assert hasattr(worker, "progress_indeterminate")

    def test_progress_indeterminate_is_bound_signal(self, qapp):
        worker = FullScanWorker()
        assert _is_signal_like(worker.progress_indeterminate)

    def test_progress_indeterminate_carries_bool(self, qapp):
        """Verifica que o sinal aceita um bool e entrega para handler."""
        worker = FullScanWorker()
        received: list[bool] = []
        worker.progress_indeterminate.connect(received.append)

        worker.progress_indeterminate.emit(True)
        worker.progress_indeterminate.emit(False)
        QCoreApplication.processEvents()

        assert received == [True, False]

    def test_existing_signals_still_present(self, qapp):
        """Garantia de não-regressão: sinais legados continuam expostos."""
        worker = FullScanWorker()
        assert hasattr(worker, "progress")
        assert hasattr(worker, "progress_percent")
        assert hasattr(worker, "finished_result")


# ─────────────────────────────────────────────────────────────────────────────
# Sprint 7.1 — sinais do painel de status
# ─────────────────────────────────────────────────────────────────────────────

class TestScanStatusSignals:
    def test_partitions_detected_exists(self, qapp):
        worker = FullScanWorker()
        assert hasattr(worker, "partitions_detected")
        assert _is_signal_like(worker.partitions_detected)

    def test_disk_state_changed_exists(self, qapp):
        worker = FullScanWorker()
        assert hasattr(worker, "disk_state_changed")
        assert _is_signal_like(worker.disk_state_changed)

    def test_global_stage_changed_exists(self, qapp):
        worker = FullScanWorker()
        assert hasattr(worker, "global_stage_changed")
        assert _is_signal_like(worker.global_stage_changed)

    def test_disk_state_changed_carries_three_strings(self, qapp):
        worker = FullScanWorker()
        received: list[tuple[str, str, str]] = []
        worker.disk_state_changed.connect(
            lambda letter, state, text: received.append((letter, state, text))
        )
        worker.disk_state_changed.emit("C:", "scanning", "Analisando…")
        worker.disk_state_changed.emit("D:", "done", "")
        QCoreApplication.processEvents()
        assert received == [
            ("C:", "scanning", "Analisando…"),
            ("D:", "done", ""),
        ]

    def test_partitions_detected_carries_list(self, qapp):
        worker = FullScanWorker()
        received: list = []
        worker.partitions_detected.connect(received.append)
        worker.partitions_detected.emit(["fake_partition_object"])
        QCoreApplication.processEvents()
        assert received == [["fake_partition_object"]]

    def test_global_stage_changed_carries_string(self, qapp):
        worker = FullScanWorker()
        received: list[str] = []
        worker.global_stage_changed.connect(received.append)
        worker.global_stage_changed.emit("Mapeando particoes...")
        worker.global_stage_changed.emit("")
        QCoreApplication.processEvents()
        assert received == ["Mapeando particoes...", ""]
