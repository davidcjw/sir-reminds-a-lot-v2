from __future__ import annotations

import calendar as cal
import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db
from logic.formatting import (
    format_spend_draft,
    parse_backdate_date,
    parse_spend_amount,
    update_spend_amount,
)

logger = logging.getLogger(__name__)


def _amount_keyboard(raw: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Amount: {format_spend_draft(raw)}", callback_data="spend:noop")],
        [InlineKeyboardButton("1", callback_data="spend:d:1"),
         InlineKeyboardButton("2", callback_data="spend:d:2"),
         InlineKeyboardButton("3", callback_data="spend:d:3")],
        [InlineKeyboardButton("4", callback_data="spend:d:4"),
         InlineKeyboardButton("5", callback_data="spend:d:5"),
         InlineKeyboardButton("6", callback_data="spend:d:6")],
        [InlineKeyboardButton("7", callback_data="spend:d:7"),
         InlineKeyboardButton("8", callback_data="spend:d:8"),
         InlineKeyboardButton("9", callback_data="spend:d:9")],
        [InlineKeyboardButton(".", callback_data="spend:d:dot"),
         InlineKeyboardButton("0", callback_data="spend:d:0"),
         InlineKeyboardButton("⌫", callback_data="spend:d:backspace")],
        [InlineKeyboardButton("Clear", callback_data="spend:d:clear"),
         InlineKeyboardButton("✅ OK", callback_data="spend:confirm_amount")],
        [InlineKeyboardButton("❌ Cancel", callback_data="spend:cancel")],
    ])


def _card_keyboard(cards: list[db.Card]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(c.name, callback_data=f"spend:card:{i}")]
        for i, c in enumerate(cards)
    ]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="spend:cancel")])
    return InlineKeyboardMarkup(buttons)


def _category_keyboard(categories: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(cat, callback_data=f"spend:cat:{i}")]
        for i, cat in enumerate(categories)
    ]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="spend:cancel")])
    return InlineKeyboardMarkup(buttons)


def _remark_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Skip", callback_data="spend:skip_remark"),
         InlineKeyboardButton("❌ Cancel", callback_data="spend:cancel")],
    ])


def _backdate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Yes", callback_data="spend:backdate:yes"),
         InlineKeyboardButton("No", callback_data="spend:backdate:no")],
        [InlineKeyboardButton("❌ Cancel", callback_data="spend:cancel")],
    ])


_CALENDAR_WEEKDAY_HEADERS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def _calendar_keyboard(year: int, month: int, today: date) -> InlineKeyboardMarkup:
    """Tap-driven month calendar: prev/next nav, future days disabled."""
    rows = []

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    is_current_month = (year, month) == (today.year, today.month)
    nav_row = [
        InlineKeyboardButton("‹", callback_data=f"spend:cal:nav:{prev_year}:{prev_month}"),
        InlineKeyboardButton(date(year, month, 1).strftime("%B %Y"), callback_data="spend:cal:noop"),
    ]
    if is_current_month:
        nav_row.append(InlineKeyboardButton(" ", callback_data="spend:cal:noop"))
    else:
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        nav_row.append(InlineKeyboardButton("›", callback_data=f"spend:cal:nav:{next_year}:{next_month}"))
    rows.append(nav_row)

    rows.append([InlineKeyboardButton(d, callback_data="spend:cal:noop") for d in _CALENDAR_WEEKDAY_HEADERS])

    for week in cal.monthcalendar(year, month):
        week_row = []
        for day in week:
            if day == 0:
                week_row.append(InlineKeyboardButton(" ", callback_data="spend:cal:noop"))
                continue
            day_date = date(year, month, day)
            label = f"•{day}" if day_date == today else str(day)
            if day_date > today:
                week_row.append(InlineKeyboardButton(label, callback_data="spend:cal:noop"))
            else:
                week_row.append(
                    InlineKeyboardButton(label, callback_data=f"spend:cal:pick:{year}:{month}:{day}")
                )
        rows.append(week_row)

    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="spend:cancel")])
    return InlineKeyboardMarkup(rows)


