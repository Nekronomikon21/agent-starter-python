"""The Telegram layer: photo in, two messages out.

Wiring only — every decision lives in `pipeline.py`, every sentence in
`respond.py`. The timeouts and the error handler below are not boilerplate:
both cost this project an evening once (`journal.md` 2026-08-17).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loguru import logger
from telegram import (
    BotCommand,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
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
from agent.mathcheck.pipeline import PageResult, apply_correction, check_page
from agent.mathcheck.respond import correction_reply, message_1, message_2, reading_note

HELLO = (
    "Send me a photo of a maths problem with your working, and I'll tell you whether "
    "it's right — and if it isn't, which line went wrong."
)
FIX_BUTTON = "you misread my answer"


@dataclass
class Session:
    """The last page a user sent, so the correction button has something to fix.

    In memory, so it does not survive a restart: the correction button goes stale
    and says so. The `mathcheck_problems` table in `architecture.md` replaces this
    when the bot is deployed — a restart mid-conversation is rare in local use and
    common in production.
    """

    image: bytes
    media_type: str = "image/jpeg"
    result: PageResult | None = None
    awaiting: str | None = None  # label we asked the user about


SESSIONS: dict[int, Session] = {}

# How many photos may be in the pipeline at once. Enough that a handful of users
# never wait on each other; low enough that a burst of photos cannot fan out into
# a bill. Deliberately not `concurrent_updates(True)`, which means 256.
MAX_CONCURRENT_PAGES = 8


def _require_token() -> str:
    token = get_settings().telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add your @BotFather token to .env.")
    return token


async def _allowed(update: Update) -> bool:
    """Authorization on top of Telegram's authentication. Declines before any paid call."""
    allow = get_settings().allowed_ids
    user = update.effective_user
    # Logged so an id can be added to the allowlist without calling getUpdates,
    # which would terminate the running long-poll (`journal.md` 2026-08-17).
    if user is not None:
        logger.info("message from telegram id {} (@{})", user.id, user.username or "-")
    if allow and (user is None or user.id not in allow):
        if update.message:
            await update.message.reply_text("This bot isn't enabled for you.")
        return False
    return True


def _fix_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(FIX_BUTTON, callback_data="fix")]])


def _label_keyboard(result: PageResult) -> InlineKeyboardMarkup:
    """Every label, not only the disputed ones — a misread can wrongly *clear* a row."""
    buttons = [InlineKeyboardButton(r.label, callback_data=f"fix:{r.label}") for r in result.rows]
    return InlineKeyboardMarkup([buttons[i : i + 4] for i in range(0, len(buttons), 4)])


# --- handlers ---------------------------------------------------------------


async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _allowed(update) or update.message is None:
        return
    await update.message.reply_text(HELLO)


