from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher

from db import Card, SpendEntry
from logic.billing import billing_period, find_due_reminders

MONEY_QUANTIZER = Decimal("0.01")

# Matches "one-off", "one off" or "oneoff" anywhere in a category or remark,
# case-insensitively. Used to flag irregular spend that can be excluded from
# the category chart.
_ONE_OFF_RE = re.compile(r"\bone[\s-]?off\b", re.IGNORECASE)


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().strip())


def is_one_off(entry: SpendEntry) -> bool:
    """True when a spend entry is tagged one-off via its category or remark."""
    return bool(
        _ONE_OFF_RE.search(entry.category or "")
        or _ONE_OFF_RE.search(entry.remarks or "")
    )


def format_money(amount: Decimal) -> str:
    return f"{amount:.2f}"


def format_due_date(value: date) -> str:
    return f"{value.day} {value:%b %Y}"


def format_due_window(days_ahead: int) -> str:
    if days_ahead == 0:
        return "today"
    if days_ahead == 1:
        return "in the next 1 day"
    return f"in the next {days_ahead} days"


def format_due_timing(due_date: date, today: date) -> str:
    days = (due_date - today).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days"


def update_spend_amount(current: str, action: str) -> str:
    if action == "clear":
        return ""
    if action == "backspace":
        return current[:-1]
    if action == "dot":
        if "." in current:
            return current
        return f"{current or '0'}."
    if not action.isdigit():
        return current
    if "." in current and len(current.rsplit(".", 1)[1]) >= 2:
        return current
    if current == "0":
        return action
    if len(current.replace(".", "")) >= 9:
        return current
    return current + action


def parse_spend_amount(raw: str) -> Decimal:
    cleaned = raw.strip().replace(",", "").lstrip("$").strip()
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("Enter an amount greater than 0.") from exc
    if amount <= 0:
        raise ValueError("Enter an amount greater than 0.")
    return amount.quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)


def format_spend_draft(raw: str) -> str:
    return f"${raw or '0'}"


def build_spend_summary_message(
    cards: list[Card],
    rows: list[SpendEntry],
    today: date,
) -> str:
    if not cards:
        return "No cards configured yet. Use /admin to add cards."

    lines = ["Spend summary:"]
    any_spend = False

    for card in cards:
        start, end = billing_period(card.cycle_start, today)
        card_rows = [
            r for r in rows
            if r.card == card.name
            and start <= datetime.strptime(r.timestamp, "%Y-%m-%d %H:%M:%S").date() <= end
        ]
        if not card_rows:
            continue
        total = sum(Decimal(r.amount) for r in card_rows)
        date_range = f"{start.day} {start:%b} – {end.day} {end:%b}"
        lines.append(f"• {card.name}: ${format_money(total)} ({date_range})")
        any_spend = True

    if not any_spend:
        return "No spend logged in the current billing period."

    return "\n".join(lines)


def aggregate_category_totals(
    rows: list[SpendEntry], today: date, exclude_one_off: bool = False
) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for row in rows:
        try:
            row_date = datetime.strptime(row.timestamp, "%Y-%m-%d %H:%M:%S").date()
            amount = Decimal(row.amount)
        except (ValueError, InvalidOperation):
            continue
        if row_date.year != today.year or row_date.month != today.month:
            continue
        if exclude_one_off and is_one_off(row):
            continue
        category = row.category.strip() or "Uncategorized"
        totals[category] = totals.get(category, Decimal("0")) + amount
    return totals


def build_due_reminder_messages(
    reminders: list[tuple[str, str, date]],
    today: date,
    days_ahead: int,
) -> list[str]:
    window = format_due_window(days_ahead)
    if not reminders:
        return [f"No credit card payments are due {window}."]

    lines = [f"Credit card payment reminder — due {window}:"]
    for card, due_day, due_date in reminders:
        lines.append(
            f"• {card}: {format_due_date(due_date)} ({format_due_timing(due_date, today)}; {due_day})"
        )
    return ["\n".join(lines)]


def build_due_dates_text(cards: list[Card]) -> str:
    if not cards:
        return "No cards configured yet. Use /admin to add cards."
    lines = ["Credit card due dates:"]
    for card in cards:
        due = card.due_day or "not set"
        cycle = f" (billing cycle starts {card.cycle_start})" if card.cycle_start != 1 else ""
        lines.append(f"• {card.name}: {due}{cycle}")
    return "\n".join(lines)


def find_matching_rules(
    rules: list[tuple[str, str]],   # (category, recommendation)
    query: str,
) -> list[tuple[str, str]]:
    norm_q = normalize(query)
    q_words = norm_q.split()
    matches: list[tuple[str, str]] = []

    for category, recommendation in rules:
        norm_c = normalize(category)
        c_words = norm_c.split()

        if norm_q in norm_c or any(w in norm_c for w in q_words) or any(w in norm_q for w in c_words):
            matches.append((category, recommendation))
            continue

        similar = [
            SequenceMatcher(None, qw, cw).ratio()
            for qw in q_words for cw in c_words
            if len(qw) >= 4 and len(cw) >= 4
        ]
        if similar and max(similar) >= 0.75:
            matches.append((category, recommendation))

    return matches
