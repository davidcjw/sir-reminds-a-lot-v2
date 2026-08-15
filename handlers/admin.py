from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db

logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────────
(
    HOME,
    ADD_CARD_NAME,
    ADD_CARD_DUE,
    ADD_CARD_CYCLE,
    ADD_CAT_NAME,
    ADD_MERCHANT_NAME,
    ADD_MERCHANT_CAT,   # inline keyboard step — awaiting category callback
    SET_RULE_TEXT,      # awaiting recommendation text after category selected
) = range(8)

_CANCEL = ConversationHandler.END


# ── Keyboards ─────────────────────────────────────────────────────────────────

def _main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📇 Cards", callback_data="adm:cards"),
         InlineKeyboardButton("🏷️ Categories", callback_data="adm:cats")],
        [InlineKeyboardButton("🏪 Merchants", callback_data="adm:merchants"),
         InlineKeyboardButton("📋 Rules", callback_data="adm:rules")],
        [InlineKeyboardButton("✖ Close", callback_data="adm:close")],
    ])


def _sub_menu(section: str, extra: list[list[InlineKeyboardButton]] | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("➕ Add", callback_data=f"adm:{section}:add"),
         InlineKeyboardButton("➖ Remove", callback_data=f"adm:{section}:remove"),
         InlineKeyboardButton("📋 List", callback_data=f"adm:{section}:list")],
    ]
    if extra:
        rows.extend(extra)
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="adm:home")])
    return InlineKeyboardMarkup(rows)


def _rules_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Set / Edit", callback_data="adm:rules:set"),
         InlineKeyboardButton("➖ Remove", callback_data="adm:rules:remove"),
         InlineKeyboardButton("📋 List", callback_data="adm:rules:list")],
        [InlineKeyboardButton("🔙 Back", callback_data="adm:home")],
    ])


