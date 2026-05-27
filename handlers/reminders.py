from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import db
from logic.billing import find_due_reminders
from logic.formatting import build_due_reminder_messages

logger = logging.getLogger(__name__)

_reminder_task: asyncio.Task | None = None


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = context.application.bot_data["config"]
    cards = db.get_cards()
    rows = [(c.name, c.due_day) for c in cards if c.due_day]
    today = date.today()
    messages = build_due_reminder_messages(
        find_due_reminders(rows, today, config.reminder_days_before),
        today,
        config.reminder_days_before,
    )
    for msg in messages:
        await update.effective_message.reply_text(msg)


async def send_due_reminders(application: Application) -> None:
    config = application.bot_data["config"]
    if not config.reminder_chat_id:
        return
    cards = db.get_cards()
    rows = [(c.name, c.due_day) for c in cards if c.due_day]
    today = date.today()
    messages = build_due_reminder_messages(
        find_due_reminders(rows, today, config.reminder_days_before),
        today,
        config.reminder_days_before,
    )
    for msg in messages:
        await application.bot.send_message(chat_id=config.reminder_chat_id, text=msg)


def _next_run(now: datetime, reminder_time: time) -> datetime:
    candidate = now.replace(
        hour=reminder_time.hour,
        minute=reminder_time.minute,
        second=0,
        microsecond=0,
    )
    if candidate <= now:
        candidate = candidate.replace(day=candidate.day + 1)
    return candidate


async def due_reminder_loop(application: Application) -> None:
    config = application.bot_data["config"]
    while True:
        now = datetime.now(tz=config.reminder_timezone)
        next_run = _next_run(now, config.reminder_time)
        wait_seconds = (next_run - now).total_seconds()
        logger.info("Next reminder scheduled in %.0f seconds", wait_seconds)
        await asyncio.sleep(wait_seconds)
        try:
            await send_due_reminders(application)
        except Exception:
            logger.exception("Error sending due reminders")


async def start_reminder_task(application: Application) -> None:
    global _reminder_task
    config = application.bot_data.get("config")
    if config and config.reminder_chat_id:
        _reminder_task = asyncio.create_task(due_reminder_loop(application))
        logger.info("Due reminder loop started")


async def stop_reminder_task(application: Application) -> None:
    global _reminder_task
    if _reminder_task:
        _reminder_task.cancel()
        _reminder_task = None


def get_handlers() -> list:
    return [
        CommandHandler("reminders", reminders_command),
    ]
