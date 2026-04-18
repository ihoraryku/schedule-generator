from __future__ import annotations

from dataclasses import dataclass

import logging

from schedule_askue.core.shift_codes import normalize_shift_code
from schedule_askue.db.models import PersonalRule

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ResolvedPersonalRule:
    forced_shift: str | None = None
    allowed_shifts: set[str] | None = None
    prohibit_duty: bool = False
    require_work: bool = False
    source_rule: PersonalRule | None = None


def rule_specificity(rule: PersonalRule) -> tuple[int, int]:
    span = max(1, rule.end_day - rule.start_day + 1)
    return (
        1 if rule.year is not None and rule.month is not None else 0,
        -span,
    )


def sort_rules_for_resolution(rules: list[PersonalRule]) -> list[PersonalRule]:
    return sorted(
        rules,
        key=lambda rule: (
            int(rule.priority),
            *rule_specificity(rule),
            int(rule.id or 0),
        ),
        reverse=True,
    )


def resolve_personal_rule_for_day(
    rules: list[PersonalRule],
    *,
    is_special_day: bool,
) -> ResolvedPersonalRule:
    resolved = ResolvedPersonalRule()
    ordered_rules = sort_rules_for_resolution(rules)

    for rule in ordered_rules:
        rule_type = rule.rule_type
        if rule_type == "strict":
            return ResolvedPersonalRule(
                forced_shift=normalize_shift_code(rule.shift_code),
                source_rule=rule,
            )
        if rule_type == "prohibit_ch":
            resolved.prohibit_duty = True
            resolved.source_rule = resolved.source_rule or rule
            continue
        if rule_type == "weekend_no_ch":
            if is_special_day:
                return ResolvedPersonalRule(
                    forced_shift="В", prohibit_duty=True, source_rule=rule
                )
            return ResolvedPersonalRule(forced_shift="Р", source_rule=rule)
        if rule_type == "weekend_force_r":
            return ResolvedPersonalRule(forced_shift="Р", source_rule=rule)
        if rule_type == "weekend_allow_ch":
            if is_special_day:
                return ResolvedPersonalRule(allowed_shifts={"В", "Д"}, source_rule=rule)
            return ResolvedPersonalRule(forced_shift="Р", source_rule=rule)

    return resolved
