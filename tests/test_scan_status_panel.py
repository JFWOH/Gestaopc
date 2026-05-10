"""
Testes para src.gui.scan_status_panel — Sprint 7.1.

Cobre:
  - _DiskRow: criação, transições de estado, fallback de label,
    rejeição silenciosa de estados inválidos
  - ScanStatusPanel: begin_scan cria linhas, update_disk altera estado,
    set_global_stage mostra/oculta texto, end_scan para timer,
    reset limpa tudo, reentrância (chamadas duplicadas).

Estratégia:
  - QApplication compartilhada via fixture de módulo (necessária para
    QWidget mas não exige event loop rodando)
  - Não dependemos de painting/display — apenas do estado interno
  - Não há disco real envolvido; PartitionInfo é construído manualmente
"""

from __future__ import annotations

import pytest

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from src.core.scanner import PartitionInfo
from src.gui.scan_status_panel import (
    ScanStatusPanel,
    STATE_DONE,
    STATE_ERROR,
    STATE_PENDING,
    STATE_SCANNING,
    VALID_STATES,
    _DiskRow,
    _DEFAULT_LABEL,
    _ICON_BY_STATE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qapp():
    """QApplication compartilhada (QWidget exige QApplication, não QCoreApplication)."""
    app = QApplication.instance() or QApplication([])
    yield app


def _make_partition(letter: str, media: str = "SSD") -> PartitionInfo:
    return PartitionInfo(
        letter=letter,
        fstype="NTFS",
        total_bytes=500 * 1024 ** 3,
        used_bytes=250 * 1024 ** 3,
        free_bytes=250 * 1024 ** 3,
        percent_used=50.0,
        media_type=media,
    )


# ─────────────────────────────────────────────────────────────────────────────
# _DiskRow
# ─────────────────────────────────────────────────────────────────────────────

class TestDiskRow:
    def test_initial_state_is_pending(self, qapp):
        row = _DiskRow("C:", "NVMe")
        assert row.state == STATE_PENDING
        assert row.letter == "C:"

    def test_transition_to_scanning(self, qapp):
        row = _DiskRow("D:", "SSD")
        row.set_state(STATE_SCANNING, "Analisando arquivos…")
        assert row.state == STATE_SCANNING

    def test_transition_to_done(self, qapp):
        row = _DiskRow("E:", "HDD")
        row.set_state(STATE_SCANNING, "trabalhando")
        row.set_state(STATE_DONE)
        assert row.state == STATE_DONE

    def test_transition_to_error(self, qapp):
        row = _DiskRow("F:", "HDD")
        row.set_state(STATE_ERROR)
        assert row.state == STATE_ERROR

    def test_invalid_state_is_silently_ignored(self, qapp):
        row = _DiskRow("G:", "SSD")
        row.set_state(STATE_SCANNING)
        row.set_state("xyzzy")  # estado inválido — não deve crashar
        assert row.state == STATE_SCANNING  # mantém o último válido

    def test_empty_stage_falls_back_to_default_label(self, qapp):
        row = _DiskRow("H:", "SSD")
        row.set_state(STATE_DONE, "")
        # O label padrão para STATE_DONE deve ter sido aplicado
        assert _DEFAULT_LABEL[STATE_DONE] in row._stage_label.text()

    def test_whitespace_only_stage_falls_back_to_default(self, qapp):
        row = _DiskRow("I:", "SSD")
        row.set_state(STATE_SCANNING, "   ")
        assert _DEFAULT_LABEL[STATE_SCANNING] in row._stage_label.text()

    def test_explicit_stage_text_used(self, qapp):
        row = _DiskRow("J:", "HDD")
        row.set_state(STATE_SCANNING, "Hash completo SHA-256")
        assert "Hash completo SHA-256" in row._stage_label.text()

    def test_icon_changes_with_state(self, qapp):
        row = _DiskRow("K:", "SSD")
        assert row._icon.text() == _ICON_BY_STATE[STATE_PENDING]
        row.set_state(STATE_SCANNING)
        assert row._icon.text() == _ICON_BY_STATE[STATE_SCANNING]
        row.set_state(STATE_DONE)
        assert row._icon.text() == _ICON_BY_STATE[STATE_DONE]
        row.set_state(STATE_ERROR)
        assert row._icon.text() == _ICON_BY_STATE[STATE_ERROR]

    def test_media_type_uppercased(self, qapp):
        row = _DiskRow("L:", "ssd")
        assert row._media_label.text() == "SSD"

    def test_empty_media_type_uses_default(self, qapp):
        row = _DiskRow("M:", "")
        # _media_type é normalizado para "Disco" quando vazio
        assert row._media_label.text() == "DISCO"


# ─────────────────────────────────────────────────────────────────────────────
# ScanStatusPanel — begin_scan
# ─────────────────────────────────────────────────────────────────────────────

class TestPanelBeginScan:
    def test_initially_hidden(self, qapp):
        panel = ScanStatusPanel()
        assert not panel.isVisible()
        assert panel._disk_count() == 0

    def test_begin_scan_creates_rows(self, qapp):
        panel = ScanStatusPanel()
        partitions = [
            _make_partition("C:", "NVMe"),
            _make_partition("D:", "SSD"),
            _make_partition("L:", "HDD"),
        ]
        panel.begin_scan(partitions)
        assert panel._disk_count() == 3
        assert panel._disk_state("C:") == STATE_PENDING
        assert panel._disk_state("L:") == STATE_PENDING

    def test_begin_scan_with_empty_list_keeps_hidden(self, qapp):
        panel = ScanStatusPanel()
        panel.begin_scan([])
        # Sem discos, não há razão para mostrar o painel
        assert panel._disk_count() == 0

    def test_begin_scan_replaces_previous_rows(self, qapp):
        panel = ScanStatusPanel()
        panel.begin_scan([_make_partition("C:")])
        assert panel._disk_count() == 1
        panel.begin_scan([
            _make_partition("D:"),
            _make_partition("E:"),
            _make_partition("F:"),
        ])
        assert panel._disk_count() == 3
        assert panel._disk_state("C:") is None  # removido
        assert panel._disk_state("D:") == STATE_PENDING


# ─────────────────────────────────────────────────────────────────────────────
# ScanStatusPanel — update_disk
# ─────────────────────────────────────────────────────────────────────────────

class TestPanelUpdateDisk:
    def test_update_changes_state(self, qapp):
        panel = ScanStatusPanel()
        panel.begin_scan([_make_partition("C:", "NVMe")])

        panel.update_disk("C:", STATE_SCANNING, "Analisando arquivos…")
        assert panel._disk_state("C:") == STATE_SCANNING

        panel.update_disk("C:", STATE_DONE)
        assert panel._disk_state("C:") == STATE_DONE

    def test_update_unknown_disk_is_ignored(self, qapp):
        """Disco que não foi inicializado em begin_scan é silenciosamente ignorado."""
        panel = ScanStatusPanel()
        panel.begin_scan([_make_partition("C:", "NVMe")])
        panel.update_disk("Z:", STATE_SCANNING)  # não deve crashar
        # Estados conhecidos não foram alterados
        assert panel._disk_state("C:") == STATE_PENDING

    def test_update_with_invalid_state_keeps_previous(self, qapp):
        panel = ScanStatusPanel()
        panel.begin_scan([_make_partition("C:", "NVMe")])
        panel.update_disk("C:", STATE_SCANNING)
        panel.update_disk("C:", "garbage_state")
        assert panel._disk_state("C:") == STATE_SCANNING

    def test_full_lifecycle(self, qapp):
        """Disco passa por pending → scanning(files) → scanning(dirs) → done."""
        panel = ScanStatusPanel()
        panel.begin_scan([_make_partition("L:", "HDD")])

        assert panel._disk_state("L:") == STATE_PENDING
        panel.update_disk("L:", STATE_SCANNING, "Analisando arquivos…")
        assert panel._disk_state("L:") == STATE_SCANNING
        panel.update_disk("L:", STATE_SCANNING, "Analisando pastas…")
        assert panel._disk_state("L:") == STATE_SCANNING
        panel.update_disk("L:", STATE_DONE)
        assert panel._disk_state("L:") == STATE_DONE


# ─────────────────────────────────────────────────────────────────────────────
# ScanStatusPanel — global stage
# ─────────────────────────────────────────────────────────────────────────────

class TestPanelGlobalStage:
    def test_global_stage_initially_hidden(self, qapp):
        panel = ScanStatusPanel()
        assert not panel._global_label.isVisible()

    def test_set_global_stage_shows_text(self, qapp):
        panel = ScanStatusPanel()
        panel.begin_scan([_make_partition("C:")])  # mostra o painel
        panel.set_global_stage("Comparando duplicatas…")
        assert panel._global_label.isVisible()
        assert "duplicatas" in panel._global_label.text()

    def test_empty_global_stage_hides_label(self, qapp):
        panel = ScanStatusPanel()
        panel.begin_scan([_make_partition("C:")])
        panel.set_global_stage("Algum estagio")
        panel.set_global_stage("")
        assert not panel._global_label.isVisible()

    def test_whitespace_global_stage_hides_label(self, qapp):
        panel = ScanStatusPanel()
        panel.begin_scan([_make_partition("C:")])
        panel.set_global_stage("Algum")
        panel.set_global_stage("   \t  ")
        assert not panel._global_label.isVisible()


# ─────────────────────────────────────────────────────────────────────────────
# ScanStatusPanel — reset / end_scan
# ─────────────────────────────────────────────────────────────────────────────

class TestPanelLifecycle:
    def test_reset_clears_rows(self, qapp):
        panel = ScanStatusPanel()
        panel.begin_scan([_make_partition("C:"), _make_partition("D:")])
        panel.reset()
        assert panel._disk_count() == 0
        assert not panel.isVisible()

    def test_reset_without_begin_is_safe(self, qapp):
        panel = ScanStatusPanel()
        panel.reset()  # não deve crashar
        assert panel._disk_count() == 0

    def test_end_scan_stops_timer_but_keeps_rows(self, qapp):
        panel = ScanStatusPanel()
        panel.begin_scan([_make_partition("C:")])
        assert panel._timer.isActive()
        panel.end_scan()
        assert not panel._timer.isActive()
        # Rows permanecem visíveis (chamador decide quando ocultar)
        assert panel._disk_count() == 1

    def test_end_scan_without_begin_is_safe(self, qapp):
        panel = ScanStatusPanel()
        panel.end_scan()  # não deve crashar

    def test_reset_after_end_scan(self, qapp):
        panel = ScanStatusPanel()
        panel.begin_scan([_make_partition("C:")])
        panel.end_scan()
        panel.reset()
        assert panel._disk_count() == 0
        assert not panel._timer.isActive()


# ─────────────────────────────────────────────────────────────────────────────
# Constantes e contratos
# ─────────────────────────────────────────────────────────────────────────────

class TestStateConstants:
    def test_all_states_have_icons(self):
        for state in VALID_STATES:
            assert state in _ICON_BY_STATE

    def test_all_states_have_default_labels(self):
        for state in VALID_STATES:
            assert state in _DEFAULT_LABEL
            assert _DEFAULT_LABEL[state]  # não vazio

    def test_valid_states_set(self):
        assert VALID_STATES == {
            STATE_PENDING, STATE_SCANNING, STATE_DONE, STATE_ERROR
        }