def _spend_summary_line(state: dict) -> str:
    line = f"Amount: ${state['amount']}\nCard: {state['card']}\nCategory: {state['category']}"
    remarks = state.get("remarks")
    if remarks:
        line += f"\nRemark: {remarks}"
    return line


def _save_spend(state: dict, remarks: str | None, timestamp: datetime | None = None) -> str:
    amount = Decimal(state["amount"])
    card = state["card"]
    category = state["category"]
    backdated = timestamp is not None
    ts = timestamp or datetime.now(tz=timezone.utc)
    db.append_spend(ts, amount, card, category, remarks)
    suffix = f" — {remarks}" if remarks else ""
    date_note = f" (backdated to {ts.date().isoformat()})" if backdated else ""
    return f"✅ Logged: ${amount:.2f} on {card} ({category}){suffix}{date_note}"


async def spend_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["spend"] = {"raw": "", "with_remarks": False}
    msg = await update.effective_message.reply_text(
        "Enter amount:",
        reply_markup=_amount_keyboard(""),
    )
    context.user_data["spend"]["message_id"] = msg.message_id


async def spend_with_remarks_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["spend"] = {"raw": "", "with_remarks": True}
    msg = await update.effective_message.reply_text(
        "Enter amount:",
        reply_markup=_amount_keyboard(""),
    )
    context.user_data["spend"]["message_id"] = msg.message_id


async def spend_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    state = context.user_data.get("spend", {})

    if data in ("spend:noop", "spend:cal:noop"):
        return

    if data == "spend:cancel":
        context.user_data.pop("spend", None)
        await query.edit_message_text("Spend log cancelled.")
        return

    # ── Amount digit entry ───────────────────────────────────────────────────
    if data.startswith("spend:d:"):
        action = data[len("spend:d:"):]
        raw = update_spend_amount(state.get("raw", ""), action)
        state["raw"] = raw
        await query.edit_message_text("Enter amount:", reply_markup=_amount_keyboard(raw))
        return

    # ── Confirm amount ───────────────────────────────────────────────────────
    if data == "spend:confirm_amount":
        try:
            amount = parse_spend_amount(state.get("raw", ""))
        except ValueError as e:
            await query.answer(str(e), show_alert=True)
            return
        state["amount"] = str(amount)
        cards = db.get_cards()
        if not cards:
            await query.edit_message_text(
                "No cards configured yet. Use /admin → Cards to add one."
            )
            context.user_data.pop("spend", None)
            return
        state["cards"] = [c.name for c in cards]
        await query.edit_message_text(
            f"Amount: ${amount}\n\nSelect card:",
            reply_markup=_card_keyboard(cards),
        )
        return

    # ── Card selection ───────────────────────────────────────────────────────
    if data.startswith("spend:card:"):
        idx = int(data[len("spend:card:"):])
        cards_list = state.get("cards", [])
        if idx >= len(cards_list):
            return
        state["card"] = cards_list[idx]
        categories = db.get_categories()
        if not categories:
            await query.edit_message_text(
                "No categories configured yet. Use /admin → Categories to add one."
            )
            context.user_data.pop("spend", None)
            return
        state["categories"] = categories
        await query.edit_message_text(
            f"Amount: ${state['amount']}\nCard: {state['card']}\n\nSelect category:",
            reply_markup=_category_keyboard(categories),
        )
        return

    # ── Category selection ───────────────────────────────────────────────────
    if data.startswith("spend:cat:"):
        idx = int(data[len("spend:cat:"):])
        cats = state.get("categories", [])
        if idx >= len(cats):
            return
        state["category"] = cats[idx]

        if state.get("with_remarks"):
            state["waiting_remarks"] = True
            await query.edit_message_text(
                f"{_spend_summary_line(state)}\n\nAdd a remark, or skip:",
                reply_markup=_remark_keyboard(),
            )
        else:
            await query.edit_message_text(
                f"{_spend_summary_line(state)}\n\nBackdate this transaction?",
                reply_markup=_backdate_keyboard(),
            )
        return

    # ── Skip remark ──────────────────────────────────────────────────────────
    if data == "spend:skip_remark":
        await query.edit_message_text(
            f"{_spend_summary_line(state)}\n\nBackdate this transaction?",
            reply_markup=_backdate_keyboard(),
        )
        return

    # ── Backdate? ────────────────────────────────────────────────────────────
    if data == "spend:backdate:no":
        confirmation = _save_spend(state, remarks=state.get("remarks"))
        context.user_data.pop("spend", None)
        await query.edit_message_text(confirmation)
        return

    if data == "spend:backdate:yes":
        today = datetime.now(tz=timezone.utc).date()
        await query.edit_message_text(
            f"{_spend_summary_line(state)}\n\nSelect a date:",
            reply_markup=_calendar_keyboard(today.year, today.month, today),
        )
        return

    # ── Calendar navigation / date pick ────────────────────────────────────────
    if data.startswith("spend:cal:nav:"):
        _, _, _, year_s, month_s = data.split(":")
        today = datetime.now(tz=timezone.utc).date()
        await query.edit_message_text(
            f"{_spend_summary_line(state)}\n\nSelect a date:",
            reply_markup=_calendar_keyboard(int(year_s), int(month_s), today),
        )
        return

    if data.startswith("spend:cal:pick:"):
        _, _, _, year_s, month_s, day_s = data.split(":")
        today = datetime.now(tz=timezone.utc).date()
        try:
            backdated = parse_backdate_date(f"{int(year_s):04d}-{int(month_s):02d}-{int(day_s):02d}", today)
        except ValueError as e:
            await query.answer(str(e), show_alert=True)
            return
        timestamp = datetime.combine(backdated, datetime.now(tz=timezone.utc).time(), tzinfo=timezone.utc)
        confirmation = _save_spend(state, remarks=state.get("remarks"), timestamp=timestamp)
        context.user_data.pop("spend", None)
        await query.edit_message_text(confirmation)
        return


