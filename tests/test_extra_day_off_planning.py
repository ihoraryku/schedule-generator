from __future__ import annotations

import gc
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from schedule_askue.db.repository import Repository
from schedule_askue.ui.balance_tab import BalanceTab
from schedule_askue.ui.main_window import MainWindow


class ExtraDayOffPlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_repository_saves_and_reads_month_plan(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            repo = Repository(root / "schedule.db")
            repo.initialize()
            employee = repo.list_employees()[0]
            self.assertIsNotNone(employee.id)

            repo.save_planned_extra_days_off(
                employee_id=int(employee.id),
                year=2026,
                month=5,
                planned_days=2,
                note="Компенсація за чергування",
            )

            planned_map = repo.get_planned_extra_days_off_map(2026, 5)

            self.assertIn(int(employee.id), planned_map)
            self.assertEqual(planned_map[int(employee.id)].planned_days, 2)
            self.assertEqual(
                planned_map[int(employee.id)].note, "Компенсація за чергування"
            )
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_repository_upserts_month_plan_by_employee_and_period(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            repo = Repository(root / "schedule.db")
            repo.initialize()
            employee = repo.list_employees()[0]
            self.assertIsNotNone(employee.id)

            first_id = repo.save_planned_extra_days_off(
                employee_id=int(employee.id),
                year=2026,
                month=6,
                planned_days=1,
                note="Перше значення",
            )
            second_id = repo.save_planned_extra_days_off(
                employee_id=int(employee.id),
                year=2026,
                month=6,
                planned_days=3,
                note="Оновлений план",
            )

            planned = repo.list_planned_extra_days_off(2026, 6)

            self.assertEqual(first_id, second_id)
            self.assertEqual(len(planned), 1)
            self.assertEqual(planned[0].planned_days, 3)
            self.assertEqual(planned[0].note, "Оновлений план")
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_repository_deletes_month_plan(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            repo = Repository(root / "schedule.db")
            repo.initialize()
            employee = repo.list_employees()[0]
            self.assertIsNotNone(employee.id)

            repo.save_planned_extra_days_off(
                employee_id=int(employee.id),
                year=2026,
                month=7,
                planned_days=2,
                note="Тимчасовий план",
            )
            repo.delete_planned_extra_days_off(int(employee.id), 2026, 7)

            planned_map = repo.get_planned_extra_days_off_map(2026, 7)

            self.assertEqual(planned_map, {})
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_repository_saves_and_reads_workday_adjustment_plan(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            repo = Repository(root / "schedule.db")
            repo.initialize()
            employee = repo.list_employees()[0]
            self.assertIsNotNone(employee.id)

            repo.save_planned_workday_adjustment(
                employee_id=int(employee.id),
                year=2026,
                month=6,
                adjustment_days=2,
                source_year=2026,
                source_month=5,
                note="Компенсація недобору",
            )

            adjustment_map = repo.get_planned_workday_adjustments_map(2026, 6)

            self.assertIn(int(employee.id), adjustment_map)
            item = adjustment_map[int(employee.id)]
            self.assertEqual(item.adjustment_days, 2)
            self.assertEqual(item.source_year, 2026)
            self.assertEqual(item.source_month, 5)
            self.assertEqual(item.note, "Компенсація недобору")
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_repository_deletes_workday_adjustment_plan(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            repo = Repository(root / "schedule.db")
            repo.initialize()
            employee = repo.list_employees()[0]
            self.assertIsNotNone(employee.id)

            repo.save_planned_workday_adjustment(
                employee_id=int(employee.id),
                year=2026,
                month=7,
                adjustment_days=1,
                source_year=2026,
                source_month=6,
                note="Тимчасовий перенос",
            )
            repo.delete_planned_workday_adjustment(int(employee.id), 2026, 7)

            adjustment_map = repo.get_planned_workday_adjustments_map(2026, 7)
            self.assertEqual(adjustment_map, {})
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_balance_tab_can_apply_underwork_to_next_month_workdays(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            repo = Repository(root / "schedule.db")
            repo.initialize()
            employees = repo.list_employees()
            employee = employees[0]
            self.assertIsNotNone(employee.id)

            assignments = {
                int(emp.id): {day: "В" for day in range(1, 31)}
                for emp in employees
                if emp.id is not None
            }
            assignments[int(employee.id)][1] = "Р"
            assignments[int(employee.id)][2] = "Р"
            repo.save_schedule(2026, 4, assignments)

            tab = BalanceTab(repo)
            tab.set_period(2026, 4)
            tab.reload_data()
            tab.compensation_table.selectRow(0)
            with patch("schedule_askue.ui.balance_tab.QMessageBox.information"):
                tab._apply_underwork_to_next_month_workdays()

            adjustments = repo.get_planned_workday_adjustments_map(2026, 5)
            self.assertIn(int(employee.id), adjustments)
            self.assertGreater(adjustments[int(employee.id)].adjustment_days, 0)
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_balance_tab_can_apply_overwork_to_balance_credit(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            repo = Repository(root / "schedule.db")
            repo.initialize()
            employees = repo.list_employees()
            employee = employees[0]
            self.assertIsNotNone(employee.id)

            assignments = {
                int(emp.id): {day: "В" for day in range(1, 31)}
                for emp in employees
                if emp.id is not None
            }
            for day in range(1, 26):
                assignments[int(employee.id)][day] = "Р"
            repo.save_schedule(2026, 4, assignments)

            tab = BalanceTab(repo)
            tab.set_period(2026, 4)
            tab.reload_data()
            tab.compensation_table.selectRow(0)
            with patch("schedule_askue.ui.balance_tab.QMessageBox.information"):
                tab._apply_overwork_to_balance_credit()

            ops = repo.list_extra_day_off_operations(2026, 4)
            credit_ops = [
                row
                for row in ops
                if row["action"] == "credit" and int(row["days_count"]) > 0
            ]
            self.assertTrue(credit_ops)
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_balance_tab_shows_compensation_action_journal(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            repo = Repository(root / "schedule.db")
            repo.initialize()
            employees = repo.list_employees()
            employee = employees[0]
            self.assertIsNotNone(employee.id)

            assignments = {
                int(emp.id): {day: "В" for day in range(1, 31)}
                for emp in employees
                if emp.id is not None
            }
            assignments[int(employee.id)][1] = "Р"
            assignments[int(employee.id)][2] = "Р"
            repo.save_schedule(2026, 4, assignments)

            tab = BalanceTab(repo)
            tab.set_period(2026, 4)
            tab.reload_data()
            tab.compensation_table.selectRow(0)
            with patch("schedule_askue.ui.balance_tab.QMessageBox.information"):
                tab._apply_underwork_to_next_month_workdays()
            tab.reload_data()

            self.assertGreater(tab.compensation_actions_table.rowCount(), 0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_balance_tab_can_use_schedule_snapshot(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            repo = Repository(root / "schedule.db")
            repo.initialize()
            window = MainWindow(root, repo)
            employees = repo.list_employees()
            employee = employees[0]
            self.assertIsNotNone(employee.id)

            draft_assignments = {
                int(emp.id): {day: "В" for day in range(1, 31)}
                for emp in employees
                if emp.id is not None
            }
            for day in range(1, 10):
                draft_assignments[int(employee.id)][day] = "Р"

            window._set_schedule_snapshot(2026, 4, draft_assignments)
            window.balance_tab.set_period(2026, 4)
            window.balance_tab.reload_data()

            fact_item = window.balance_tab.compensation_table.item(0, 1)
            self.assertIsNotNone(fact_item)
            self.assertEqual(fact_item.text(), "9")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_balance_tab_shows_partial_status_when_delta_is_partly_compensated(
        self,
    ) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            repo = Repository(root / "schedule.db")
            repo.initialize()
            employees = repo.list_employees()
            employee = employees[0]
            self.assertIsNotNone(employee.id)

            assignments = {
                int(emp.id): {day: "В" for day in range(1, 31)}
                for emp in employees
                if emp.id is not None
            }
            assignments[int(employee.id)][1] = "Р"
            assignments[int(employee.id)][2] = "Р"
            repo.save_schedule(2026, 4, assignments)
            repo.save_planned_workday_adjustment(
                employee_id=int(employee.id),
                year=2026,
                month=4,
                adjustment_days=5,
                source_year=2026,
                source_month=3,
                note="Часткова компенсація",
            )

            tab = BalanceTab(repo)
            tab.set_period(2026, 4)
            tab.reload_data()

            status_item = tab.compensation_table.item(0, 5)
            self.assertIsNotNone(status_item)
            self.assertEqual(status_item.text(), "Частково")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_save_schedule_syncs_auto_planned_usage_idempotently(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            repo = Repository(root / "schedule.db")
            repo.initialize()
            employees = repo.list_employees()
            employee = employees[0]
            self.assertIsNotNone(employee.id)

            repo.create_extra_day_off_operation(
                employee_id=int(employee.id),
                action="credit",
                days_count=5,
                schedule_year=2026,
                schedule_month=2,
                description="Початкове нарахування",
            )
            repo.save_planned_extra_days_off(
                employee_id=int(employee.id),
                year=2026,
                month=2,
                planned_days=3,
                note="Компенсація",
            )

            assignments = {
                int(emp.id): {day: "Д" for day in range(1, 29)}
                for emp in employees
                if emp.id is not None
            }
            assignments[int(employee.id)][2] = "В"
            assignments[int(employee.id)][3] = "В"
            assignments[int(employee.id)][4] = "В"

            repo.save_schedule(2026, 2, assignments)
            repo.save_schedule(2026, 2, assignments)

            usage_totals = repo.get_extra_day_off_usage_totals(2026, 2)
            operations = repo.list_extra_day_off_operations(2026, 2)
            auto_usage_ops = [
                row for row in operations if row["action"] == "auto_planned_usage"
            ]

            self.assertEqual(usage_totals[int(employee.id)], 3)
            self.assertEqual(len(auto_usage_ops), 1)
            self.assertEqual(int(auto_usage_ops[0]["days_count"]), -3)
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_auto_planned_usage_counts_only_working_day_day_offs(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            (root / "config.yaml").write_text(
                "calendar:\n  martial_law: true\n", encoding="utf-8"
            )
            repo = Repository(root / "schedule.db")
            repo.initialize()
            employees = repo.list_employees()
            employee = employees[0]
            self.assertIsNotNone(employee.id)

            repo.create_extra_day_off_operation(
                employee_id=int(employee.id),
                action="credit",
                days_count=4,
                schedule_year=2026,
                schedule_month=2,
                description="Початкове нарахування",
            )
            repo.save_planned_extra_days_off(
                employee_id=int(employee.id),
                year=2026,
                month=2,
                planned_days=2,
                note="Перевірка буднів",
            )

            assignments = {
                int(emp.id): {day: "Д" for day in range(1, 29)}
                for emp in employees
                if emp.id is not None
            }
            assignments[int(employee.id)][1] = (
                "В"  # Неділя, не має рахуватись як додатковий вихідний.
            )
            assignments[int(employee.id)][2] = "В"  # Понеділок, має рахуватись.

            repo.save_schedule(2026, 2, assignments)

            usage_totals = repo.get_extra_day_off_usage_totals(2026, 2)

            self.assertEqual(usage_totals[int(employee.id)], 1)
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
