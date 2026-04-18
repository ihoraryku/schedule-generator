from __future__ import annotations

import logging
from dataclasses import dataclass

from schedule_askue.core.priority_scheduler import PriorityScheduleBuilder
from schedule_askue.db.models import (
    Employee,
    PersonalRule,
    PlannedExtraDayOff,
    PlannedWorkdayAdjustment,
    Rule,
    Wish,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GenerationWarning:
    code: str
    message: str


@dataclass(slots=True)
class GenerationResult:
    assignments: dict[int, dict[int, str]]
    warnings: list[GenerationWarning]


class ScheduleGenerator:
    """
    Пріоритет генерації:
    1. Побажання
    2. Правила
    3. Автоматичний розподіл
    """

    def __init__(self) -> None:
        self._builder = PriorityScheduleBuilder()

    def generate(
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
    ) -> GenerationResult:
        logger.info(
            f"Генерація графіка {year}-{month:02d}: {len(employees)} працівників, {len(wishes or [])} побажань, {len(rules or [])} правил"
        )
        settings_with_year_month = dict(settings or {})
        settings_with_year_month["year"] = str(year)
        settings_with_year_month["month"] = str(month)
        result = self._builder.build(
            year=year,
            month=month,
            employees=employees,
            wishes=wishes,
            rules=rules,
            settings=settings_with_year_month,
            prev_month_schedule=prev_month_schedule,
            next_month_schedule=next_month_schedule,
            personal_rules=personal_rules,
            planned_extra_days_off=planned_extra_days_off,
            planned_workday_adjustments=planned_workday_adjustments,
        )
        logger.info(f"Генерація завершена: {len(result.warnings)} warnings")
        return GenerationResult(
            assignments=result.assignments,
            warnings=[
                GenerationWarning(code=item.code, message=item.message)
                for item in result.warnings
            ],
        )
