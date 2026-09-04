"""The race: a fast solve against a slow review, with cancel-and-skip.

Offline. `read_page`, `solve` and `review` are replaced with fakes, so this
tests the orchestration itself — which rows get reviewed, which get dropped,
and when message 1 fires.

    uv run pytest scripts/tests/test_pipeline.py
"""

import asyncio
import os

import pytest

os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-real")

from agent.mathcheck import pipeline as pl  # noqa: E402
from agent.mathcheck.models import Problem  # noqa: E402
from agent.mathcheck.review import Review  # noqa: E402

IMAGE = b"not-really-a-jpeg"


def problem(label: str, statement: str, answer: str, read_ok: bool = True) -> Problem:
    return Problem(
        label=label,
        statement=statement,
        student_answer=answer,
        read_ok=read_ok,
        uncertain_field=None if read_ok else "answer",
    )


class Fakes:
    """Stand-ins for the three models, with counters."""

    def __init__(self, problems: list[Problem], answers: dict[str, str], verdict: str = "mistake"):
        self.problems = problems
        self.answers = answers  # label -> what `solve` returns
        self.verdict = verdict
        self.review_started: list[str] = []
        self.review_finished: list[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_read_page(image, *, media_type="image/jpeg", model=""):  # noqa: ANN001
            return self.problems

        async def fake_solve(statement, *, model=""):  # noqa: ANN001
            await asyncio.sleep(0.01)  # the fast pass
            label = next(p.label for p in self.problems if p.statement == statement)
            return self.answers[label]

        async def fake_review(image, statement, *, label=None, media_type="", model=""):  # noqa: ANN001
            self.review_started.append(label or "?")
            await asyncio.sleep(0.20)  # the slow pass
            self.review_finished.append(label or "?")
            return Review(verdict=self.verdict, line="line 2", why="the rule")

        monkeypatch.setattr(pl, "read_page", fake_read_page)
        monkeypatch.setattr(pl, "solve", fake_solve)
        monkeypatch.setattr(pl, "review", fake_review)


async def test_all_correct_never_pays_for_a_review(monkeypatch: pytest.MonkeyPatch) -> None:
    problems = [problem("1", "a", "17"), problem("2", "b", "11/12")]
    fakes = Fakes(problems, {"1": "17", "2": "11/12"})
    fakes.install(monkeypatch)

    result = await pl.check_page(IMAGE)

    assert [r.status for r in result.rows] == ["cleared", "cleared"]
    # It may speculate, but nothing expensive is allowed to *complete*.
    assert fakes.review_finished == []


async def test_only_the_disputed_row_is_reviewed(monkeypatch: pytest.MonkeyPatch) -> None:
    problems = [problem("1", "a", "17"), problem("2", "b", "9"), problem("3", "c", "5")]
    fakes = Fakes(problems, {"1": "17", "2": "17", "3": "5"})
    fakes.install(monkeypatch)

    result = await pl.check_page(IMAGE)

    assert fakes.review_finished == ["2"]
    assert {r.label: r.status for r in result.rows} == {
        "1": "cleared",
        "2": "diagnosed",
        "3": "cleared",
    }
    assert result.rows[1].verdict is not None
    assert result.rows[1].verdict.why


async def test_a_review_in_flight_is_cancelled_when_its_row_clears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Row 1 is correct but gets speculated on first; row 2 is the wrong one.
    problems = [problem("1", "a", "17"), problem("2", "b", "9")]
    fakes = Fakes(problems, {"1": "17", "2": "17"})
    fakes.install(monkeypatch)

    await pl.check_page(IMAGE)

    assert "1" in fakes.review_started, "row 1 should have been speculated on"
    assert fakes.review_finished == ["2"], "row 1's review must be dropped, not awaited"


async def test_message_1_fires_before_the_review_lands(monkeypatch: pytest.MonkeyPatch) -> None:
    problems = [problem("1", "a", "9")]
    fakes = Fakes(problems, {"1": "17"})
    fakes.install(monkeypatch)
    seen: list[tuple[str, str | None]] = []

    async def on_fast_pass(result: pl.PageResult) -> None:
        row = result.rows[0]
        seen.append((row.status, row.correct_answer))
        assert row.verdict is None, "message 1 must not wait for the diagnosis"

    result = await pl.check_page(IMAGE, on_fast_pass=on_fast_pass)

    assert seen == [("disputed", "17")]
    assert result.rows[0].status == "diagnosed"


async def test_shaky_reading_plus_dispute_goes_to_the_user_not_the_reviewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problems = [problem("1", "a", "9", read_ok=False)]
    fakes = Fakes(problems, {"1": "17"})
    fakes.install(monkeypatch)

    result = await pl.check_page(IMAGE)

    assert result.rows[0].status == "awaiting_user"
    assert fakes.review_started == [], "a row we must ask about is never speculated on"


async def test_shaky_reading_that_agrees_asks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate that keeps the bot quiet: read_ok is false, but the answers agree."""
    problems = [problem("1", "a", "17", read_ok=False)]
    fakes = Fakes(problems, {"1": "17"})
    fakes.install(monkeypatch)

    result = await pl.check_page(IMAGE)

    assert result.rows[0].status == "cleared"
    assert fakes.review_started == []


async def test_valid_verdict_exonerates(monkeypatch: pytest.MonkeyPatch) -> None:
    """`solve` was wrong; review says the working is fine. The student is right."""
    problems = [problem("1", "a", "9")]
    fakes = Fakes(problems, {"1": "17"}, verdict="valid")
    fakes.install(monkeypatch)

    result = await pl.check_page(IMAGE)

    assert result.rows[0].status == "exonerated"


# --- the two messages ---------------------------------------------------------


async def _run(monkeypatch: pytest.MonkeyPatch, fakes: Fakes) -> pl.PageResult:
    fakes.install(monkeypatch)
    return await pl.check_page(IMAGE)


async def test_all_correct_says_so_and_sends_no_second_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent.mathcheck.respond import message_1, message_2

    problems = [problem("1", "a", "17"), problem("2", "b", "5")]
    result = await _run(monkeypatch, Fakes(problems, {"1": "17", "2": "5"}))

    assert message_1(result) == "All of them look right."
    assert message_2(result) is None


async def test_message_1_reports_and_never_judges(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent.mathcheck.respond import message_1

    problems = [problem("1", "a", "17"), problem("2", "b", "9"), problem("3", "c", "5")]
    result = await _run(monkeypatch, Fakes(problems, {"1": "17", "2": "17", "3": "5"}))

    text = message_1(result)
    assert text == "1 and 3 look right. Checking your working on 2 now."
    # It goes out before the review has verified anything...
    for accusation in ("wrong", "mistake", "incorrect"):
        assert accusation not in text.lower(), text
    # ...and it carries no answer, so it can't be read as an answer key.
    assert "17" not in text


async def test_message_2_names_the_line_and_the_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent.mathcheck.respond import message_2

    result = await _run(monkeypatch, Fakes([problem("2", "b", "9")], {"2": "17"}))

    assert message_2(result) == "2 — wrong. line 2: the rule The answer is 17."


async def test_message_2_retracts_when_the_student_was_right(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await _run(monkeypatch, Fakes([problem("2", "b", "9")], {"2": "17"}, verdict="valid"))
    from agent.mathcheck.respond import message_2

    text = message_2(result) or ""
    assert "your 9 for 2 is right" in text
    assert "my first pass had it wrong" in text


async def test_message_2_asks_rather_than_accuses_on_a_shaky_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent.mathcheck.respond import message_2

    result = await _run(monkeypatch, Fakes([problem("1", "a", "9", read_ok=False)], {"1": "17"}))

    text = message_2(result) or ""
    assert text == "For 1 I read your answer as 9 — is that right, or what did you write?"
    assert "wrong" not in text.lower()


async def test_a_drawn_answer_is_never_solved_or_reviewed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """page01 №4: a graph. `solve` returned nonsense and `review` then invented a
    critique of the sketch — a manufactured mistake by a route the exits miss."""
    from agent.mathcheck.respond import message_1, message_2

    drawn = Problem(
        label="4",
        statement="y = x + 2",
        student_answer="a graph",
        answer_kind="drawing",
        read_ok=True,
    )
    fakes = Fakes([drawn], {"4": "unused"})
    fakes.install(monkeypatch)

    result = await pl.check_page(IMAGE)

    assert result.rows[0].status == "uncheckable"
    assert fakes.review_started == []
    assert result.rows[0].correct_answer is None, "no point solving a drawing"
    assert "drawing" in (message_2(result) or "")
    assert message_1(result)  # still says something rather than crashing


async def test_a_quoted_answer_never_breaks_the_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Answers come off a photo with newlines in them (page01 №3: 'x = 6\ny = 5')."""
    from agent.mathcheck.respond import message_2

    messy = Problem(
        label="3",
        statement="x + 7 = y + 8; x = y + 1",
        student_answer="x = 6\ny = 5",
        read_ok=False,
        uncertain_field="answer",
    )
    fakes = Fakes([messy], {"3": "infinitely many solutions"})
    fakes.install(monkeypatch)

    result = await pl.check_page(IMAGE)
    text = message_2(result) or ""

    assert "\n" not in text
    assert "x = 6 y = 5" in text


async def test_a_literal_escape_in_an_answer_is_flattened_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """read_page sometimes emits the two-character escape, not a real newline."""
    from agent.mathcheck.respond import message_2

    messy = Problem(
        label="3",
        statement="x + 7 = y + 8; x = y + 1",
        student_answer="{ x = 6\\n{ y = 5",
        read_ok=False,
        uncertain_field="answer",
    )
    fakes = Fakes([messy], {"3": "infinitely many solutions"})
    fakes.install(monkeypatch)

    text = message_2(await pl.check_page(IMAGE)) or ""

    assert "\\n" not in text, text
    assert "{ x = 6 { y = 5" in text
