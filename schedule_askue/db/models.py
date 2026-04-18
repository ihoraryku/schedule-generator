from __future__ import annotations

from dataclasses import dataclass


SHIFT_TYPE_MIXED = "mixed"
SHIFT_TYPE_FULL_R = "full_R"
SHIFT_TYPE_SPLIT_CH = "split_CH"


@dataclass(slots=True)
class Employee:
    id: int | None
    full_name: str
    short_name: str
    shift_type: str
    rate: float = 1.0
    position: str = ""
    is_active: bool = True
    sort_order: int = 0


@dataclass(slots=True)
class Wish:
    id: int | None
    employee_id: int
    year: int
    month: int
    wish_type: str
    date_from: int | None = None
    date_to: int | None = None
    priority: str = "desired"
    use_extra_day_off: bool = False
    comment: str = ""


@dataclass(slots=True)
class Rule:
    id: int | None
    rule_type: str
    scope: str = "all"
    year: int | None = None
    month: int | None = None
    day: int | None = None
    params: str = "{}"
    is_active: bool = True
    priority: int = 100
    sort_order: int = 0
    description: str = ""


@dataclass(slots=True)
class PersonalRule:
    id: int | None
    employee_id: int
    year: int | None
    month: int | None
    start_day: int
    end_day: int
    shift_code: str
    rule_type: str
    is_active: bool = True
    priority: int = 100
    sort_order: int = 0
    description: str = ""


@dataclass(slots=True)
class Setting:
    key: str
    value: str


@dataclass(slots=True)
class PlannedExtraDayOff:
    id: int | None
    employee_id: int
    year: int
    month: int
    planned_days: int = 0
    note: str = ""


@dataclass(slots=True)
class PlannedWorkdayAdjustment:
    id: int | None
    employee_id: int
    year: int
    month: int
    adjustment_days: int = 0
    source_year: int | None = None
    source_month: int | None = None
    note: str = ""


@dataclass(slots=True)
class WorkNormCompensationAction:
    id: int | None
    employee_id: int
    action_type: str
    days_count: int
    source_year: int
    source_month: int
    target_year: int | None = None
    target_month: int | None = None
    description: str = ""
    created_at: str = ""


DEFAULT_SETTINGS: dict[str, str] = {
    "company_name": 'ТОВ "Компанія АСКУЕ"',
    "director_title": "Заступник директора",
    "director_name": "ПІБ керівника",
    "department_name": "інженерів АСКУЕ",
    "schedule_title": "Графік роботи інженерів АСКУЕ",
    "work_days_tolerance": "1",
    "martial_law": "1",
    "daily_shift_d_count": "2",
    "daily_shift_ch_count": "2",
    "max_regular_per_day": "1",
    "max_consecutive_work_days": "6",
    "hard_max_consecutive_work_days": "9",
    "max_consecutive_duty_days": "5",
    "max_vacation_overlap": "1",
    "use_auto_norm": "1",
    "export_dir": "exports",
    "weekday_regular_target": "1",
    "special_day_regular_target": "0",
    "month_start_full_staff_days": "4",
    "month_start_regular_per_day": "1",
    "weekend_pairing": "1",
    "weekend_auto_regular_allowed": "0",
}


SAMPLE_EMPLOYEES: list[Employee] = [
    Employee(
        id=None,
        full_name="Петрова О.В.",
        short_name="Петрова О.В.",
        shift_type=SHIFT_TYPE_MIXED,
        sort_order=1,
    ),
    Employee(
        id=None,
        full_name="Арику І.В.",
        short_name="Арику І.В.",
        shift_type=SHIFT_TYPE_MIXED,
        sort_order=2,
    ),
    Employee(
        id=None,
        full_name="Юхименко А.А.",
        short_name="Юхименко А.А.",
        shift_type=SHIFT_TYPE_MIXED,
        sort_order=3,
    ),
    Employee(
        id=None,
        full_name="Гайдуков Ю.Б.",
        short_name="Гайдуков Ю.Б.",
        shift_type=SHIFT_TYPE_MIXED,
        sort_order=4,
    ),
]