async def _keep_typing(chat: Chat) -> None:
    """Telegram's typing status lasts about five seconds; the work takes twenty.

    Sending it once leaves the chat frozen for the rest, which is exactly what a
    crash looks like. Refresh it until the work is done.
    """
    try:
        while True:
            await chat.send_action(ChatAction.TYPING)
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def on_photo(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """The main path: read the page, race the two passes, send both messages."""
    if not await _allowed(update) or update.message is None or update.effective_user is None:
        return
    message = update.message
    await message.reply_text("Reading your page…")
    typing = asyncio.create_task(_keep_typing(message.chat))

    try:
        photo = await message.photo[-1].get_file()  # [-1] is the largest size
        image = bytes(await photo.download_as_bytearray())
        session = Session(image=image)
        SESSIONS[update.effective_user.id] = session

        async def announce_read(result: PageResult) -> None:
            await message.reply_text(reading_note(result))

        async def send_fast_pass(result: PageResult) -> None:
            await message.reply_text(message_1(result))

        result = await check_page(image, on_read=announce_read, on_fast_pass=send_fast_pass)
        session.result = result

        second = message_2(result)
        await message.reply_text(second or "Nothing else to flag.", reply_markup=_fix_keyboard())
    except Exception as exc:
        # Never leave the chat silent. Without this, a failure anywhere in the
        # page shows the user a progress note and then nothing, ever — which is
        # exactly the "it froze" complaint, arriving by a different route.
        logger.opt(exception=exc).error("checking the page failed")
        await message.reply_text(
            "Something went wrong on my side and I couldn't finish checking that page. "
            "Send it again and I'll retry."
        )
        return
    finally:
        typing.cancel()

    # One open question and one row to ask about: a plain reply is unambiguous.
    waiting = [r for r in result.rows if r.status == "awaiting_user"]
    session.awaiting = waiting[0].label if len(waiting) == 1 else None


async def on_fix(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """`you misread my answer` → the labels, then which one."""
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    await query.answer()
    if not await _allowed(update):
        return  # a stranger has no session anyway, but the check belongs on every path
    session = SESSIONS.get(update.effective_user.id)
    if session is None or session.result is None:
        await query.edit_message_text("That page is gone — send it again and I'll recheck it.")
        return

    data = query.data or ""
    if data == "fix":
        await query.edit_message_reply_markup(reply_markup=_label_keyboard(session.result))
        return

    label = data.removeprefix("fix:")
    session.awaiting = label
    await query.edit_message_reply_markup(reply_markup=None)
    if isinstance(query.message, Message):
        await query.message.reply_text(
            f"What did you write for {label}? Type it, or send a clearer photo."
        )


async def on_text(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """A typed answer, when we've asked for one. Otherwise, a nudge."""
    if not await _allowed(update) or update.message is None or update.effective_user is None:
        return
    session = SESSIONS.get(update.effective_user.id)
    if session is None or session.result is None or session.awaiting is None:
        await update.message.reply_text(HELLO)
        return

    label, session.awaiting = session.awaiting, None
    row = next((r for r in session.result.rows if r.label == label), None)
    if row is None:
        await update.message.reply_text(HELLO)
        return

    # A correction runs solve and review too, so it can take half a minute. One
    # `send_action` lasts about five seconds; the silence after it reads as a crash
    # exactly the way the photo path used to.
    typing = asyncio.create_task(_keep_typing(update.message.chat))
    try:
        await apply_correction(
            row, update.message.text or "", session.image, media_type=session.media_type
        )
    except Exception as exc:
        logger.opt(exception=exc).error("applying the correction failed")
        await update.message.reply_text(
            "Something went wrong on my side and I couldn't recheck that one. "
            "Send the page again and I'll retry."
        )
        return
    finally:
        typing.cancel()
    await update.message.reply_text(correction_reply(row), reply_markup=_fix_keyboard())


async def on_unsupported(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is not None:
        await update.message.reply_text("I can take a photo of your working, or text.")


async def on_error(_: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A failure must never kill the bot *silently*.

    Without this, an unhandled error — classically `Conflict`, another getUpdates
    consumer on the same token — stops the updater while the process stays alive.
    The bot then looks healthy and simply never answers again.
    """
    logger.opt(exception=context.error).error("unhandled telegram error: {}", context.error)


# --- wiring -----------------------------------------------------------------


async def post_init(app: Application) -> None:
    if not get_settings().allowed_ids:
        logger.warning(
            "ALLOWED_TELEGRAM_IDS is empty: anyone who finds this bot can spend your credits"
        )
    await app.bot.set_my_commands([BotCommand("start", "How this works")])


def build_application() -> Application:
    """Attach every handler. Used by polling here, and by a webhook server later."""
    app = (
        ApplicationBuilder()
        .token(_require_token())
        # PTB defaults to a 5s read timeout, too tight for this link: every
        # photo download fails with TimedOut while text works fine. That
        # asymmetry is the tell. Ceilings, not waits — free on a fast link.
        .connect_timeout(20.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .media_write_timeout(60.0)
        # Must comfortably exceed the long-poll interval.
        .get_updates_connect_timeout(20.0)
        .get_updates_read_timeout(40.0)
        # PTB processes updates one at a time by default (its builder sets
        # max_concurrent_updates=1). With more than one user that is not a slow
        # reply, it is *no* reply: the second person's photo sits behind the
        # first person's whole ~40s pipeline, ack included.
        .concurrent_updates(MAX_CONCURRENT_PAGES)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_fix, pattern=r"^fix"))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(~filters.COMMAND, on_unsupported))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    """`uv run mathcheck-bot` — long polling, for local use."""
    setup_logging()
    logger.info("starting mathcheck bot (polling)")
    build_application().run_polling()


if __name__ == "__main__":
    main()
