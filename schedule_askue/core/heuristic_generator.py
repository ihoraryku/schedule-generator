from __future__ import annotations

import logging

from schedule_askue.core.priority_scheduler import PriorityScheduleBuilder
from schedule_askue.db.models import Employee, PersonalRule, PlannedExtraDayOff, Rule, Wish

logger = logging.getLogger(__name__)


class HeuristicScheduleGenerator:
    """
    Історична назва залишена для сумісності.
    Фактична генерація виконується новим пріоритетним планувальником.
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
    ) -> dict[int, dict[int, str]]:
        settings_with_year_month = dict(settings or {})
        settings_with_year_month["year"] = str(year)
        settings_with_year_month["month"] = str(month)
        return self._builder.build(
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
        ).assignments
