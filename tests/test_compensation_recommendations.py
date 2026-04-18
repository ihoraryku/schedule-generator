from __future__ import annotations

import unittest

from schedule_askue.core.compensation_recommendations import (
    build_compensation_recommendations,
)
from schedule_askue.db.models import (
    Employee,
    PlannedExtraDayOff,
    PlannedWorkdayAdjustment,
)


class CompensationRecommendationTests(unittest.TestCase):
    def test_underwork_recommendation_prefers_current_extra_off_when_balance_exists(
        self,
    ) -> None:
        employees = [Employee(1, "Петрова", "Петрова", "mixed")]
        assignments = {1: {day: "В" for day in range(1, 22)}}
        assignments[1][1] = "Р"
        assignments[1][2] = "Р"

        items = build_compensation_recommendations(
            employees=employees,
            assignments=assignments,
            working_days=21,
            month_days=31,
            extra_off_balances={1: 5},
            planned_extra_days_off={
                1: PlannedExtraDayOff(None, 1, 2026, 5, planned_days=1, note="")
            },
            planned_workday_adjustments={},
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, "underwork")
        self.assertIn("вихідними в цьому місяці", items[0].message)
        self.assertIn("\n", items[0].message)

    def test_overwork_recommendation_mentions_next_month_extra_off_or_balance(
        self,
    ) -> None:
        employees = [Employee(1, "Арику", "Арику", "mixed")]
        assignments = {1: {day: "Р" for day in range(1, 24)}}

        items = build_compensation_recommendations(
            employees=employees,
            assignments=assignments,
            working_days=21,
            month_days=30,
            extra_off_balances={1: 0},
            planned_extra_days_off={},
            planned_workday_adjustments={
                1: PlannedWorkdayAdjustment(
                    None,
                    1,
                    2026,
                    6,
                    adjustment_days=1,
                    source_year=2026,
                    source_month=5,
                )
            },
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, "overwork")
        self.assertIn("вихідних на наступний місяць", items[0].message)
        self.assertIn("в баланс вихідних", items[0].message)
        self.assertIn("\n", items[0].message)

    def test_recommendation_disappears_when_delta_already_compensated(self) -> None:
        employees = [Employee(1, "Петрова", "Петрова", "mixed")]
        assignments = {1: {day: "В" for day in range(1, 22)}}
        assignments[1][1] = "Р"
        assignments[1][2] = "Р"

        items = build_compensation_recommendations(
            employees=employees,
            assignments=assignments,
            working_days=21,
            month_days=31,
            extra_off_balances={1: 20},
            planned_extra_days_off={
                1: PlannedExtraDayOff(None, 1, 2026, 5, planned_days=19, note="")
            },
            planned_workday_adjustments={},
        )

        self.assertEqual(items, [])
