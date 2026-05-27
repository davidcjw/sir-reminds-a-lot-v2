from __future__ import annotations

import csv
import io
import logging
from datetime import date, timezone, datetime

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import db
from logic.chart import build_category_pie_image
from logic.formatting import aggregate_category_totals, build_spend_summary_message, format_money
from decimal import Decimal

logger = logging.getLogger(__name__)


async def spend_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = date.today()
    cards = db.get_cards()
    rows = db.get_all_spend_rows()
    text = build_spend_summary_message(cards, rows, today)
    await update.effective_message.reply_text(text)


async def category_chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = date.today()
    rows = db.get_all_spend_rows()
    totals = aggregate_category_totals(rows, today)

    if not totals:
        await update.effective_message.reply_text("No spend logged this month.")
        return

    image_bytes = build_category_pie_image(rows, today)
    if image_bytes:
        await update.effective_message.reply_photo(photo=image_bytes)
    else:
        grand_total = sum(totals.values())
        lines = [f"📊 Spend by Category — {today.strftime('%B %Y')}", ""]
        for cat, total in sorted(totals.items(), key=lambda x: x[1], reverse=True):
            pct = int(total / grand_total * 100)
            lines.append(f"• {cat}: ${format_money(total)} ({pct}%)")
        lines += ["", f"Total: ${format_money(grand_total)}"]
        await update.effective_message.reply_text("\n".join(lines))


async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = db.get_all_spend_rows()
    if not rows:
        await update.effective_message.reply_text("No spend data to export.")
        return

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Timestamp", "Amount", "Card", "Category", "Remarks"])
    for row in rows:
        writer.writerow([row.timestamp, row.amount, row.card, row.category, row.remarks or ""])

    await update.effective_message.reply_document(
        document=buf.getvalue().encode(),
        filename=f"spend_export_{date.today()}.csv",
        caption=f"Exported {len(rows)} entries.",
    )


def get_handlers() -> list:
    return [
        CommandHandler("spend_summary", spend_summary),
        CommandHandler("category_chart", category_chart),
        CommandHandler("export", export_csv),
    ]
