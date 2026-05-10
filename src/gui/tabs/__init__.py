"""
Pacote src.gui.tabs — sub-widgets de cada aba da MainWindow.

Exportações públicas:
    OverviewTab, TopFilesTab, TopDirsTab, DuplicatesTab,
    SuggestionsTab, HistoryTab
"""

from src.gui.tabs.overview_tab import OverviewTab
from src.gui.tabs.top_files_tab import TopFilesTab
from src.gui.tabs.top_dirs_tab import TopDirsTab
from src.gui.tabs.duplicates_tab import DuplicatesTab
from src.gui.tabs.suggestions_tab import SuggestionsTab
from src.gui.tabs.history_tab import HistoryTab

__all__ = [
    "OverviewTab",
    "TopFilesTab",
    "TopDirsTab",
    "DuplicatesTab",
    "SuggestionsTab",
    "HistoryTab",
]
