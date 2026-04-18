from __future__ import annotations

import calendar
import json
import logging
from dataclasses import dataclass
from datetime import date

import holidays

from schedule_askue.core.calendar_rules import special_days_for_month
from schedule_askue.core.personal_rule_periods import covered_days_for_personal_rule
from schedule_askue.core.personal_rule_logic import (
    resolve_personal_rule_for_day,
    sort_rules_for_resolution,
)
from schedule_askue.core.shift_codes import WORK_SHIFT_CODES, normalize_shift_code
from schedule_askue.db.models import (
    SHIFT_TYPE_FULL_R,
    SHIFT_TYPE_MIXED,
    SHIFT_TYPE_SPLIT_CH,
    Employee,
    PersonalRule,
    PlannedExtraDayOff,
    PlannedWorkdayAdjustment,
    Rule,
    Wish,
)
from schedule_askue.core.work_norms import employee_base_target_work

logger = logging.getLogger(__name__)

CODE_R = "Р"
CODE_D = "Д"
CODE_OFF = "В"
CODE_VAC = "О"
WORK_CODES = WORK_SHIFT_CODES
WORK_CODES_SET = set(WORK_SHIFT_CODES)


@dataclass(slots=True)
class SchedulerWarning:
    code: str
    message: str


@dataclass(slots=True)
class SchedulerResult:
    assignments: dict[int, dict[int, str]]
    warnings: list[SchedulerWarning]


@dataclass(slots=True)
class DayConstraint:
    exact_shift: str | None = None
    exact_priority: int = -1
    exact_source: str = ""
    allow_shifts: set[str] | None = None
    require_work: bool = False
    prohibit_duty: bool = False
    require_work_priority: int = -1
    desired_shift: str | None = None
    locked_by_wish: bool = False
    locked_by_rule: bool = False


@dataclass(slots=True)
class EmployeeState:
    work_total: int = 0
    duty_total: int = 0
    special_duty_total: int = 0
    work_streak: int = 0
    duty_streak: int = 0
    last_shift: str = CODE_OFF


@dataclass(slots=True)
class EmployeeTarget:
    base_target_work: int
    target_work: int
    min_work: int
    max_work: int
    target_duty: int
    planned_extra_days_off: int = 0
    planned_workday_adjustment: int = 0


@dataclass(slots=True)
class CandidateAssignment:
    shifts: dict[int, str]
    score: int


@dataclass(slots=True)
class DayPatternCandidate:
    duty_target: int
    regular_target: int
    min_staff_required: int
    kind: str
    label: str


@dataclass(slots=True)
class DayPatternSelection:
    pattern: DayPatternCandidate
    assignment: CandidateAssignment


@dataclass(slots=True)
class PatternRoleSlots:
    duty_slots: int
    regular_slots: int
    off_slots: int


@dataclass(slots=True)
class MonthPatternBudget:
    total_target_work: int
    total_duty_budget: int
    total_regular_budget: int
    planned_regular_days: int
    planned_zero_regular_days: int


