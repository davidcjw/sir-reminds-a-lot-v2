from __future__ import annotations

import logging
import sys

from telegram import ReplyKeyboardMarkup, Update
from telegram.constants import MessageEntityType
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

import db
from config import load_config
from handlers import admin, cards, reminders, spend, summary

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

MENU_BUTTONS = [
    ["💸 Log spend", "💬 Log spend with remarks"],
    ["📊 Spend Summary", "📈 Category Chart"],
    ["🧾 Transactions", "📅 Due dates"],
    ["🔔 Reminders", "⚙️ Admin"],
    ["✨ Help"],
]

BUTTON_ALIASES = {
    "💸 log spend": "spend",
    "log spend": "spend",
    "💬 log spend with remarks": "spend_with_remarks",
    "log spend with remarks": "spend_with_remarks",
    "📊 spend summary": "spend_summary",
    "spend summary": "spend_summary",
    "🧾 transactions": "transactions",
    "transactions": "transactions",
    "📈 category chart": "category_chart",
    "category chart": "category_chart",
    "📅 due dates": "due",
    "due dates": "due",
    "🔔 reminders": "reminders",
    "⚙️ admin": "admin",
    "✨ help": "help",
    "help": "help",
}


def _main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(MENU_BUTTONS, resize_keyboard=True)


async def authorize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global authorization gate.

    Runs before every other handler (lowest group). Only senders whose user ID
    or chat ID is on the allowlist may proceed. Everyone else is rejected and all
    further handler processing is stopped via ApplicationHandlerStop — so no
    command, callback, conversation, or admin/export/spend handler is reachable.

    The bot FAILS CLOSED: if the allowlist is empty, every sender is rejected.
    """
    config = context.bot_data.get("config")
    allowed = config.allowed_chat_ids if config else []

    user_id = update.effective_user.id if update.effective_user else None
    chat_id = update.effective_chat.id if update.effective_chat else None

    if (user_id is not None and user_id in allowed) or (
        chat_id is not None and chat_id in allowed
    ):
        return  # Authorized — let the update flow to the real handlers.

    logger.warning(
        "Rejected unauthorized update (user=%s, chat=%s)", user_id, chat_id
    )
    if update.effective_message is not None:
        try:
            await update.effective_message.reply_text(
                "⛔ You are not authorized to use this bot."
            )
        except Exception:  # pragma: no cover - best-effort notice only
            pass
    # Stop propagation so NO downstream handler runs for this sender.
    raise ApplicationHandlerStop


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not db.get_cards():
        await update.message.reply_text(
            "👋 Welcome to Sir Reminds-A-Lot!\n\n"
            "Before you can log spend, set up at least:\n"
            "  1️⃣ One card  (e.g. DBS Visa)\n"
            "  2️⃣ One category  (e.g. Food, Transport)\n\n"
            "Run /admin to open setup.",
            reply_markup=_main_menu_keyboard(),
        )
        return
    await update.message.reply_text(
        "👋 Hi! I'm your personal spend tracker.\n\n"
        "Use the menu below or type a command.\n"
        "Run /admin to configure your cards and categories.",
        reply_markup=_main_menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "/spend — log a spend entry\n"
        "/spend_summary — show spend by card this billing period\n"
        "/transactions — show your latest 5 transactions\n"
        "/category_chart — pie chart of spend by category this month\n"
        "/due — show card due dates\n"
        "/reminders — check upcoming due dates\n"
        "/delete_last — delete the most recent spend entry\n"
        "/export — download all spend data as CSV\n"
        "/admin — manage cards, categories, merchants, and rules\n"
        "/chatid — show this chat's ID (for reminder config)",
        reply_markup=_main_menu_keyboard(),
    )


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Chat ID: `{update.effective_chat.id}`", parse_mode="Markdown")


async def menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user and update.effective_user.is_bot:
        return
    entities = update.message.entities or []
    if any(e.type in (MessageEntityType.URL, MessageEntityType.TEXT_LINK) for e in entities):
        return

    text = (update.message.text or "").strip().lower()
    command = BUTTON_ALIASES.get(text)
    if not command:
        await cards.merchant_lookup(update, context)
        return

    # Route to the appropriate handler by simulating the command
    handler_map = {
        "spend": spend.spend_start,
        "spend_summary": summary.spend_summary,
        "transactions": summary.transactions,
        "category_chart": summary.category_chart,
        "due": cards.due_dates,
        "reminders": reminders.reminders_command,
        "help": help_command,
    }
    if command in handler_map:
        await handler_map[command](update, context)
    elif command == "spend_with_remarks":
        await spend.spend_with_remarks_start(update, context)



async def log_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Update %s caused error", update, exc_info=context.error)


def main() -> int:
    try:
        config = load_config()
    except ValueError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    try:
        db.init(config.database_path)
    except db.DatabasePermissionError as e:
        print(f"Database error: {e}", file=sys.stderr)
        return 1

    app = (
        Application.builder()
        .token(config.token)
        .post_init(reminders.start_reminder_task)
        .post_shutdown(reminders.stop_reminder_task)
        .build()
    )
    app.bot_data["config"] = config

    if not config.allowed_chat_ids:
        logger.warning(
            "ALLOWED_CHAT_IDS is empty and no TELEGRAM_REMINDER_CHAT_ID fallback "
            "is set — the bot will reject ALL commands (fail closed). Set "
            "ALLOWED_CHAT_IDS in .env to your Telegram user/chat ID(s)."
        )

    # Authorization gate — MUST run before every other handler (lowest group).
    app.add_handler(TypeHandler(Update, authorize), group=-100)

    # Core commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("chatid", chatid))

    # Feature handlers
    for h in spend.get_handlers():
        app.add_handler(h)
    for h in summary.get_handlers():
        app.add_handler(h)
    for h in cards.get_handlers():
        app.add_handler(h)
    for h in reminders.get_handlers():
        app.add_handler(h)
    for h in admin.get_handlers():
        app.add_handler(h)

    # Remark capture — group -1 runs before the menu handler, only acts when waiting_remarks=True
    app.add_handler(spend.remark_handler, group=-1)

    # Menu button text → command routing (lowest priority)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button))

    app.add_error_handler(log_error)

    logger.info("Bot starting…")
    app.run_polling()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
