from __future__ import annotations

import calendar
import json
import logging
from dataclasses import dataclass
from datetime import date

import holidays

from schedule_askue.core.calendar_rules import (
    is_special_day_info,
    special_days_for_month,
)
from schedule_askue.core.personal_rule_logic import (
    resolve_personal_rule_for_day,
    sort_rules_for_resolution,
)
from schedule_askue.core.personal_rule_periods import covered_days_for_personal_rule
from schedule_askue.core.shift_codes import (
    CANONICAL_SHIFT_CODES,
    WORK_SHIFT_CODES,
    normalize_shift_code,
)
from schedule_askue.core.work_norms import employee_work_delta
from schedule_askue.db.models import Employee, PersonalRule, Rule, Wish

logger = logging.getLogger(__name__)
WORK_CODES = WORK_SHIFT_CODES


@dataclass(slots=True)
class ValidationError:
    type: str
    severity: str
    employee_id: int | None
    day: int | None
    message: str


class ScheduleValidator:
    def validate(
        self,
        schedule: dict[int, dict[int, str]],
        employees: list[Employee],
        rules: list[Rule] | None,
        settings: dict[str, str] | None,
        personal_rules: list[PersonalRule] | None = None,
        prev_month_tail: dict[int, dict[int, str]] | None = None,
        month_info: dict[int, object] | None = None,
        wishes: list[Wish] | None = None,
        extra_day_off_usage: dict[int, int] | None = None,
    ) -> list[ValidationError]:
        settings = settings or {}
        year = int(settings.get("schedule_year", "0") or 0)
        month = int(settings.get("schedule_month", "0") or 0)
        logger.info(
            f"Валідація графіка {year}-{month:02d}: {len(employees)} працівників"
        )

        schedule = {
            employee_id: {
                day: normalize_shift_code(value) for day, value in days.items()
            }
            for employee_id, days in schedule.items()
        }
        errors: list[ValidationError] = []
        active_rules = [rule for rule in (rules or []) if rule.is_active]
        active_personal_rules = [
            rule for rule in (personal_rules or []) if rule.is_active
        ]
        employee_by_id = {
            employee.id or index + 1: employee
            for index, employee in enumerate(employees)
        }
        special_days = self._special_days(year, month, month_info, settings)
        mandatory_wishes = self._build_mandatory_wish_lookup(wishes or [])
        mandatory_wish_codes = self._build_mandatory_wish_code_lookup(wishes or [])

        errors.extend(self._validate_known_shift_codes(schedule))
        errors.extend(self._validate_daily_duty_count(schedule, settings))
        errors.extend(self._validate_min_staff(schedule, active_rules))
        errors.extend(
            self._validate_must_rules(
                schedule, active_rules, employee_by_id, mandatory_wishes
            )
        )
        errors.extend(self._validate_max_vacation_overlap(schedule, settings))
        errors.extend(
            self._validate_max_consecutive(
                schedule,
                employees,
                settings,
                prev_month_tail or {},
                active_personal_rules,
                wishes,
            )
        )
        errors.extend(
            self._validate_work_day_norm(
                schedule,
                employees,
                settings,
                month_info,
                extra_day_off_usage or {},
            )
        )
        errors.extend(
            self._validate_personal_rules(
                schedule,
                active_personal_rules,
                employee_by_id,
                special_days,
                mandatory_wishes,
            )
        )
        errors.extend(
            self._validate_isolated_day_off_patterns(
                schedule, employees, settings, prev_month_tail or {}, special_days
            )
        )
        errors.extend(self._validate_broken_work_patterns(schedule, employees))
        errors.extend(
            self._validate_special_day_balance(
                schedule,
                employees,
                special_days,
                mandatory_wish_codes,
                active_personal_rules,
            )
        )

        error_count = sum(1 for e in errors if e.severity == "error")
        warning_count = sum(1 for e in errors if e.severity == "warning")
        logger.info(
            f"Валідація завершена: {error_count} помилок, {warning_count} попереджень"
        )
        return errors

    def _validate_known_shift_codes(
        self, schedule: dict[int, dict[int, str]]
    ) -> list[ValidationError]:
        allowed = CANONICAL_SHIFT_CODES
        errors: list[ValidationError] = []
        for employee_id, days in schedule.items():
            for day, value in days.items():
                if value not in allowed:
                    errors.append(
                        ValidationError(
                            type="unknown_shift",
                            severity="error",
                            employee_id=employee_id,
                            day=day,
                            message=f"Невідомий код зміни: {value}",
                        )
                    )
        return errors

    def _validate_min_staff(
        self, schedule: dict[int, dict[int, str]], rules: list[Rule]
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        min_staff_by_day: dict[int, int] = {}

        for rule in rules:
            if rule.rule_type != "min_staff":
                continue
            params = self._parse_rule_params(rule.params)
            required = int(params.get("value", 0) or 0)
            if required <= 0:
                continue
            for day in self._resolve_rule_days(rule, schedule):
                min_staff_by_day[day] = max(min_staff_by_day.get(day, 0), required)

        for day, required in sorted(min_staff_by_day.items()):
            actual = sum(1 for days in schedule.values() if days.get(day) in WORK_CODES)
            if actual < required:
                errors.append(
                    ValidationError(
                        type="min_staff",
                        severity="error",
                        employee_id=None,
                        day=day,
                        message=f"На день {day} заплановано {actual} працівник(ів), потрібно мінімум {required}.",
                    )
                )
        return errors

    def _validate_must_rules(
        self,
        schedule: dict[int, dict[int, str]],
        rules: list[Rule],
        employee_by_id: dict[int, Employee],
        mandatory_wishes: dict[int, set[int]],
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        effective_rules: dict[int, dict[int, str]] = {}
        for rule in rules:
            if rule.rule_type not in {"must_work", "must_off"}:
                continue
        ordered_rules = sorted(
            [rule for rule in rules if rule.rule_type in {"must_work", "must_off"}],
            key=lambda rule: (
                int(rule.priority),
                1 if rule.scope.startswith("employee:") else 0,
                1 if rule.day is not None else 0,
                int(rule.id or 0),
            ),
            reverse=True,
        )
        for rule in ordered_rules:
            target_ids = self._resolve_rule_employee_ids(rule, employee_by_id)
            days = self._resolve_rule_days(rule, schedule)
            for employee_id in target_ids:
                for day in days:
                    effective_rules.setdefault(employee_id, {}).setdefault(
                        day, rule.rule_type
                    )
        for employee_id, days in effective_rules.items():
            employee = employee_by_id.get(employee_id)
            if employee is None:
                continue
            for day, rule_type in days.items():
                if self._has_mandatory_wish(mandatory_wishes, employee_id, day):
                    continue
                actual = schedule.get(employee_id, {}).get(day, "")
                if rule_type == "must_work" and actual not in WORK_CODES:
                    errors.append(
                        ValidationError(
                            type="must_work",
                            severity="error",
                            employee_id=employee_id,
                            day=day,
                            message=f"{employee.short_name} повинен працювати у день {day}.",
                        )
                    )
                if rule_type == "must_off" and actual not in {"В", "О"}:
                    errors.append(
                        ValidationError(
                            type="must_off",
                            severity="error",
                            employee_id=employee_id,
                            day=day,
                            message=f"{employee.short_name} повинен мати вихідний у день {day}.",
                        )
                    )
        return errors

    def _validate_max_vacation_overlap(
        self,
        schedule: dict[int, dict[int, str]],
        settings: dict[str, str],
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        max_vacation_overlap = int(settings.get("max_vacation_overlap", "1"))
        if max_vacation_overlap <= 0:
            return errors

        max_day = max(
            (max(days.keys(), default=0) for days in schedule.values()), default=0
        )
        for day in range(1, max_day + 1):
            actual = sum(1 for days in schedule.values() if days.get(day) == "О")
            if actual > max_vacation_overlap:
                errors.append(
                    ValidationError(
                        type="max_vacation_overlap",
                        severity="error",
                        employee_id=None,
                        day=day,
                        message=f"На день {day} у відпустці {actual} працівник(ів), дозволено максимум {max_vacation_overlap}.",
                    )
                )
        return errors

    def _validate_max_consecutive(
        self,
        schedule: dict[int, dict[int, str]],
        employees: list[Employee],
        settings: dict[str, str],
        prev_month_tail: dict[int, dict[int, str]],
        personal_rules: list[PersonalRule] | None = None,
        wishes: list[Wish] | None = None,
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        max_consecutive = int(
            settings.get(
                "hard_max_consecutive_work_days",
                settings.get("max_consecutive_work_days", "7"),
            )
        )
        soft_max = int(settings.get("max_consecutive_work_days", "7"))
        employee_by_id = {
            employee.id or index + 1: employee
            for index, employee in enumerate(employees)
        }
        special_days_set: set[int] | None = None

        grouped_rules: dict[int, dict[int, list[PersonalRule]]] = {}
        for rule in personal_rules or []:
            if not rule.is_active:
                continue
            for day in range(rule.start_day, rule.end_day + 1):
                grouped_rules.setdefault(rule.employee_id, {}).setdefault(
                    day, []
                ).append(rule)

        mandatory_wish_set: set[tuple[int, int]] = set()
        for w in wishes or []:
            if w.priority == "mandatory" and w.wish_type != "vacation":
                for day in range(w.date_from or 1, (w.date_to or 31) + 1):
                    mandatory_wish_set.add((w.employee_id, day))

        for employee_id, days in schedule.items():
            tail = prev_month_tail.get(employee_id, {})
            consecutive = 0
            streak_start = 0
            for tail_day in sorted(tail):
                consecutive = consecutive + 1 if tail[tail_day] in WORK_CODES else 0
            for day in sorted(days):
                if days[day] in WORK_CODES:
                    if consecutive == 0:
                        streak_start = day
                    consecutive += 1
                    if consecutive > max_consecutive:
                        employee = employee_by_id.get(employee_id)
                        name = (
                            employee.short_name
                            if employee is not None
                            else f"ID {employee_id}"
                        )
                        errors.append(
                            ValidationError(
                                type="max_consecutive_work_days",
                                severity="error",
                                employee_id=employee_id,
                                day=day,
                                message=f"{name} перевищує ліміт {max_consecutive} робочих днів підряд.",
                            )
                        )
                    elif consecutive > soft_max:
                        all_rule_or_wish = True
                        for d in range(streak_start, day + 1):
                            if (employee_id, d) in mandatory_wish_set:
                                continue
                            day_rules = grouped_rules.get(employee_id, {}).get(d, [])
                            if day_rules:
                                resolved = resolve_personal_rule_for_day(
                                    day_rules,
                                    is_special_day=False,
                                )
                                if (
                                    resolved.require_work
                                    or resolved.forced_shift in WORK_CODES
                                ):
                                    continue
                            all_rule_or_wish = False
                            break
                        if all_rule_or_wish:
                            continue
                        employee = employee_by_id.get(employee_id)
                        name = (
                            employee.short_name
                            if employee is not None
                            else f"ID {employee_id}"
                        )
                        errors.append(
                            ValidationError(
                                type="soft_max_consecutive_work_days",
                                severity="warning",
                                employee_id=employee_id,
                                day=day,
                                message=f"{name}: серія {consecutive} робочих днів перевищує бажаний ліміт {soft_max}.",
                            )
                        )
                else:
                    consecutive = 0
        return errors

    def _validate_work_day_norm(
        self,
        schedule: dict[int, dict[int, str]],
        employees: list[Employee],
        settings: dict[str, str],
        month_info: dict[int, object] | None,
        extra_day_off_usage: dict[int, int],
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        tolerance = int(settings.get("work_days_tolerance", "0"))
        year = int(settings.get("schedule_year", "0") or 0)
        month = int(settings.get("schedule_month", "0") or 0)
        if year <= 0 or month <= 0:
            return errors

        working_days = self._count_working_days(year, month, month_info)
        employee_by_id = {
            employee.id or index + 1: employee
            for index, employee in enumerate(employees)
        }
        for employee_id, employee in employee_by_id.items():
            actual, target, deviation = employee_work_delta(
                employee,
                days=schedule.get(employee_id, {}),
                working_days=working_days,
                month_days=calendar.monthrange(year, month)[1],
                used_extra_days_off=extra_day_off_usage.get(employee_id, 0),
            )
            if abs(deviation) > tolerance:
                state = "переробка" if deviation > 0 else "недобір"
                errors.append(
                    ValidationError(
                        type="work_day_norm",
                        severity="warning",
                        employee_id=employee_id,
                        day=None,
                        message=f"{employee.short_name}: {state} відносно норми. Факт {actual}, норма {target}, допуск ±{tolerance}.",
                    )
                )
        return errors

    def _validate_personal_rules(
        self,
        schedule: dict[int, dict[int, str]],
        rules: list[PersonalRule],
        employee_by_id: dict[int, Employee],
        special_days: set[int],
        mandatory_wishes: dict[int, set[int]],
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        month_days = max(
            [day for days in schedule.values() for day in days.keys()]
            + list(special_days),
            default=0,
        )
        grouped_rules: dict[int, dict[int, list[PersonalRule]]] = {}
        for rule in sort_rules_for_resolution(rules):
            for day in covered_days_for_personal_rule(
                rule,
                month_days=month_days,
                special_days=special_days,
            ):
                grouped_rules.setdefault(rule.employee_id, {}).setdefault(
                    day, []
                ).append(rule)

        for employee_id, by_day in grouped_rules.items():
            employee = employee_by_id.get(employee_id)
            if employee is None:
                continue
            for day, day_rules in by_day.items():
                if self._has_mandatory_wish(mandatory_wishes, employee_id, day):
                    continue
                actual = schedule.get(employee_id, {}).get(day, "")
                resolved = resolve_personal_rule_for_day(
                    day_rules,
                    is_special_day=day in special_days,
                )
                if (
                    resolved.forced_shift is not None
                    and actual != resolved.forced_shift
                ):
                    errors.append(
                        ValidationError(
                            type="personal_rule_forced_shift",
                            severity="error",
                            employee_id=employee_id,
                            day=day,
                            message=f"{employee.short_name}: персональне правило вимагає '{resolved.forced_shift}' у день {day}.",
                        )
                    )
                    continue
                if (
                    resolved.allowed_shifts is not None
                    and actual not in resolved.allowed_shifts
                ):
                    allowed_text = " або ".join(sorted(resolved.allowed_shifts))
                    errors.append(
                        ValidationError(
                            type="personal_rule_allowed_shifts",
                            severity="error",
                            employee_id=employee_id,
                            day=day,
                            message=f"{employee.short_name}: у день {day} дозволені лише '{allowed_text}'.",
                        )
                    )
                    continue
                if resolved.prohibit_duty and actual == "Д":
                    errors.append(
                        ValidationError(
                            type="personal_rule_prohibit_ch",
                            severity="error",
                            employee_id=employee_id,
                            day=day,
                            message=f"{employee.short_name}: персональне правило забороняє 'Д' у день {day}.",
                        )
                    )
        return errors

    def _validate_isolated_day_off_patterns(
        self,
        schedule: dict[int, dict[int, str]],
        employees: list[Employee],
        settings: dict[str, str],
        prev_month_tail: dict[int, dict[int, str]],
        special_days: set[int],
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        max_consecutive = int(
            settings.get(
                "hard_max_consecutive_work_days",
                settings.get("max_consecutive_work_days", "7"),
            )
        )
        employee_by_id = {
            employee.id or index + 1: employee
            for index, employee in enumerate(employees)
        }
        for employee_id, days in schedule.items():
            ordered_days = sorted(days)
            for index in range(1, len(ordered_days) - 1):
                day = ordered_days[index]
                prev_day = ordered_days[index - 1]
                next_day = ordered_days[index + 1]
                if days.get(day) != "В":
                    continue
                if day in special_days:
                    continue
                if (
                    days.get(prev_day) not in WORK_CODES
                    or days.get(next_day) not in WORK_CODES
                ):
                    continue
                if (
                    self._consecutive_span_if_work(
                        days, day, prev_month_tail.get(employee_id, {})
                    )
                    > max_consecutive
                ):
                    continue
                employee = employee_by_id.get(employee_id)
                name = (
                    employee.short_name if employee is not None else f"ID {employee_id}"
                )
                errors.append(
                    ValidationError(
                        type="isolated_day_off",
                        severity="warning",
                        employee_id=employee_id,
                        day=day,
                        message=f"{name}: одиночний вихідний між робочими днями у день {day} робить графік рваним.",
                    )
                )
        return errors

    def _validate_daily_duty_count(
        self,
        schedule: dict[int, dict[int, str]],
        settings: dict[str, str],
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        expected = int(
            settings.get(
                "daily_shift_d_count", settings.get("daily_shift_ch_count", "0")
            )
            or 0
        )
        if expected <= 0:
            return errors
        max_day = max(
            (max(days.keys(), default=0) for days in schedule.values()), default=0
        )
        for day in range(1, max_day + 1):
            actual = sum(1 for days in schedule.values() if days.get(day) == "Д")
            if actual == expected:
                continue
            errors.append(
                ValidationError(
                    type="daily_duty_count",
                    severity="error",
                    employee_id=None,
                    day=day,
                    message=f"На день {day} заплановано {actual} чергувань 'Д', потрібно рівно {expected}.",
                )
            )
        return errors

    def _consecutive_span_if_work(
        self,
        days: dict[int, str],
        day: int,
        prev_month_tail: dict[int, str],
    ) -> int:
        streak = 1
        cursor = day - 1
        while days.get(cursor) in WORK_CODES:
            streak += 1
            cursor -= 1
        if cursor < 1:
            for tail_day in sorted(prev_month_tail, reverse=True):
                if prev_month_tail[tail_day] in WORK_CODES:
                    streak += 1
                else:
                    break
        cursor = day + 1
        while days.get(cursor) in WORK_CODES:
            streak += 1
            cursor += 1
        return streak

    def _validate_broken_work_patterns(
        self,
        schedule: dict[int, dict[int, str]],
        employees: list[Employee],
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        employee_by_id = {
            employee.id or index + 1: employee
            for index, employee in enumerate(employees)
        }
        for employee_id, days in schedule.items():
            ordered_days = sorted(days)
            for index in range(1, len(ordered_days) - 1):
                prev_day = ordered_days[index - 1]
                day = ordered_days[index]
                next_day = ordered_days[index + 1]
                sequence = [
                    days.get(prev_day, ""),
                    days.get(day, ""),
                    days.get(next_day, ""),
                ]
                if sequence not in (["Р", "Д", "Р"], ["Д", "Р", "Д"]):
                    continue
                employee = employee_by_id.get(employee_id)
                name = (
                    employee.short_name if employee is not None else f"ID {employee_id}"
                )
                errors.append(
                    ValidationError(
                        type="broken_work_pattern",
                        severity="warning",
                        employee_id=employee_id,
                        day=day,
                        message=f"{name}: рваний шаблон роботи {sequence[0]}-{sequence[1]}-{sequence[2]} біля дня {day}.",
                    )
                )
        return errors

    def _validate_special_day_balance(
        self,
        schedule: dict[int, dict[int, str]],
        employees: list[Employee],
        special_days: set[int],
        mandatory_wish_codes: dict[int, dict[int, str]],
        personal_rules: list[PersonalRule],
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        if len(special_days) < 2:
            return errors
        employees_by_type: dict[str, list[Employee]] = {}
        for employee in employees:
            employee_id = employee.id or 0
            if employee_id not in schedule:
                continue
            employees_by_type.setdefault(employee.shift_type, []).append(employee)
        for shift_type, group in employees_by_type.items():
            if len(group) < 2:
                continue
            counts = {
                employee.id or 0: sum(
                    1
                    for day, value in schedule.get(employee.id or 0, {}).items()
                    if day in special_days and value in WORK_CODES
                )
                for employee in group
            }
            if not counts:
                continue
            minimum = min(counts.values())
            maximum = max(counts.values())
            if maximum - minimum <= 1:
                continue
            if not self._has_special_day_rebalance_candidate(
                schedule,
                group,
                special_days,
                mandatory_wish_codes,
                personal_rules,
                counts,
                minimum,
                maximum,
            ):
                continue
            overloaded = [
                employee.short_name
                for employee in group
                if counts.get(employee.id or 0, 0) == maximum
            ]
            errors.append(
                ValidationError(
                    type="special_day_balance",
                    severity="warning",
                    employee_id=None,
                    day=None,
                    message=f"Навантаження у вихідні/святкові для групи '{shift_type}' нерівномірне: найбільше мають {', '.join(overloaded)}.",
                )
            )
        return errors

    def _has_special_day_rebalance_candidate(
        self,
        schedule: dict[int, dict[int, str]],
        group: list[Employee],
        special_days: set[int],
        mandatory_wish_codes: dict[int, dict[int, str]],
        personal_rules: list[PersonalRule],
        counts: dict[int, int],
        minimum: int,
        maximum: int,
    ) -> bool:
        overloaded_ids = {
            employee.id or 0
            for employee in group
            if counts.get(employee.id or 0, 0) == maximum
        }
        underloaded_ids = {
            employee.id or 0
            for employee in group
            if counts.get(employee.id or 0, 0) == minimum
        }
        group_by_id = {e.id or 0: e for e in group}
        for overloaded_id in overloaded_ids:
            for day in special_days:
                if schedule.get(overloaded_id, {}).get(day) not in WORK_CODES:
                    continue
                forced_overloaded = self._mandatory_or_personal_special_constraint(
                    overloaded_id,
                    day,
                    mandatory_wish_codes,
                    personal_rules,
                    employee_by_id=group_by_id,
                )
                if forced_overloaded == "work":
                    continue
                for underloaded_id in underloaded_ids:
                    if schedule.get(underloaded_id, {}).get(day) in WORK_CODES:
                        continue
                    forced_underloaded = self._mandatory_or_personal_special_constraint(
                        underloaded_id,
                        day,
                        mandatory_wish_codes,
                        personal_rules,
                        employee_by_id=group_by_id,
                    )
                    if forced_underloaded == "off":
                        continue
                    return True
        return False

    def _mandatory_or_personal_special_constraint(
        self,
        employee_id: int,
        day: int,
        mandatory_wish_codes: dict[int, dict[int, str]],
        personal_rules: list[PersonalRule],
        employee_by_id: dict[int, Employee] | None = None,
    ) -> str | None:
        mandatory_code = mandatory_wish_codes.get(employee_id, {}).get(day)
        if mandatory_code in WORK_CODES:
            return "work"
        if mandatory_code in {"В", "О"}:
            return "off"
        for rule in personal_rules:
            if rule.employee_id != employee_id:
                continue
            if not (rule.start_day <= day <= rule.end_day):
                continue
        day_rules = [
            rule
            for rule in personal_rules
            if rule.employee_id == employee_id and rule.start_day <= day <= rule.end_day
        ]
        resolved = resolve_personal_rule_for_day(
            day_rules,
            is_special_day=True,
        )
        if resolved.forced_shift in WORK_CODES:
            return "work"
        if resolved.forced_shift in {"В", "О"}:
            return "off"
        if resolved.allowed_shifts is not None and "Д" not in resolved.allowed_shifts:
            return "off"
        return None

    def _special_days(
        self,
        year: int,
        month: int,
        month_info: dict[int, object] | None,
        settings: dict[str, str],
    ) -> set[int]:
        if month_info:
            return {
                day for day, info in month_info.items() if is_special_day_info(info)
            }
        if year <= 0 or month <= 0:
            return set()
        martial_law = settings.get("martial_law", "1") == "1"
        ua_holidays = holidays.Ukraine(years=[year])
        return special_days_for_month(
            year, month, martial_law=martial_law, ua_holidays=ua_holidays
        )

    def _count_working_days(
        self, year: int, month: int, month_info: dict[int, object] | None
    ) -> int:
        if month_info:
            return sum(
                1
                for info in month_info.values()
                if getattr(info, "is_working_day", False)
            )
        month_days = calendar.monthrange(year, month)[1]
        return sum(
            1
            for day in range(1, month_days + 1)
            if date(year, month, day).weekday() < 5
        )

    def _resolve_rule_employee_ids(
        self, rule: Rule, employee_by_id: dict[int, Employee]
    ) -> list[int]:
        if rule.scope == "all":
            return list(employee_by_id.keys())
        if rule.scope.startswith("employee:"):
            try:
                employee_id = int(rule.scope.split(":", 1)[1])
            except ValueError:
                return []
            return [employee_id]
        return []

    def _resolve_rule_days(
        self, rule: Rule, schedule: dict[int, dict[int, str]]
    ) -> list[int]:
        max_day = 31
        if schedule:
            max_day = max(
                (max(days.keys(), default=0) for days in schedule.values()), default=31
            )
        if rule.day is None:
            return list(range(1, max_day + 1))
        if 1 <= rule.day <= max_day:
            return [rule.day]
        return []

    def _parse_rule_params(self, raw: str) -> dict[str, object]:
        try:
            value = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def _build_mandatory_wish_lookup(self, wishes: list[Wish]) -> dict[int, set[int]]:
        result: dict[int, set[int]] = {}
        for wish in wishes:
            if wish.priority != "mandatory":
                continue
            start_day = wish.date_from or 1
            end_day = wish.date_to or start_day
            result.setdefault(wish.employee_id, set()).update(
                range(start_day, end_day + 1)
            )
        return result

    def _build_mandatory_wish_code_lookup(
        self, wishes: list[Wish]
    ) -> dict[int, dict[int, str]]:
        result: dict[int, dict[int, str]] = {}
        for wish in wishes:
            if wish.priority != "mandatory":
                continue
            start_day = wish.date_from or 1
            end_day = wish.date_to or start_day
            normalized = self._wish_to_shift_code(wish)
            for day in range(start_day, end_day + 1):
                result.setdefault(wish.employee_id, {})[day] = normalized
        return result

    def _has_mandatory_wish(
        self, mandatory_wishes: dict[int, set[int]], employee_id: int, day: int
    ) -> bool:
        return day in mandatory_wishes.get(employee_id, set())

    def _wish_to_shift_code(self, wish: Wish) -> str:
        if wish.wish_type == "work_day":
            normalized = normalize_shift_code(wish.comment)
            if normalized in WORK_CODES:
                return normalized
            return "Р"
        mapping = {"vacation": "О", "day_off": "В", "work_day": "Р"}
        return mapping.get(wish.wish_type, "В")
