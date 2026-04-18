from __future__ import annotations

from dataclasses import dataclass

from schedule_askue.core.work_norms import employee_effective_target_work
from schedule_askue.db.models import (
    Employee,
    PlannedExtraDayOff,
    PlannedWorkdayAdjustment,
)


@dataclass(slots=True)
class CompensationRecommendation:
    employee_id: int
    employee_name: str
    delta_days: int
    kind: str
    message: str


def build_compensation_recommendations(
    *,
    employees: list[Employee],
    assignments: dict[int, dict[int, str]],
    working_days: int,
    month_days: int,
    extra_off_balances: dict[int, int],
    planned_extra_days_off: dict[int, PlannedExtraDayOff],
    planned_workday_adjustments: dict[int, PlannedWorkdayAdjustment],
) -> list[CompensationRecommendation]:
    recommendations: list[CompensationRecommendation] = []
    for employee in employees:
        employee_id = employee.id or 0
        current_plan = planned_extra_days_off.get(employee_id)
        current_adjustment = planned_workday_adjustments.get(employee_id)
        actual, target, delta = employee_effective_target_work(
            employee,
            days=assignments.get(employee_id, {}),
            working_days=working_days,
            month_days=month_days,
            planned_extra_days_off=(
                current_plan.planned_days if current_plan is not None else 0
            ),
            planned_workday_adjustment=(
                current_adjustment.adjustment_days
                if current_adjustment is not None
                else 0
            ),
        )
        if delta == 0:
            continue

        if delta < 0:
            missing = abs(delta)
            balance = extra_off_balances.get(employee_id, 0)
            available_balance = max(
                0,
                balance
                - (current_plan.planned_days if current_plan is not None else 0),
            )
            if available_balance > 0:
                message = (
                    f"Недобір {missing} дн. | факт {actual}, скоригована норма {target}.\n"
                    f"Можна: до {min(missing, available_balance)} дн. вихідними в цьому місяці або {missing} дн. у роботу наступного місяця."
                )
            else:
                message = (
                    f"Недобір {missing} дн. | факт {actual}, скоригована норма {target}.\n"
                    f"Баланс вихідних вичерпано. Рекомендовано перенести {missing} дн. у роботу наступного місяця."
                )
            recommendations.append(
                CompensationRecommendation(
                    employee_id=employee_id,
                    employee_name=employee.short_name,
                    delta_days=delta,
                    kind="underwork",
                    message=message,
                )
            )
            continue

        overwork = delta
        next_month_extra_off = overwork
        current_carry = (
            current_adjustment.adjustment_days if current_adjustment is not None else 0
        )
        message = (
            f"Переробка {overwork} дн. | факт {actual}, скоригована норма {target}.\n"
            f"Можна: {next_month_extra_off} дн. вихідних на наступний місяць або {overwork} дн. в баланс вихідних."
        )
        if current_carry > 0:
            message += f"\nУже є перенесення роботи на цей місяць: {current_carry} дн."
        recommendations.append(
            CompensationRecommendation(
                employee_id=employee_id,
                employee_name=employee.short_name,
                delta_days=delta,
                kind="overwork",
                message=message,
            )
        )

    return recommendations
