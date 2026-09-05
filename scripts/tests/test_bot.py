"""The Telegram wiring.

The handlers are deliberately thin — every decision lives in `pipeline.py` and
every sentence in `respond.py`, both tested there. What is worth asserting here
is the builder configuration that a *second* user depends on, because nothing
about it is visible until two people use the bot at once.

    uv run pytest scripts/tests/test_bot.py
"""

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-real")

from telegram.ext import Application  # noqa: E402

from agent.config import get_settings  # noqa: E402
from agent.mathcheck import bot  # noqa: E402


@pytest.fixture
def application(monkeypatch: pytest.MonkeyPatch) -> Iterator[Application]:
    """A built Application, with a fake token and the settings cache restored."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:fake-token-for-tests")
    get_settings.cache_clear()
    try:
        yield bot.build_application()
    finally:
        get_settings.cache_clear()


def test_one_users_page_does_not_block_another(application: Application) -> None:
    """PTB processes updates one at a time unless told otherwise.

    That default is invisible with one user and brutal with two: the second
    person's photo waits behind the first person's whole pipeline, so they get
    no reply at all — not a slow one — for the better part of a minute.
    """
    assert application.concurrent_updates > 1


def test_concurrency_is_capped(application: Application) -> None:
    """`concurrent_updates(True)` means 256, and each of these spends real money.

    Every page is a read, a solve per row and an Opus review. The cap is what
    stops a burst of photos fanning out into a bill.
    """
    assert application.concurrent_updates == bot.MAX_CONCURRENT_PAGES
    assert bot.MAX_CONCURRENT_PAGES <= 16
