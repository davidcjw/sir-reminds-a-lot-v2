from __future__ import annotations

import calendar
import csv
import io
import logging
from datetime import date, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

import db
from logic.chart import build_category_pie_image
from logic.formatting import (
    aggregate_category_totals,
    build_recent_transactions_message,
    build_spend_summary_message,
    format_money,
)

logger = logging.getLogger(__name__)


def _parse_month_arg(args: list[str] | None, today: date) -> tuple[date, date, date]:
    """Parse optional YYYY-MM arg; returns (month_start, month_end, ref_date).

    ref_date is the first day of the month, used as 'today' for chart/aggregate
    functions that filter by today.year/today.month.
    """
    if args:
        try:
            ref = datetime.strptime(args[0], "%Y-%m").date()  # noqa: DTZ007 (month-only, no tz needed)
        except ValueError:
            ref = today.replace(day=1)
    else:
        ref = today.replace(day=1)

    last_day = calendar.monthrange(ref.year, ref.month)[1]
    return date(ref.year, ref.month, 1), date(ref.year, ref.month, last_day), ref


async def spend_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = context.application.bot_data["config"]
    today = datetime.now(tz=config.reminder_timezone).date()
    cards = db.get_cards()
    rows = db.get_all_spend_rows()
    text = build_spend_summary_message(cards, rows, today)
    await update.effective_message.reply_text(text)


def _one_off_prompt_keyboard(month_str: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Yes", callback_data=f"chart:exclude:{month_str}"),
         InlineKeyboardButton("No", callback_data=f"chart:include:{month_str}")],
    ])


async def transactions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = db.get_recent_spend_rows(5)
    await update.effective_message.reply_text(build_recent_transactions_message(rows, 5))


async def category_chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Ask whether to exclude one-off transactions before building the chart.
    # The chosen month is carried through the callback via the button payload.
    config = context.application.bot_data["config"]
    today = datetime.now(tz=config.reminder_timezone).date()
    _, _, ref = _parse_month_arg(context.args, today)
    await update.effective_message.reply_text(
        "Exclude one-off transactions?",
        reply_markup=_one_off_prompt_keyboard(ref.strftime("%Y-%m")),
    )


async def category_chart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    # Payload: chart:{exclude|include}:{YYYY-MM}
    parts = (query.data or "").split(":")
    exclude_one_off = len(parts) > 1 and parts[1] == "exclude"
    month_arg = parts[2] if len(parts) > 2 else None
    config = context.application.bot_data["config"]
    today = datetime.now(tz=config.reminder_timezone).date()
    start, end, ref = _parse_month_arg([month_arg] if month_arg else None, today)

    rows = db.get_spend_rows_in_range(start, end)
    totals = aggregate_category_totals(rows, ref, exclude_one_off=exclude_one_off)

    if not totals:
        suffix = " after excluding one-off transactions" if exclude_one_off else ""
        await query.edit_message_text(
            f"No spend logged for {ref.strftime('%B %Y')}{suffix}."
        )
        return

    label = " (excluding one-off)" if exclude_one_off else ""
    await query.edit_message_text(f"📈 Spend by Category — {ref.strftime('%B %Y')}{label}")

    image_bytes = build_category_pie_image(rows, ref, exclude_one_off=exclude_one_off)
    if image_bytes:
        await query.message.reply_photo(photo=image_bytes)
    else:
        grand_total = sum(totals.values())
        lines = [f"📊 Spend by Category — {ref.strftime('%B %Y')}{label}", ""]
        for cat, total in sorted(totals.items(), key=lambda x: x[1], reverse=True):
            pct = int(total / grand_total * 100)
            lines.append(f"• {cat}: ${format_money(total)} ({pct}%)")
        lines += ["", f"Total: ${format_money(grand_total)}"]
        await query.message.reply_text("\n".join(lines))


async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = context.application.bot_data["config"]
    today = datetime.now(tz=config.reminder_timezone).date()
    start, end, ref = _parse_month_arg(context.args, today)
    rows = db.get_spend_rows_in_range(start, end)

    if not rows:
        await update.effective_message.reply_text(
            f"No spend data for {ref.strftime('%B %Y')}."
        )
        return

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Timestamp", "Amount", "Card", "Category", "Remarks"])
    for row in rows:
        writer.writerow([row.timestamp, row.amount, row.card, row.category, row.remarks or ""])

    month_str = ref.strftime("%Y-%m")
    await update.effective_message.reply_document(
        document=buf.getvalue().encode(),
        filename=f"spend_export_{month_str}.csv",
        caption=f"Exported {len(rows)} entries for {ref.strftime('%B %Y')}.",
    )


def get_handlers() -> list:
    return [
        CommandHandler("spend_summary", spend_summary),
        CommandHandler("transactions", transactions),
        CommandHandler("category_chart", category_chart),
        CommandHandler("export", export_csv),
        CallbackQueryHandler(category_chart_callback, pattern=r"^chart:"),
    ]
