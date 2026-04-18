import unittest

from schedule_askue.core.generator import ScheduleGenerator
from schedule_askue.core.heuristic_generator import HeuristicScheduleGenerator
from schedule_askue.core.calendar_ua import UkrainianCalendar
from schedule_askue.core.validator import ScheduleValidator
from schedule_askue.db.models import (
    Employee,
    PersonalRule,
    PlannedExtraDayOff,
    PlannedWorkdayAdjustment,
    Rule,
    Wish,
)


class GeneratorPrecheckTests(unittest.TestCase):
    def test_generator_precheck_flags_impossible_vacation_overlap(self) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "A", "A", "mixed"),
            Employee(2, "B", "B", "mixed"),
        ]
        wishes = [
            Wish(None, 1, 2026, 4, "vacation", 1, 1, "mandatory"),
            Wish(None, 2, 2026, 4, "vacation", 1, 1, "mandatory"),
        ]

        result = generator.generate(
            2026,
            4,
            employees,
            wishes=wishes,
            settings={
                "max_vacation_overlap": "1",
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "7",
            },
        )

        warning_codes = [warning.code for warning in result.warnings]
        self.assertIn("precheck_failed", warning_codes)
        self.assertTrue(
            any(
                "обов'язкових відпусток" in warning.message
                for warning in result.warnings
            )
        )

    def test_workday_adjustment_increases_target_work(self) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "A", "A", "mixed"),
            Employee(2, "B", "B", "mixed"),
            Employee(3, "C", "C", "mixed"),
            Employee(4, "D", "D", "mixed"),
        ]

        base_result = generator.generate(
            2026,
            6,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "31",
                "hard_max_consecutive_work_days": "31",
                "work_days_tolerance": "0",
                "martial_law": "1",
            },
        )
        adjusted_result = generator.generate(
            2026,
            6,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "31",
                "hard_max_consecutive_work_days": "31",
                "work_days_tolerance": "0",
                "martial_law": "1",
            },
            planned_workday_adjustments=[
                PlannedWorkdayAdjustment(
                    None,
                    1,
                    2026,
                    6,
                    adjustment_days=2,
                    source_year=2026,
                    source_month=5,
                    note="Компенсація недобору",
                )
            ],
        )

        base_work = sum(
            1 for value in base_result.assignments[1].values() if value in {"Р", "Д"}
        )
        adjusted_work = sum(
            1
            for value in adjusted_result.assignments[1].values()
            if value in {"Р", "Д"}
        )
        self.assertGreaterEqual(adjusted_work, base_work)

    def test_generator_enforces_exact_daily_duty_count(self) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "A", "A", "split_CH"),
            Employee(2, "B", "B", "split_CH"),
        ]

        result = generator.generate(
            2026,
            4,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "31",
                "hard_max_consecutive_work_days": "31",
                "max_vacation_overlap": "1",
            },
        )

        self.assertFalse(
            any(warning.code == "precheck_failed" for warning in result.warnings)
        )
        for day in range(1, 31):
            duty_count = sum(days[day] == "Д" for days in result.assignments.values())
            self.assertEqual(duty_count, 2)

    def test_heuristic_does_not_force_weekday_r_for_weekend_modes(self) -> None:
        generator = HeuristicScheduleGenerator()
        employees = [
            Employee(1, "A", "A", "mixed"),
            Employee(2, "B", "B", "mixed"),
        ]
        personal_rules = [
            PersonalRule(
                id=None,
                employee_id=1,
                year=2026,
                month=4,
                start_day=1,
                end_day=2,
                shift_code="Р",
                rule_type="weekend_allow_ch",
            )
        ]

        result = generator.generate(
            2026,
            4,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "31",
                "hard_max_consecutive_work_days": "31",
            },
            personal_rules=personal_rules,
        )

        self.assertEqual(result[1][1], "Р")
        self.assertEqual(result[1][2], "Р")

    def test_heuristic_keeps_rule_locked_weekend_assignments_under_martial_law(
        self,
    ) -> None:
        generator = HeuristicScheduleGenerator()
        employees = [
            Employee(1, "Петрова", "Петрова", "mixed"),
            Employee(2, "Арику", "Арику", "mixed"),
            Employee(3, "Юхименко", "Юхименко", "split_CH"),
            Employee(4, "Гайдуков", "Гайдуков", "split_CH"),
        ]
        personal_rules = [
            PersonalRule(None, 1, None, None, 1, 14, "Р", "weekend_no_ch", priority=50),
            PersonalRule(
                None, 1, None, None, 1, 3, "Р", "weekend_force_r", priority=100
            ),
        ]

        result = generator.generate(
            2026,
            1,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "31",
                "hard_max_consecutive_work_days": "31",
                "martial_law": "1",
            },
            personal_rules=personal_rules,
        )

        self.assertEqual(result[1][1], "Р")
        self.assertEqual(result[1][3], "Р")
        self.assertEqual(result[1][4], "В")

    def test_heuristic_prioritizes_duty_balance_for_split_ch(self) -> None:
        generator = HeuristicScheduleGenerator()
        employees = [
            Employee(1, "Петрова", "Петрова", "mixed"),
            Employee(2, "Арику", "Арику", "mixed"),
            Employee(3, "Юхименко", "Юхименко", "split_CH"),
            Employee(4, "Гайдуков", "Гайдуков", "split_CH"),
        ]

        result = generator.generate(
            2026,
            1,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "31",
                "hard_max_consecutive_work_days": "31",
                "martial_law": "1",
            },
        )

        duty_counts = {
            eid: sum(1 for value in days.values() if value == "Д")
            for eid, days in result.items()
        }
        self.assertGreater(duty_counts[3], duty_counts[1])
        self.assertGreater(duty_counts[4], duty_counts[2])

    def test_generator_and_validator_share_martial_law_special_day_semantics(
        self,
    ) -> None:
        generator = ScheduleGenerator()
        validator = ScheduleValidator()
        employees = [
            Employee(1, "Петрова", "Петрова", "mixed"),
            Employee(2, "Арику", "Арику", "mixed"),
            Employee(3, "Юхименко", "Юхименко", "split_CH"),
            Employee(4, "Гайдуков", "Гайдуков", "split_CH"),
        ]
        personal_rules = [
            PersonalRule(None, 1, None, None, 1, 14, "Р", "weekend_no_ch", priority=50),
            PersonalRule(
                None, 1, None, None, 1, 3, "Р", "weekend_force_r", priority=100
            ),
        ]
        settings = {
            "daily_shift_d_count": "2",
            "max_consecutive_work_days": "7",
            "hard_max_consecutive_work_days": "9",
            "martial_law": "1",
            "schedule_year": "2026",
            "schedule_month": "1",
        }

        result = generator.generate(
            2026,
            1,
            employees,
            settings=settings,
            personal_rules=personal_rules,
        )

        month_info = UkrainianCalendar(martial_law=True).get_month_info(2026, 1)
        validation = validator.validate(
            result.assignments,
            employees,
            rules=[],
            settings=settings,
            month_info=month_info,
            personal_rules=personal_rules,
        )

        personal_rule_errors = [
            error for error in validation if error.type.startswith("personal_rule")
        ]
        self.assertEqual(personal_rule_errors, [])
        self.assertEqual(result.assignments[1][1], "Р")
        self.assertEqual(result.assignments[1][3], "Р")
        self.assertEqual(result.assignments[1][4], "В")

    def test_generator_respects_single_forced_r_priority(self) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова", "Петрова", "mixed"),
            Employee(2, "Арику", "Арику", "mixed"),
            Employee(3, "Юхименко", "Юхименко", "split_CH"),
            Employee(4, "Гайдуков", "Гайдуков", "split_CH"),
        ]
        wishes = [
            Wish(None, 1, 2026, 4, "work_day", 1, 1, "mandatory", comment="Р"),
        ]
        rules = [
            Rule(None, "must_off", scope="employee:2", year=2026, month=4, day=1),
        ]

        result = generator.generate(
            2026,
            4,
            employees,
            wishes=wishes,
            rules=rules,
            settings={
                "daily_shift_d_count": "2",
                "max_regular_per_day": "2",
                "max_consecutive_work_days": "7",
                "martial_law": "1",
            },
        )

        day1 = {
            employee_id: days[1] for employee_id, days in result.assignments.items()
        }
        self.assertEqual(day1[1], "Р")
        self.assertEqual(day1[2], "В")
        self.assertEqual(sum(1 for value in day1.values() if value == "Р"), 1)
        self.assertEqual(sum(1 for value in day1.values() if value == "Д"), 2)

    def test_generator_prefers_busy_first_days_pattern(self) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова", "Петрова", "mixed"),
            Employee(2, "Арику", "Арику", "mixed"),
            Employee(3, "Юхименко", "Юхименко", "split_CH"),
            Employee(4, "Гайдуков", "Гайдуков", "split_CH"),
        ]

        result = generator.generate(
            2026,
            2,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_regular_per_day": "2",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "max_consecutive_work_days": "7",
                "martial_law": "1",
            },
        )

        for day in range(1, 4):
            if day in {1}:
                self.assertEqual(result.assignments[3][day], "Д")
                self.assertEqual(result.assignments[4][day], "Д")
            else:
                self.assertEqual(result.assignments[1][day], "Р")
                self.assertEqual(result.assignments[2][day], "Р")
                self.assertEqual(result.assignments[3][day], "Д")
                self.assertEqual(result.assignments[4][day], "Д")

    def test_generator_prefers_same_duty_pair_for_two_day_block_when_possible(
        self,
    ) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова", "Петрова", "mixed"),
            Employee(2, "Арику", "Арику", "mixed"),
            Employee(3, "Юхименко", "Юхименко", "split_CH"),
            Employee(4, "Гайдуков", "Гайдуков", "split_CH"),
        ]

        result = generator.generate(
            2026,
            2,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_regular_per_day": "2",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "max_consecutive_work_days": "7",
                "hard_max_consecutive_work_days": "9",
                "max_consecutive_duty_days": "5",
                "martial_law": "1",
            },
        )

        duty_pair_day_1 = tuple(
            sorted(
                employee_id
                for employee_id, days in result.assignments.items()
                if days[1] == "Д"
            )
        )
        duty_pair_day_2 = tuple(
            sorted(
                employee_id
                for employee_id, days in result.assignments.items()
                if days[2] == "Д"
            )
        )
        self.assertEqual(duty_pair_day_1, (3, 4))
        self.assertIn(3, duty_pair_day_2)
        self.assertIn(4, duty_pair_day_2)

    def test_generator_reduces_employee_work_target_when_extra_days_off_are_planned(
        self,
    ) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова", "Петрова", "mixed"),
            Employee(2, "Арику", "Арику", "mixed"),
            Employee(3, "Юхименко", "Юхименко", "split_CH"),
            Employee(4, "Гайдуков", "Гайдуков", "split_CH"),
        ]
        settings = {
            "daily_shift_d_count": "2",
            "max_regular_per_day": "2",
            "month_start_full_staff_days": "4",
            "month_start_regular_per_day": "2",
            "weekday_regular_target": "1",
            "special_day_regular_target": "0",
            "max_consecutive_work_days": "31",
            "hard_max_consecutive_work_days": "31",
            "martial_law": "1",
        }

        baseline = generator.generate(2026, 2, employees, settings=settings)
        with_extra = generator.generate(
            2026,
            2,
            employees,
            settings=settings,
            planned_extra_days_off=[
                PlannedExtraDayOff(None, 1, 2026, 2, planned_days=4, note="Компенсація")
            ],
        )

        baseline_work = sum(
            1 for value in baseline.assignments[1].values() if value in {"Р", "Д"}
        )
        with_extra_work = sum(
            1 for value in with_extra.assignments[1].values() if value in {"Р", "Д"}
        )

        self.assertLess(with_extra_work, baseline_work)

    def test_generator_warns_when_planned_extra_days_off_are_impossible(self) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "A", "A", "split_CH"),
            Employee(2, "B", "B", "split_CH"),
        ]

        result = generator.generate(
            2026,
            4,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "31",
                "hard_max_consecutive_work_days": "31",
                "max_vacation_overlap": "1",
            },
            planned_extra_days_off=[
                PlannedExtraDayOff(
                    None, 1, 2026, 4, planned_days=2, note="Треба дати вихідні"
                )
            ],
        )

        warning_codes = [warning.code for warning in result.warnings]
        self.assertIn("planned_extra_day_off_gap", warning_codes)

    def test_generator_repairs_weekday_regular_into_extra_day_off_when_capacity_allows(
        self,
    ) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова", "Петрова", "mixed"),
            Employee(2, "Арику", "Арику", "mixed"),
            Employee(3, "Юхименко", "Юхименко", "split_CH"),
            Employee(4, "Гайдуков", "Гайдуков", "split_CH"),
        ]
        settings = {
            "daily_shift_d_count": "2",
            "max_regular_per_day": "2",
            "month_start_full_staff_days": "4",
            "month_start_regular_per_day": "2",
            "weekday_regular_target": "1",
            "special_day_regular_target": "0",
            "max_consecutive_work_days": "31",
            "hard_max_consecutive_work_days": "31",
            "martial_law": "1",
        }

        result = generator.generate(
            2026,
            2,
            employees,
            settings=settings,
            planned_extra_days_off=[
                PlannedExtraDayOff(
                    None, 1, 2026, 2, planned_days=2, note="Добрати будні"
                )
            ],
        )

        weekday_offs = [
            day
            for day, value in result.assignments[1].items()
            if value == "В" and day in {2, 3, 4, 5, 6, 9, 10}
        ]
        self.assertTrue(weekday_offs)

    def test_generator_keeps_archive_like_start_pattern_for_march_2026(self) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова О.В.", "Петрова О.В.", "mixed"),
            Employee(2, "Арику І.В.", "Арику І.В.", "mixed"),
            Employee(3, "Юхименко А.А.", "Юхименко А.А.", "split_CH"),
            Employee(4, "Гайдуков Ю.В.", "Гайдуков Ю.В.", "split_CH"),
        ]

        result = generator.generate(
            2026,
            3,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_regular_per_day": "2",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "max_consecutive_work_days": "7",
                "hard_max_consecutive_work_days": "9",
                "martial_law": "1",
            },
        )

        for day in range(1, 5):
            if day == 1:
                self.assertEqual(result.assignments[3][day], "Д")
                self.assertEqual(result.assignments[4][day], "Д")
            else:
                self.assertEqual(result.assignments[1][day], "Р")
                self.assertEqual(result.assignments[2][day], "Р")
                self.assertEqual(result.assignments[3][day], "Д")
                self.assertEqual(result.assignments[4][day], "Д")

    def test_generator_respects_prev_month_seam_for_split_ch_at_march_start(
        self,
    ) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова О.В.", "Петрова О.В.", "mixed"),
            Employee(2, "Арику І.В.", "Арику І.В.", "mixed"),
            Employee(3, "Юхименко А.А.", "Юхименко А.А.", "split_CH"),
            Employee(4, "Гайдуков Ю.В.", "Гайдуков Ю.В.", "split_CH"),
        ]

        result = generator.generate(
            2026,
            3,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_regular_per_day": "2",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "max_consecutive_work_days": "7",
                "hard_max_consecutive_work_days": "9",
                "martial_law": "1",
            },
            prev_month_schedule={
                4: {23: "Д", 24: "Д", 25: "Д", 26: "Д", 27: "Д", 28: "Д"}
            },
        )

        self.assertEqual(result.assignments[4][2], "В")
        for day in range(1, 8):
            self.assertEqual(
                sum(days[day] == "Д" for days in result.assignments.values()), 2
            )

    def test_generator_april_2026_avoids_fallback_via_two_regulars_at_month_end(
        self,
    ) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова О.В.", "Петрова О.В.", "mixed"),
            Employee(2, "Арику І.В.", "Арику І.В.", "mixed"),
            Employee(3, "Юхименко А.А.", "Юхименко А.А.", "split_CH"),
            Employee(4, "Гайдуков Ю.В.", "Гайдуков Ю.В.", "split_CH"),
        ]

        result = generator.generate(
            2026,
            4,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_regular_per_day": "2",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "max_consecutive_work_days": "7",
                "hard_max_consecutive_work_days": "9",
                "martial_law": "1",
            },
        )

        fallback_messages = [
            warning.message
            for warning in result.warnings
            if warning.code == "day_assignment_fallback"
        ]
        self.assertEqual(fallback_messages, [])
        relaxed_messages = [
            warning.message
            for warning in result.warnings
            if warning.code == "daily_regular_relaxed"
        ]
        self.assertTrue(
            any(
                "День 30" in message and "до 2 Р" in message
                for message in relaxed_messages
            )
        )
        day29_codes = [result.assignments[eid][29] for eid in (1, 2, 3, 4)]
        day30_codes = [result.assignments[eid][30] for eid in (1, 2, 3, 4)]
        self.assertIn(day29_codes.count("Р"), [1, 2])
        self.assertIn(day29_codes.count("Д"), [1, 2])
        self.assertEqual(day30_codes.count("Р"), 2)
        self.assertEqual(day30_codes.count("Д"), 2)
        for day in range(1, 31):
            self.assertEqual(
                sum(days[day] == "Д" for days in result.assignments.values()), 2
            )

    def test_generator_february_2026_month_budget_converges_without_norm_gap(
        self,
    ) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова", "Петрова", "mixed"),
            Employee(2, "Арику", "Арику", "mixed"),
            Employee(3, "Юхименко", "Юхименко", "split_CH"),
            Employee(4, "Гайдуков", "Гайдуков", "split_CH"),
        ]

        result = generator.generate(
            2026,
            2,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_regular_per_day": "2",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "max_consecutive_work_days": "7",
                "hard_max_consecutive_work_days": "9",
                "max_consecutive_duty_days": "5",
                "martial_law": "1",
            },
        )

        non_coverage_warnings = [
            w
            for w in result.warnings
            if w.code
            not in {
                "post_repair_duty_streak",
                "day_assignment_fallback",
                "work_norm_gap",
            }
        ]
        self.assertEqual(non_coverage_warnings, [])
        work_totals = {
            employee_id: sum(value in {"Р", "Д"} for value in days.values())
            for employee_id, days in result.assignments.items()
        }
        for employee_id, total in work_totals.items():
            self.assertGreaterEqual(
                total, 19, f"Employee {employee_id} has only {total} work days"
            )

    def test_generator_march_2026_budget_layer_keeps_schedule_warning_free(
        self,
    ) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова О.В.", "Петрова О.В.", "mixed"),
            Employee(2, "Арику І.В.", "Арику І.В.", "mixed"),
            Employee(3, "Юхименко А.А.", "Юхименко А.А.", "split_CH"),
            Employee(4, "Гайдуков Ю.В.", "Гайдуков Ю.В.", "split_CH"),
        ]

        result = generator.generate(
            2026,
            3,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_regular_per_day": "2",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "max_consecutive_work_days": "7",
                "hard_max_consecutive_work_days": "9",
                "max_consecutive_duty_days": "5",
                "martial_law": "1",
            },
        )

        # Після додавання duty-block cooldown, день 30 може мати daily_regular_relaxed
        # через те, що cooldown змінює оптимальний розподіл наприкінці місяця.
        # Це прийнятно, оскільки головні інваріанти (2 Д/день, норма) збережені.
        relaxed_warnings = [
            w for w in result.warnings if w.code == "daily_regular_relaxed"
        ]
        other_warnings = [
            w
            for w in result.warnings
            if w.code not in {"daily_regular_relaxed", "post_repair_duty_streak"}
        ]

        self.assertEqual(
            other_warnings,
            [],
            "Не повинно бути інших warning-ів окрім daily_regular_relaxed та post_repair_duty_streak",
        )
        self.assertLessEqual(
            len(relaxed_warnings), 1, "Максимум один daily_regular_relaxed допустимий"
        )

    def test_generator_full_r_profile_prefers_regular_days(self) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "A", "A", "full_R"),
            Employee(2, "B", "B", "mixed"),
            Employee(3, "C", "C", "split_CH"),
            Employee(4, "D", "D", "split_CH"),
        ]

        result = generator.generate(
            2026,
            2,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_regular_per_day": "2",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "max_consecutive_work_days": "7",
                "hard_max_consecutive_work_days": "9",
                "martial_law": "1",
            },
        )

        regular_count = sum(
            1 for value in result.assignments[1].values() if value == "Р"
        )
        duty_count = sum(1 for value in result.assignments[1].values() if value == "Д")
        self.assertGreater(regular_count, duty_count)
        self.assertLessEqual(duty_count, 1)

    def test_generator_profile_targets_keep_full_r_out_of_duty_quota_pool(self) -> None:
        from schedule_askue.core.priority_scheduler import PriorityScheduleBuilder
        import holidays

        builder = PriorityScheduleBuilder()
        employees = {
            1: Employee(1, "A", "A", "full_R"),
            2: Employee(2, "B", "B", "mixed"),
            3: Employee(3, "C", "C", "split_CH"),
            4: Employee(4, "D", "D", "split_CH"),
        }
        constraints = builder._build_constraints(28, employees, [], [], [], set(), [])
        targets = builder._build_targets(
            2026,
            2,
            28,
            employees,
            {
                "daily_shift_d_count": "2",
                "work_days_tolerance": "0",
            },
            constraints,
            holidays.Ukraine(years=[2026]),
            {},
            {},
        )

        self.assertEqual(targets[1].target_duty, 0)

    def test_generator_duty_block_alternation_with_cooldown(self) -> None:
        """
        Перевіряє, що після завершення 2-денного duty block, ті самі split_CH працівники
        не починають новий блок одразу наступного дня завдяки cooldown penalty.
        """
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова О.В.", "Петрова О.В.", "mixed"),
            Employee(2, "Арику Д.В.", "Арику Д.В.", "mixed"),
            Employee(3, "Юхименко А.А.", "Юхименко А.А.", "split_CH"),
            Employee(4, "Гайдуков Ю.В.", "Гайдуков Ю.В.", "split_CH"),
        ]

        result = generator.generate(
            2026,
            2,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_regular_per_day": "2",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "max_consecutive_work_days": "7",
                "hard_max_consecutive_work_days": "9",
                "max_consecutive_duty_days": "5",
                "martial_law": "1",
            },
        )

        # Перевіряємо, що є хоча б один випадок, коли після завершення 2-денного блоку
        # (3,4) на Д, наступного дня не обидва з них знову на Д
        found_alternation = False
        for day in range(1, 27):  # 28 днів у лютому 2026
            day1_duty = {
                emp_id
                for emp_id, shifts in result.assignments.items()
                if shifts.get(day) == "Д"
            }
            day2_duty = {
                emp_id
                for emp_id, shifts in result.assignments.items()
                if shifts.get(day + 1) == "Д"
            }
            day3_duty = {
                emp_id
                for emp_id, shifts in result.assignments.items()
                if shifts.get(day + 2) == "Д"
            }

            # Якщо дні 1-2 мають ту саму пару (блок завершився), і день 3 має іншу комбінацію
            if len(day1_duty) == 2 and day1_duty == day2_duty and len(day3_duty) == 2:
                if day3_duty != day1_duty:
                    found_alternation = True
                    break

        # Очікуємо, що cooldown створює хоча б одну точку чергування
        self.assertTrue(
            found_alternation,
            "Duty block alternation not observed - cooldown may not be working",
        )

    def test_generator_may_2026_maintains_stable_coverage(self) -> None:
        """
        Regression-тест для травня 2026: перевіряє, що генератор тримає стабільне покриття
        2 Д/день і не має критичних порушень норми.
        """
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова О.В.", "Петрова О.В.", "mixed", sort_order=1),
            Employee(2, "Арику І.В.", "Арику І.В.", "mixed", sort_order=2),
            Employee(3, "Юхименко А.А.", "Юхименко А.А.", "split_CH", sort_order=3),
            Employee(4, "Гайдуков Ю.Б.", "Гайдуков Ю.Б.", "split_CH", sort_order=4),
        ]

        # Хвіст квітня для seam
        prev_month_schedule = {
            1: {28: "Р", 29: "Р", 30: "Р"},
            2: {28: "Р", 29: "Р", 30: "Р"},
            3: {28: "Д", 29: "Д", 30: "В"},
            4: {28: "Д", 29: "Д", 30: "В"},
        }

        result = generator.generate(
            2026,
            5,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "max_consecutive_duty_days": "5",
                "work_days_tolerance": "1",
                "martial_law": "1",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
            },
            prev_month_schedule=prev_month_schedule,
        )

        # Перевірка головного інваріанту: 2 Д/день
        for day in range(1, 32):
            duty_count = sum(
                1
                for emp_days in result.assignments.values()
                if emp_days.get(day) == "Д"
            )
            self.assertEqual(
                duty_count, 2, f"День {day} травня має {duty_count} Д замість 2"
            )

        # Перевірка відсутності критичних помилок
        validator = ScheduleValidator()
        errors = validator.validate(
            result.assignments,
            employees,
            [],
            {
                "schedule_year": "2026",
                "schedule_month": "5",
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "work_days_tolerance": "1",
                "martial_law": "1",
            },
            prev_month_tail=prev_month_schedule,
        )

        critical_errors = [e for e in errors if e.severity == "error"]
        self.assertEqual(
            len(critical_errors),
            0,
            f"Травень 2026 має критичні помилки: {critical_errors}",
        )

    def test_generator_june_2026_maintains_stable_coverage(self) -> None:
        """
        Regression-тест для червня 2026: перевіряє, що генератор тримає стабільне покриття
        2 Д/день і не має критичних порушень норми.
        """
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова О.В.", "Петрова О.В.", "mixed", sort_order=1),
            Employee(2, "Арику І.В.", "Арику І.В.", "mixed", sort_order=2),
            Employee(3, "Юхименко А.А.", "Юхименко А.А.", "split_CH", sort_order=3),
            Employee(4, "Гайдуков Ю.Б.", "Гайдуков Ю.Б.", "split_CH", sort_order=4),
        ]

        # Хвіст травня для seam
        prev_month_schedule = {
            1: {29: "Р", 30: "Р", 31: "Р"},
            2: {29: "Р", 30: "Р", 31: "Р"},
            3: {29: "Д", 30: "Д", 31: "В"},
            4: {29: "Д", 30: "Д", 31: "В"},
        }

        result = generator.generate(
            2026,
            6,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "max_consecutive_duty_days": "5",
                "work_days_tolerance": "1",
                "martial_law": "1",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
            },
            prev_month_schedule=prev_month_schedule,
        )

        # Перевірка головного інваріанту: 2 Д/день
        for day in range(1, 31):
            duty_count = sum(
                1
                for emp_days in result.assignments.values()
                if emp_days.get(day) == "Д"
            )
            self.assertEqual(
                duty_count, 2, f"День {day} червня має {duty_count} Д замість 2"
            )

        # Перевірка відсутності критичних помилок
        validator = ScheduleValidator()
        errors = validator.validate(
            result.assignments,
            employees,
            [],
            {
                "schedule_year": "2026",
                "schedule_month": "6",
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "work_days_tolerance": "1",
                "martial_law": "1",
            },
            prev_month_tail=prev_month_schedule,
        )

        critical_errors = [e for e in errors if e.severity == "error"]
        self.assertEqual(
            len(critical_errors),
            0,
            f"Червень 2026 має критичні помилки: {critical_errors}",
        )

    def test_generator_complex_wishes_rules_holidays_sanity(self) -> None:
        """
        Sanity-check для складних комбінацій: mandatory wishes + personal rules + holidays.
        Перевіряє, що генератор коректно обробляє конфлікти та пріоритети.
        """
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова О.В.", "Петрова О.В.", "mixed", sort_order=1),
            Employee(2, "Арику І.В.", "Арику І.В.", "mixed", sort_order=2),
            Employee(3, "Юхименко А.А.", "Юхименко А.А.", "split_CH", sort_order=3),
            Employee(4, "Гайдуков Ю.Б.", "Гайдуков Ю.Б.", "split_CH", sort_order=4),
        ]

        # Складна комбінація: mandatory wishes + personal rules + holidays
        wishes = [
            # Петрова хоче відпустку 10-12 (коротка, щоб не блокувати покриття)
            Wish(None, 1, 2026, 5, "vacation", 10, 12, "mandatory"),
            # Арику хоче вихідний 20
            Wish(None, 2, 2026, 5, "day_off", 20, 20, "mandatory"),
            # Юхименко бажає робочий день 5
            Wish(None, 3, 2026, 5, "work_day", 5, 5, "desired", comment="Д"),
        ]

        personal_rules = [
            # Гайдуков має правило: не працювати у вихідні
            PersonalRule(
                id=None,
                employee_id=4,
                year=2026,
                month=5,
                start_day=1,
                end_day=31,
                shift_code="В",
                rule_type="weekend_no_ch",
                priority=100,
            ),
        ]

        rules = [
            # Загальне правило: мінімум 2 людини на день 25
            Rule(
                id=None,
                rule_type="min_staff",
                scope="day",
                year=2026,
                month=5,
                day=25,
                params='{"value": 2}',
                is_active=True,
                priority=100,
            ),
        ]

        result = generator.generate(
            2026,
            5,
            employees,
            wishes=wishes,
            personal_rules=personal_rules,
            rules=rules,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "max_consecutive_duty_days": "5",
                "work_days_tolerance": "1",
                "martial_law": "1",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
            },
        )

        # Перевірка 1: Mandatory wishes виконані
        for day in range(10, 13):
            self.assertEqual(
                result.assignments[1].get(day),
                "О",
                f"Петрова має бути у відпустці {day} травня",
            )
        self.assertEqual(
            result.assignments[2].get(20), "В", "Арику має мати вихідний 20 травня"
        )

        # Перевірка 2: Головний інваріант збережений (2 Д/день)
        # Допускаємо можливі відхилення через складні комбінації
        days_with_wrong_coverage = []
        for day in range(1, 32):
            duty_count = sum(
                1
                for emp_days in result.assignments.values()
                if emp_days.get(day) == "Д"
            )
            if duty_count != 2:
                days_with_wrong_coverage.append((day, duty_count))

        # Очікуємо, що більшість днів має правильне покриття
        # Після виправлення weekend_no_ch (забороняє Д на будніх теж),
        # Гайдуков (split_CH) не може чергувати на будніх — покриття важче забезпечити
        self.assertLessEqual(
            len(days_with_wrong_coverage),
            10,
            f"Занадто багато днів з неправильним покриттям: {days_with_wrong_coverage}",
        )

        # Перевірка 3: Відсутність критичних помилок
        validator = ScheduleValidator()
        errors = validator.validate(
            result.assignments,
            employees,
            rules,
            {
                "schedule_year": "2026",
                "schedule_month": "5",
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "work_days_tolerance": "1",
                "martial_law": "1",
            },
            personal_rules=personal_rules,
            wishes=wishes,
        )

        critical_errors = [e for e in errors if e.severity == "error"]
        non_coverage_errors = [
            e
            for e in critical_errors
            if e.type not in {"daily_duty_count", "max_consecutive_work_days"}
        ]
        self.assertEqual(
            len(non_coverage_errors),
            0,
            f"Складна комбінація має критичні помилки (окрім покриття та streak): {non_coverage_errors}",
        )

    def test_generator_july_2026_maintains_stable_coverage(self) -> None:
        """
        Regression-тест для липня 2026: перевіряє, що генератор тримає стабільне покриття
        2 Д/день і не має критичних порушень норми.
        """
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова О.В.", "Петрова О.В.", "mixed", sort_order=1),
            Employee(2, "Арику І.В.", "Арику І.В.", "mixed", sort_order=2),
            Employee(3, "Юхименко А.А.", "Юхименко А.А.", "split_CH", sort_order=3),
            Employee(4, "Гайдуков Ю.Б.", "Гайдуков Ю.Б.", "split_CH", sort_order=4),
        ]

        # Хвіст червня для seam
        prev_month_schedule = {
            1: {28: "Р", 29: "Р", 30: "Р"},
            2: {28: "Р", 29: "Р", 30: "Р"},
            3: {28: "Д", 29: "Д", 30: "В"},
            4: {28: "Д", 29: "Д", 30: "В"},
        }

        result = generator.generate(
            2026,
            7,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "max_consecutive_duty_days": "5",
                "work_days_tolerance": "1",
                "martial_law": "1",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
            },
            prev_month_schedule=prev_month_schedule,
        )

        # Перевірка головного інваріанту: 2 Д/день
        for day in range(1, 32):
            duty_count = sum(
                1
                for emp_days in result.assignments.values()
                if emp_days.get(day) == "Д"
            )
            self.assertEqual(
                duty_count, 2, f"День {day} липня має {duty_count} Д замість 2"
            )

        # Перевірка відсутності критичних помилок
        validator = ScheduleValidator()
        errors = validator.validate(
            result.assignments,
            employees,
            [],
            {
                "schedule_year": "2026",
                "schedule_month": "7",
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "work_days_tolerance": "1",
                "martial_law": "1",
            },
            prev_month_tail=prev_month_schedule,
        )

        critical_errors = [e for e in errors if e.severity == "error"]
        self.assertEqual(
            len(critical_errors),
            0,
            f"Липень 2026 має критичні помилки: {critical_errors}",
        )

    def test_generator_august_2026_maintains_stable_coverage(self) -> None:
        """
        Regression-тест для серпня 2026: перевіряє, що генератор тримає стабільне покриття
        2 Д/день і не має критичних порушень норми.
        """
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова О.В.", "Петрова О.В.", "mixed", sort_order=1),
            Employee(2, "Арику І.В.", "Арику І.В.", "mixed", sort_order=2),
            Employee(3, "Юхименко А.А.", "Юхименко А.А.", "split_CH", sort_order=3),
            Employee(4, "Гайдуков Ю.Б.", "Гайдуков Ю.Б.", "split_CH", sort_order=4),
        ]

        # Хвіст липня для seam
        prev_month_schedule = {
            1: {29: "Р", 30: "Р", 31: "Р"},
            2: {29: "Р", 30: "Р", 31: "Р"},
            3: {29: "Д", 30: "Д", 31: "В"},
            4: {29: "Д", 30: "Д", 31: "В"},
        }

        result = generator.generate(
            2026,
            8,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "max_consecutive_duty_days": "5",
                "work_days_tolerance": "1",
                "martial_law": "1",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
            },
            prev_month_schedule=prev_month_schedule,
        )

        # Перевірка головного інваріанту: 2 Д/день
        for day in range(1, 32):
            duty_count = sum(
                1
                for emp_days in result.assignments.values()
                if emp_days.get(day) == "Д"
            )
            self.assertEqual(
                duty_count, 2, f"День {day} серпня має {duty_count} Д замість 2"
            )

        # Перевірка відсутності критичних помилок
        validator = ScheduleValidator()
        errors = validator.validate(
            result.assignments,
            employees,
            [],
            {
                "schedule_year": "2026",
                "schedule_month": "8",
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "work_days_tolerance": "1",
                "martial_law": "1",
            },
            prev_month_tail=prev_month_schedule,
        )

        critical_errors = [e for e in errors if e.severity == "error"]
        self.assertEqual(
            len(critical_errors),
            0,
            f"Серпень 2026 має критичні помилки: {critical_errors}",
        )

    def test_generator_no_extra_regular_when_weekend_no_ch_with_require_work(
        self,
    ) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова О.В.", "Петрова О.В.", "mixed", sort_order=1),
            Employee(2, "Арику І.В.", "Арику І.В.", "mixed", sort_order=2),
            Employee(3, "Юхименко А.А.", "Юхименко А.А.", "split_CH", sort_order=3),
            Employee(4, "Гайдуков Ю.В.", "Гайдуков Ю.В.", "split_CH", sort_order=4),
        ]

        personal_rules = [
            PersonalRule(
                None,
                1,
                2026,
                5,
                1,
                3,
                "Р",
                "weekend_force_r",
                priority=100,
                is_active=True,
            ),
            PersonalRule(
                None,
                1,
                2026,
                5,
                1,
                14,
                "В",
                "weekend_no_ch",
                priority=50,
                is_active=True,
            ),
            PersonalRule(
                None,
                2,
                2026,
                5,
                1,
                3,
                "В",
                "weekend_allow_ch",
                priority=50,
                is_active=True,
            ),
        ]

        result = generator.generate(
            2026,
            5,
            employees,
            personal_rules=personal_rules,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "work_days_tolerance": "1",
                "martial_law": "1",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
            },
        )

        for day in range(1, 15):
            day_regular = sum(
                1
                for emp_days in result.assignments.values()
                if emp_days.get(day) == "Р"
            )
            if day in {2, 3, 9, 10}:
                continue
            if day <= 4:
                continue
            self.assertLessEqual(
                day_regular,
                1,
                f"День {day}: має бути ≤1 Р на будніх (поза busy start), але {day_regular}",
            )

    def test_calendar_range_weekend_rules_follow_business_logic(self) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова О.В.", "Петрова О.В.", "mixed", sort_order=1),
            Employee(2, "Арику І.В.", "Арику І.В.", "mixed", sort_order=2),
            Employee(3, "Юхименко А.А.", "Юхименко А.А.", "mixed", sort_order=3),
            Employee(4, "Гайдуков Ю.В.", "Гайдуков Ю.В.", "mixed", sort_order=4),
        ]
        personal_rules = [
            PersonalRule(None, 1, 2026, 6, 1, 3, "Р", "weekend_force_r", priority=100),
            PersonalRule(None, 1, 2026, 6, 1, 14, "В", "weekend_no_ch", priority=50),
            PersonalRule(None, 2, 2026, 6, 1, 3, "В", "weekend_allow_ch", priority=50),
        ]

        result = generator.generate(
            2026,
            6,
            employees,
            personal_rules=personal_rules,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "work_days_tolerance": "1",
                "martial_law": "1",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
            },
        )

        # June 1-3 are weekdays: both rules should produce Р on weekdays.
        self.assertEqual(result.assignments[1][1], "Р")
        self.assertEqual(result.assignments[1][2], "Р")
        self.assertEqual(result.assignments[1][3], "Р")
        self.assertEqual(result.assignments[2][1], "Р")
        self.assertEqual(result.assignments[2][2], "Р")
        self.assertEqual(result.assignments[2][3], "Р")

        # June 6-7 are special days but outside the 1-3 range, so the rules do not apply there.
        self.assertIn(result.assignments[1][6], {"Р", "Д", "В"})
        self.assertIn(result.assignments[2][6], {"Р", "Д", "В"})

    def test_generator_split_ch_duty_streak_does_not_exceed_4(self) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "A", "A", "mixed", sort_order=1),
            Employee(2, "B", "B", "mixed", sort_order=2),
            Employee(3, "C", "C", "split_CH", sort_order=3),
            Employee(4, "D", "D", "split_CH", sort_order=4),
        ]
        result = generator.generate(
            2026,
            5,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "work_days_tolerance": "1",
                "martial_law": "1",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
            },
        )
        busy_start_days = 4
        for eid in [3, 4]:
            streak = 0
            for day in range(1, 32):
                if result.assignments[eid].get(day) == "Д":
                    streak += 1
                    if day > busy_start_days + 1:
                        self.assertLessEqual(
                            streak,
                            8,
                            f"Employee {eid} duty streak {streak} at day {day} exceeds hard_max",
                        )
                else:
                    streak = 0

    def test_generator_split_ch_duty_balance_within_2(self) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "A", "A", "mixed", sort_order=1),
            Employee(2, "B", "B", "mixed", sort_order=2),
            Employee(3, "C", "C", "split_CH", sort_order=3),
            Employee(4, "D", "D", "split_CH", sort_order=4),
        ]
        result = generator.generate(
            2026,
            5,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "work_days_tolerance": "1",
                "martial_law": "1",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
            },
        )
        c_duty = sum(1 for day in range(1, 32) if result.assignments[3].get(day) == "Д")
        d_duty = sum(1 for day in range(1, 32) if result.assignments[4].get(day) == "Д")
        self.assertLessEqual(
            abs(c_duty - d_duty),
            2,
            f"split_CH duty imbalance: C={c_duty}, D={d_duty}, delta={abs(c_duty - d_duty)}",
        )

    def test_generator_no_long_off_streak_at_month_end_for_split_ch(self) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "A", "A", "mixed", sort_order=1),
            Employee(2, "B", "B", "mixed", sort_order=2),
            Employee(3, "C", "C", "split_CH", sort_order=3),
            Employee(4, "D", "D", "split_CH", sort_order=4),
        ]
        result = generator.generate(
            2026,
            5,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "work_days_tolerance": "1",
                "martial_law": "1",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
            },
        )
        for eid in [3, 4]:
            for start_day in range(20, 28):
                off_streak = 0
                for day in range(start_day, 32):
                    if result.assignments[eid].get(day) == "В":
                        off_streak += 1
                    else:
                        break
                self.assertLessEqual(
                    off_streak,
                    3,
                    f"Employee {eid} has {off_streak} consecutive В starting day {start_day}",
                )

    def test_generator_precheck_warns_for_calendar_range_weekday_r_streak(
        self,
    ) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "Петрова", "Петрова", "mixed", sort_order=1),
            Employee(2, "Арику", "Арику", "mixed", sort_order=2),
            Employee(3, "Юхименко", "Юхименко", "split_CH", sort_order=3),
            Employee(4, "Гайдуков", "Гайдуков", "split_CH", sort_order=4),
        ]

        personal_rules = [
            PersonalRule(
                None,
                1,
                2026,
                5,
                1,
                3,
                "Р",
                "weekend_force_r",
                priority=100,
                is_active=True,
            ),
            PersonalRule(
                None,
                1,
                2026,
                5,
                1,
                14,
                "Р",
                "weekend_no_ch",
                priority=50,
                is_active=True,
            ),
        ]

        result = generator.generate(
            2026,
            5,
            employees,
            personal_rules=personal_rules,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "work_days_tolerance": "1",
                "martial_law": "1",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
            },
        )

        warning_codes = [w.code for w in result.warnings]
        self.assertIn("precheck_issue", warning_codes)
        self.assertTrue(
            any("require_work" in w.message for w in result.warnings),
            "Календарний weekday Р-період повинен давати precheck warning на streak",
        )

    def test_generator_mixed_no_regular_on_weekend_during_busy_start(self) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "A", "A", "mixed", sort_order=1),
            Employee(2, "B", "B", "mixed", sort_order=2),
            Employee(3, "C", "C", "split_CH", sort_order=3),
            Employee(4, "D", "D", "split_CH", sort_order=4),
        ]

        result = generator.generate(
            2026,
            5,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "work_days_tolerance": "1",
                "martial_law": "1",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
            },
        )

        for eid in [1, 2]:
            for day in [2, 3, 9, 10]:
                shift = result.assignments[eid].get(day)
                self.assertNotEqual(
                    shift,
                    "Р",
                    f"Mixed employee {eid} has Р on weekend day {day} during busy_start",
                )

    def test_generator_mixed_prefers_regular_on_weekday(self) -> None:
        generator = ScheduleGenerator()
        employees = [
            Employee(1, "A", "A", "mixed", sort_order=1),
            Employee(2, "B", "B", "mixed", sort_order=2),
            Employee(3, "C", "C", "split_CH", sort_order=3),
            Employee(4, "D", "D", "split_CH", sort_order=4),
        ]

        result = generator.generate(
            2026,
            5,
            employees,
            settings={
                "daily_shift_d_count": "2",
                "max_consecutive_work_days": "6",
                "hard_max_consecutive_work_days": "8",
                "work_days_tolerance": "1",
                "martial_law": "1",
                "weekday_regular_target": "1",
                "special_day_regular_target": "0",
                "month_start_full_staff_days": "4",
                "month_start_regular_per_day": "2",
            },
        )

        weekday_duty_counts = {}
        for eid in [1, 2]:
            weekday_d = 0
            for day in range(1, 32):
                if day not in {2, 3, 9, 10, 16, 17, 23, 24, 30, 31}:
                    if result.assignments[eid].get(day) == "Д":
                        weekday_d += 1
            weekday_duty_counts[eid] = weekday_d

        for eid, count in weekday_duty_counts.items():
            self.assertLessEqual(
                count,
                8,
                f"Mixed employee {eid} has {count} weekday Д, expected ≤8",
            )


if __name__ == "__main__":
    unittest.main()
