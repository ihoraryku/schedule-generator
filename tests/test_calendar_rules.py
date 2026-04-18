import unittest
from datetime import date

from schedule_askue.core.calendar_rules import is_special_day, special_days_for_month


class CalendarRulesTests(unittest.TestCase):
    def test_martial_law_excludes_weekday_holiday_from_special_days(self) -> None:
        ua_holidays = {date(2026, 1, 1)}
        self.assertFalse(is_special_day(date(2026, 1, 1), martial_law=True, ua_holidays=ua_holidays))
        special_days = special_days_for_month(2026, 1, martial_law=True, ua_holidays=ua_holidays)
        self.assertNotIn(1, special_days)
        self.assertIn(3, special_days)

    def test_non_martial_law_includes_weekday_holiday_in_special_days(self) -> None:
        ua_holidays = {date(2026, 1, 1)}
        self.assertTrue(is_special_day(date(2026, 1, 1), martial_law=False, ua_holidays=ua_holidays))
        special_days = special_days_for_month(2026, 1, martial_law=False, ua_holidays=ua_holidays)
        self.assertIn(1, special_days)


if __name__ == "__main__":
    unittest.main()
