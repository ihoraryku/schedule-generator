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
