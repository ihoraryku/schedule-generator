from __future__ import annotations

from pathlib import Path

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QScreen
from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget, QVBoxLayout, QWidget

from schedule_askue.core.calendar_ua import UkrainianCalendar
from schedule_askue.db.repository import Repository
from schedule_askue.ui.balance_tab import BalanceTab
from schedule_askue.ui.rules_tab import RulesTab
from schedule_askue.ui.schedule_tab import ScheduleTab
from schedule_askue.ui.settings_tab import SettingsTab
from schedule_askue.ui.staff_tab import StaffTab
from schedule_askue.ui.wishes_tab import WishesTab

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, project_root: Path, repository: Repository) -> None:
        super().__init__()
        self.project_root = project_root
        self.repository = repository
        self._schedule_snapshot: dict[int, dict[int, str]] | None = None
        self._schedule_snapshot_year: int | None = None
        self._schedule_snapshot_month: int | None = None

        self.setWindowTitle("АСКУЕ — Генератор графіків")
        self.resize(1280, 780)
        self.setMinimumSize(800, 600)

        self.settings = self.repository.get_settings()
        self.calendar = UkrainianCalendar(
            martial_law=self.settings.get("martial_law", "1") == "1"
        )

        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self.tabs = QTabWidget(central)
        self.tabs.setDocumentMode(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.wishes_tab = WishesTab(
            self.repository,
            self.calendar,
            self._on_wishes_changed,
            self._on_staff_changed,
        )
        self.rules_tab = RulesTab(self.repository, self._on_rules_changed)
        self.balance_tab = BalanceTab(
            self.repository,
            self._on_balance_changed,
            self._get_schedule_snapshot,
        )
        self.schedule_tab = ScheduleTab(
            self.repository,
            self.calendar,
            self._on_schedule_period_changed,
            self._on_staff_changed,
            self._set_schedule_snapshot,
        )
        self.settings_tab = SettingsTab(self.repository, self._on_settings_saved)
        self.staff_tab = StaffTab(self.repository, self._on_staff_changed)

        self.tabs.addTab(self.schedule_tab, "Графік")
        self.tabs.addTab(self.wishes_tab, "Побажання")
        self.tabs.addTab(self.rules_tab, "Правила")
        self.tabs.addTab(self.balance_tab, "Облік вихідних")
        self.tabs.addTab(self.staff_tab, "Персонал")
        self.tabs.addTab(self.settings_tab, "Налаштування")

        layout.addWidget(self.tabs)
        self.setCentralWidget(central)

        self._on_schedule_period_changed(
            self.schedule_tab.current_year, self.schedule_tab.current_month
        )
        self._adapt_to_screen()

    def resizeEvent(self, event):
        """Динамічна адаптація при зміні розміру вікна."""
        super().resizeEvent(event)
        self._adapt_layout_to_size()

    def closeEvent(self, event):
        """При закритті вікна зберегти всі налаштування таблиць."""
        if hasattr(self, 'balance_tab'):
            self.balance_tab._save_auto_layout()
        if hasattr(self, 'wishes_tab'):
            self.wishes_tab._save_auto_layout()
        if hasattr(self, 'rules_tab'):
            self.rules_tab._save_auto_layout()
        if hasattr(self, 'schedule_tab'):
            self.schedule_tab._save_auto_layout()
        if hasattr(self, 'staff_tab'):
            self.staff_tab._save_auto_layout()
        super().closeEvent(event)

    def _adapt_to_screen(self) -> None:
        screen = self.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        is_compact = available.height() <= 800
        if is_compact:
            self.resize(min(1360, available.width()), min(860, available.height()))

    def _adapt_layout_to_size(self) -> None:
        """Адаптувати layout під поточний розмір вікна."""
        width = self.width()
        height = self.height()
        
        # Визначити категорію екрану
        if width < 1280:
            layout_mode = "compact"
        elif width < 1920:
            layout_mode = "normal"
        else:
            layout_mode = "spacious"
        
        # Зберегти режим для використання в дочірніх компонентах
        self.setProperty("layoutMode", layout_mode)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            "QMainWindow { background: #F4F1EA; }"
            "QWidget { font-size: 13px; color: #24303F; }"
            "QTabWidget::pane { border: 1px solid #D8D5CC; background: #FCFBF8; top: -1px; }"
            "QTabBar::tab { background: #E9E4DA; border: 1px solid #D8D5CC; padding: 6px 12px; margin-right: 4px; border-top-left-radius: 6px; border-top-right-radius: 6px; }"
            "QTabBar::tab:selected { background: #FCFBF8; color: #1A3D5A; font-weight: 600; }"
            "QTabBar::tab:hover:!selected { background: #F1ECE3; }"
            "QPushButton { background: #F8F5EE; border: 1px solid #C9C1B4; border-radius: 4px; padding: 4px 8px; min-height: 22px; }"
            "QPushButton:hover { background: #EFE8DC; }"
            "QPushButton:pressed { background: #E1D7C7; }"
            "QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #FFFFFF; border: 1px solid #CFC8BC; border-radius: 5px; min-height: 28px; padding: 2px 8px; }"
            "QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid #7A9E7E; }"
            "QTableWidget { background: #FFFFFF; alternate-background-color: #FAF8F3; }"
            "QHeaderView::section { font-weight: 600; }"
            "QToolTip { background: #FFFDF7; color: #24303F; border: 1px solid #D8D5CC; padding: 6px; }"
        )

    def _on_schedule_period_changed(self, year: int, month: int) -> None:
        self.wishes_tab.set_period(year, month)
        self.rules_tab.set_period(year, month)
        self.balance_tab.set_period(year, month)

    def _on_settings_saved(self) -> None:
        self.settings = self.repository.get_settings()
        self.calendar = UkrainianCalendar(
            martial_law=self.settings.get("martial_law", "1") == "1"
        )
        self.schedule_tab.update_calendar(self.calendar)
        self.wishes_tab.update_calendar(self.calendar)

    def _on_staff_changed(self) -> None:
        self.schedule_tab.reload_table()
        self.wishes_tab.reload_data()
        self.rules_tab.reload_data()

    def _on_wishes_changed(self) -> None:
        self.schedule_tab.reload_table()

    def _on_rules_changed(self) -> None:
        self.schedule_tab.reload_table()

    def _on_balance_changed(self) -> None:
        self.schedule_tab._refresh_stats()
        self.schedule_tab._run_validation()
        self.balance_tab.reload_data()

    def _set_schedule_snapshot(
        self, year: int, month: int, assignments: dict[int, dict[int, str]] | None
    ) -> None:
        self._schedule_snapshot_year = year
        self._schedule_snapshot_month = month
        self._schedule_snapshot = assignments
        self.balance_tab.reload_data()

    def _get_schedule_snapshot(
        self, year: int, month: int
    ) -> dict[int, dict[int, str]] | None:
        if (
            self._schedule_snapshot_year == year
            and self._schedule_snapshot_month == month
        ):
            return self._schedule_snapshot
        return None
