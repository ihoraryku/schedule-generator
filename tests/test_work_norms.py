from __future__ import annotations

import unittest

from schedule_askue.core.work_norms import employee_work_delta
from schedule_askue.db.models import Employee


class WorkNormsTests(unittest.TestCase):
    def test_employee_work_delta_subtracts_vacation_from_target(self) -> None:
        employee = Employee(1, "Петрова", "Петрова", "mixed", rate=1.0)
        days = {
            1: "Р",
            2: "Р",
            3: "О",
            4: "О",
            5: "Д",
        }

        actual, target, deviation = employee_work_delta(
            employee,
            days=days,
            working_days=21,
            month_days=31,
        )

        self.assertEqual(actual, 3)
        self.assertEqual(target, 19)
        self.assertEqual(deviation, -16)

    def test_employee_work_delta_subtracts_used_extra_days_from_target(self) -> None:
        employee = Employee(1, "Арику", "Арику", "mixed", rate=1.0)
        days = {day: ("Д" if day <= 16 else "В") for day in range(1, 32)}

        actual, target, deviation = employee_work_delta(
            employee,
            days=days,
            working_days=21,
            month_days=31,
            used_extra_days_off=5,
        )

        self.assertEqual(actual, 16)
        self.assertEqual(target, 16)
        self.assertEqual(deviation, 0)
