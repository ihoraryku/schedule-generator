from __future__ import annotations

import unittest

from schedule_askue.core.calendar_ua import UkrainianCalendar
from schedule_askue.core.personal_rule_periods import covered_days_for_personal_rule
from schedule_askue.db.models import PersonalRule


class PersonalRulePeriodTests(unittest.TestCase):
    def test_weekend_rule_keeps_calendar_day_range_in_may_2026(self) -> None:
        month_info = UkrainianCalendar(martial_law=True).get_month_info(2026, 5)
        special_days = {
            day
            for day, info in month_info.items()
            if info.is_weekend or info.is_holiday
        }
        rule = PersonalRule(
            None, 1, 2026, 5, 1, 3, "В", "weekend_allow_ch", priority=50
        )

        covered = covered_days_for_personal_rule(
            rule,
            month_days=len(month_info),
            special_days=special_days,
        )

        self.assertEqual(covered, [1, 2, 3])

    def test_weekend_rule_keeps_calendar_day_range_in_june_2026(self) -> None:
        month_info = UkrainianCalendar(martial_law=True).get_month_info(2026, 6)
        special_days = {
            day
            for day, info in month_info.items()
            if info.is_weekend or info.is_holiday
        }
        rule = PersonalRule(
            None, 1, 2026, 6, 1, 3, "В", "weekend_allow_ch", priority=50
        )

        covered = covered_days_for_personal_rule(
            rule,
            month_days=len(month_info),
            special_days=special_days,
        )

        self.assertEqual(covered, [1, 2, 3])

    def test_regular_personal_rule_keeps_calendar_day_range(self) -> None:
        rule = PersonalRule(None, 1, 2026, 6, 3, 5, "В", "prohibit_ch", priority=50)

        covered = covered_days_for_personal_rule(
            rule,
            month_days=30,
            special_days={6, 7, 13},
        )

        self.assertEqual(covered, [3, 4, 5])
