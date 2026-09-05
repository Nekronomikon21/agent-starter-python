"""Production entrypoint: the Telegram webhook, hosted by FastAPI.

    uv run fastapi run src/agent/mathcheck/app.py   # what Railway runs
    uv run mathcheck-bot                            # what you run locally (polling)

Locally the bot long-polls and needs no public URL. Deployed it can't: Railway
hands us a URL and Telegram pushes updates to it. The switch is entirely config —
`PUBLIC_URL` set means "register a webhook" — so the same handlers serve both and
there is no second copy of the logic to keep in step.

**A different bot token per environment is not optional.** Telegram allows one
update-consumer per token, so a local poller and a deployed webhook sharing one
token produce `409 Conflict` and a bot that answers intermittently or not at all
(`docs/deploy.md`).
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from loguru import logger
from telegram import Update
from telegram.ext import Application

from agent.config import get_settings
from agent.logging_setup import setup_logging
from agent.mathcheck.bot import build_application, post_init, post_shutdown

# No secret in the path. URLs are written to proxy and access logs on every
# request; the header Telegram echoes back is not (`docs/deploy.md`).
WEBHOOK_PATH = "/telegram/webhook"

_ptb: Application | None = None  # built on startup, torn down on shutdown


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Drive the PTB Application by hand, because FastAPI owns the process.

    `Application.initialize()` and `.shutdown()` do **not** run `post_init` and
    `post_shutdown` — their own docstrings say so, and only `run_polling` and
    `run_webhook` call them. Forget that and the migrations never run in
    production, which is precisely where the table has to exist.
    """
    global _ptb
    setup_logging()
    settings = get_settings()
    ptb = build_application()
    _ptb = ptb

    await ptb.initialize()
    await post_init(ptb)
    await ptb.start()  # starts the background fetcher that drains `update_queue`

    if settings.public_url:
        url = f"{settings.public_url.rstrip('/')}{WEBHOOK_PATH}"
        # `drop_pending_updates` is deliberately left off: a photo sent during a
        # deploy would otherwise vanish in silence, and a late answer beats none.
        await ptb.bot.set_webhook(
            url=url,
            secret_token=settings.telegram_webhook_secret,
            allowed_updates=Update.ALL_TYPES,
        )
        logger.info("webhook registered at {}", url)
    else:
        logger.warning("PUBLIC_URL not set — no webhook registered (fine for local dev)")

    yield

    await ptb.stop()
    await ptb.shutdown()
    await post_shutdown(ptb)


app = FastAPI(title="Maths homework checker", lifespan=lifespan)


@app.get("/")
async def root() -> dict[str, str]:
    """Liveness. Deliberately says nothing about the bot — it is a public URL."""
    return {"status": "ok"}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    """Take one update from Telegram, queue it, and answer immediately.

    **Queued, not awaited.** Checking a page takes the better part of a minute;
    holding Telegram's connection open that long gets the update re-delivered on
    timeout — two answers and two bills for one photo. Putting it on PTB's own
    queue also keeps `MAX_CONCURRENT_PAGES`, which a direct `process_update` call
    would bypass.

    Fails closed: no configured secret means nothing is accepted at all, rather
    than an open endpoint sitting on a public URL.
    """
    secret = get_settings().telegram_webhook_secret
    if not secret or not secrets.compare_digest(x_telegram_bot_api_secret_token or "", secret):
        raise HTTPException(status_code=403)

    ptb = _ptb
    if ptb is None:
        raise HTTPException(status_code=503)

    update = Update.de_json(await request.json(), ptb.bot)
    if update is not None:
        await ptb.update_queue.put(update)
    return {"ok": True}