async def spend_remark_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.user_data.get("spend", {})
    if not state.get("waiting_remarks"):
        return
    state["waiting_remarks"] = False
    state["remarks"] = (update.message.text or "").strip() or None
    await update.message.reply_text(
        f"{_spend_summary_line(state)}\n\nBackdate this transaction?",
        reply_markup=_backdate_keyboard(),
    )


async def delete_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = db.get_last_spend()
    if not entry:
        await update.effective_message.reply_text("No spend entries to delete.")
        return
    remarks_line = f"\n  Remark: {entry.remarks}" if entry.remarks else ""
    await update.effective_message.reply_text(
        f"Delete this entry?\n\n"
        f"  {entry.timestamp}\n"
        f"  ${entry.amount} on {entry.card} ({entry.category}){remarks_line}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 Delete", callback_data="delete_last:confirm"),
             InlineKeyboardButton("Cancel", callback_data="delete_last:cancel")],
        ]),
    )


async def delete_last_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "delete_last:cancel":
        await query.edit_message_text("Cancelled.")
        return

    entry = db.delete_last_spend()
    if entry:
        await query.edit_message_text(
            f"✅ Deleted: ${entry.amount} on {entry.card} ({entry.category})"
        )
    else:
        await query.edit_message_text("Nothing to delete.")


def get_handlers() -> list:
    return [
        CommandHandler("spend", spend_start),
        CommandHandler("delete_last", delete_last),
        CallbackQueryHandler(spend_callback, pattern=r"^spend:"),
        CallbackQueryHandler(delete_last_callback, pattern=r"^delete_last:"),
    ]


# Registered in group -1 in bot.py so it runs independently of the menu handler
remark_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, spend_remark_message)