def _back_to(section: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"adm:{section}")]])


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _edit(query, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await query.edit_message_text(text, reply_markup=markup)
    except TelegramError:
        logger.debug("Failed to edit message (likely unchanged content)", exc_info=True)


def _truncate(s: str, n: int = 30) -> str:
    return s[:n] + "…" if len(s) > n else s


# ── Entry ─────────────────────────────────────────────────────────────────────

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("adm", None)
    await update.effective_message.reply_text("⚙️ Admin", reply_markup=_main_menu())
    return HOME


# ── HOME state callbacks ───────────────────────────────────────────────────────

async def home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    # ── Navigation ────────────────────────────────────────────────────────────
    if data == "adm:home":
        await _edit(query, "⚙️ Admin", _main_menu())
        return HOME

    if data == "adm:close":
        await _edit(query, "Admin closed.")
        return _CANCEL

    if data == "adm:cards":
        await _edit(query, "📇 Cards", _sub_menu("cards"))
        return HOME

    if data == "adm:cats":
        await _edit(query, "🏷️ Categories", _sub_menu("cats"))
        return HOME

    if data == "adm:merchants":
        await _edit(query, "🏪 Merchants", _sub_menu("merchants"))
        return HOME

    if data == "adm:rules":
        await _edit(query, "📋 Rules", _rules_menu())
        return HOME

    # ── Cards: add → transition to text input ─────────────────────────────────
    if data in ("adm:cards:add", "adm:cards:more"):
        await _edit(query, "Card name?")
        return ADD_CARD_NAME

    if data == "adm:cards:done":
        await _edit(query, "✅ Done adding cards.")
        return _CANCEL

    # ── Cards: remove — show list ─────────────────────────────────────────────
    if data == "adm:cards:remove":
        cards = db.get_cards()
        if not cards:
            await _edit(query, "No cards to remove.", _back_to("cards"))
            return HOME
        buttons = [
            [InlineKeyboardButton(f"🗑 {c.name}", callback_data=f"adm:cards:rm:{c.name}")]
            for c in cards
        ]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="adm:cards")])
        await _edit(query, "Select card to remove:", InlineKeyboardMarkup(buttons))
        return HOME

    if data.startswith("adm:cards:rm:"):
        name = data[len("adm:cards:rm:"):]
        db.remove_card(name)
        await _edit(query, f"✅ Removed card: {name}", _back_to("cards"))
        return HOME

    # ── Cards: list ───────────────────────────────────────────────────────────
    if data == "adm:cards:list":
        cards = db.get_cards()
        if not cards:
            text = "No cards configured yet."
        else:
            lines = ["Cards:"]
            for c in cards:
                due = c.due_day or "no due date"
                cycle = f", cycle from {c.cycle_start}" if c.cycle_start != 1 else ""
                lines.append(f"• {c.name}: {due}{cycle}")
            text = "\n".join(lines)
        await _edit(query, text, _back_to("cards"))
        return HOME

    # ── Categories: add → transition ──────────────────────────────────────────
    if data in ("adm:cats:add", "adm:cats:more"):
        await _edit(query, "Category name? (separate multiple with commas)")
        return ADD_CAT_NAME

    if data == "adm:cats:done":
        await _edit(query, "✅ Done adding categories.")
        return _CANCEL

    # ── Categories: remove ────────────────────────────────────────────────────
    if data == "adm:cats:remove":
        cats = db.get_categories()
        if not cats:
            await _edit(query, "No categories to remove.", _back_to("cats"))
            return HOME
        buttons = [
            [InlineKeyboardButton(f"🗑 {c}", callback_data=f"adm:cats:rm:{c}")]
            for c in cats
        ]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="adm:cats")])
        await _edit(query, "Select category to remove:", InlineKeyboardMarkup(buttons))
        return HOME

    if data.startswith("adm:cats:rm:"):
        name = data[len("adm:cats:rm:"):]
        db.remove_category(name)
        await _edit(query, f"✅ Removed category: {name}", _back_to("cats"))
        return HOME

    if data == "adm:cats:list":
        cats = db.get_categories()
        text = "Categories:\n" + "\n".join(f"• {c}" for c in cats) if cats else "No categories configured yet."
        await _edit(query, text, _back_to("cats"))
        return HOME

    # ── Merchants: add → transition ───────────────────────────────────────────
    if data == "adm:merchants:add":
        await _edit(query, "Merchant name?")
        return ADD_MERCHANT_NAME

    # ── Merchants: remove ─────────────────────────────────────────────────────
    if data == "adm:merchants:remove":
        aliases = db.get_merchant_aliases()
        if not aliases:
            await _edit(query, "No merchant aliases to remove.", _back_to("merchants"))
            return HOME
        buttons = [
            [InlineKeyboardButton(f"🗑 {m}", callback_data=f"adm:merch:rm:{m}")]
            for m, _ in aliases
        ]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="adm:merchants")])
        await _edit(query, "Select merchant to remove:", InlineKeyboardMarkup(buttons))
        return HOME

    if data.startswith("adm:merch:rm:"):
        merchant = data[len("adm:merch:rm:"):]
        db.remove_merchant_alias(merchant)
        await _edit(query, f"✅ Removed merchant alias: {merchant}", _back_to("merchants"))
        return HOME

    if data == "adm:merchants:list":
        aliases = db.get_merchant_aliases()
        if not aliases:
            text = "No merchant aliases configured yet."
        else:
            lines = ["Merchant aliases:"]
            for merchant, cat in aliases:
                lines.append(f"• {merchant} → {cat}")
            text = "\n".join(lines)
        await _edit(query, text, _back_to("merchants"))
        return HOME

    # ── Merchant category selection (after entering name) ────────────────────
    if data.startswith("adm:merch:cat:"):
        category = data[len("adm:merch:cat:"):]
        merchant = context.user_data.get("adm", {}).get("merchant_name", "")
        if merchant:
            db.add_merchant_alias(merchant, category)
            await _edit(query, f"✅ Saved: {merchant} → {category}", _back_to("merchants"))
        context.user_data.pop("adm", None)
        return HOME

    # ── Rules ─────────────────────────────────────────────────────────────────
    if data == "adm:rules:list":
        rules = db.get_card_rules()
        if not rules:
            text = "No rules configured yet."
        else:
            lines = ["Rules (category → recommendation):"]
            for cat, rec in rules:
                lines.append(f"• {cat}: {rec}")
            text = "\n".join(lines)
        await _edit(query, text, _back_to("rules"))
        return HOME

    if data == "adm:rules:set":
        cats = db.get_categories()
        if not cats:
            await _edit(query, "Add categories first (/admin → Categories).", _back_to("rules"))
            return HOME
        buttons = [
            [InlineKeyboardButton(c, callback_data=f"adm:rules:setcat:{c}")]
            for c in cats
        ]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="adm:rules")])
        await _edit(query, "Select category:", InlineKeyboardMarkup(buttons))
        return HOME

    if data.startswith("adm:rules:setcat:"):
        category = data[len("adm:rules:setcat:"):]
        context.user_data["adm"] = {"rule_category": category}
        await _edit(query, f'Recommendation for “{category}”?\n(e.g. Card A / Card B)')
        return SET_RULE_TEXT

    if data == "adm:rules:remove":
        rules = db.get_card_rules()
        if not rules:
            await _edit(query, "No rules to remove.", _back_to("rules"))
            return HOME
        buttons = [
            [InlineKeyboardButton(f"🗑 {cat}", callback_data=f"adm:rules:rm:{cat}")]
            for cat, _ in rules
        ]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="adm:rules")])
        await _edit(query, "Select rule to remove:", InlineKeyboardMarkup(buttons))
        return HOME

    if data.startswith("adm:rules:rm:"):
        category = data[len("adm:rules:rm:"):]
        db.remove_card_rule(category)
        await _edit(query, f"✅ Removed rule for: {category}", _back_to("rules"))
        return HOME

    return HOME


