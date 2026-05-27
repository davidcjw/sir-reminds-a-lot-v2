from __future__ import annotations

import logging
from datetime import date

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import db
from logic.formatting import build_due_dates_text, find_matching_rules

logger = logging.getLogger(__name__)


async def due_dates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cards = db.get_cards()
    await update.effective_message.reply_text(build_due_dates_text(cards))


async def what_card_to_use(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    query = " ".join(args).strip()

    rules = db.get_card_rules()
    if not rules:
        await update.effective_message.reply_text(
            "No card rules configured yet. Use /admin → Rules to add recommendations."
        )
        return

    if not query:
        lines = ["/what_card_to_use <category>", "", "Configured rules:"]
        for category, rec in rules:
            lines.append(f"• {category}: {rec}")
        await update.effective_message.reply_text("\n".join(lines))
        return

    matches = find_matching_rules(rules, query)
    if not matches:
        await update.effective_message.reply_text(
            f'No card recommendation found for “{query}”.\n\n'
            "Use /admin → Rules to add one."
        )
        return

    lines = [f'Card recommendation for "{query}":']
    for category, rec in matches:
        lines.append(f"• {category}: {rec}")
    if len(matches) > 1:
        lines.append("\n❗ If multiple cards are listed, prefer the first unless told otherwise.")
    await update.effective_message.reply_text("\n".join(lines))


def get_handlers() -> list:
    return [
        CommandHandler("due", due_dates),
        CommandHandler("what_card_to_use", what_card_to_use),
    ]
