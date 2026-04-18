from __future__ import annotations

import calendar
from datetime import date

import logging

import holidays

logger = logging.getLogger(__name__)


def is_special_day(current_date: date, *, martial_law: bool, ua_holidays: holidays.Ukraine | None = None) -> bool:
    if current_date.weekday() >= 5:
        return True
    if ua_holidays is None:
        ua_holidays = holidays.Ukraine(years=[current_date.year])
    return current_date in ua_holidays and not martial_law


def special_days_for_month(year: int, month: int, *, martial_law: bool, ua_holidays: holidays.Ukraine | None = None) -> set[int]:
    if ua_holidays is None:
        ua_holidays = holidays.Ukraine(years=[year])
    month_days = calendar.monthrange(year, month)[1]
    return {
        day
        for day in range(1, month_days + 1)
        if is_special_day(date(year, month, day), martial_law=martial_law, ua_holidays=ua_holidays)
    }


def is_special_day_info(info: object) -> bool:
    is_weekend = bool(getattr(info, "is_weekend", False))
    is_holiday = bool(getattr(info, "is_holiday", False))
    is_working_day = bool(getattr(info, "is_working_day", False))
    return is_weekend or (is_holiday and not is_working_day)