class PriorityScheduleBuilder:
    def build(
        self,
        year: int,
        month: int,
        employees: list[Employee],
        wishes: list[Wish] | None = None,
        rules: list[Rule] | None = None,
        settings: dict[str, str] | None = None,
        prev_month_schedule: dict[int, dict[int, str]] | None = None,
        next_month_schedule: dict[int, dict[int, str]] | None = None,
        personal_rules: list[PersonalRule] | None = None,
        planned_extra_days_off: list[PlannedExtraDayOff] | None = None,
        planned_workday_adjustments: list[PlannedWorkdayAdjustment] | None = None,
    ) -> SchedulerResult:
        if not employees:
            return SchedulerResult(assignments={}, warnings=[])

        logger.info(
            f"PriorityScheduleBuilder.build({year}-{month:02d}): старт генерації"
        )

        wishes = wishes or []
        rules = [rule for rule in (rules or []) if rule.is_active]
        personal_rules = [rule for rule in (personal_rules or []) if rule.is_active]
        planned_extra_days_off = planned_extra_days_off or []
        planned_workday_adjustments = planned_workday_adjustments or []
        settings = settings or {}
        planned_extra_days_by_employee = self._build_planned_extra_days_map(
            planned_extra_days_off
        )
        planned_workday_adjustments_by_employee = (
            self._build_planned_workday_adjustment_map(planned_workday_adjustments)
        )
        prev_month_schedule = {
            employee_id: {
                day: normalize_shift_code(value) for day, value in days.items()
            }
            for employee_id, days in (prev_month_schedule or {}).items()
        }
        next_month_schedule = {
            employee_id: {
                day: normalize_shift_code(value) for day, value in days.items()
            }
            for employee_id, days in (next_month_schedule or {}).items()
        }

        warnings: list[SchedulerWarning] = []
        month_days = calendar.monthrange(year, month)[1]
        employee_by_id = {
            employee.id or index + 1: employee
            for index, employee in enumerate(employees)
        }
        employee_ids = list(employee_by_id.keys())
        ua_holidays = holidays.Ukraine(years=[year])
        martial_law = self._setting_as_bool(settings.get("martial_law", "1"))
        special_days = special_days_for_month(
            year, month, martial_law=martial_law, ua_holidays=ua_holidays
        )
        constraints = self._build_constraints(
            month_days,
            employee_by_id,
            wishes,
            rules,
            personal_rules,
            special_days,
            warnings,
        )
        targets = self._build_targets(
            year,
            month,
            month_days,
            employee_by_id,
            settings,
            constraints,
            ua_holidays,
            planned_extra_days_by_employee,
            planned_workday_adjustments_by_employee,
        )
        state = {
            employee_id: self._initial_state(employee_id, prev_month_schedule)
            for employee_id in employee_ids
        }
        assignments = {
            employee_id: {day: "" for day in range(1, month_days + 1)}
            for employee_id in employee_ids
        }

        target_duty_per_day = int(
            settings.get(
                "daily_shift_d_count", settings.get("daily_shift_ch_count", "2")
            )
        )
        max_regular_per_day = int(settings.get("max_regular_per_day", "1"))
        max_vacation_overlap = int(settings.get("max_vacation_overlap", "1"))
        month_pattern_budget = self._build_month_pattern_budget(
            year=year,
            month=month,
            targets=targets,
            target_duty_per_day=target_duty_per_day,
            month_days=month_days,
            settings=settings,
            ua_holidays=ua_holidays,
        )

        precheck_issues = self._precheck(
            employee_ids,
            month_days,
            constraints,
            target_duty_per_day,
            max_regular_per_day,
            max_vacation_overlap,
            max_consecutive_work_days=int(
                settings.get("max_consecutive_work_days", "7")
            ),
            hard_max_consecutive_work_days=int(
                settings.get("hard_max_consecutive_work_days", "9")
            ),
        )
        if precheck_issues:
            warnings.append(
                SchedulerWarning(
                    "precheck_failed",
                    "Перед генерацією знайдено конфлікти в побажаннях/правилах. Графік буде зібрано з максимально можливим урахуванням обмежень.",
                )
            )
            warnings.extend(
                SchedulerWarning("precheck_issue", issue) for issue in precheck_issues
            )

        min_staff_by_day = self._build_min_staff_map(rules, month_days)
        previous_day_duty_pair: tuple[int, int] | None = None
        previous_day_duty_block_length = 0
        completed_duty_pair_blocks: dict[tuple[int, int], int] = {}
        last_duty_block_end: dict[int, int] = self._seed_duty_block_end_from_prev_month(
            prev_month_schedule,
            employee_by_id,
        )
        for day in range(1, month_days + 1):
            day_assignment, day_warnings = self._assign_day(
                day=day,
                employee_by_id=employee_by_id,
                employee_ids=employee_ids,
                constraints=constraints,
                desired_duty_count=target_duty_per_day,
                max_regular_per_day=max_regular_per_day,
                special_days=special_days,
                targets=targets,
                state=state,
                month_days=month_days,
                settings=settings,
                min_staff_required=min(
                    min_staff_by_day.get(day, 0),
                    max(
                        target_duty_per_day,
                        min_staff_by_day.get(day, 0)
                        if day not in special_days
                        else target_duty_per_day,
                    ),
                ),
                prev_month_schedule=prev_month_schedule,
                previous_day_duty_pair=previous_day_duty_pair,
                previous_day_duty_block_length=previous_day_duty_block_length,
                completed_duty_pair_blocks=completed_duty_pair_blocks,
                month_pattern_budget=month_pattern_budget,
                last_duty_block_end=last_duty_block_end,
            )
            warnings.extend(day_warnings)
            for employee_id, shift_code in day_assignment.items():
                assignments[employee_id][day] = shift_code
                self._apply_shift_to_state(
                    state[employee_id], shift_code, is_special=day in special_days
                )
            current_duty_pair = tuple(
                sorted(
                    employee_id
                    for employee_id, shift_code in day_assignment.items()
                    if shift_code == CODE_D
                )
            )
            if (
                len(current_duty_pair) == 2
                and current_duty_pair == previous_day_duty_pair
            ):
                previous_day_duty_block_length += 1
                if previous_day_duty_block_length == 2:
                    completed_duty_pair_blocks[current_duty_pair] = (
                        completed_duty_pair_blocks.get(current_duty_pair, 0) + 1
                    )
                    for block_emp_id in current_duty_pair:
                        last_duty_block_end[block_emp_id] = day
            else:
                previous_day_duty_block_length = 1 if len(current_duty_pair) == 2 else 0
            previous_day_duty_pair = (
                current_duty_pair if len(current_duty_pair) == 2 else None
            )

        warnings.extend(
            self._repair_norms(
                assignments=assignments,
                employee_by_id=employee_by_id,
                constraints=constraints,
                targets=targets,
                special_days=special_days,
                settings=settings,
                prev_month_schedule=prev_month_schedule,
            )
        )
        warnings.extend(
            self._repair_planned_extra_days_off(
                assignments=assignments,
                employee_by_id=employee_by_id,
                constraints=constraints,
                targets=targets,
                settings=settings,
                year=year,
                month=month,
                ua_holidays=ua_holidays,
            )
        )
        warnings.extend(
            self._warn_for_unfulfilled_planned_extra_days_off(
                assignments=assignments,
                employee_by_id=employee_by_id,
                targets=targets,
            )
        )
        warnings.extend(
            self._check_post_repair_invariants(
                assignments=assignments,
                employee_by_id=employee_by_id,
                constraints=constraints,
                settings=settings,
                prev_month_schedule=prev_month_schedule,
            )
        )
        warnings.extend(
            self._warn_for_next_month_seam(
                assignments=assignments,
                next_month_schedule=next_month_schedule,
                settings=settings,
            )
        )
        logger.info(
            f"PriorityScheduleBuilder.build({year}-{month:02d}): завершено, {len(warnings)} warnings"
        )
        return SchedulerResult(assignments=assignments, warnings=warnings)

    def _build_constraints(
        self,
        month_days: int,
        employee_by_id: dict[int, Employee],
        wishes: list[Wish],
        rules: list[Rule],
        personal_rules: list[PersonalRule],
        special_days: set[int],
        warnings: list[SchedulerWarning],
    ) -> dict[int, dict[int, DayConstraint]]:
        constraints = {
            employee_id: {day: DayConstraint() for day in range(1, month_days + 1)}
            for employee_id in employee_by_id
        }

        for wish in wishes:
            start_day = max(1, wish.date_from or 1)
            end_day = min(month_days, wish.date_to or start_day)
            exact_shift = self._wish_to_code(wish)
            desired_shift = self._desired_wish_to_code(wish)
            for day in range(start_day, end_day + 1):
                constraint = constraints[wish.employee_id][day]
                if wish.priority == "mandatory":
                    if (
                        constraint.exact_shift
                        and constraint.exact_shift != exact_shift
                        and not constraint.locked_by_wish
                    ):
                        warnings.append(
                            SchedulerWarning(
                                "wish_rule_conflict",
                                f"Побажання працівника {wish.employee_id} на день {day} перекрило попереднє правило.",
                            )
                        )
                    constraint.exact_shift = exact_shift
                    constraint.exact_priority = 1_000_000
                    constraint.exact_source = "wish"
                    constraint.locked_by_wish = True
                    constraint.locked_by_rule = False
                    constraint.require_work = exact_shift in WORK_CODES
                    if exact_shift == CODE_D:
                        constraint.prohibit_duty = False
                elif desired_shift:
                    constraint.desired_shift = desired_shift

        grouped_personal: dict[int, dict[int, list[PersonalRule]]] = {}
        for rule in sort_rules_for_resolution(personal_rules):
            for day in covered_days_for_personal_rule(
                rule,
                month_days=month_days,
                special_days=special_days,
            ):
                grouped_personal.setdefault(rule.employee_id, {}).setdefault(
                    day, []
                ).append(rule)

        for employee_id, by_day in grouped_personal.items():
            for day, rules_for_day in by_day.items():
                constraint = constraints[employee_id][day]
                if constraint.locked_by_wish:
                    continue
                resolved = resolve_personal_rule_for_day(
                    rules_for_day,
                    is_special_day=day in special_days,
                )
                rule_priority = int(
                    resolved.source_rule.priority
                    if resolved.source_rule is not None
                    else 100
                )
                if (
                    resolved.forced_shift is not None
                    and rule_priority >= constraint.exact_priority
                ):
                    constraint.exact_shift = normalize_shift_code(resolved.forced_shift)
                    constraint.exact_priority = rule_priority
                    constraint.exact_source = "personal_rule"
                    constraint.locked_by_rule = True
                    constraint.require_work = constraint.exact_shift in WORK_CODES
                if resolved.allowed_shifts is not None:
                    allowed = {
                        normalize_shift_code(value) for value in resolved.allowed_shifts
                    }
                    constraint.allow_shifts = (
                        allowed
                        if constraint.allow_shifts is None
                        else constraint.allow_shifts & allowed
                    )
                if resolved.prohibit_duty:
                    constraint.prohibit_duty = True
                if (
                    resolved.require_work
                    and rule_priority >= constraint.require_work_priority
                ):
                    constraint.require_work = True
                    constraint.require_work_priority = rule_priority

        ordered_general = sorted(
            [rule for rule in rules if rule.rule_type in {"must_work", "must_off"}],
            key=lambda rule: (
                int(rule.priority),
                1 if rule.scope.startswith("employee:") else 0,
                1 if rule.day is not None else 0,
                int(rule.id or 0),
            ),
            reverse=True,
        )
        for rule in ordered_general:
            target_ids = self._resolve_rule_employee_ids(rule, employee_by_id)
            target_days = self._resolve_rule_days(rule, month_days)
            for employee_id in target_ids:
                for day in target_days:
                    constraint = constraints[employee_id][day]
                    if constraint.locked_by_wish:
                        continue
                    if rule.rule_type == "must_off":
                        if int(rule.priority) >= constraint.exact_priority:
                            constraint.exact_shift = CODE_OFF
                            constraint.exact_priority = int(rule.priority)
                            constraint.exact_source = "rule"
                            constraint.locked_by_rule = True
                            constraint.require_work = False
                    elif rule.rule_type == "must_work":
                        if int(rule.priority) >= constraint.require_work_priority:
                            constraint.require_work = True
                            constraint.require_work_priority = int(rule.priority)
                            if constraint.exact_shift is None:
                                constraint.exact_shift = self._preferred_rule_work_code(
                                    employee_by_id[employee_id],
                                    day,
                                    special_days,
                                )
                                constraint.exact_priority = int(rule.priority)
                                constraint.exact_source = "rule"
                                constraint.locked_by_rule = True
        return constraints

    def _build_targets(
        self,
        year: int,
        month: int,
        month_days: int,
        employee_by_id: dict[int, Employee],
        settings: dict[str, str],
        constraints: dict[int, dict[int, DayConstraint]],
        ua_holidays: holidays.Ukraine,
        planned_extra_days_by_employee: dict[int, int],
        planned_workday_adjustments_by_employee: dict[int, int],
    ) -> dict[int, EmployeeTarget]:
        tolerance = int(settings.get("work_days_tolerance", "0"))
        working_days = self._count_working_days(year, month, settings, ua_holidays)
        target_duty_per_day = int(
            settings.get(
                "daily_shift_d_count", settings.get("daily_shift_ch_count", "2")
            )
        )
        total_duty = target_duty_per_day * month_days

        targets: dict[int, EmployeeTarget] = {}
        for employee_id, employee in employee_by_id.items():
            mandatory_vacations = sum(
                1
                for item in constraints[employee_id].values()
                if item.exact_shift == CODE_VAC
            )
            base_target_work = employee_base_target_work(
                employee,
                working_days=working_days,
                month_days=month_days,
                vacation_days=mandatory_vacations,
            )
            planned_extra_days = max(
                0,
                min(
                    base_target_work, planned_extra_days_by_employee.get(employee_id, 0)
                ),
            )
            planned_workday_adjustment = max(
                0, planned_workday_adjustments_by_employee.get(employee_id, 0)
            )
            target_work = max(
                0,
                min(
                    month_days,
                    base_target_work + planned_workday_adjustment - planned_extra_days,
                ),
            )
            min_work = max(0, target_work - tolerance)
            max_work = min(month_days, target_work + tolerance)
            targets[employee_id] = EmployeeTarget(
                base_target_work=base_target_work,
                target_work=target_work,
                min_work=min_work,
                max_work=max_work,
                target_duty=0,
                planned_extra_days_off=planned_extra_days,
                planned_workday_adjustment=planned_workday_adjustment,
            )

        split_ids = [
            employee_id
            for employee_id, employee in employee_by_id.items()
            if employee.shift_type == SHIFT_TYPE_SPLIT_CH
        ]
        full_r_ids = [
            employee_id
            for employee_id, employee in employee_by_id.items()
            if employee.shift_type == SHIFT_TYPE_FULL_R
        ]
        mixed_ids = [
            employee_id
            for employee_id, employee in employee_by_id.items()
            if employee.shift_type == SHIFT_TYPE_MIXED
        ]
        remaining_duty = total_duty
        if split_ids:
            split_total_target = sum(
                targets[employee_id].target_work for employee_id in split_ids
            )
            for employee_id in split_ids:
                quota = round(
                    total_duty
                    * targets[employee_id].target_work
                    / max(1, split_total_target)
                )
                quota = max(0, min(targets[employee_id].target_work, quota))
                targets[employee_id].target_duty = quota
                remaining_duty -= quota
        remaining_duty = max(0, remaining_duty)
        if full_r_ids:
            for employee_id in full_r_ids:
                targets[employee_id].target_duty = 0
        if mixed_ids:
            mixed_total_target = sum(
                targets[employee_id].target_work for employee_id in mixed_ids
            )
            assigned = 0
            for employee_id in mixed_ids:
                quota = round(
                    remaining_duty
                    * targets[employee_id].target_work
                    / max(1, mixed_total_target)
                )
                quota = max(0, min(targets[employee_id].target_work, quota))
                targets[employee_id].target_duty = quota
                assigned += quota
            remainder = remaining_duty - assigned
            for employee_id in mixed_ids:
                if remainder <= 0:
                    break
                if targets[employee_id].target_duty >= targets[employee_id].target_work:
                    continue
                targets[employee_id].target_duty += 1
                remainder -= 1
        return targets

    def _build_planned_extra_days_map(
        self, planned_extra_days_off: list[PlannedExtraDayOff]
    ) -> dict[int, int]:
        planned_by_employee: dict[int, int] = {}
        for item in planned_extra_days_off:
            planned_by_employee[item.employee_id] = max(0, int(item.planned_days))
        return planned_by_employee

    def _build_planned_workday_adjustment_map(
        self, planned_workday_adjustments: list[PlannedWorkdayAdjustment]
    ) -> dict[int, int]:
        planned_by_employee: dict[int, int] = {}
        for item in planned_workday_adjustments:
            planned_by_employee[item.employee_id] = max(0, int(item.adjustment_days))
        return planned_by_employee

    def _precheck(
        self,
        employee_ids: list[int],
        month_days: int,
        constraints: dict[int, dict[int, DayConstraint]],
        target_duty_per_day: int,
        max_regular_per_day: int,
        max_vacation_overlap: int,
        max_consecutive_work_days: int = 7,
        hard_max_consecutive_work_days: int = 9,
    ) -> list[str]:
        issues: list[str] = []
        for day in range(1, month_days + 1):
            forced_r = 0
            forced_d = 0
            forced_vac = 0
            max_possible_d = 0
            for employee_id in employee_ids:
                constraint = constraints[employee_id][day]
                if constraint.exact_shift == CODE_R:
                    forced_r += 1
                if constraint.exact_shift == CODE_D:
                    forced_d += 1
                if constraint.exact_shift == CODE_VAC:
                    forced_vac += 1
                if self._can_take_duty_by_constraints(constraint):
                    max_possible_d += 1
            if forced_vac > max_vacation_overlap:
                issues.append(
                    f"День {day}: обов'язкових відпусток {forced_vac}, а ліміт {max_vacation_overlap}."
                )
            if forced_d > target_duty_per_day:
                issues.append(
                    f"День {day}: уже зафіксовано {forced_d} чергувань, а ціль {target_duty_per_day}."
                )
            if max_possible_d < target_duty_per_day:
                issues.append(
                    f"День {day}: максимум доступно {max_possible_d} працівників для Д, а потрібно {target_duty_per_day}."
                )
            if forced_r > max_regular_per_day:
                issues.append(
                    f"День {day}: уже зафіксовано {forced_r} змін Р, а денний максимум {max_regular_per_day}."
                )

        for employee_id in employee_ids:
            streak = 0
            streak_start = 0
            for day in range(1, month_days + 1):
                if constraints[employee_id][day].require_work:
                    if streak == 0:
                        streak_start = day
                    streak += 1
                else:
                    if streak > hard_max_consecutive_work_days:
                        issues.append(
                            f"Працівник {employee_id}: require_work підряд {streak} днів (з {streak_start} по {streak_start + streak - 1}), що перевищує безпечний ліміт {hard_max_consecutive_work_days}. Алгоритм зламає streak для безпеки."
                        )
                    elif streak > max_consecutive_work_days:
                        issues.append(
                            f"Працівник {employee_id}: require_work підряд {streak} днів (з {streak_start} по {streak_start + streak - 1}), що перевищує рекомендований ліміт {max_consecutive_work_days}. Правила мають пріоритет — streak буде виконано до безпечного ліміту {hard_max_consecutive_work_days}."
                        )
                    streak = 0
            if streak > hard_max_consecutive_work_days:
                issues.append(
                    f"Працівник {employee_id}: require_work підряд {streak} днів (з {streak_start} по {streak_start + streak - 1}), що перевищує безпечний ліміт {hard_max_consecutive_work_days}. Алгоритм зламає streak для безпеки."
                )
            elif streak > max_consecutive_work_days:
                issues.append(
                    f"Працівник {employee_id}: require_work підряд {streak} днів (з {streak_start} по {streak_start + streak - 1}), що перевищує рекомендований ліміт {max_consecutive_work_days}. Правила мають пріоритет — streak буде виконано до безпечного ліміту {hard_max_consecutive_work_days}."
                )

        return issues

    def _assign_day(
        self,
        *,
        day: int,
        employee_by_id: dict[int, Employee],
        employee_ids: list[int],
        constraints: dict[int, dict[int, DayConstraint]],
        desired_duty_count: int,
        max_regular_per_day: int,
        special_days: set[int],
        targets: dict[int, EmployeeTarget],
        state: dict[int, EmployeeState],
        month_days: int,
        settings: dict[str, str],
        min_staff_required: int,
        prev_month_schedule: dict[int, dict[int, str]],
        previous_day_duty_pair: tuple[int, int] | None,
        previous_day_duty_block_length: int,
        completed_duty_pair_blocks: dict[tuple[int, int], int],
        month_pattern_budget: MonthPatternBudget,
        last_duty_block_end: dict[int, int],
    ) -> tuple[dict[int, str], list[SchedulerWarning]]:
        warnings: list[SchedulerWarning] = []
        is_special = day in special_days
        desired_regular = self._desired_regular_count(
            day=day,
            is_special=is_special,
            settings=settings,
            employee_count=len(employee_ids),
            desired_duty_count=desired_duty_count,
            min_staff_required=min_staff_required,
            max_regular_per_day=max_regular_per_day,
        )
        if day <= 4 and is_special:
            logger.debug(
                "Day %d: is_special=%s, desired_regular=%d (before cap)",
                day,
                is_special,
                desired_regular,
            )
        if day <= 4 and is_special:
            logger.debug(
                "Day %d: is_special=%s, desired_regular=%d (before cap)",
                day,
                is_special,
                desired_regular,
            )
        desired_regular = self._cap_regular_by_month_budget(
            desired_regular=desired_regular,
            day=day,
            month_days=month_days,
            desired_duty_count=desired_duty_count,
            state=state,
            month_pattern_budget=month_pattern_budget,
        )
        max_cw = int(settings.get("max_consecutive_work_days", "7"))
        hard_max_cw = int(settings.get("hard_max_consecutive_work_days", "9"))
        for eid in employee_ids:
            con = constraints[eid][day]
            if not con.require_work:
                continue
            streak = state[eid].work_streak
            if streak >= hard_max_cw:
                con.require_work = False
                con.prohibit_duty = True
                con.allow_shifts = {CODE_OFF}
        options_by_employee: dict[int, list[str]] = {}
        for employee_id in employee_ids:
            options_by_employee[employee_id] = self._candidate_codes(
                employee=employee_by_id[employee_id],
                constraint=constraints[employee_id][day],
                is_special=is_special,
                allow_auto_regular=desired_regular > 0,
                day=day,
                settings=settings,
                employee_state=state[employee_id],
            )
        if day <= 4 and is_special:
            logger.debug(
                "Day %d: desired_regular=%d, options=%s",
                day,
                desired_regular,
                {eid: options_by_employee[eid] for eid in employee_ids},
            )
        duty_capable = sum(
            1 for eid in employee_ids if CODE_D in options_by_employee[eid]
        )
        if duty_capable < desired_duty_count:
            streak_blocked = sorted(
                [
                    eid
                    for eid in employee_ids
                    if CODE_D not in options_by_employee[eid]
                    and constraints[eid][day].exact_shift is None
                    and not constraints[eid][day].prohibit_duty
                    and employee_by_id[eid].shift_type != SHIFT_TYPE_FULL_R
                    and state[eid].work_streak >= max_cw
                ],
                key=lambda eid: state[eid].work_streak,
                reverse=True,
            )
            needed = desired_duty_count - duty_capable
            for eid in streak_blocked[:needed]:
                options_by_employee[eid] = [CODE_D, CODE_OFF]
        forced_r = sum(
            1 for eid in employee_ids if options_by_employee[eid] == [CODE_R]
        )
        forced_d = sum(
            1 for eid in employee_ids if options_by_employee[eid] == [CODE_D]
        )
        max_possible_duty = sum(
            1 for eid in employee_ids if CODE_D in options_by_employee[eid]
        )
        max_possible_work = sum(
            1
            for eid in employee_ids
            if any(c in WORK_CODES_SET for c in options_by_employee[eid])
        )
        max_regular_feasible = min(
            max_regular_per_day,
            sum(1 for eid in employee_ids if CODE_R in options_by_employee[eid]),
            max(0, max_possible_work - desired_duty_count),
        )
        logger.debug(
            "День %d: desired_regular=%d forced_r=%d forced_d=%d "
            "max_regular_per_day=%d max_possible_duty=%d "
            "options={%s}",
            day,
            desired_regular,
            forced_r,
            forced_d,
            max_regular_per_day,
            max_possible_duty,
            ", ".join(f"{eid}:{opts}" for eid, opts in options_by_employee.items()),
        )
        pattern_candidates = self._build_day_pattern_candidates(
            desired_duty_count=desired_duty_count,
            desired_regular=desired_regular,
            min_staff_required=min_staff_required,
            forced_r=forced_r,
            forced_d=forced_d,
            max_possible_duty=max_possible_duty,
            max_regular_feasible=max_regular_feasible,
            max_possible_work=max_possible_work,
            allow_expanded_regular=self._allow_expanded_regular_for_day(
                day=day,
                month_days=month_days,
                desired_duty_count=desired_duty_count,
                desired_regular=desired_regular,
                state=state,
                month_pattern_budget=month_pattern_budget,
            ),
            max_regular_per_day=max_regular_per_day,
        )
        logger.debug(
            "День %d: pattern_candidates=%s",
            day,
            [(c.duty_target, c.regular_target, c.kind) for c in pattern_candidates],
        )

        chosen = self._choose_day_pattern(
            day=day,
            pattern_candidates=pattern_candidates,
            employee_by_id=employee_by_id,
            employee_ids=employee_ids,
            constraints=constraints,
            targets=targets,
            state=state,
            month_days=month_days,
            special_days=special_days,
            settings=settings,
            prev_month_schedule=prev_month_schedule,
            previous_day_duty_pair=previous_day_duty_pair,
            previous_day_duty_block_length=previous_day_duty_block_length,
            completed_duty_pair_blocks=completed_duty_pair_blocks,
            last_duty_block_end=last_duty_block_end,
            options_by_employee=options_by_employee,
        )

        if chosen is None:
            logger.debug(
                "Day %d: fallback — candidates=%s, forced_r=%d, forced_d=%d, desired_regular=%d",
                day,
                [(c.duty_target, c.regular_target, c.kind) for c in pattern_candidates],
                forced_r,
                forced_d,
                desired_regular,
            )
            fallback_assignments: dict[int, str] = {}
            for employee_id in employee_ids:
                fallback_assignments[employee_id] = self._fallback_day_shift(
                    employee_by_id[employee_id],
                    constraints[employee_id][day],
                    is_special=is_special,
                    employee_state=state.get(employee_id),
                    settings=settings,
                    max_regular_per_day=max_regular_per_day,
                    day_regular_count=sum(
                        1
                        for eid, code in fallback_assignments.items()
                        if code == CODE_R
                    ),
                    day_duty_count=sum(
                        1
                        for eid, code in fallback_assignments.items()
                        if code == CODE_D
                    ),
                    desired_duty_count=desired_duty_count,
                )
            fallback = fallback_assignments
            warnings.append(
                SchedulerWarning(
                    "day_assignment_fallback",
                    f"День {day}: не вдалося підібрати повністю коректний патерн, застосовано аварійне заповнення.",
                )
            )
            return fallback, warnings

        chosen_duty = chosen.pattern.duty_target
        chosen_regular = chosen.pattern.regular_target
        if chosen_duty != desired_duty_count:
            warnings.append(
                SchedulerWarning(
                    "daily_duty_relaxed",
                    f"День {day}: вдалося поставити лише {chosen_duty} Д замість цілі {desired_duty_count}.",
                )
            )
        forced_regular_target = min(
            max(forced_r, desired_regular),
            max_regular_per_day,
        )
        regular_relaxed_due_to_forced_r = (
            forced_r > desired_regular and chosen_regular == forced_regular_target
        )
        if chosen_regular != desired_regular and not regular_relaxed_due_to_forced_r:
            warnings.append(
                SchedulerWarning(
                    "daily_regular_relaxed",
                    f"День {day}: патерн зміщено до {chosen_regular} Р замість бажаних {desired_regular}.",
                )
            )
        if chosen_regular > max_regular_per_day:
            warnings.append(
                SchedulerWarning(
                    "daily_regular_exceeded",
                    f"День {day}: патерн {chosen_regular} Р перевищує ліміт {max_regular_per_day}.",
                )
            )
        logger.debug(
            "День %d: chosen duty=%d regular=%d assignments={%s}",
            day,
            chosen_duty,
            chosen_regular,
            ", ".join(
                f"{eid}:{code}" for eid, code in chosen.assignment.shifts.items()
            ),
        )
        return chosen.assignment.shifts, warnings

    def _choose_day_pattern(
        self,
        *,
        day: int,
        pattern_candidates: list[DayPatternCandidate],
        employee_by_id: dict[int, Employee],
        employee_ids: list[int],
        constraints: dict[int, dict[int, DayConstraint]],
        targets: dict[int, EmployeeTarget],
        state: dict[int, EmployeeState],
        month_days: int,
        special_days: set[int],
        settings: dict[str, str],
        prev_month_schedule: dict[int, dict[int, str]],
        previous_day_duty_pair: tuple[int, int] | None,
        previous_day_duty_block_length: int,
        completed_duty_pair_blocks: dict[tuple[int, int], int],
        last_duty_block_end: dict[int, int],
        options_by_employee: dict[int, list[str]] | None = None,
    ) -> DayPatternSelection | None:
        primary_patterns = [
            pattern
            for pattern in pattern_candidates
            if pattern.kind != "expanded_regular"
        ]
        expanded_patterns = [
            pattern
            for pattern in pattern_candidates
            if pattern.kind == "expanded_regular"
        ]

        best_primary = self._choose_best_pattern_from_group(
            patterns=primary_patterns,
            day=day,
            employee_by_id=employee_by_id,
            employee_ids=employee_ids,
            constraints=constraints,
            targets=targets,
            state=state,
            month_days=month_days,
            special_days=special_days,
            settings=settings,
            prev_month_schedule=prev_month_schedule,
            previous_day_duty_pair=previous_day_duty_pair,
            previous_day_duty_block_length=previous_day_duty_block_length,
            completed_duty_pair_blocks=completed_duty_pair_blocks,
            last_duty_block_end=last_duty_block_end,
            options_by_employee=options_by_employee,
        )
        if best_primary is not None:
            return best_primary

        return self._choose_best_pattern_from_group(
            patterns=expanded_patterns,
            day=day,
            employee_by_id=employee_by_id,
            employee_ids=employee_ids,
            constraints=constraints,
            targets=targets,
            state=state,
            month_days=month_days,
            special_days=special_days,
            settings=settings,
            prev_month_schedule=prev_month_schedule,
            previous_day_duty_pair=previous_day_duty_pair,
            previous_day_duty_block_length=previous_day_duty_block_length,
            completed_duty_pair_blocks=completed_duty_pair_blocks,
            last_duty_block_end=last_duty_block_end,
            options_by_employee=options_by_employee,
        )

    def _choose_best_pattern_from_group(
        self,
        *,
        patterns: list[DayPatternCandidate],
        day: int,
        employee_by_id: dict[int, Employee],
        employee_ids: list[int],
        constraints: dict[int, dict[int, DayConstraint]],
        targets: dict[int, EmployeeTarget],
        state: dict[int, EmployeeState],
        month_days: int,
        special_days: set[int],
        settings: dict[str, str],
        prev_month_schedule: dict[int, dict[int, str]],
        previous_day_duty_pair: tuple[int, int] | None,
        previous_day_duty_block_length: int,
        completed_duty_pair_blocks: dict[tuple[int, int], int],
        last_duty_block_end: dict[int, int],
        options_by_employee: dict[int, list[str]] | None = None,
    ) -> DayPatternSelection | None:
        best: DayPatternSelection | None = None
        for pattern in patterns:
            candidate = self._search_day_assignment(
                day=day,
                employee_by_id=employee_by_id,
                employee_ids=employee_ids,
                constraints=constraints,
                targets=targets,
                state=state,
                regular_target=pattern.regular_target,
                duty_target=pattern.duty_target,
                min_staff_required=pattern.min_staff_required,
                month_days=month_days,
                special_days=special_days,
                settings=settings,
                prev_month_schedule=prev_month_schedule,
                previous_day_duty_pair=previous_day_duty_pair,
                previous_day_duty_block_length=previous_day_duty_block_length,
                completed_duty_pair_blocks=completed_duty_pair_blocks,
                last_duty_block_end=last_duty_block_end,
                precomputed_options=options_by_employee,
            )
            if candidate is None:
                continue
            selection = DayPatternSelection(pattern=pattern, assignment=candidate)
            if best is None or selection.assignment.score < best.assignment.score:
                best = selection
        return best

    def _build_day_pattern_candidates(
        self,
        *,
        desired_duty_count: int,
        desired_regular: int,
        min_staff_required: int,
        forced_r: int,
        forced_d: int,
        max_possible_duty: int,
        max_regular_feasible: int,
        max_possible_work: int,
        allow_expanded_regular: bool,
        max_regular_per_day: int,
    ) -> list[DayPatternCandidate]:
        candidates: list[DayPatternCandidate] = []

        if forced_d > desired_duty_count:
            duty_targets = [desired_duty_count]
        elif max_possible_duty < desired_duty_count:
            duty_targets = list(range(max_possible_duty, -1, -1))
        else:
            duty_targets = [desired_duty_count]

        if forced_r > 0:
            capped_regular = min(max(forced_r, desired_regular), max_regular_per_day)
            regular_targets = [capped_regular]
        else:
            regular_targets = list(range(desired_regular, -1, -1))

        for duty_target in duty_targets:
            for regular_target in regular_targets:
                if duty_target + regular_target > max_possible_work:
                    continue
                candidates.append(
                    DayPatternCandidate(
                        duty_target=duty_target,
                        regular_target=regular_target,
                        min_staff_required=min_staff_required,
                        kind="desired"
                        if duty_target == desired_duty_count
                        and regular_target == desired_regular
                        else "relaxed",
                        label=self._pattern_label(
                            desired_regular=desired_regular,
                            regular_target=regular_target,
                            desired_duty_count=desired_duty_count,
                            duty_target=duty_target,
                            kind="desired"
                            if duty_target == desired_duty_count
                            and regular_target == desired_regular
                            else "relaxed",
                        ),
                    )
                )

        if (
            allow_expanded_regular
            and forced_r == 0
            and desired_regular < max_regular_feasible
        ):
            expanded_cap = min(max_regular_feasible, max_regular_per_day)
            for regular_target in range(desired_regular + 1, expanded_cap + 1):
                for duty_target in duty_targets:
                    if duty_target + regular_target > max_possible_work:
                        continue
                    candidates.append(
                        DayPatternCandidate(
                            duty_target=duty_target,
                            regular_target=regular_target,
                            min_staff_required=min_staff_required,
                            kind="expanded_regular",
                            label=self._pattern_label(
                                desired_regular=desired_regular,
                                regular_target=regular_target,
                                desired_duty_count=desired_duty_count,
                                duty_target=duty_target,
                                kind="expanded_regular",
                            ),
                        )
                    )

        deduped: list[DayPatternCandidate] = []
        seen: set[tuple[int, int, int, str]] = set()
        for candidate in candidates:
            key = (
                candidate.duty_target,
                candidate.regular_target,
                candidate.min_staff_required,
                candidate.kind,
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped

    def _pattern_label(
        self,
        *,
        desired_regular: int,
        regular_target: int,
        desired_duty_count: int,
        duty_target: int,
        kind: str,
    ) -> str:
        if kind == "expanded_regular":
            return f"expanded_regular_{regular_target}r_{duty_target}d"
        if duty_target != desired_duty_count:
            return f"relaxed_duty_{regular_target}r_{duty_target}d"
        if regular_target == desired_regular:
            return f"desired_{regular_target}r_{duty_target}d"
        return f"relaxed_regular_{regular_target}r_{duty_target}d"

    def _search_day_assignment(
        self,
        *,
        day: int,
        employee_by_id: dict[int, Employee],
        employee_ids: list[int],
        constraints: dict[int, dict[int, DayConstraint]],
        targets: dict[int, EmployeeTarget],
        state: dict[int, EmployeeState],
        regular_target: int,
        duty_target: int,
        min_staff_required: int,
        month_days: int,
        special_days: set[int],
        settings: dict[str, str],
        prev_month_schedule: dict[int, dict[int, str]],
        previous_day_duty_pair: tuple[int, int] | None,
        previous_day_duty_block_length: int,
        completed_duty_pair_blocks: dict[tuple[int, int], int],
        last_duty_block_end: dict[int, int],
        precomputed_options: dict[int, list[str]] | None = None,
    ) -> CandidateAssignment | None:
        is_special = day in special_days
        role_slots = self._build_pattern_role_slots(
            employee_count=len(employee_ids),
            duty_target=duty_target,
            regular_target=regular_target,
        )
        if precomputed_options is not None:
            options_by_employee = precomputed_options
            for eid in employee_ids:
                if not options_by_employee.get(eid):
                    logger.debug(
                        "Day %d: search skipped — employee %s has empty options",
                        day,
                        employee_by_id[eid].short_name,
                    )
                    return None
            ordered_ids = sorted(
                employee_ids,
                key=lambda employee_id: (
                    len(options_by_employee[employee_id]),
                    0 if constraints[employee_id][day].exact_shift is not None else 1,
                    0
                    if employee_by_id[employee_id].shift_type == SHIFT_TYPE_SPLIT_CH
                    else 1,
                    max(
                        0,
                        state[employee_id].duty_total
                        - targets[employee_id].target_duty,
                    ),
                    max(
                        0,
                        state[employee_id].work_total
                        - targets[employee_id].target_work,
                    ),
                    state[employee_id].duty_total,
                    state[employee_id].work_total,
                    employee_ids.index(employee_id),
                ),
            )
        else:
            options_by_employee, ordered_ids = self._build_pattern_assignment_inputs(
                day=day,
                employee_by_id=employee_by_id,
                employee_ids=employee_ids,
                constraints=constraints,
                is_special=is_special,
                regular_target=regular_target,
                settings=settings,
                state=state,
                targets=targets,
            )
        if options_by_employee is None or ordered_ids is None:
            logger.debug("Day %d: search skipped — no assignment inputs", day)
            return None
        best: CandidateAssignment | None = None

        def search(
            index: int,
            chosen: dict[int, str],
            duty_count: int,
            regular_count: int,
            work_count: int,
        ) -> None:
            nonlocal best
            if duty_count > duty_target or regular_count > regular_target:
                return
            if not self._pattern_branch_feasible(
                ordered_ids=ordered_ids,
                index=index,
                options_by_employee=options_by_employee,
                duty_count=duty_count,
                regular_count=regular_count,
                work_count=work_count,
                duty_target=duty_target,
                regular_target=regular_target,
                min_staff_required=min_staff_required,
            ):
                return

            if index >= len(ordered_ids):
                if (
                    duty_count != duty_target
                    or regular_count != regular_target
                    or work_count < min_staff_required
                ):
                    logger.debug(
                        "Day %d: search complete but mismatch — duty=%d/%d, regular=%d/%d, work=%d/%d",
                        day,
                        duty_count,
                        duty_target,
                        regular_count,
                        regular_target,
                        work_count,
                        min_staff_required,
                    )
                    return
                score = self._score_day_assignment(
                    day=day,
                    chosen=chosen,
                    employee_by_id=employee_by_id,
                    constraints=constraints,
                    targets=targets,
                    state=state,
                    month_days=month_days,
                    special_days=special_days,
                    settings=settings,
                    next_month_schedule={},
                    previous_day_duty_pair=previous_day_duty_pair,
                    previous_day_duty_block_length=previous_day_duty_block_length,
                    completed_duty_pair_blocks=completed_duty_pair_blocks,
                    last_duty_block_end=last_duty_block_end,
                )
                candidate = CandidateAssignment(shifts=dict(chosen), score=score)
                if best is None or candidate.score < best.score:
                    best = candidate
                return

            employee_id = ordered_ids[index]
            employee = employee_by_id[employee_id]
            constraint = constraints[employee_id][day]
            codes_to_try = self._ordered_codes_for_pattern_slots(
                options=options_by_employee[employee_id],
                duty_count=duty_count,
                regular_count=regular_count,
                role_slots=role_slots,
                previous_day_duty_pair=previous_day_duty_pair,
                previous_day_duty_block_length=previous_day_duty_block_length,
                employee_id=employee_id,
                employee_state=state[employee_id],
                employee_target=targets[employee_id],
                employee=employee,
            )
            for code in codes_to_try:
                if (
                    constraint.exact_shift is not None
                    and code != constraint.exact_shift
                ):
                    continue
                if constraint.prohibit_duty and code == CODE_D:
                    continue
                projected_total = state[employee_id].work_total + (
                    1 if code in WORK_CODES else 0
                )
                projected_remaining_max = projected_total + (month_days - day)
                has_work_option = any(
                    c in WORK_CODES_SET for c in options_by_employee[employee_id]
                )
                if (
                    projected_remaining_max < targets[employee_id].min_work
                    and has_work_option
                ):
                    continue
                if projected_total > targets[employee_id].max_work + 1:
                    continue
                chosen[employee_id] = code
                search(
                    index + 1,
                    chosen,
                    duty_count + (1 if code == CODE_D else 0),
                    regular_count + (1 if code == CODE_R else 0),
                    work_count + (1 if code in WORK_CODES else 0),
                )
                chosen.pop(employee_id, None)

        search(0, {}, 0, 0, 0)
        return best

    def _ordered_codes_for_pattern_slots(
        self,
        *,
        options: list[str],
        duty_count: int,
        regular_count: int,
        role_slots: PatternRoleSlots,
        previous_day_duty_pair: tuple[int, int] | None,
        previous_day_duty_block_length: int,
        employee_id: int,
        employee_state: EmployeeState,
        employee_target: EmployeeTarget,
        employee: Employee,
    ) -> list[str]:
        ordered = list(options)
        duties_remaining = max(0, role_slots.duty_slots - duty_count)
        regulars_remaining = max(0, role_slots.regular_slots - regular_count)

        def rank(code: str) -> tuple[int, int]:
            if duties_remaining > 0 and code == CODE_D:
                pair_bonus = 0
                if (
                    previous_day_duty_pair is not None
                    and previous_day_duty_block_length == 1
                ):
                    pair_bonus = 0 if employee_id in previous_day_duty_pair else 1
                quota_rank = self._duty_quota_rank(
                    employee=employee,
                    employee_state=employee_state,
                    employee_target=employee_target,
                )
                return (0, quota_rank + pair_bonus)
            if duties_remaining > 0:
                return (
                    1 if code == CODE_R else 2 if code == CODE_OFF else 3,
                    self._regular_profile_rank(
                        employee, employee_state, employee_target
                    ),
                )
            if regulars_remaining > 0 and code == CODE_R:
                return (
                    0,
                    self._regular_profile_rank(
                        employee, employee_state, employee_target
                    ),
                )
            if regulars_remaining > 0:
                return (1 if code == CODE_OFF else 2 if code == CODE_D else 3, 0)
            if code == CODE_OFF:
                return (0, 0)
            return (1 if code == CODE_R else 2, 0)

        ordered.sort(key=rank)
        return ordered

    def _duty_quota_rank(
        self,
        *,
        employee: Employee,
        employee_state: EmployeeState,
        employee_target: EmployeeTarget,
    ) -> int:
        projected_duty = employee_state.duty_total + 1
        projected_work = employee_state.work_total + 1
        duty_over = max(0, projected_duty - employee_target.target_duty)
        work_over = max(0, projected_work - employee_target.max_work)
        duty_gap = max(0, employee_target.target_duty - projected_duty)
        if work_over > 0:
            return 100 + work_over * 20
        if duty_over > 0:
            return 60 + duty_over * 10
        if employee.shift_type == SHIFT_TYPE_SPLIT_CH:
            base = 0
        elif employee.shift_type == SHIFT_TYPE_MIXED:
            base = 30
        else:
            base = 90
        return base + duty_gap

    def _regular_profile_rank(
        self,
        employee: Employee,
        employee_state: EmployeeState,
        employee_target: EmployeeTarget,
    ) -> int:
        projected_work = employee_state.work_total + 1
        work_gap = max(0, employee_target.target_work - projected_work)
        if employee.shift_type == SHIFT_TYPE_FULL_R:
            base = 0
        elif employee.shift_type == SHIFT_TYPE_MIXED:
            base = 20
        else:
            base = 80
        return base + work_gap

    def _build_pattern_role_slots(
        self, *, employee_count: int, duty_target: int, regular_target: int
    ) -> PatternRoleSlots:
        off_slots = max(0, employee_count - duty_target - regular_target)
        return PatternRoleSlots(
            duty_slots=duty_target, regular_slots=regular_target, off_slots=off_slots
        )

    def _build_pattern_assignment_inputs(
        self,
        *,
        day: int,
        employee_by_id: dict[int, Employee],
        employee_ids: list[int],
        constraints: dict[int, dict[int, DayConstraint]],
        is_special: bool,
        regular_target: int,
        settings: dict[str, str],
        state: dict[int, EmployeeState],
        targets: dict[int, EmployeeTarget],
    ) -> tuple[dict[int, list[str]] | None, list[int] | None]:
        options_by_employee: dict[int, list[str]] = {}
        for employee_id in employee_ids:
            options_by_employee[employee_id] = self._candidate_codes(
                employee=employee_by_id[employee_id],
                constraint=constraints[employee_id][day],
                is_special=is_special,
                allow_auto_regular=regular_target > 0,
                day=day,
                settings=settings,
                employee_state=state[employee_id],
            )
            if not options_by_employee[employee_id]:
                logger.debug(
                    "Day %d: employee %s has empty candidate_codes (require_work=%s, prohibit_duty=%s, exact_shift=%s, shift_type=%s, work_streak=%d, duty_streak=%d)",
                    day,
                    employee_by_id[employee_id].short_name,
                    constraints[employee_id][day].require_work,
                    constraints[employee_id][day].prohibit_duty,
                    constraints[employee_id][day].exact_shift,
                    employee_by_id[employee_id].shift_type,
                    state[employee_id].work_streak,
                    state[employee_id].duty_streak,
                )
                return None, None

        ordered_ids = sorted(
            employee_ids,
            key=lambda employee_id: (
                len(options_by_employee[employee_id]),
                0 if constraints[employee_id][day].exact_shift is not None else 1,
                0
                if employee_by_id[employee_id].shift_type == SHIFT_TYPE_SPLIT_CH
                else 1,
                max(
                    0, state[employee_id].duty_total - targets[employee_id].target_duty
                ),
                max(
                    0, state[employee_id].work_total - targets[employee_id].target_work
                ),
                state[employee_id].duty_total,
                state[employee_id].work_total,
                employee_ids.index(employee_id),
            ),
        )
        return options_by_employee, ordered_ids

    def _pattern_branch_feasible(
        self,
        *,
        ordered_ids: list[int],
        index: int,
        options_by_employee: dict[int, list[str]],
        duty_count: int,
        regular_count: int,
        work_count: int,
        duty_target: int,
        regular_target: int,
        min_staff_required: int,
    ) -> bool:
        remaining_ids = ordered_ids[index:]
        max_possible_duty = duty_count + sum(
            1
            for employee_id in remaining_ids
            if CODE_D in options_by_employee[employee_id]
        )
        min_possible_duty = duty_count + sum(
            1
            for employee_id in remaining_ids
            if options_by_employee[employee_id] == [CODE_D]
        )
        max_possible_regular = regular_count + sum(
            1
            for employee_id in remaining_ids
            if CODE_R in options_by_employee[employee_id]
        )
        min_possible_regular = regular_count + sum(
            1
            for employee_id in remaining_ids
            if options_by_employee[employee_id] == [CODE_R]
        )
        max_possible_work = work_count + sum(
            1
            for employee_id in remaining_ids
            if any(code in WORK_CODES for code in options_by_employee[employee_id])
        )
        feasible = not (
            max_possible_duty < duty_target
            or min_possible_duty > duty_target
            or max_possible_regular < regular_target
            or min_possible_regular > regular_target
            or max_possible_work < min_staff_required
        )
        return feasible

    def _score_day_assignment(
        self,
        *,
        day: int,
        chosen: dict[int, str],
        employee_by_id: dict[int, Employee],
        constraints: dict[int, dict[int, DayConstraint]],
        targets: dict[int, EmployeeTarget],
        state: dict[int, EmployeeState],
        month_days: int,
        special_days: set[int],
        settings: dict[str, str],
        next_month_schedule: dict[int, dict[int, str]],
        previous_day_duty_pair: tuple[int, int] | None,
        previous_day_duty_block_length: int,
        completed_duty_pair_blocks: dict[tuple[int, int], int],
        last_duty_block_end: dict[int, int],
    ) -> int:
        is_special = day in special_days
        busy_start_days = int(settings.get("month_start_full_staff_days", "4"))
        score = 0

        w_split_ch_duty = int(settings.get("scoring_split_ch_duty", "0"))
        w_split_ch_regular = int(settings.get("scoring_split_ch_regular", "80"))
        w_split_ch_off = int(settings.get("scoring_split_ch_off", "8"))
        w_full_r_regular = int(settings.get("scoring_full_r_regular", "-22"))
        w_full_r_duty = int(settings.get("scoring_full_r_duty", "60"))
        w_full_r_off = int(settings.get("scoring_full_r_off", "8"))
        w_mixed_regular = int(settings.get("scoring_mixed_regular", "-14"))
        w_mixed_duty = int(settings.get("scoring_mixed_duty", "4"))
        w_mixed_off = int(settings.get("scoring_mixed_off", "6"))
        w_busy_start_split_ch_non_duty = int(
            settings.get("scoring_busy_start_split_ch_non_duty", "14")
        )
        w_busy_start_full_r_non_regular = int(
            settings.get("scoring_busy_start_full_r_non_regular", "18")
        )
        w_busy_start_mixed_non_regular = int(
            settings.get("scoring_busy_start_mixed_non_regular", "16")
        )
        w_special_day_regular = int(settings.get("scoring_special_day_regular", "40"))
        w_mixed_weekday_duty = int(settings.get("scoring_mixed_weekday_duty", "35"))
        w_mixed_weekday_regular = int(
            settings.get("scoring_mixed_weekday_regular", "-20")
        )
        w_work_deficit = int(settings.get("scoring_work_deficit", "8"))
        w_min_deficit = int(settings.get("scoring_min_deficit", "12"))
        w_off_work_deficit = int(settings.get("scoring_off_work_deficit", "4"))
        w_off_min_deficit = int(settings.get("scoring_off_min_deficit", "10"))
        w_duty_deficit = int(settings.get("scoring_duty_deficit", "6"))
        w_split_ch_duty_deficit = int(
            settings.get("scoring_split_ch_duty_deficit", "4")
        )
        w_desired_shift_match = int(settings.get("scoring_desired_shift_match", "-18"))
        w_desired_shift_mismatch = int(
            settings.get("scoring_desired_shift_mismatch", "7")
        )
        w_streak_continue = int(settings.get("scoring_streak_continue", "-6"))
        w_streak_break_to_off = int(settings.get("scoring_streak_break_to_off", "3"))
        w_streak_start_after_off = int(
            settings.get("scoring_streak_start_after_off", "1")
        )
        w_work_streak_near_max = int(settings.get("scoring_work_streak_near_max", "25"))
        w_duty_streak_near_max = int(settings.get("scoring_duty_streak_near_max", "12"))
        w_split_ch_duty_streak_continue = int(
            settings.get("scoring_split_ch_duty_streak_continue", "8")
        )
        w_require_work_streak_break = int(
            settings.get("scoring_require_work_streak_break", "-30")
        )
        w_locked_by_wish = int(settings.get("scoring_locked_by_wish", "-40"))
        w_locked_by_rule = int(settings.get("scoring_locked_by_rule", "-16"))
        w_weekend_pairing = int(settings.get("scoring_weekend_pairing", "-30"))
        w_duty_first_violation = int(settings.get("scoring_duty_first_violation", "50"))

        desired_duty_count = int(
            settings.get(
                "daily_shift_d_count", settings.get("daily_shift_ch_count", "2")
            )
        )
        day_duty_count = sum(1 for c in chosen.values() if c == CODE_D)

        from datetime import date as dt_date

        try:
            year_val = int(settings.get("year", 0))
            month_val = int(settings.get("month", 0))
            if year_val > 0 and month_val > 0:
                current_date = dt_date(year_val, month_val, day)
                is_weekend = current_date.weekday() >= 5
            else:
                is_weekend = False
        except (ValueError, OverflowError):
            is_weekend = False

        for employee_id, code in chosen.items():
            employee = employee_by_id[employee_id]
            constraint = constraints[employee_id][day]
            employee_state = state[employee_id]
            target = targets[employee_id]
            projected_work = employee_state.work_total + (
                1 if code in WORK_CODES else 0
            )
            work_deficit = max(0, target.target_work - projected_work)
            min_deficit = max(0, target.min_work - projected_work)
            duty_deficit = max(
                0,
                target.target_duty
                - (employee_state.duty_total + (1 if code == CODE_D else 0)),
            )

            if employee.shift_type == SHIFT_TYPE_SPLIT_CH:
                score += (
                    w_split_ch_duty
                    if code == CODE_D
                    else w_split_ch_off + work_deficit * w_off_work_deficit
                )
                if code == CODE_R:
                    score += w_split_ch_regular
            elif employee.shift_type == SHIFT_TYPE_FULL_R:
                if code == CODE_R:
                    score += w_full_r_regular
                elif code == CODE_D:
                    score += w_full_r_duty
                else:
                    score += w_full_r_off + work_deficit * w_off_work_deficit
            else:
                if is_special:
                    if code == CODE_R:
                        score += w_special_day_regular
                    elif code == CODE_D:
                        score += w_mixed_duty
                    else:
                        score += w_mixed_off + work_deficit * w_off_work_deficit
                else:
                    if code == CODE_R:
                        score += w_mixed_weekday_regular
                    elif code == CODE_D:
                        score += w_mixed_weekday_duty
                    else:
                        score += w_mixed_off + work_deficit * w_off_work_deficit

            if day <= busy_start_days:
                if employee.shift_type == SHIFT_TYPE_SPLIT_CH:
                    score += 0 if code == CODE_D else w_busy_start_split_ch_non_duty
                elif employee.shift_type == SHIFT_TYPE_FULL_R:
                    score += 0 if code == CODE_R else w_busy_start_full_r_non_regular
                elif is_special:
                    score += 0 if code == CODE_D else w_busy_start_mixed_non_regular
                else:
                    score += 0 if code == CODE_R else w_busy_start_mixed_non_regular
            elif (
                is_special
                and code == CODE_R
                and employee.shift_type == SHIFT_TYPE_FULL_R
            ):
                score += w_special_day_regular

            if code in WORK_CODES:
                score -= work_deficit * w_work_deficit
                score -= min_deficit * w_min_deficit
            else:
                score += work_deficit * w_off_work_deficit
                score += min_deficit * w_off_min_deficit

            if code == CODE_D:
                score -= duty_deficit * w_duty_deficit
            elif employee.shift_type == SHIFT_TYPE_SPLIT_CH:
                score += duty_deficit * w_split_ch_duty_deficit

            if (
                code == CODE_R
                and employee.shift_type == SHIFT_TYPE_MIXED
                and day_duty_count < desired_duty_count
                and not constraint.require_work
            ):
                score += w_duty_first_violation

            if constraint.desired_shift:
                score += (
                    w_desired_shift_match
                    if code == constraint.desired_shift
                    else w_desired_shift_mismatch
                )
            if employee_state.last_shift == code and code in WORK_CODES:
                score += w_streak_continue
            elif employee_state.last_shift in WORK_CODES and code == CODE_OFF:
                score += w_streak_break_to_off
            elif employee_state.last_shift == CODE_OFF and code in WORK_CODES:
                score += w_streak_start_after_off
            if (
                code in WORK_CODES
                and employee_state.work_streak
                >= int(settings.get("max_consecutive_work_days", "7")) - 1
            ):
                score += w_work_streak_near_max
            if (
                code == CODE_D
                and employee_state.duty_streak
                >= int(settings.get("max_consecutive_duty_days", "5")) - 1
            ):
                score += w_duty_streak_near_max
            if (
                code == CODE_D
                and employee.shift_type == SHIFT_TYPE_SPLIT_CH
                and employee_state.duty_streak >= 4
            ):
                streak_weight = (employee_state.duty_streak - 4) * 12
                score += w_split_ch_duty_streak_continue + streak_weight
            if (
                constraint.require_work
                and code == CODE_OFF
                and employee_state.work_streak
                >= int(settings.get("max_consecutive_work_days", "7")) - 2
            ):
                score += w_require_work_streak_break
            if (
                constraint.require_work
                and code in WORK_CODES
                and employee_state.work_streak
                >= int(settings.get("max_consecutive_work_days", "7"))
            ):
                score += 15
            if constraint.locked_by_wish:
                score += w_locked_by_wish
            elif constraint.locked_by_rule:
                score += w_locked_by_rule

            if (
                is_weekend
                and code == CODE_OFF
                and settings.get("weekend_pairing", "true").lower()
                in ("true", "1", "yes")
            ):
                if employee_state.last_shift == CODE_OFF:
                    score += w_weekend_pairing

        score += self._future_feasibility_penalty(
            day=day, chosen=chosen, targets=targets, state=state, month_days=month_days
        )
        score += self._month_work_budget_penalty(
            day=day,
            chosen=chosen,
            targets=targets,
            state=state,
            month_days=month_days,
            settings=settings,
        )
        score += self._end_of_month_seam_penalty(
            day=day,
            chosen=chosen,
            next_month_schedule=next_month_schedule,
            settings=settings,
        )
        score += self._duty_pair_block_bonus(
            chosen=chosen,
            previous_day_duty_pair=previous_day_duty_pair,
            previous_day_duty_block_length=previous_day_duty_block_length,
        )
        score += self._duty_pair_rotation_penalty(
            chosen=chosen,
            completed_duty_pair_blocks=completed_duty_pair_blocks,
        )
        score += self._duty_rotation_penalty(
            day=day,
            chosen=chosen,
            employee_by_id=employee_by_id,
            constraints=constraints,
            state=state,
        )
        score += self._duty_block_cooldown_penalty(
            day=day,
            chosen=chosen,
            last_duty_block_end=last_duty_block_end,
        )
        score += self._duty_pacing_penalty(
            day=day,
            chosen=chosen,
            employee_by_id=employee_by_id,
            targets=targets,
            state=state,
            month_days=month_days,
        )
        score += self._split_ch_simultaneous_off_penalty(
            day=day,
            chosen=chosen,
            employee_by_id=employee_by_id,
        )
        return score

    def _month_work_budget_penalty(
        self,
        *,
        day: int,
        chosen: dict[int, str],
        targets: dict[int, EmployeeTarget],
        state: dict[int, EmployeeState],
        month_days: int,
        settings: dict[str, str],
    ) -> int:
        total_target_work = sum(target.target_work for target in targets.values())
        current_total_work = sum(
            state[employee_id].work_total for employee_id in targets
        )
        chosen_work = sum(1 for code in chosen.values() if code in WORK_CODES)
        remaining_days = month_days - day
        minimum_future_work = remaining_days * int(
            settings.get(
                "daily_shift_d_count", settings.get("daily_shift_ch_count", "2")
            )
        )
        over_budget = (
            current_total_work + chosen_work + minimum_future_work - total_target_work
        )
        if over_budget <= 0:
            return 0
        return over_budget * 120

    def _duty_pair_block_bonus(
        self,
        *,
        chosen: dict[int, str],
        previous_day_duty_pair: tuple[int, int] | None,
        previous_day_duty_block_length: int,
    ) -> int:
        if previous_day_duty_pair is None or previous_day_duty_block_length != 1:
            return 0
        current_pair = tuple(
            sorted(
                employee_id for employee_id, code in chosen.items() if code == CODE_D
            )
        )
        if len(current_pair) != 2:
            return 0
        if current_pair == previous_day_duty_pair:
            return -24
        if any(employee_id in previous_day_duty_pair for employee_id in current_pair):
            return -6
        return 0

    def _duty_pair_rotation_penalty(
        self,
        *,
        chosen: dict[int, str],
        completed_duty_pair_blocks: dict[tuple[int, int], int],
    ) -> int:
        current_pair = tuple(
            sorted(
                employee_id for employee_id, code in chosen.items() if code == CODE_D
            )
        )
        if len(current_pair) != 2:
            return 0
        completed_blocks = completed_duty_pair_blocks.get(current_pair, 0)
        if completed_blocks <= 0:
            return 0
        return completed_blocks * 18

    def _duty_rotation_penalty(
        self,
        *,
        day: int,
        chosen: dict[int, str],
        employee_by_id: dict[int, Employee],
        constraints: dict[int, dict[int, DayConstraint]],
        state: dict[int, EmployeeState],
    ) -> int:
        penalty = 0
        split_ch_ids = [
            employee_id
            for employee_id, employee in employee_by_id.items()
            if employee.shift_type == SHIFT_TYPE_SPLIT_CH
        ]
        chosen_split_duty = [
            employee_id
            for employee_id in split_ch_ids
            if chosen.get(employee_id) == CODE_D
        ]
        available_split_non_duty = [
            employee_id
            for employee_id in split_ch_ids
            if chosen.get(employee_id) != CODE_D
            and self._can_take_duty_by_constraints(constraints[employee_id][day])
        ]
        if not chosen_split_duty or not available_split_non_duty:
            return 0

        for chosen_id in chosen_split_duty:
            chosen_state = state[chosen_id]
            for alt_id in available_split_non_duty:
                alt_state = state[alt_id]
                duty_delta = chosen_state.duty_total - alt_state.duty_total
                work_delta = chosen_state.work_total - alt_state.work_total
                if duty_delta > 0:
                    penalty += duty_delta * 25
                if work_delta > 0:
                    penalty += work_delta * 8
        return penalty

    def _duty_block_cooldown_penalty(
        self,
        *,
        day: int,
        chosen: dict[int, str],
        last_duty_block_end: dict[int, int],
    ) -> int:
        """
        Penalty for employees on Д who recently completed a 2-day duty block.
        This encourages alternation: after a block ends, those employees should rest
        before starting another block.
        """
        penalty = 0
        for employee_id, code in chosen.items():
            if code != CODE_D:
                continue
            if employee_id not in last_duty_block_end:
                continue
            days_since_block = day - last_duty_block_end[employee_id]
            if days_since_block == 1:
                penalty += 35
            elif days_since_block == 2:
                penalty += 15
        return penalty

    def _duty_pacing_penalty(
        self,
        *,
        day: int,
        chosen: dict[int, str],
        employee_by_id: dict[int, Employee],
        targets: dict[int, EmployeeTarget],
        state: dict[int, EmployeeState],
        month_days: int,
    ) -> int:
        penalty = 0
        progress = day / month_days
        for employee_id, code in chosen.items():
            if code != CODE_D:
                continue
            if employee_by_id[employee_id].shift_type != SHIFT_TYPE_SPLIT_CH:
                continue
            target_duty = targets[employee_id].target_duty
            expected_by_now = progress * target_duty
            surplus = state[employee_id].duty_total + 1 - expected_by_now
            if surplus > 1:
                penalty += int(surplus * 30)
        return penalty

    def _split_ch_simultaneous_off_penalty(
        self,
        *,
        day: int,
        chosen: dict[int, str],
        employee_by_id: dict[int, Employee],
    ) -> int:
        split_ch_ids = [
            eid
            for eid, emp in employee_by_id.items()
            if emp.shift_type == SHIFT_TYPE_SPLIT_CH
        ]
        if len(split_ch_ids) < 2:
            return 0
        all_off = all(chosen.get(eid) == CODE_OFF for eid in split_ch_ids)
        if not all_off:
            return 0
        duty_count = sum(1 for code in chosen.values() if code == CODE_D)
        if duty_count < 2:
            return 200
        return 80

    def _seed_duty_block_end_from_prev_month(
        self,
        prev_month_schedule: dict[int, dict[int, str]],
        employee_by_id: dict[int, Employee],
    ) -> dict[int, int]:
        """
        Scan the last 2-3 days of prev_month_schedule to detect if a duty block
        just completed at month boundary. If so, seed last_duty_block_end for those
        employees so day 1 of current month sees them with cooldown.
        """
        last_duty_block_end: dict[int, int] = {}
        if not prev_month_schedule:
            return last_duty_block_end

        all_prev_days = set()
        for days_dict in prev_month_schedule.values():
            all_prev_days.update(days_dict.keys())
        if not all_prev_days:
            return last_duty_block_end

        sorted_prev_days = sorted(all_prev_days)
        if len(sorted_prev_days) < 2:
            return last_duty_block_end

        last_day = sorted_prev_days[-1]
        second_last_day = sorted_prev_days[-2]

        last_day_duty = set()
        second_last_day_duty = set()

        for employee_id, days_dict in prev_month_schedule.items():
            if (
                last_day in days_dict
                and normalize_shift_code(days_dict[last_day]) == CODE_D
            ):
                last_day_duty.add(employee_id)
            if (
                second_last_day in days_dict
                and normalize_shift_code(days_dict[second_last_day]) == CODE_D
            ):
                second_last_day_duty.add(employee_id)

        if len(last_day_duty) == 2 and last_day_duty == second_last_day_duty:
            for employee_id in last_day_duty:
                last_duty_block_end[employee_id] = 0

        return last_duty_block_end

    def _future_feasibility_penalty(
        self,
        *,
        day: int,
        chosen: dict[int, str],
        targets: dict[int, EmployeeTarget],
        state: dict[int, EmployeeState],
        month_days: int,
    ) -> int:
        penalty = 0
        remaining_days = month_days - day
        for employee_id, code in chosen.items():
            projected_work = state[employee_id].work_total + (
                1 if code in WORK_CODES else 0
            )
            target = targets[employee_id]
            max_possible = projected_work + remaining_days
            if max_possible < target.min_work:
                penalty += 10_000 * (target.min_work - max_possible)
            if projected_work > target.max_work:
                penalty += 500 * (projected_work - target.max_work)
        return penalty

    def _end_of_month_seam_penalty(
        self,
        *,
        day: int,
        chosen: dict[int, str],
        next_month_schedule: dict[int, dict[int, str]],
        settings: dict[str, str],
    ) -> int:
        if not next_month_schedule:
            return 0
        max_consecutive = int(settings.get("max_consecutive_work_days", "7"))
        penalty = 0
        for employee_id, code in chosen.items():
            if code not in WORK_CODES:
                continue
            head = next_month_schedule.get(employee_id, {})
            head_streak = 0
            for next_day in sorted(head):
                if normalize_shift_code(head[next_day]) in WORK_CODES:
                    head_streak += 1
                else:
                    break
            if head_streak + 1 > max_consecutive:
                penalty += 50
        return penalty

    def _repair_norms(
        self,
        *,
        assignments: dict[int, dict[int, str]],
        employee_by_id: dict[int, Employee],
        constraints: dict[int, dict[int, DayConstraint]],
        targets: dict[int, EmployeeTarget],
        special_days: set[int],
        settings: dict[str, str],
        prev_month_schedule: dict[int, dict[int, str]],
    ) -> list[SchedulerWarning]:
        warnings: list[SchedulerWarning] = []
        month_days = len(next(iter(assignments.values()), {}))
        desired_duty = int(
            settings.get(
                "daily_shift_d_count", settings.get("daily_shift_ch_count", "2")
            )
        )
        max_regular = int(settings.get("max_regular_per_day", "1"))
        employee_ids = list(employee_by_id.keys())

        changed = True
        max_iterations = len(employee_ids) * month_days
        iteration = 0
        while changed and iteration < max_iterations:
            changed = False
            iteration += 1
            work_totals = {
                employee_id: sum(
                    1
                    for value in assignments[employee_id].values()
                    if value in WORK_CODES
                )
                for employee_id in employee_ids
            }
            underworked = sorted(
                [
                    employee_id
                    for employee_id in employee_ids
                    if work_totals[employee_id] < targets[employee_id].min_work
                ],
                key=lambda employee_id: (
                    targets[employee_id].min_work - work_totals[employee_id]
                ),
                reverse=True,
            )
            for employee_id in underworked:
                for day in range(1, month_days + 1):
                    if assignments[employee_id][day] != CODE_OFF:
                        continue
                    constraint = constraints[employee_id][day]
                    if (
                        constraint.locked_by_wish
                        or constraint.locked_by_rule
                        or constraint.exact_shift is not None
                    ):
                        continue
                    if (
                        day in special_days
                        and employee_by_id[employee_id].shift_type
                        != SHIFT_TYPE_SPLIT_CH
                    ):
                        continue

                    regular_limit = self._allowed_regular_limit_for_day(
                        day=day,
                        special_days=special_days,
                        settings=settings,
                        desired_duty=desired_duty,
                        employee_count=len(employee_ids),
                        max_regular_per_day=max_regular,
                        forced_regular=sum(
                            1
                            for other_id in employee_ids
                            if constraints[other_id][day].exact_shift == CODE_R
                            or (
                                constraints[other_id][day].require_work
                                and constraints[other_id][day].prohibit_duty
                                and constraints[other_id][day].exact_shift is None
                            )
                        ),
                    )
                    day_regular = sum(
                        1
                        for other_id in employee_ids
                        if assignments[other_id][day] == CODE_R
                    )
                    day_duty = sum(
                        1
                        for other_id in employee_ids
                        if assignments[other_id][day] == CODE_D
                    )

                    if (
                        employee_by_id[employee_id].shift_type != SHIFT_TYPE_SPLIT_CH
                        and day_regular < regular_limit
                        and day not in special_days
                    ):
                        if self._can_assign_work_day(
                            assignments,
                            employee_id,
                            day,
                            CODE_R,
                            settings,
                            prev_month_schedule,
                            require_work=constraint.require_work,
                        ):
                            assignments[employee_id][day] = CODE_R
                            changed = True
                            break

                    if (
                        employee_by_id[employee_id].shift_type != SHIFT_TYPE_FULL_R
                        and self._can_take_duty_by_constraints(constraint)
                        and day_duty < desired_duty
                    ):
                        if self._can_assign_work_day(
                            assignments,
                            employee_id,
                            day,
                            CODE_D,
                            settings,
                            prev_month_schedule,
                            require_work=constraint.require_work,
                        ):
                            assignments[employee_id][day] = CODE_D
                            changed = True
                            break

                    donor_id = self._find_duty_swap_donor(
                        employee_ids=employee_ids,
                        target_employee_id=employee_id,
                        day=day,
                        assignments=assignments,
                        employee_by_id=employee_by_id,
                        constraints=constraints,
                        targets=targets,
                    )
                    if donor_id is None:
                        continue
                    if not self._can_take_duty_by_constraints(
                        constraints[employee_id][day]
                    ):
                        continue
                    if not self._can_assign_work_day(
                        assignments,
                        employee_id,
                        day,
                        CODE_D,
                        settings,
                        prev_month_schedule,
                        require_work=constraints[employee_id][day].require_work,
                    ):
                        continue
                    assignments[employee_id][day] = CODE_D
                    if employee_by_id[donor_id].shift_type == SHIFT_TYPE_SPLIT_CH:
                        assignments[donor_id][day] = CODE_OFF
                    elif day in special_days:
                        assignments[donor_id][day] = CODE_OFF
                    elif day_regular >= regular_limit:
                        assignments[donor_id][day] = CODE_OFF
                    else:
                        assignments[donor_id][day] = CODE_R
                    changed = True
                    break
                if changed:
                    break

        self._rebalance_split_ch_overwork(
            assignments=assignments,
            employee_by_id=employee_by_id,
            constraints=constraints,
            targets=targets,
            special_days=special_days,
            settings=settings,
            prev_month_schedule=prev_month_schedule,
        )

        final_work_totals = {
            employee_id: sum(
                1 for value in assignments[employee_id].values() if value in WORK_CODES
            )
            for employee_id in employee_ids
        }
        for employee_id in employee_ids:
            target = targets[employee_id]
            actual = final_work_totals[employee_id]
            if actual < target.min_work or actual > target.max_work:
                warnings.append(
                    SchedulerWarning(
                        "work_norm_gap",
                        f"{employee_by_id[employee_id].short_name}: не вдалося вкластися в допуск норми ({actual} при цілі {target.target_work}, допуск {target.min_work}-{target.max_work}).",
                    )
                )
        return warnings

    def _rebalance_split_ch_overwork(
        self,
        *,
        assignments: dict[int, dict[int, str]],
        employee_by_id: dict[int, Employee],
        constraints: dict[int, dict[int, DayConstraint]],
        targets: dict[int, EmployeeTarget],
        special_days: set[int],
        settings: dict[str, str],
        prev_month_schedule: dict[int, dict[int, str]],
    ) -> None:
        employee_ids = list(employee_by_id.keys())
        desired_duty = int(
            settings.get(
                "daily_shift_d_count", settings.get("daily_shift_ch_count", "2")
            )
        )
        split_ids = [
            employee_id
            for employee_id in employee_ids
            if employee_by_id[employee_id].shift_type == SHIFT_TYPE_SPLIT_CH
        ]
        mixed_ids = [
            employee_id
            for employee_id in employee_ids
            if employee_by_id[employee_id].shift_type == SHIFT_TYPE_MIXED
        ]
        if not split_ids or not mixed_ids:
            return

        changed = True
        max_iterations = len(employee_ids) * 31
        iteration = 0
        while changed and iteration < max_iterations:
            changed = False
            iteration += 1
            work_totals = {
                employee_id: sum(
                    1
                    for value in assignments[employee_id].values()
                    if value in WORK_CODES
                )
                for employee_id in employee_ids
            }
            duty_totals = {
                employee_id: sum(
                    1 for value in assignments[employee_id].values() if value == CODE_D
                )
                for employee_id in employee_ids
            }
            overworked_split = [
                employee_id
                for employee_id in split_ids
                if work_totals[employee_id] > targets[employee_id].max_work
            ]
            if not overworked_split:
                break

            for donor_id in sorted(
                overworked_split,
                key=lambda employee_id: (
                    work_totals[employee_id] - targets[employee_id].max_work
                ),
                reverse=True,
            ):
                for day in sorted(assignments[donor_id]):
                    if assignments[donor_id][day] != CODE_D:
                        continue
                    donor_constraint = constraints[donor_id][day]
                    if (
                        donor_constraint.locked_by_wish
                        or donor_constraint.locked_by_rule
                    ):
                        continue
                    if (
                        donor_constraint.exact_shift is not None
                        or donor_constraint.require_work
                    ):
                        continue

                    candidate_receivers = []
                    for receiver_id in mixed_ids:
                        if assignments[receiver_id][day] != CODE_R:
                            continue
                        receiver_constraint = constraints[receiver_id][day]
                        if (
                            receiver_constraint.locked_by_wish
                            or receiver_constraint.locked_by_rule
                        ):
                            continue
                        if receiver_constraint.exact_shift is not None:
                            continue
                        if receiver_constraint.require_work:
                            continue
                        if not self._can_take_duty_by_constraints(receiver_constraint):
                            continue
                        candidate_receivers.append(receiver_id)

                    candidate_receivers.sort(
                        key=lambda employee_id: (
                            work_totals[employee_id] - targets[employee_id].target_work,
                            duty_totals[employee_id] - targets[employee_id].target_duty,
                            work_totals[employee_id],
                            duty_totals[employee_id],
                        )
                    )

                    for receiver_id in candidate_receivers:
                        day_duty = sum(
                            1
                            for other_id in employee_ids
                            if assignments[other_id][day] == CODE_D
                        )
                        if day_duty > desired_duty:
                            break
                        assignments[donor_id][day] = CODE_OFF
                        assignments[receiver_id][day] = CODE_D
                        if not self._can_assign_work_day(
                            assignments,
                            receiver_id,
                            day,
                            CODE_D,
                            settings,
                            prev_month_schedule,
                            require_work=constraints[receiver_id][day].require_work,
                        ):
                            assignments[donor_id][day] = CODE_D
                            assignments[receiver_id][day] = CODE_R
                            continue
                        if not self._can_assign_work_day(
                            assignments,
                            donor_id,
                            day,
                            CODE_OFF,
                            settings,
                            prev_month_schedule,
                        ):
                            assignments[donor_id][day] = CODE_D
                            assignments[receiver_id][day] = CODE_R
                            continue
                        changed = True
                        break

                    if changed:
                        break
                if changed:
                    break

    def _check_post_repair_invariants(
        self,
        *,
        assignments: dict[int, dict[int, str]],
        employee_by_id: dict[int, Employee],
        constraints: dict[int, dict[int, DayConstraint]],
        settings: dict[str, str],
        prev_month_schedule: dict[int, dict[int, str]],
    ) -> list[SchedulerWarning]:
        warnings: list[SchedulerWarning] = []
        desired_duty = int(
            settings.get(
                "daily_shift_d_count", settings.get("daily_shift_ch_count", "2")
            )
        )
        max_consecutive_duty = int(settings.get("max_consecutive_duty_days", "5"))
        employee_ids = list(employee_by_id.keys())
        month_days = len(next(iter(assignments.values()), {}))

        for day in range(1, month_days + 1):
            day_duty = sum(
                1 for other_id in employee_ids if assignments[other_id][day] == CODE_D
            )
            if day_duty != desired_duty:
                warnings.append(
                    SchedulerWarning(
                        "post_repair_duty_count",
                        f"Після ремонту: день {day} має {day_duty} Д замість {desired_duty}.",
                    )
                )

        for employee_id in employee_ids:
            duty_streak = 0
            for day in range(1, month_days + 1):
                if assignments[employee_id][day] == CODE_D:
                    duty_streak += 1
                    if duty_streak > max_consecutive_duty:
                        name = employee_by_id[employee_id].short_name
                        warnings.append(
                            SchedulerWarning(
                                "post_repair_duty_streak",
                                f"Після ремонту: {name} має {duty_streak} Д підряд у день {day} (ліміт {max_consecutive_duty}).",
                            )
                        )
                else:
                    duty_streak = 0

            for day in range(1, month_days + 1):
                constraint = constraints[employee_id][day]
                if constraint.prohibit_duty and assignments[employee_id][day] == CODE_D:
                    name = employee_by_id[employee_id].short_name
                    warnings.append(
                        SchedulerWarning(
                            "post_repair_prohibit_duty",
                            f"Після ремонту: {name} має Д у день {day} всупереч правилу prohibit_duty.",
                        )
                    )

        return warnings

    def _repair_planned_extra_days_off(
        self,
        *,
        assignments: dict[int, dict[int, str]],
        employee_by_id: dict[int, Employee],
        constraints: dict[int, dict[int, DayConstraint]],
        targets: dict[int, EmployeeTarget],
        settings: dict[str, str],
        year: int,
        month: int,
        ua_holidays: holidays.Ukraine,
    ) -> list[SchedulerWarning]:
        warnings: list[SchedulerWarning] = []
        if not assignments:
            return warnings

        month_days = len(next(iter(assignments.values()), {}))
        min_staff_by_day = self._build_min_staff_map([], month_days)
        working_day_set = {
            day
            for day in range(1, month_days + 1)
            if date(year, month, day).weekday() < 5
            and not (
                date(year, month, day) in ua_holidays
                and not self._setting_as_bool(settings.get("martial_law", "1"))
            )
        }

        for employee_id, target in targets.items():
            if target.planned_extra_days_off <= 0:
                continue
            actual_work = sum(
                1 for value in assignments[employee_id].values() if value in WORK_CODES
            )
            realized_extra_days = max(0, target.base_target_work - actual_work)
            missing = target.planned_extra_days_off - realized_extra_days
            if missing <= 0:
                continue

            candidate_days = [
                day
                for day, value in assignments[employee_id].items()
                if day in working_day_set
                and value == CODE_R
                and not constraints[employee_id][day].locked_by_wish
                and not constraints[employee_id][day].locked_by_rule
                and constraints[employee_id][day].exact_shift is None
                and not constraints[employee_id][day].require_work
            ]
            for day in candidate_days:
                day_work = sum(
                    1
                    for other_id in employee_by_id
                    if assignments[other_id][day] in WORK_CODES
                )
                min_staff_required = max(
                    int(
                        settings.get(
                            "daily_shift_d_count",
                            settings.get("daily_shift_ch_count", "2"),
                        )
                    ),
                    min_staff_by_day.get(day, 0),
                )
                if day_work - 1 < min_staff_required:
                    continue
                assignments[employee_id][day] = CODE_OFF
                missing -= 1
                if missing <= 0:
                    break

            if missing > 0:
                warnings.append(
                    SchedulerWarning(
                        "planned_extra_day_off_repair_gap",
                        f"{employee_by_id[employee_id].short_name}: repair-прохід не зміг добрати ще {missing} запланованих додаткових вихідних.",
                    )
                )
        return warnings

    def _warn_for_next_month_seam(
        self,
        *,
        assignments: dict[int, dict[int, str]],
        next_month_schedule: dict[int, dict[int, str]],
        settings: dict[str, str],
    ) -> list[SchedulerWarning]:
        if not next_month_schedule:
            return []
        warnings: list[SchedulerWarning] = []
        max_consecutive = int(settings.get("max_consecutive_work_days", "7"))
        for employee_id, days in assignments.items():
            tail_streak = 0
            for day in sorted(days, reverse=True):
                if normalize_shift_code(days[day]) in WORK_CODES:
                    tail_streak += 1
                else:
                    break
            head_days = next_month_schedule.get(employee_id, {})
            head_streak = 0
            for day in sorted(head_days):
                if normalize_shift_code(head_days[day]) in WORK_CODES:
                    head_streak += 1
                else:
                    break
            if tail_streak + head_streak > max_consecutive:
                warnings.append(
                    SchedulerWarning(
                        "next_month_seam",
                        f"Працівник {employee_id}: перехід у наступний місяць дає {tail_streak + head_streak} робочих днів підряд.",
                    )
                )
        return warnings

    def _warn_for_unfulfilled_planned_extra_days_off(
        self,
        *,
        assignments: dict[int, dict[int, str]],
        employee_by_id: dict[int, Employee],
        targets: dict[int, EmployeeTarget],
    ) -> list[SchedulerWarning]:
        warnings: list[SchedulerWarning] = []
        for employee_id, days in assignments.items():
            target = targets[employee_id]
            if target.planned_extra_days_off <= 0:
                continue
            actual_work = sum(1 for value in days.values() if value in WORK_CODES)
            realized_extra_days = max(0, target.base_target_work - actual_work)
            if realized_extra_days >= target.planned_extra_days_off:
                continue
            warnings.append(
                SchedulerWarning(
                    "planned_extra_day_off_gap",
                    f"{employee_by_id[employee_id].short_name}: не вдалося повністю врахувати план додаткових вихідних "
                    f"({realized_extra_days} з {target.planned_extra_days_off}).",
                )
            )
        return warnings

    def _candidate_codes(
        self,
        *,
        employee: Employee,
        constraint: DayConstraint,
        is_special: bool,
        allow_auto_regular: bool,
        day: int,
        settings: dict[str, str],
        employee_state: EmployeeState | None = None,
    ) -> list[str]:
        if constraint.exact_shift is not None:
            return [constraint.exact_shift]
        allowed = {CODE_OFF, CODE_D}
        if allow_auto_regular and (
            not is_special
            or day <= int(settings.get("month_start_full_staff_days", "4"))
        ):
            allowed.add(CODE_R)
        if employee.shift_type == SHIFT_TYPE_FULL_R:
            allowed.discard(CODE_D)
        if constraint.allow_shifts is not None:
            allowed &= constraint.allow_shifts
        if constraint.prohibit_duty:
            allowed.discard(CODE_D)
        if constraint.require_work:
            allowed.discard(CODE_OFF)
        max_consecutive_work = int(settings.get("max_consecutive_work_days", "7"))
        hard_max_consecutive_work = int(
            settings.get("hard_max_consecutive_work_days", "9")
        )
        if employee_state is not None:
            if employee_state.work_streak >= hard_max_consecutive_work:
                allowed -= WORK_CODES_SET
            elif employee_state.work_streak >= max_consecutive_work:
                if not constraint.require_work:
                    allowed -= WORK_CODES_SET
            if constraint.require_work and not (allowed & WORK_CODES_SET):
                allowed.add(CODE_OFF)
        if not allowed:
            return []
        preferred_order = (
            [CODE_D, CODE_OFF, CODE_R]
            if employee.shift_type == SHIFT_TYPE_SPLIT_CH
            else [CODE_R, CODE_D, CODE_OFF]
        )
        return [code for code in preferred_order if code in allowed]

    def _fallback_day_shift(
        self,
        employee: Employee,
        constraint: DayConstraint,
        *,
        is_special: bool,
        employee_state: EmployeeState | None = None,
        settings: dict[str, str] | None = None,
        max_regular_per_day: int = 1,
        day_regular_count: int = 0,
        day_duty_count: int = 0,
        desired_duty_count: int = 2,
    ) -> str:
        if constraint.exact_shift is not None:
            return constraint.exact_shift
        hard_max_cw = (
            int(settings.get("hard_max_consecutive_work_days", "9")) if settings else 9
        )
        at_hard_limit = (
            employee_state is not None and employee_state.work_streak >= hard_max_cw
        )
        regular_full = day_regular_count >= max_regular_per_day
        duty_needs = day_duty_count < desired_duty_count
        if constraint.require_work and not at_hard_limit:
            if duty_needs and not constraint.prohibit_duty:
                return CODE_D
            if not is_special and not regular_full:
                return CODE_R
            if not constraint.prohibit_duty and duty_needs:
                return CODE_D
            if not regular_full:
                return CODE_R
            return CODE_OFF
        if constraint.require_work and at_hard_limit:
            return CODE_OFF
        if constraint.allow_shifts:
            for code in (CODE_D, CODE_R, CODE_OFF):
                if code in constraint.allow_shifts:
                    if code == CODE_R and regular_full:
                        continue
                    return code
        if duty_needs and not constraint.prohibit_duty:
            return CODE_D
        if not is_special and not regular_full:
            return CODE_R
        return CODE_OFF

    def _find_duty_swap_donor(
        self,
        *,
        employee_ids: list[int],
        target_employee_id: int,
        day: int,
        assignments: dict[int, dict[int, str]],
        employee_by_id: dict[int, Employee],
        constraints: dict[int, dict[int, DayConstraint]],
        targets: dict[int, EmployeeTarget],
    ) -> int | None:
        work_totals = {
            employee_id: sum(
                1 for value in assignments[employee_id].values() if value in WORK_CODES
            )
            for employee_id in employee_ids
        }
        donors = [
            employee_id
            for employee_id in employee_ids
            if employee_id != target_employee_id
            and assignments[employee_id][day] == CODE_D
            and not constraints[employee_id][day].locked_by_wish
            and not constraints[employee_id][day].locked_by_rule
            and not constraints[employee_id][day].require_work
            and constraints[employee_id][day].exact_shift is None
        ]
        donors.sort(
            key=lambda employee_id: (
                0
                if employee_by_id[employee_id].shift_type != SHIFT_TYPE_SPLIT_CH
                else 1,
                -(work_totals[employee_id] - targets[employee_id].target_work),
                -sum(
                    1 for value in assignments[employee_id].values() if value == CODE_D
                ),
            )
        )
        return donors[0] if donors else None

    def _can_assign_work_day(
        self,
        assignments: dict[int, dict[int, str]],
        employee_id: int,
        day: int,
        shift_code: str,
        settings: dict[str, str],
        prev_month_schedule: dict[int, dict[int, str]],
        *,
        require_work: bool = False,
    ) -> bool:
        max_consecutive = int(settings.get("max_consecutive_work_days", "7"))
        hard_max_consecutive = int(settings.get("hard_max_consecutive_work_days", "9"))
        max_consecutive_duty = int(settings.get("max_consecutive_duty_days", "5"))
        streak = 0
        duty_streak = 0
        check_day = day - 1
        while check_day >= 1:
            if assignments[employee_id].get(check_day) in WORK_CODES:
                streak += 1
                if assignments[employee_id].get(check_day) == CODE_D:
                    duty_streak += 1
                else:
                    duty_streak = 0
                check_day -= 1
            else:
                break
        if check_day < 1:
            prev = prev_month_schedule.get(employee_id, {})
            for prev_day in sorted(prev, reverse=True):
                normalized = normalize_shift_code(prev[prev_day])
                if normalized in WORK_CODES:
                    streak += 1
                    if normalized == CODE_D:
                        duty_streak += 1
                    else:
                        duty_streak = 0
                else:
                    break
        effective_max = hard_max_consecutive if require_work else max_consecutive
        if shift_code in WORK_CODES and streak >= effective_max:
            return False
        if shift_code == CODE_D and duty_streak >= max_consecutive_duty:
            return False
        return True

    def _apply_shift_to_state(
        self, state: EmployeeState, shift_code: str, *, is_special: bool
    ) -> None:
        if shift_code in WORK_CODES:
            state.work_total += 1
            state.work_streak += 1
            state.last_shift = shift_code
            if shift_code == CODE_D:
                state.duty_total += 1
                state.duty_streak += 1
                if is_special:
                    state.special_duty_total += 1
            else:
                state.duty_streak = 0
        else:
            state.work_streak = 0
            state.duty_streak = 0
            state.last_shift = shift_code

    def _initial_state(
        self, employee_id: int, prev_month_schedule: dict[int, dict[int, str]]
    ) -> EmployeeState:
        prev_days = prev_month_schedule.get(employee_id, {})
        if not prev_days:
            return EmployeeState()
        normalized = {
            day: normalize_shift_code(value) for day, value in prev_days.items()
        }
        work_streak = 0
        duty_streak = 0
        last_shift = CODE_OFF
        for day in sorted(normalized, reverse=True):
            current = normalized[day]
            if last_shift == CODE_OFF:
                last_shift = current
            if current in WORK_CODES:
                work_streak += 1
            else:
                break
        for day in sorted(normalized, reverse=True):
            if normalized[day] == CODE_D:
                duty_streak += 1
            else:
                break
        return EmployeeState(
            work_streak=work_streak, duty_streak=duty_streak, last_shift=last_shift
        )

    def _desired_regular_count(
        self,
        *,
        day: int,
        is_special: bool,
        settings: dict[str, str],
        employee_count: int,
        desired_duty_count: int,
        min_staff_required: int,
        max_regular_per_day: int,
    ) -> int:
        busy_start_days = int(settings.get("month_start_full_staff_days", "4"))
        weekday_target = int(settings.get("weekday_regular_target", "1"))
        special_target = int(settings.get("special_day_regular_target", "0"))
        busy_target = int(settings.get("month_start_regular_per_day", "1"))
        desired_regular = (
            busy_target
            if day <= busy_start_days and not is_special
            else (special_target if is_special else weekday_target)
        )
        if not is_special:
            desired_regular = max(
                desired_regular, max(0, min_staff_required - desired_duty_count)
            )
        desired_regular = min(
            desired_regular,
            max_regular_per_day,
            max(0, employee_count - desired_duty_count),
        )
        return desired_regular

    def _cap_regular_by_month_budget(
        self,
        *,
        desired_regular: int,
        day: int,
        month_days: int,
        desired_duty_count: int,
        state: dict[int, EmployeeState],
        month_pattern_budget: MonthPatternBudget,
    ) -> int:
        if desired_regular <= 0:
            return 0
        current_total_work = sum(
            employee_state.work_total for employee_state in state.values()
        )
        remaining_days_after_today = month_days - day
        minimum_future_work = remaining_days_after_today * desired_duty_count
        available_today_work = (
            month_pattern_budget.total_target_work
            - current_total_work
            - minimum_future_work
        )
        if available_today_work <= desired_duty_count:
            return 0
        max_today_regular = available_today_work - desired_duty_count
        return max(0, min(desired_regular, max_today_regular))

    def _allow_expanded_regular_for_day(
        self,
        *,
        day: int,
        month_days: int,
        desired_duty_count: int,
        desired_regular: int,
        state: dict[int, EmployeeState],
        month_pattern_budget: MonthPatternBudget,
    ) -> bool:
        if desired_regular <= 0:
            return False
        current_total_work = sum(
            employee_state.work_total for employee_state in state.values()
        )
        chosen_work = desired_duty_count + desired_regular
        remaining_days_after_today = month_days - day
        minimum_future_work = remaining_days_after_today * desired_duty_count
        available_after_today = (
            month_pattern_budget.total_target_work
            - current_total_work
            - chosen_work
            - minimum_future_work
        )
        used_regular_budget = current_total_work - ((day - 1) * desired_duty_count)
        remaining_regular_budget = (
            month_pattern_budget.total_regular_budget - used_regular_budget
        )
        return available_after_today > 0 and remaining_regular_budget > desired_regular

    def _build_month_pattern_budget(
        self,
        *,
        year: int,
        month: int,
        targets: dict[int, EmployeeTarget],
        target_duty_per_day: int,
        month_days: int,
        settings: dict[str, str],
        ua_holidays: holidays.Ukraine,
    ) -> MonthPatternBudget:
        total_target_work = sum(target.target_work for target in targets.values())
        total_duty_budget = target_duty_per_day * month_days
        total_regular_budget = max(0, total_target_work - total_duty_budget)
        busy_start_days = int(settings.get("month_start_full_staff_days", "4"))
        weekday_target = int(settings.get("weekday_regular_target", "1"))
        special_target = int(settings.get("special_day_regular_target", "0"))
        busy_target = int(settings.get("month_start_regular_per_day", "1"))
        special_days = special_days_for_month(
            year,
            month,
            martial_law=self._setting_as_bool(settings.get("martial_law", "1")),
            ua_holidays=ua_holidays,
        )
        planned_regular_days = 0
        for day in range(1, month_days + 1):
            if day <= busy_start_days and day not in special_days:
                desired_regular = busy_target
            else:
                desired_regular = (
                    special_target if day in special_days else weekday_target
                )
            if desired_regular > 0:
                planned_regular_days += 1
        return MonthPatternBudget(
            total_target_work=total_target_work,
            total_duty_budget=total_duty_budget,
            total_regular_budget=total_regular_budget,
            planned_regular_days=planned_regular_days,
            planned_zero_regular_days=month_days - planned_regular_days,
        )

    def _allowed_regular_limit_for_day(
        self,
        *,
        day: int,
        special_days: set[int],
        settings: dict[str, str],
        desired_duty: int,
        employee_count: int,
        max_regular_per_day: int,
        forced_regular: int,
    ) -> int:
        if forced_regular > 0:
            desired = self._desired_regular_count(
                day=day,
                is_special=day in special_days,
                settings=settings,
                employee_count=employee_count,
                desired_duty_count=desired_duty,
                min_staff_required=0,
                max_regular_per_day=max_regular_per_day,
            )
            return min(max(forced_regular, desired), max_regular_per_day)
        return self._desired_regular_count(
            day=day,
            is_special=day in special_days,
            settings=settings,
            employee_count=employee_count,
            desired_duty_count=desired_duty,
            min_staff_required=0,
            max_regular_per_day=max_regular_per_day,
        )

    def _build_min_staff_map(
        self, rules: list[Rule], month_days: int
    ) -> dict[int, int]:
        min_staff_by_day: dict[int, int] = {}
        for rule in rules:
            if rule.rule_type != "min_staff":
                continue
            params = self._parse_rule_params(rule.params)
            required = int(params.get("value", 0) or 0)
            if required <= 0:
                continue
            for day in self._resolve_rule_days(rule, month_days):
                min_staff_by_day[day] = max(min_staff_by_day.get(day, 0), required)
        return min_staff_by_day

    def _can_take_duty_by_constraints(self, constraint: DayConstraint) -> bool:
        if constraint.exact_shift == CODE_D:
            return True
        if constraint.exact_shift in {CODE_R, CODE_OFF, CODE_VAC}:
            return False
        if constraint.prohibit_duty:
            return False
        if (
            constraint.allow_shifts is not None
            and CODE_D not in constraint.allow_shifts
        ):
            return False
        return True

    def _preferred_rule_work_code(
        self, employee: Employee, day: int, special_days: set[int]
    ) -> str:
        if employee.shift_type == SHIFT_TYPE_SPLIT_CH:
            return CODE_D
        return CODE_D if day in special_days else CODE_R

    def _wish_to_code(self, wish: Wish) -> str:
        if wish.wish_type == "work_day":
            normalized = normalize_shift_code(wish.comment)
            if normalized in {CODE_R, CODE_D}:
                return normalized
            return CODE_R
        mapping = {"vacation": CODE_VAC, "day_off": CODE_OFF, "work_day": CODE_R}
        return mapping.get(wish.wish_type, CODE_OFF)

    def _desired_wish_to_code(self, wish: Wish) -> str | None:
        if wish.priority != "desired":
            return None
        if wish.wish_type == "vacation":
            return CODE_OFF
        return self._wish_to_code(wish)

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

    def _resolve_rule_days(self, rule: Rule, month_days: int) -> list[int]:
        if rule.day is None:
            return list(range(1, month_days + 1))
        if 1 <= rule.day <= month_days:
            return [rule.day]
        return []

    def _parse_rule_params(self, raw: str) -> dict[str, object]:
        try:
            value = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def _count_working_days(
        self,
        year: int,
        month: int,
        settings: dict[str, str],
        ua_holidays: holidays.Ukraine,
    ) -> int:
        martial_law = self._setting_as_bool(settings.get("martial_law", "1"))
        month_days = calendar.monthrange(year, month)[1]
        count = 0
        for day in range(1, month_days + 1):
            current_date = date(year, month, day)
            if current_date.weekday() >= 5:
                continue
            if current_date in ua_holidays and not martial_law:
                continue
            count += 1
        return count

    def _setting_as_bool(self, raw: str | None) -> bool:
        return str(raw or "").strip().lower() not in {"", "0", "false", "no", "off"}
