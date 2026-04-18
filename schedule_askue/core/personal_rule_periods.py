from __future__ import annotations

from schedule_askue.db.models import PersonalRule


WEEKEND_INDEXED_RULE_TYPES = frozenset(
    {"weekend_force_r", "weekend_no_ch", "weekend_allow_ch"}
)


def is_weekend_indexed_personal_rule(rule_type: str) -> bool:
    return rule_type in WEEKEND_INDEXED_RULE_TYPES


def covered_days_for_personal_rule(
    rule: PersonalRule,
    *,
    month_days: int,
    special_days: set[int],
) -> list[int]:
    start_day = max(1, min(month_days, rule.start_day))
    end_day = max(start_day, min(month_days, rule.end_day))
    return list(range(start_day, end_day + 1))
