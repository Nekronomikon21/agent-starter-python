"""An empty read is a question, not a verdict.

Offline. The model call is replaced, so what's under test is the retry policy:
who gets asked, in what order, and what is kept when nobody can read the page.

    uv run pytest scripts/tests/test_read_page.py
"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-real")

from agent.mathcheck import read_page as rp  # noqa: E402
from agent.mathcheck.models import Problem  # noqa: E402

IMAGE = b"not-really-a-jpeg"


def problem(label: str = "1") -> Problem:
    return Problem(label=label, statement="2+2", student_answer="4", read_ok=True)


class FakeReader:
    """Returns a queued result per call, and records which model was asked."""

    def __init__(self, *results: list[Problem]):
        self.results = list(results)
        self.asked: list[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_read_once(image: bytes, *, media_type: str, model: str) -> list[Problem]:
            self.asked.append(model)
            return self.results.pop(0)

        monkeypatch.setattr(rp, "_read_once", fake_read_once)


async def test_a_good_read_never_pays_for_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = FakeReader([problem("1"), problem("2")])
    reader.install(monkeypatch)

    problems = await rp.read_page(IMAGE)

    assert [p.label for p in problems] == ["1", "2"]
    assert reader.asked == [rp.DEFAULT_MODEL]  # the second model was never asked


async def test_an_empty_read_is_retried_on_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = FakeReader([], [problem("1")])
    reader.install(monkeypatch)

    problems = await rp.read_page(IMAGE)

    # The page was readable all along; the first model just shrugged at it.
    assert [p.label for p in problems] == ["1"]
    assert reader.asked == [rp.DEFAULT_MODEL, rp.FALLBACK_MODEL]


async def test_a_page_nobody_can_read_is_kept_for_diagnosis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reader = FakeReader([], [])
    reader.install(monkeypatch)
    monkeypatch.setattr(rp, "UNREAD_DIR", tmp_path / "unread")

    problems = await rp.read_page(IMAGE)

    assert problems == []
    kept = list((tmp_path / "unread").iterdir())
    assert len(kept) == 1
    assert kept[0].read_bytes() == IMAGE  # re-runnable offline, which a log line is not


async def test_keeping_the_page_never_costs_the_user_their_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A disk that won't take the file is not a reason to fail the request."""
    reader = FakeReader([], [])
    reader.install(monkeypatch)
    monkeypatch.setattr(rp, "UNREAD_DIR", tmp_path / "unread")

    def explode(*_: object, **__: object) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr(Path, "write_bytes", explode)

    assert await rp.read_page(IMAGE) == []


async def test_the_retry_can_be_turned_off(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = FakeReader([])
    reader.install(monkeypatch)

    assert await rp.read_page(IMAGE, fallback=None) == []
    assert reader.asked == [rp.DEFAULT_MODEL]
