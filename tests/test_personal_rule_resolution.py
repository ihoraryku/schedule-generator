import unittest

from schedule_askue.core.personal_rule_logic import resolve_personal_rule_for_day
from schedule_askue.db.models import PersonalRule


class PersonalRuleResolutionTests(unittest.TestCase):
    def test_higher_priority_rule_wins(self) -> None:
        rules = [
            PersonalRule(
                id=1,
                employee_id=1,
                year=2026,
                month=1,
                start_day=1,
                end_day=10,
                shift_code="Р",
                rule_type="weekend_no_ch",
                priority=50,
            ),
            PersonalRule(
                id=2,
                employee_id=1,
                year=2026,
                month=1,
                start_day=1,
                end_day=10,
                shift_code="Р",
                rule_type="weekend_force_r",
                priority=200,
            ),
        ]

        resolved = resolve_personal_rule_for_day(rules, is_special_day=True)
        self.assertEqual(resolved.forced_shift, "Р")

    def test_tie_break_prefers_more_specific_range(self) -> None:
        rules = [
            PersonalRule(
                id=1,
                employee_id=1,
                year=2026,
                month=1,
                start_day=1,
                end_day=10,
                shift_code="Р",
                rule_type="weekend_force_r",
                priority=100,
            ),
            PersonalRule(
                id=2,
                employee_id=1,
                year=2026,
                month=1,
                start_day=5,
                end_day=6,
                shift_code="Р",
                rule_type="weekend_no_ch",
                priority=100,
            ),
        ]

        resolved = resolve_personal_rule_for_day(rules, is_special_day=True)
        self.assertEqual(resolved.forced_shift, "В")

    def test_weekend_allow_ch_forces_weekday_r(self) -> None:
        rules = [
            PersonalRule(
                id=1,
                employee_id=1,
                year=2026,
                month=1,
                start_day=1,
                end_day=10,
                shift_code="Р",
                rule_type="weekend_allow_ch",
                priority=100,
            )
        ]

        resolved = resolve_personal_rule_for_day(rules, is_special_day=False)
        self.assertEqual(resolved.forced_shift, "Р")
        self.assertIsNone(resolved.allowed_shifts)
        self.assertFalse(resolved.prohibit_duty)

    def test_weekend_no_ch_forces_r_on_weekdays_and_v_on_special_days(self) -> None:
        rules = [
            PersonalRule(
                id=1,
                employee_id=1,
                year=2026,
                month=5,
                start_day=1,
                end_day=14,
                shift_code="В",
                rule_type="weekend_no_ch",
                priority=50,
            )
        ]

        resolved_weekend = resolve_personal_rule_for_day(rules, is_special_day=True)
        self.assertEqual(resolved_weekend.forced_shift, "В")
        self.assertTrue(resolved_weekend.prohibit_duty)
        self.assertFalse(resolved_weekend.require_work)

        resolved_weekday = resolve_personal_rule_for_day(rules, is_special_day=False)
        self.assertEqual(resolved_weekday.forced_shift, "Р")
        self.assertFalse(resolved_weekday.prohibit_duty)
        self.assertFalse(resolved_weekday.require_work)

    def test_weekend_no_ch_on_weekday_does_not_override_higher_priority(self) -> None:
        rules = [
            PersonalRule(
                id=1,
                employee_id=1,
                year=2026,
                month=5,
                start_day=1,
                end_day=14,
                shift_code="В",
                rule_type="weekend_no_ch",
                priority=50,
            ),
            PersonalRule(
                id=2,
                employee_id=1,
                year=2026,
                month=5,
                start_day=1,
                end_day=3,
                shift_code="Р",
                rule_type="weekend_force_r",
                priority=100,
            ),
        ]

        resolved_weekend = resolve_personal_rule_for_day(rules, is_special_day=True)
        self.assertEqual(resolved_weekend.forced_shift, "Р")

        resolved_weekday = resolve_personal_rule_for_day(rules, is_special_day=False)
        self.assertEqual(resolved_weekday.forced_shift, "Р")
        self.assertFalse(resolved_weekday.prohibit_duty)
        self.assertFalse(resolved_weekday.require_work)

    def test_weekend_no_ch_forces_r_on_weekdays(self) -> None:
        rules = [
            PersonalRule(
                id=1,
                employee_id=1,
                year=2026,
                month=5,
                start_day=1,
                end_day=14,
                shift_code="В",
                rule_type="weekend_no_ch",
                priority=50,
            )
        ]

        resolved = resolve_personal_rule_for_day(rules, is_special_day=False)
        self.assertEqual(resolved.forced_shift, "Р")
        self.assertFalse(resolved.prohibit_duty)
        self.assertFalse(resolved.require_work)
        self.assertIsNone(resolved.allowed_shifts)

    def test_weekend_force_r_always_forces_r(self) -> None:
        rules = [
            PersonalRule(
                id=1,
                employee_id=1,
                year=2026,
                month=5,
                start_day=1,
                end_day=3,
                shift_code="Р",
                rule_type="weekend_force_r",
                priority=100,
            )
        ]

        resolved_full_r = resolve_personal_rule_for_day(rules, is_special_day=True)
        self.assertEqual(resolved_full_r.forced_shift, "Р")

        resolved_mixed = resolve_personal_rule_for_day(rules, is_special_day=True)
        self.assertEqual(resolved_mixed.forced_shift, "Р")

        resolved_split_ch = resolve_personal_rule_for_day(rules, is_special_day=True)
        self.assertEqual(resolved_split_ch.forced_shift, "Р")

        resolved_no_type = resolve_personal_rule_for_day(rules, is_special_day=True)
        self.assertEqual(resolved_no_type.forced_shift, "Р")

    def test_weekend_force_r_with_weekend_no_ch_override(self) -> None:
        rules = [
            PersonalRule(
                id=1,
                employee_id=1,
                year=2026,
                month=5,
                start_day=1,
                end_day=14,
                shift_code="В",
                rule_type="weekend_no_ch",
                priority=50,
            ),
            PersonalRule(
                id=2,
                employee_id=1,
                year=2026,
                month=5,
                start_day=1,
                end_day=3,
                shift_code="Р",
                rule_type="weekend_force_r",
                priority=100,
            ),
        ]

        resolved = resolve_personal_rule_for_day(rules, is_special_day=True)
        self.assertEqual(resolved.forced_shift, "Р")


if __name__ == "__main__":
    unittest.main()
