"""The production webhook: who gets in, and what happens to an update once it does.

Offline. The endpoint is called directly with a stub request, so nothing here
starts a server, builds a real Application or touches Telegram.

    uv run pytest scripts/tests/test_webhook.py
"""

import asyncio
import os
from typing import Any

import pytest
from fastapi import HTTPException

os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-real")

from agent.config import get_settings  # noqa: E402
from agent.mathcheck import app as webhook  # noqa: E402

SECRET = "a-long-random-webhook-secret"
UPDATE = {"update_id": 1}


class _Request:
    """Just enough of `fastapi.Request` for the endpoint: it only reads the body."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def json(self) -> dict[str, Any]:
        return self._payload


class _FakePTB:
    """A stand-in Application. `process_update` records, so we can prove it is unused."""

    def __init__(self) -> None:
        self.bot = None
        self.update_queue: asyncio.Queue[Any] = asyncio.Queue()
        self.processed: list[Any] = []

    async def process_update(self, update: Any) -> None:
        self.processed.append(update)


@pytest.fixture
def secret_set(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture
def no_secret(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


async def test_a_missing_secret_closes_the_endpoint(no_secret: None) -> None:
    """Fail closed. An unconfigured secret must not mean "let everyone in".

    This endpoint sits on a public URL and every accepted update spends money.
    """
    with pytest.raises(HTTPException) as raised:
        await webhook.telegram_webhook(_Request(UPDATE), SECRET)  # pyright: ignore[reportArgumentType]

    assert raised.value.status_code == 403


async def test_a_wrong_secret_is_refused(secret_set: None) -> None:
    with pytest.raises(HTTPException) as raised:
        await webhook.telegram_webhook(_Request(UPDATE), "not-the-secret")  # pyright: ignore[reportArgumentType]

    assert raised.value.status_code == 403


async def test_no_header_at_all_is_refused(secret_set: None) -> None:
    with pytest.raises(HTTPException) as raised:
        await webhook.telegram_webhook(_Request(UPDATE), None)  # pyright: ignore[reportArgumentType]

    assert raised.value.status_code == 403


async def test_an_update_before_startup_is_a_503(
    secret_set: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Telegram retries a 503, so an update arriving mid-boot isn't lost."""
    monkeypatch.setattr(webhook, "_ptb", None)

    with pytest.raises(HTTPException) as raised:
        await webhook.telegram_webhook(_Request(UPDATE), SECRET)  # pyright: ignore[reportArgumentType]

    assert raised.value.status_code == 503


async def test_a_valid_update_is_queued_not_awaited(
    secret_set: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The decision this file exists to protect.

    Checking a page takes the better part of a minute. Awaiting it here holds
    Telegram's connection until it times out and re-delivers the update — two
    answers and two bills for one photo — and bypasses `MAX_CONCURRENT_PAGES`,
    which only applies on the queue path.
    """
    fake = _FakePTB()
    monkeypatch.setattr(webhook, "_ptb", fake)

    result = await webhook.telegram_webhook(_Request(UPDATE), SECRET)  # pyright: ignore[reportArgumentType]

    assert result == {"ok": True}
    assert fake.update_queue.qsize() == 1, "the update must reach PTB's own queue"
    assert fake.processed == [], "it must not be processed inline"


def test_the_webhook_path_carries_no_secret() -> None:
    """A secret in the URL lands in proxy and access logs on every request."""
    assert webhook.WEBHOOK_PATH == "/telegram/webhook"
    assert SECRET not in webhook.WEBHOOK_PATH
