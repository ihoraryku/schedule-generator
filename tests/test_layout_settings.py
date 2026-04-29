from __future__ import annotations

import gc
import shutil
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from schedule_askue.core.calendar_ua import UkrainianCalendar
from schedule_askue.db.repository import Repository
from schedule_askue.ui.table_widgets import GridTableWidget
from schedule_askue.ui.wishes_tab import WishesTab


class LayoutSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_repository_normalizes_legacy_auto_width_payload(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repo = Repository(Path(temp_dir) / "schedule.db")
            repo.initialize()
            repo.save_settings(
                {
                    "auto_width_wishesTab_main": '{"0": 160, "1": "33", "bad": "x"}',
                    "auto_width_balance_tab_all": '{"balance": {"0": 120, "1": "1100"}, "plan": {"0": "120"}}',
                }
            )

            widths = repo.get_auto_table_widths("wishesTab", "main")
            self.assertEqual(widths, {0: 160, 1: 33})

            balance_widths = repo.get_auto_table_widths("balance_tab", "all")
            self.assertEqual(balance_widths, {"balance": {0: 120, 1: 1100}, "plan": {0: 120}})
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_grid_table_widget_accepts_legacy_string_width_keys(self) -> None:
        table = GridTableWidget()
        table.setColumnCount(3)

        table.set_column_widths({"0": "25", "1": 40, "bad": 99, "4": 120})

        self.assertEqual(table.columnWidth(0), 25)
        self.assertEqual(table.columnWidth(1), 40)

    def test_wishes_tab_restores_legacy_layout_without_crash(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repo = Repository(Path(temp_dir) / "schedule.db")
            repo.initialize()
            repo.save_settings(
                {"auto_width_wishesTab_main": '{"0": 180, "1": "33", "2": "34"}'}
            )

            tab = WishesTab(repo, UkrainianCalendar(martial_law=True))

            self.assertGreaterEqual(tab.table.columnWidth(0), 20)
            self.assertGreaterEqual(tab.table.columnWidth(1), 20)
            del tab
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
