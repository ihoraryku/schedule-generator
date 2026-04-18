from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

import logging

import holidays

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DayInfo:
    day: int
    weekday: int
    is_weekend: bool
    is_holiday: bool
    holiday_name: str | None
    is_working_day: bool


class UkrainianCalendar:
    def __init__(self, martial_law: bool = False) -> None:
        self.martial_law = martial_law
        self.ua_holidays = holidays.Ukraine(years=range(2020, 2037))

    def is_working_day(self, current_date: date) -> bool:
        if current_date.weekday() >= 5:
            return False
        if not self.martial_law and current_date in self.ua_holidays:
            return False
        return True

    def get_production_norm(self, year: int, month: int) -> int:
        month_days = calendar.monthrange(year, month)[1]
        working_days = sum(
            1
            for day in range(1, month_days + 1)
            if self.is_working_day(date(year, month, day))
        )
        return working_days * 8

    def get_month_info(self, year: int, month: int) -> dict[int, DayInfo]:
        month_days = calendar.monthrange(year, month)[1]
        info: dict[int, DayInfo] = {}
        for day in range(1, month_days + 1):
            current_date = date(year, month, day)
            holiday_name = self.ua_holidays.get(current_date)
            info[day] = DayInfo(
                day=day,
                weekday=current_date.weekday(),
                is_weekend=current_date.weekday() >= 5,
                is_holiday=bool(holiday_name),
                holiday_name=str(holiday_name) if holiday_name else None,
                is_working_day=self.is_working_day(current_date),
            )
        return info
