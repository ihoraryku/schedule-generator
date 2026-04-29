from __future__ import annotations

import gc
import shutil
import tempfile
import unittest
from pathlib import Path

from schedule_askue.core.calendar_ua import UkrainianCalendar
from schedule_askue.core.validator import ScheduleValidator
from schedule_askue.db.models import Employee, PersonalRule
from schedule_askue.db.repository import Repository


class ValidatorRulesTests(unittest.TestCase):
    def test_work_day_norm_ignores_vacation_days_in_target(self) -> None:
        validator = ScheduleValidator()
        employees = [Employee(1, "Петрова О.В.", "Петрова О.В.", "mixed")]
        schedule = {
            1: {
                1: "Р",
                2: "Р",
                3: "Р",
                4: "Р",
                5: "Р",
                6: "О",
                7: "О",
                8: "О",
                9: "О",
                10: "О",
                11: "О",
                12: "О",
                13: "О",
                14: "О",
                15: "О",
                16: "О",
                17: "О",
                18: "О",
                19: "О",
                20: "О",
                21: "О",
            }
        }
        month_info = UkrainianCalendar(martial_law=True).get_month_info(2026, 5)

        errors = validator.validate(
            schedule,
            employees,
            rules=[],
            settings={
                "schedule_year": "2026",
                "schedule_month": "5",
                "work_days_tolerance": "0",
                "daily_shift_d_count": "0",
            },
            month_info=month_info,
        )

        norm_errors = [error for error in errors if error.type == "work_day_norm"]
        self.assertEqual(norm_errors, [])

    def test_isolated_special_day_off_is_not_reported(self) -> None:
        validator = ScheduleValidator()
        employees = [Employee(1, "Тест", "Тест", "mixed")]
        schedule = {1: {1: "Р", 2: "В", 3: "Р"}}

        errors = validator.validate(
            schedule,
            employees,
            rules=[],
            settings={
                "schedule_year": "2026",
                "schedule_month": "4",
                "max_consecutive_work_days": "7",
            },
            month_info={
                1: type(
                    "DayInfo",
                    (),
                    {"is_weekend": False, "is_holiday": False, "is_working_day": True},
                )(),
                2: type(
                    "DayInfo",
                    (),
                    {"is_weekend": True, "is_holiday": False, "is_working_day": False},
                )(),
                3: type(
                    "DayInfo",
                    (),
                    {"is_weekend": False, "is_holiday": False, "is_working_day": True},
                )(),
            },
        )

        isolated = [error for error in errors if error.type == "isolated_day_off"]
        self.assertEqual(isolated, [])

    def test_work_days_tolerance_controls_work_day_norm_warning(self) -> None:
        validator = ScheduleValidator()
        employees = [Employee(1, "Тест", "Тест", "mixed")]
        schedule = {1: {day: ("Р" if day <= 20 else "В") for day in range(1, 31)}}
        month_info = {
            day: type(
                "DayInfo",
                (),
                {
                    "is_weekend": day > 22,
                    "is_holiday": False,
                    "is_working_day": day <= 22,
                },
            )()
            for day in range(1, 31)
        }

        errors_tight = validator.validate(
            schedule,
            employees,
            rules=[],
            settings={
                "schedule_year": "2026",
                "schedule_month": "4",
                "work_days_tolerance": "1",
            },
            month_info=month_info,
        )

        norm_warnings_tight = [
            error for error in errors_tight if error.type == "work_day_norm"
        ]
        self.assertGreater(len(norm_warnings_tight), 0)

        errors_relaxed = validator.validate(
            schedule,
            employees,
            rules=[],
            settings={
                "schedule_year": "2026",
                "schedule_month": "4",
                "work_days_tolerance": "2",
            },
            month_info=month_info,
        )

        norm_warnings_relaxed = [
            error for error in errors_relaxed if error.type == "work_day_norm"
        ]
        self.assertEqual(norm_warnings_relaxed, [])

    def test_used_extra_days_close_work_day_norm_underwork(self) -> None:
        validator = ScheduleValidator()
        employees = [Employee(1, "Арику І.В.", "Арику І.В.", "mixed")]
        schedule = {1: {day: ("Д" if day <= 16 else "В") for day in range(1, 32)}}
        month_info = {
            day: type(
                "DayInfo",
                (),
                {
                    "is_weekend": day > 21,
                    "is_holiday": False,
                    "is_working_day": day <= 21,
                },
            )()
            for day in range(1, 32)
        }

        errors = validator.validate(
            schedule,
            employees,
            rules=[],
            settings={
                "schedule_year": "2026",
                "schedule_month": "5",
                "work_days_tolerance": "0",
            },
            month_info=month_info,
            extra_day_off_usage={1: 5},
        )

        norm_warnings = [error for error in errors if error.type == "work_day_norm"]
        self.assertEqual(norm_warnings, [])

    def test_repository_resets_split_ch_to_mixed(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            repo = Repository(Path(temp_dir) / "schedule.db")
            repo.initialize()
            with repo.connect() as conn:
                conn.execute("DELETE FROM settings WHERE key = 'shift_types_reset_v2'")
                conn.execute(
                    "UPDATE employees SET shift_type = 'split_CH' WHERE short_name IN ('Юхименко А.А.', 'Гайдуков Ю.Б.')"
                )
            repo.initialize()
            employees = {
                employee.short_name: employee.shift_type
                for employee in repo.list_employees(include_archived=True)
            }

            self.assertEqual(employees["Юхименко А.А."], "mixed")
            self.assertEqual(employees["Гайдуков Ю.Б."], "mixed")
            del repo
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_special_day_balance_warning_is_skipped_when_work_is_forced(self) -> None:
        validator = ScheduleValidator()
        employees = [
            Employee(1, "Петрова", "Петрова", "mixed"),
            Employee(2, "Арику", "Арику", "mixed"),
        ]
        schedule = {
            1: {4: "Р", 5: "Р", 11: "Р", 12: "В"},
            2: {4: "В", 5: "В", 11: "В", 12: "В"},
        }
        month_info = {
            4: type(
                "DayInfo",
                (),
                {"is_weekend": True, "is_holiday": False, "is_working_day": False},
            )(),
            5: type(
                "DayInfo",
                (),
                {"is_weekend": True, "is_holiday": False, "is_working_day": False},
            )(),
            11: type(
                "DayInfo",
                (),
                {"is_weekend": True, "is_holiday": False, "is_working_day": False},
            )(),
            12: type(
                "DayInfo",
                (),
                {"is_weekend": True, "is_holiday": False, "is_working_day": False},
            )(),
        }

        from schedule_askue.db.models import Wish

        wishes = [
            Wish(None, 1, 2026, 4, "work_day", 4, 4, "mandatory", comment="Р"),
            Wish(None, 1, 2026, 4, "work_day", 5, 5, "mandatory", comment="Р"),
            Wish(None, 1, 2026, 4, "work_day", 11, 11, "mandatory", comment="Р"),
        ]

        errors = validator.validate(
            schedule,
            employees,
            rules=[],
            settings={"schedule_year": "2026", "schedule_month": "4"},
            month_info=month_info,
            wishes=wishes,
        )

        special_balance = [
            error for error in errors if error.type == "special_day_balance"
        ]
        self.assertEqual(special_balance, [])

    def test_validator_reports_missing_daily_duty_coverage(self) -> None:
        validator = ScheduleValidator()
        employees = [
            Employee(1, "A", "A", "mixed"),
            Employee(2, "B", "B", "mixed"),
        ]
        schedule = {
            1: {1: "Д", 2: "Д"},
            2: {1: "В", 2: "Д"},
        }

        errors = validator.validate(
            schedule,
            employees,
            rules=[],
            settings={
                "daily_shift_d_count": "2",
                "schedule_year": "2026",
                "schedule_month": "4",
            },
            month_info={
                1: type(
                    "DayInfo",
                    (),
                    {"is_weekend": False, "is_holiday": False, "is_working_day": True},
                )(),
                2: type(
                    "DayInfo",
                    (),
                    {"is_weekend": False, "is_holiday": False, "is_working_day": True},
                )(),
            },
        )

        duty_errors = [error for error in errors if error.type == "daily_duty_count"]
        self.assertEqual(len(duty_errors), 1)
        self.assertEqual(duty_errors[0].day, 1)

    def test_validator_treats_weekday_holiday_as_non_special_under_martial_law(
        self,
    ) -> None:
        validator = ScheduleValidator()
        employees = [Employee(1, "Петрова", "Петрова", "mixed")]
        calendar_ua = UkrainianCalendar(martial_law=True)
        month_info = calendar_ua.get_month_info(2026, 1)
        schedule = {1: {1: "В", 2: "В", 3: "Р", 4: "В"}}
        personal_rules = [
            PersonalRule(None, 1, None, None, 1, 14, "Р", "weekend_no_ch", priority=50),
            PersonalRule(
                None, 1, None, None, 1, 3, "Р", "weekend_force_r", priority=100
            ),
        ]

        errors = validator.validate(
            schedule,
            employees,
            rules=[],
            settings={
                "schedule_year": "2026",
                "schedule_month": "1",
                "martial_law": "1",
            },
            month_info=month_info,
            personal_rules=personal_rules,
        )

        day1_errors = [
            error
            for error in errors
            if error.day == 1 and error.type.startswith("personal_rule")
        ]
        day3_errors = [
            error
            for error in errors
            if error.day == 3 and error.type.startswith("personal_rule")
        ]
        self.assertEqual(len(day1_errors), 1)
        self.assertEqual(day1_errors[0].type, "personal_rule_forced_shift")
        self.assertEqual(day3_errors, [])


if __name__ == "__main__":
    unittest.main()
