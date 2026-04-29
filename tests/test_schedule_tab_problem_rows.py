from __future__ import annotations

import gc
import shutil
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QListWidgetItem

from schedule_askue.core.calendar_ua import UkrainianCalendar
from schedule_askue.db.repository import Repository
from schedule_askue.ui.schedule_tab import ScheduleTab


class ScheduleTabProblemRowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_collect_assignments_include_all_preserves_hidden_rows(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repo = Repository(Path(temp_dir) / "schedule.db")
            repo.initialize()
            employees = repo.list_employees()
            assignments = {
                int(employee.id): {day: "В" for day in range(1, 31)}
                for employee in employees
                if employee.id is not None
            }
            first_employee_id = int(employees[0].id)
            second_employee_id = int(employees[1].id)
            assignments[first_employee_id][1] = "Р"
            assignments[second_employee_id][1] = "Д"
            repo.save_schedule(2026, 4, assignments)

            tab = ScheduleTab(repo, UkrainianCalendar(martial_law=True))
            tab.current_year = 2026
            tab.current_month = 4
            tab.reload_table()

            item = QListWidgetItem("problem")
            item.setData(
                Qt.ItemDataRole.UserRole,
                {"employee_id": first_employee_id, "day": 1, "severity": "error"},
            )
            tab.problem_panel.clear()
            tab.problem_panel.addItem(item)
            tab._toggle_problem_rows_only(True)

            filtered = tab._collect_assignments_from_table()
            self.assertEqual(set(filtered), {first_employee_id})

            full = tab._collect_assignments_from_table(include_all=True)
            self.assertIn(first_employee_id, full)
            self.assertIn(second_employee_id, full)
            self.assertEqual(full[first_employee_id][1], "Р")
            self.assertEqual(full[second_employee_id][1], "Д")
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_stats_show_used_extra_days_from_current_table(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repo = Repository(Path(temp_dir) / "schedule.db")
            repo.initialize()
            employees = repo.list_employees()
            employee = employees[0]
            self.assertIsNotNone(employee.id)
            employee_id = int(employee.id)

            repo.save_planned_extra_days_off(
                employee_id=employee_id,
                year=2026,
                month=2,
                planned_days=2,
                note="Перевірка статистики",
            )
            assignments = {
                int(emp.id): {day: "Д" for day in range(1, 29)}
                for emp in employees
                if emp.id is not None
            }
            repo.save_schedule(2026, 2, assignments)

            tab = ScheduleTab(repo, UkrainianCalendar(martial_law=True))
            tab.current_year = 2026
            tab.current_month = 2
            tab.reload_table()
            tab.table.item(0, 2).setText("В")
            tab.table.item(0, 3).setText("В")
            tab._refresh_stats()

            self.assertEqual(
                tab.stats_table.horizontalHeaderItem(2).text(), "Викор. дод. вихідних"
            )
            self.assertEqual(tab.stats_table.item(0, 2).text(), "2")
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
