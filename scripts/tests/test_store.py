"""The page store: what has to survive a restart.

The round-trip test is offline and is the one that matters — it pins exactly the
fields a correction needs, and it fails loudly if `Row` grows one that `store`
forgets to persist. The live test then proves the same thing through real
Postgres, because "it serialises" and "it round-trips through JSONB" are not the
same claim.

    uv run pytest scripts/tests/test_store.py
    uv run pytest -m integration scripts/tests/test_store.py
"""

import os

import pytest

os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-real")

from agent.config import get_settings  # noqa: E402
from agent.mathcheck import store  # noqa: E402
from agent.mathcheck.models import Problem  # noqa: E402
from agent.mathcheck.pipeline import PageResult, Row  # noqa: E402
from agent.mathcheck.review import Review  # noqa: E402

# A user id no real Telegram account can have, so a live run can't touch a person.
TEST_USER = -999_001


def _page() -> PageResult:
    """One of every kind of row the correction path has to cope with."""
    return PageResult(
        rows=[
            Row(
                problem=Problem(
                    label="№1",
                    statement="|4(x+2)| = 82",
                    student_answer="21",
                    read_ok=False,
                    uncertain_field="answer",
                ),
                correct_answer="{18.5, -22.5}",
                status="awaiting_user",
            ),
            Row(
                problem=Problem(
                    label="№2", statement="2(x+7)^2 = 81", student_answer="-2.5", read_ok=True
                ),
                correct_answer="{-2.5, -11.5}",
                answer_source="user_confirmed",
                status="diagnosed",
                verdict=Review(
                    verdict="mistake", line="2(x+7) = 9", line_number=2, why="the ± was dropped"
                ),
            ),
            Row(
                problem=Problem(
                    label="№4",
                    statement="y = x + 2",
                    student_answer="a graph",
                    answer_kind="drawing",
                    read_ok=True,
                ),
                status="uncheckable",
            ),
        ]
    )


def test_a_row_survives_the_round_trip() -> None:
    """Everything `apply_correction` and `correction_reply` read must come back."""
    for original in _page().rows:
        restored = store._load_row(store._dump_row(original))

        assert restored.problem == original.problem  # all six transcription fields
        assert restored.correct_answer == original.correct_answer
        assert restored.answer_source == original.answer_source
        assert restored.status == original.status
        assert restored.verdict == original.verdict


def test_the_verdict_line_survives() -> None:
    """The line is what a corrected-but-still-wrong reply points at."""
    diagnosed = _page().rows[1]
    restored = store._load_row(store._dump_row(diagnosed))

    assert restored.verdict is not None
    assert restored.verdict.line == "2(x+7) = 9"
    assert restored.verdict.why == "the ± was dropped"


def test_a_restored_row_is_not_stuck_settled() -> None:
    """`settled` is in-flight signalling between the workers, not state to persist.

    A restored row must start unset, or a later review on it would be dropped the
    instant it began.
    """
    restored = store._load_row(store._dump_row(_page().rows[0]))

    assert not restored.settled.is_set()


# --- live, against real Postgres ---------------------------------------------


def _db_ready() -> bool:
    try:
        return bool(get_settings().database_url)
    except Exception:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _db_ready(), reason="DATABASE_URL not set in .env")
async def test_a_page_outlives_the_process() -> None:
    """Save, read back, correct, read back again — the restart the deploy performs."""
    from agent.services import db

    await db.apply_migrations(store.MIGRATIONS)
    await store.forget(TEST_USER)
    try:
        await store.save_page(
            TEST_USER,
            photo_file_id="AgACAgIAAxkBAAI-fake-file-id",
            media_type="image/jpeg",
            result=_page(),
            awaiting="№1",
        )

        stored = await store.load_page(TEST_USER)
        assert stored is not None
        assert stored.awaiting == "№1"
        assert stored.photo_file_id == "AgACAgIAAxkBAAI-fake-file-id"
        assert [r.label for r in stored.result.rows] == ["№1", "№2", "№4"]
        assert stored.result.rows[1].verdict is not None
        assert stored.result.rows[1].verdict.line == "2(x+7) = 9"
        assert stored.result.rows[2].problem.answer_kind == "drawing"

        # The user answers the question we asked, and the row is re-decided.
        await store.set_awaiting(TEST_USER, None)
        stored.result.rows[0].status = "cleared"
        await store.save_rows(TEST_USER, stored.result)

        again = await store.load_page(TEST_USER)
        assert again is not None
        assert again.awaiting is None
        assert again.result.rows[0].status == "cleared"
        assert again.photo_file_id == "AgACAgIAAxkBAAI-fake-file-id"  # untouched by save_rows
    finally:
        await store.forget(TEST_USER)
        await db.close_pool()


@pytest.mark.integration
@pytest.mark.skipif(not _db_ready(), reason="DATABASE_URL not set in .env")
async def test_a_user_with_no_page_reads_back_as_nothing() -> None:
    """The correction button's "that page is gone" path."""
    from agent.services import db

    await db.apply_migrations(store.MIGRATIONS)
    await store.forget(TEST_USER)
    try:
        assert await store.load_page(TEST_USER) is None
    finally:
        await db.close_pool()
