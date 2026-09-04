"""The Telegram bot: command + message handlers and the Application wiring.

Run it locally with long polling (no public URL needed):

    uv run python -m examples.inspiration_bot.bot

In production the same handlers run via webhook — see app.py. Identity is free: every
update carries a verified `effective_user.id`, which is our whole "auth".
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agent.config import get_settings
from agent.logging_setup import setup_logging
from agent.services import db, storage
from examples.inspiration_bot import ingest, store
from examples.inspiration_bot.jobs import generate_for_user

HERE = Path(__file__).parent

HELLO = (
    "Hi! I'm your inspiration tracker. 🌱\n\n"
    "Send me anything that inspires you — a photo, a quote, a stray thought — and I'll quietly "
    "file it and learn your taste. Each morning I'll send you one small thing that fits.\n\n"
    "Try it now: forward a photo, or send me a line that stuck with you.\n"
    "Commands: /inspire (one now), /profile (what I've learned), /help, /delete."
)

HELP = (
    "Feed me photos and text and I'll learn what inspires you, then nudge you with something "
    "personal each morning.\n\n"
    "• /inspire — get a nudge right now\n"
    "• /profile — see what I've learned about you\n"
    '• tell me "send me at 7am on weekdays" or "pause" to change my schedule\n'
    "• /delete — erase everything I know about you"
)


def _require_token() -> str:
    token = get_settings().telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add your @BotFather token to .env.")
    return token


async def _allowed(update: Update) -> bool:
    """Authorization (separate from Telegram's authentication): an optional allowlist."""
    allow = get_settings().allowed_ids
    user = update.effective_user
    if allow and (user is None or user.id not in allow):
        if update.message:
            await update.message.reply_text("This bot isn't enabled for you.")
        return False
    return True


async def _ensure_user(update: Update) -> store.User | None:
    """Return the user row, creating it on the fly if this is their first message."""
    tg = update.effective_user
    if tg is None:
        return None
    user = await store.get_user(tg.id)
    if user is None:
        await store.upsert_user(tg.id, tg.username, tg.first_name)
        user = await store.get_user(tg.id)
    return user


# --- command handlers -------------------------------------------------------


async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    if tg is None or update.message is None or not await _allowed(update):
        return
    is_new = await store.upsert_user(tg.id, tg.username, tg.first_name)
    await update.message.reply_text(HELLO if is_new else f"Welcome back! 🌱\n\n{HELP}")


async def cmd_help(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(HELP)


async def cmd_profile(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not await _allowed(update):
        return
    user = await _ensure_user(update)
    if user is None:
        return
    if not user.profile:
        await update.message.reply_text(
            "I don't know your taste yet — send me a few things that inspire you first."
        )
        return
    count = await store.item_count(user.telegram_id)
    schedule = (
        "paused"
        if user.paused
        else f"{user.cadence} around {user.send_hour:02d}:00 {user.timezone}"
    )
    await update.message.reply_text(
        f"Here's what I think inspires you ({count} saved):\n\n{user.profile}\n\n"
        f"🕗 Nudges: {schedule}"
    )


async def cmd_inspire(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not await _allowed(update):
        return
    user = await _ensure_user(update)
    if user is None:
        return
    logger.info("/inspire requested by {}", user.telegram_id)
    # Generation takes a while (LLM + tools, maybe an image), and the typing indicator
    # fades after a few seconds — so acknowledge immediately so it's not a black box.
    await update.message.chat.send_action(ChatAction.TYPING)
    await update.message.reply_text("✨ Let me think of something for you…")
    try:
        await generate_for_user(context.bot, user)
    except Exception:  # noqa: BLE001 — show the user a friendly message, keep the bot up
        logger.exception("/inspire failed for {}", user.telegram_id)
        await update.message.reply_text(
            "Hmm, I couldn't come up with something just now — try again in a moment."
        )


async def cmd_delete(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not await _allowed(update):
        return
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Yes, delete everything", callback_data="del:yes"),
                InlineKeyboardButton("Cancel", callback_data="del:no"),
            ]
        ]
    )
    await update.message.reply_text(
        "This erases everything I know about you — saved items and all. Are you sure?",
        reply_markup=keyboard,
    )


async def on_delete_choice(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None:
        return
    await query.answer()
    if query.data == "del:yes":
        keys = await store.delete_everything(query.from_user.id)
        for key in keys:
            try:
                await storage.delete_key(key)
            except Exception:  # noqa: BLE001 — a stray orphaned file isn't worth failing on
                logger.warning("could not delete R2 key {}", key)
        await query.edit_message_text(
            "Done — I've forgotten everything. Send /start to begin again."
        )
    else:
        await query.edit_message_text("Cancelled — nothing was deleted.")


# --- message handlers -------------------------------------------------------


async def on_photo(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not update.message.photo or not await _allowed(update):
        return
    user = await _ensure_user(update)
    if user is None:
        return
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        photo = update.message.photo[-1]  # the largest available size
        file = await photo.get_file()
        data = bytes(await file.download_as_bytearray())
        understanding = await ingest.log_photo(user, data, "image/jpeg")
        await update.message.reply_text(f"✓ filed — {', '.join(understanding.themes)}")
    except Exception:  # noqa: BLE001
        logger.exception("photo ingest failed for {}", user.telegram_id)
        await update.message.reply_text("Couldn't read that image — mind sending it again?")


async def on_text(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not update.message.text or not await _allowed(update):
        return
    user = await _ensure_user(update)
    if user is None:
        return
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        understanding = await ingest.log_text(user, update.message.text)
        await update.message.reply_text(f"✓ filed — {', '.join(understanding.themes)}")
    except Exception:  # noqa: BLE001
        logger.exception("text ingest failed for {}", user.telegram_id)
        await update.message.reply_text("Hmm, I couldn't process that just now — try again?")


async def on_unsupported(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("I can take photos and text for now 🙂")


# --- wiring -----------------------------------------------------------------


async def post_init(app: Application) -> None:
    """Runs once after the Application initializes: migrate the DB and set the command menu."""
    applied = await db.apply_migrations(HERE / "migrations")
    if applied:
        logger.info("applied migrations: {}", applied)
    await app.bot.set_my_commands(
        [
            BotCommand("start", "Start / say hello"),
            BotCommand("inspire", "Get an inspiration nudge now"),
            BotCommand("profile", "See what I've learned about you"),
            BotCommand("help", "How this works"),
            BotCommand("delete", "Delete all my data"),
        ]
    )


async def on_error(_: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Last-resort handler so a failure can never kill the bot *silently*.

    Without this, an unhandled error (notably `Conflict` — another getUpdates consumer
    on the same token) stops the updater while the process stays alive. The bot then
    looks fine and simply never answers again, which is the worst way to fail.
    """
    logger.opt(exception=context.error).error("unhandled telegram error: {}", context.error)


def build_application() -> Application:
    """Build the python-telegram-bot Application with all handlers attached.

    Used by both polling (this file) and the webhook server (app.py).
    """
    app = (
        ApplicationBuilder()
        .token(_require_token())
        # PTB defaults to a 5s read timeout, which is too tight for Telegram from a
        # slow or high-latency link — photo downloads (get_file + the file fetch)
        # fail spuriously with TimedOut. These are ceilings, not fixed waits, so
        # raising them costs nothing on a fast connection.
        .connect_timeout(20.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .media_write_timeout(60.0)
        # Must comfortably exceed the long-poll interval, or every poll times out.
        .get_updates_connect_timeout(20.0)
        .get_updates_read_timeout(40.0)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("inspire", cmd_inspire))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CallbackQueryHandler(on_delete_choice, pattern=r"^del:"))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    # Anything else (voice, video, sticker, document) lands here, after the above.
    app.add_handler(MessageHandler(~filters.COMMAND, on_unsupported))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    """Local entrypoint: long polling. `uv run python -m examples.inspiration_bot.bot`."""
    setup_logging()
    logger.info("starting inspiration bot (polling) in {} mode", get_settings().environment)
    build_application().run_polling()


if __name__ == "__main__":
    main()
