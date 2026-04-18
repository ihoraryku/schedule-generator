from __future__ import annotations

import gc
import shutil
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from schedule_askue.db.repository import Repository
from schedule_askue.ui.staff_tab import StaffTab


class StaffTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_selected_employee_uses_visible_row_employee_id(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repo = Repository(Path(temp_dir) / "schedule.db")
            repo.initialize()
            tab = StaffTab(repo)
            tab.search_input.setText("Юхименко")
            tab.reload_data()

            self.assertEqual(tab.table.rowCount(), 1)
            tab.table.selectRow(0)
            employee = tab._selected_employee()

            self.assertIsNotNone(employee)
            self.assertEqual(employee.short_name, "Юхименко А.А.")
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
