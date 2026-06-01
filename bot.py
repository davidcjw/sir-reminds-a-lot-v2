from __future__ import annotations

import logging
import sys

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

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
    ["📅 Due dates", "🔔 Reminders"],
    ["⚙️ Admin", "✨ Help"],
]

BUTTON_ALIASES = {
    "💸 log spend": "spend",
    "log spend": "spend",
    "💬 log spend with remarks": "spend_with_remarks",
    "log spend with remarks": "spend_with_remarks",
    "📊 spend summary": "spend_summary",
    "spend summary": "spend_summary",
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
    entities = update.message.entities or []
    if any(e.type in ("url", "text_link") for e in entities):
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

    db.init(config.database_path)

    app = (
        Application.builder()
        .token(config.token)
        .post_init(reminders.start_reminder_task)
        .post_shutdown(reminders.stop_reminder_task)
        .build()
    )
    app.bot_data["config"] = config

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
