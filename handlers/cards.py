from __future__ import annotations

import logging
import re
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

import db
from logic.formatting import build_due_dates_text, find_matching_rules

logger = logging.getLogger(__name__)


def _norm(value: str) -> str:
    """Normalize for merchant matching: lowercase, strip punctuation, collapse spaces."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


async def merchant_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if not text:
        return

    key = _norm(text)
    aliases = db.get_merchant_aliases()
    merchant_map = {_norm(m): cat for m, cat in aliases}
    category = merchant_map.get(key)

    if category:
        if _norm(category) == "shopping":
            context.user_data["merchant_query"] = text
            await update.message.reply_text(
                f'Is "{text}" in-store or online?',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏪 In-store", callback_data="mlookup:offline"),
                    InlineKeyboardButton("🌐 Online", callback_data="mlookup:online"),
                ]]),
            )
            return

        rules = db.get_card_rules()
        matches = find_matching_rules(rules, category)
        if matches:
            lines = [f"*{cat}*: {rec}" for cat, rec in matches]
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        else:
            await update.message.reply_text(
                f"Category: *{category}*\n_(No card rule set — use /admin → Rules to add one)_",
                parse_mode="Markdown",
            )
        return

    # No merchant match — try the text as a category query
    rules = db.get_card_rules()
    if rules:
        matches = find_matching_rules(rules, text)
        if matches:
            lines = [f"*{cat}*: {rec}" for cat, rec in matches]
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
            return

    await update.message.reply_text(
        f'No mapping found for "*{text}*".\n'
        "Add it via /admin → Merchants, or check /admin → Rules.",
        parse_mode="Markdown",
    )


async def shopping_clarify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    mode = query.data.split(":")[-1]  # "online" or "offline"
    category_query = "Online Shopping" if mode == "online" else "Offline Shopping"

    rules = db.get_card_rules()
    matches = find_matching_rules(rules, category_query)
    if matches:
        lines = [f"*{cat}*: {rec}" for cat, rec in matches]
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown")
    else:
        await query.edit_message_text(
            f"No card rule set for *{category_query}*. Use /admin → Rules to add one.",
            parse_mode="Markdown",
        )


async def due_dates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cards = db.get_cards()
    await update.effective_message.reply_text(build_due_dates_text(cards))



def get_handlers() -> list:
    return [
        CommandHandler("due", due_dates),
        CallbackQueryHandler(shopping_clarify_callback, pattern=r"^mlookup:(online|offline)$"),
    ]
