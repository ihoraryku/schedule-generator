from __future__ import annotations

import json
import logging
import sys
import traceback
from dataclasses import asdict

from schedule_askue.core.generator import ScheduleGenerator
from schedule_askue.db.models import (
    Employee,
    PersonalRule,
    PlannedExtraDayOff,
    PlannedWorkdayAdjustment,
    Rule,
    Wish,
)

logger = logging.getLogger(__name__)


def _employee_from_dict(data: dict[str, object]) -> Employee:
    return Employee(**data)


def _wish_from_dict(data: dict[str, object]) -> Wish:
    return Wish(**data)


def _rule_from_dict(data: dict[str, object]) -> Rule:
    return Rule(**data)


def _personal_rule_from_dict(data: dict[str, object]) -> PersonalRule:
    return PersonalRule(**data)


def _planned_extra_day_off_from_dict(data: dict[str, object]) -> PlannedExtraDayOff:
    return PlannedExtraDayOff(**data)


def _planned_workday_adjustment_from_dict(
    data: dict[str, object],
) -> PlannedWorkdayAdjustment:
    return PlannedWorkdayAdjustment(**data)


def _normalize_assignments(
    assignments: dict[int, dict[int, str]],
) -> dict[str, dict[str, str]]:
    return {
        str(employee_id): {str(day): value for day, value in days.items()}
        for employee_id, days in assignments.items()
    }


def main() -> int:
    try:
        raw_payload = sys.stdin.read()
        payload = json.loads(raw_payload or "{}")
        generator = ScheduleGenerator()
        result = generator.generate(
            int(payload["year"]),
            int(payload["month"]),
            [_employee_from_dict(item) for item in payload.get("employees", [])],
            wishes=[_wish_from_dict(item) for item in payload.get("wishes", [])],
            rules=[_rule_from_dict(item) for item in payload.get("rules", [])],
            settings={
                str(key): str(value)
                for key, value in payload.get("settings", {}).items()
            },
            prev_month_schedule={
                int(employee_id): {int(day): str(value) for day, value in days.items()}
                for employee_id, days in payload.get("prev_month_schedule", {}).items()
            },
            next_month_schedule={
                int(employee_id): {int(day): str(value) for day, value in days.items()}
                for employee_id, days in payload.get("next_month_schedule", {}).items()
            },
            personal_rules=[
                _personal_rule_from_dict(item)
                for item in payload.get("personal_rules", [])
            ],
            planned_extra_days_off=[
                _planned_extra_day_off_from_dict(item)
                for item in payload.get("planned_extra_days_off", [])
            ],
            planned_workday_adjustments=[
                _planned_workday_adjustment_from_dict(item)
                for item in payload.get("planned_workday_adjustments", [])
            ],
        )
        response = {
            "status": "ok",
            "assignments": _normalize_assignments(result.assignments),
            "warnings": [asdict(warning) for warning in result.warnings],
        }
        sys.stdout.write(json.dumps(response, ensure_ascii=False))
        sys.stdout.flush()
        return 0
    except Exception as exc:
        response = {
            "status": "error",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        sys.stdout.write(json.dumps(response, ensure_ascii=False))
        sys.stdout.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