# ── Text input states ─────────────────────────────────────────────────────────

async def recv_card_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("Card name can't be empty. Try again:")
        return ADD_CARD_NAME
    context.user_data["adm"] = {"card_name": name}
    await update.message.reply_text(
        f'Card name: "{name}"\n\nDue day? (e.g. 15th, last, last day of month)\nSend "none" if no due date.'
    )
    return ADD_CARD_DUE


async def recv_card_due(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    due_day = None if text.lower() in {"none", "n/a", "-", ""} else text
    context.user_data["adm"]["due_day"] = due_day
    await update.message.reply_text(
        'Billing cycle start day? (number, e.g. 13)\nSend "1" or "skip" for calendar month.'
    )
    return ADD_CARD_CYCLE


async def recv_card_cycle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip().lower()
    try:
        cycle_start = 1 if text in {"skip", "1", ""} else int(text)
    except ValueError:
        await update.message.reply_text('Enter a number (1-28), or "skip":')
        return ADD_CARD_CYCLE

    adm = context.user_data.get("adm", {})
    name = adm.get("card_name", "")
    due_day = adm.get("due_day")
    db.add_card(name, due_day, cycle_start)
    context.user_data.pop("adm", None)
    await update.message.reply_text(
        f"✅ Added card: {name}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ Add another card", callback_data="adm:cards:more"),
            InlineKeyboardButton("✅ Done", callback_data="adm:cards:done"),
        ]]),
    )
    return HOME


async def recv_cat_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.message.text or "").strip()
    if not raw:
        await update.message.reply_text("Category name can't be empty. Try again:")
        return ADD_CAT_NAME
    names = [n.strip() for n in raw.split(",") if n.strip()]
    for name in names:
        db.add_category(name)
    added = ", ".join(names)
    await update.message.reply_text(
        f"✅ Added: {added}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ Add more", callback_data="adm:cats:more"),
            InlineKeyboardButton("✅ Done", callback_data="adm:cats:done"),
        ]]),
    )
    return HOME


async def recv_merchant_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("Merchant name can't be empty. Try again:")
        return ADD_MERCHANT_NAME
    context.user_data["adm"] = {"merchant_name": name}
    cats = db.get_categories()
    if not cats:
        await update.message.reply_text("Add categories first (/admin → Categories).")
        return _CANCEL
    buttons = [
        [InlineKeyboardButton(c, callback_data=f"adm:merch:cat:{c}")]
        for c in cats
    ]
    await update.message.reply_text(
        f'Merchant: "{name}"\n\nSelect category:',
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return ADD_MERCHANT_CAT


async def recv_rule_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    recommendation = (update.message.text or "").strip()
    if not recommendation:
        await update.message.reply_text("Recommendation can't be empty. Try again:")
        return SET_RULE_TEXT
    category = context.user_data.get("adm", {}).get("rule_category", "")
    db.set_card_rule(category, recommendation)
    context.user_data.pop("adm", None)
    await update.message.reply_text(f"✅ Rule set: {category} → {recommendation}")
    return _CANCEL


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("adm", None)
    await update.effective_message.reply_text("Admin cancelled.")
    return _CANCEL


# ── Handler registration ──────────────────────────────────────────────────────

def get_handlers() -> list:
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("admin", admin_start),
            MessageHandler(filters.Regex("^⚙️ Admin$"), admin_start),
        ],
        states={
            HOME: [CallbackQueryHandler(home_callback, pattern=r"^adm:")],
            ADD_CARD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_card_name)],
            ADD_CARD_DUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_card_due)],
            ADD_CARD_CYCLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_card_cycle)],
            ADD_CAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_cat_name)],
            ADD_MERCHANT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_merchant_name)],
            ADD_MERCHANT_CAT: [CallbackQueryHandler(home_callback, pattern=r"^adm:merch:cat:")],
            SET_RULE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_rule_text)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    return [conv]
