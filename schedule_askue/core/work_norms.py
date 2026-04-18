from __future__ import annotations

from schedule_askue.db.models import Employee


CODE_VAC = "О"
WORK_CODES = {"Р", "Д"}


def employee_base_target_work(
    employee: Employee,
    *,
    working_days: int,
    month_days: int,
    vacation_days: int = 0,
) -> int:
    return max(
        0,
        min(
            month_days,
            round(working_days * employee.rate) - max(0, vacation_days),
        ),
    )


def count_vacation_days(days: dict[int, str]) -> int:
    return sum(1 for value in days.values() if value == CODE_VAC)


def count_actual_work_days(days: dict[int, str]) -> int:
    return sum(1 for value in days.values() if value in WORK_CODES)


def employee_work_delta(
    employee: Employee,
    *,
    days: dict[int, str],
    working_days: int,
    month_days: int,
) -> tuple[int, int, int]:
    vacation_days = count_vacation_days(days)
    target = employee_base_target_work(
        employee,
        working_days=working_days,
        month_days=month_days,
        vacation_days=vacation_days,
    )
    actual = count_actual_work_days(days)
    return actual, target, actual - target


def employee_effective_target_work(
    employee: Employee,
    *,
    days: dict[int, str],
    working_days: int,
    month_days: int,
    planned_extra_days_off: int = 0,
    planned_workday_adjustment: int = 0,
) -> tuple[int, int, int]:
    actual, base_target, _ = employee_work_delta(
        employee,
        days=days,
        working_days=working_days,
        month_days=month_days,
    )
    effective_target = max(
        0,
        min(
            month_days,
            base_target
            + max(0, planned_workday_adjustment)
            - max(0, planned_extra_days_off),
        ),
    )
    return actual, effective_target, actual - effective_target
