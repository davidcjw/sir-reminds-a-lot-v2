from __future__ import annotations

import calendar
import re
from datetime import date, timedelta


def _safe_date(year: int, month: int, day: int) -> date:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def billing_period(cycle_start: int, today: date) -> tuple[date, date]:
    if cycle_start == 1:
        last = calendar.monthrange(today.year, today.month)[1]
        return date(today.year, today.month, 1), date(today.year, today.month, last)

    if today.day >= cycle_start:
        start_year, start_month = today.year, today.month
    elif today.month == 1:
        start_year, start_month = today.year - 1, 12
    else:
        start_year, start_month = today.year, today.month - 1

    start = _safe_date(start_year, start_month, cycle_start)

    if start_month == 12:
        end = _safe_date(start_year + 1, 1, cycle_start - 1)
    else:
        end = _safe_date(start_year, start_month + 1, cycle_start - 1)

    return start, end


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().strip())


def resolve_due_date(due_day: str, year: int, month: int) -> date | None:
    last_day = calendar.monthrange(year, month)[1]
    normalized = _normalize(due_day)

    if normalized in {"last", "last day", "last day month", "last day of month", "end of month", "month end"}:
        return date(year, month, last_day)

    m = re.search(r"\b([1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\b", due_day.lower())
    if not m:
        return None

    day = min(int(m.group(1)), last_day)
    return date(year, month, day)


def _add_months(value: date, months: int) -> tuple[int, int]:
    idx = value.month - 1 + months
    return value.year + idx // 12, idx % 12 + 1


def find_due_reminders(
    cards: list[tuple[str, str]],   # (card_name, due_day)
    today: date,
    days_ahead: int,
) -> list[tuple[str, str, date]]:
    end_date = today + timedelta(days=days_ahead)
    reminders: list[tuple[str, str, date]] = []

    for card, due_day in cards:
        for offset in range(2):
            year, month = _add_months(today, offset)
            due_date = resolve_due_date(due_day, year, month)
            if due_date is not None and today <= due_date <= end_date:
                reminders.append((card, due_day, due_date))
                break

    return reminders
