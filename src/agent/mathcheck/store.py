"""Conversation state that outlives the process.

One row per user: the last page they sent, so `you misread my answer` still works
after a restart. Locally that's a rare annoyance; on a deploy it's routine, since
every release restarts the process (`docs/architecture.md`).

**We store Telegram's `file_id`, never the photo's bytes.** Telegram keeps the
file and hands it back on demand, so a correction re-downloads it. No blobs in
Postgres, no R2 dependency, and the photo still only lives in memory for the
length of a request — which is what `architecture.md` says about `storage`.

Every query is parameterised and scoped by `telegram_id`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from agent.mathcheck.models import Problem
from agent.mathcheck.pipeline import AnswerSource, PageResult, Row, Status
from agent.mathcheck.review import Review
from agent.services import db

MIGRATIONS = Path(__file__).parent / "migrations"


@dataclass
class StoredPage:
    """A page read back out of the database, ready for a correction."""

    result: PageResult
    photo_file_id: str
    media_type: str
    awaiting: str | None  # the label we asked about, if we asked about one


def _dump_row(row: Row) -> dict[str, Any]:
    """One `Row` → JSON. `settled` is deliberately dropped: it is an in-flight
    signal between the two workers, meaningless once the page is settled."""
    return {
        "problem": row.problem.model_dump(),
        "correct_answer": row.correct_answer,
        "answer_source": row.answer_source,
        "status": row.status,
        "verdict": row.verdict.model_dump() if row.verdict is not None else None,
    }


def _load_row(data: dict[str, Any]) -> Row:
    verdict = data.get("verdict")
    return Row(
        problem=Problem(**data["problem"]),
        correct_answer=data.get("correct_answer"),
        answer_source=cast(AnswerSource, data.get("answer_source", "read")),
        status=cast(Status, data["status"]),
        verdict=Review(**verdict) if verdict else None,
    )


def _dump_rows(result: PageResult) -> str:
    # No JSON codec is registered on the shared pool, so jsonb goes in and comes
    # back as text. Encoding here keeps `services/db.py` generic for other projects.
    return json.dumps([_dump_row(row) for row in result.rows])


def _load_rows(raw: Any) -> list[Row]:
    data = json.loads(raw) if isinstance(raw, str) else raw
    return [_load_row(item) for item in data]


async def save_page(
    telegram_id: int,
    *,
    photo_file_id: str,
    media_type: str,
    result: PageResult,
    awaiting: str | None = None,
) -> None:
    """Replace whatever we held for this user with the page they just sent."""
    await db.execute(
        """
        INSERT INTO mathcheck_sessions
            (telegram_id, photo_file_id, media_type, awaiting, rows, updated_at)
        VALUES ($1, $2, $3, $4, $5, now())
        ON CONFLICT (telegram_id) DO UPDATE SET
            photo_file_id = EXCLUDED.photo_file_id,
            media_type    = EXCLUDED.media_type,
            awaiting      = EXCLUDED.awaiting,
            rows          = EXCLUDED.rows,
            updated_at    = now()
        """,
        telegram_id,
        photo_file_id,
        media_type,
        awaiting,
        _dump_rows(result),
    )


async def load_page(telegram_id: int) -> StoredPage | None:
    """The last page this user sent, or None when we have nothing for them."""
    record = await db.fetchrow(
        "SELECT photo_file_id, media_type, awaiting, rows"
        " FROM mathcheck_sessions WHERE telegram_id = $1",
        telegram_id,
    )
    if record is None:
        return None
    return StoredPage(
        result=PageResult(rows=_load_rows(record["rows"])),
        photo_file_id=record["photo_file_id"],
        media_type=record["media_type"],
        awaiting=record["awaiting"],
    )


async def set_awaiting(telegram_id: int, label: str | None) -> None:
    """Remember which problem we asked about — or that we are no longer asking."""
    await db.execute(
        "UPDATE mathcheck_sessions SET awaiting = $2, updated_at = now() WHERE telegram_id = $1",
        telegram_id,
        label,
    )


async def save_rows(telegram_id: int, result: PageResult) -> None:
    """Write the rows back after a correction re-decided one."""
    await db.execute(
        "UPDATE mathcheck_sessions SET rows = $2, updated_at = now() WHERE telegram_id = $1",
        telegram_id,
        _dump_rows(result),
    )


async def forget(telegram_id: int) -> None:
    """Drop a user's page. Used by the tests; a user has no way to call it yet."""
    await db.execute("DELETE FROM mathcheck_sessions WHERE telegram_id = $1", telegram_id)
