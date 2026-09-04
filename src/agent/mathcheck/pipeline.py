"""Race a fast solve against a slow review, over the rows of one page.

The shape (`docs/architecture.md`): both workers start at once. `solve` can only
ever *clear* a row; `review` is the expensive pass and survives only where the
answers disagree. So the strong model is already in flight by the time we know
we need it, and gets dropped on every row that turns out fine.

State lives in memory for the length of one request. The row *states* are what
make cancel-and-skip safe; the table in `architecture.md` is how they survive
across messages, and arrives with the Telegram layer that needs it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from loguru import logger

from agent.mathcheck.compare import compare
from agent.mathcheck.models import Problem
from agent.mathcheck.read_page import read_page
from agent.mathcheck.review import Review, review
from agent.mathcheck.solve import solve

Status = Literal[
    "pending",
    "cleared",
    "disputed",
    "awaiting_user",
    "diagnosed",
    "exonerated",
    "wrong_problem",
    "uncheckable",
    "unanswered",
    "unreadable",
    "failed",
]


# What each review verdict does to the row.
_OUTCOME: dict[str, Status] = {
    "mistake": "diagnosed",
    "valid": "exonerated",
    "wrong_problem": "wrong_problem",
}


# "?", "x = ?", a dash, a blank: they have not answered it. Checked in code as
# well as asked of the model, because a missed flag here means `review` is sent
# to find the mistake in unfinished working — and it will find one.
_NOT_AN_ANSWER = set("?-—–.…") | {" ", chr(9), chr(10)}


def _has_no_statement(statement: str) -> bool:
    """No question text: there is nothing to solve and nothing to check against.

    `read_page` can return a row with a label and an answer but no question — a
    continuation sheet, or a crop that cut the wording off. Handing that to
    `solve` sends the model an empty prompt, which every provider rejects with a
    400. Every other guard here watches the *answer*; this one watches the
    statement, and its absence is what took a whole page down.
    """
    return not statement.strip()


def _looks_unanswered(answer: str) -> bool:
    stripped = answer.strip()
    if not stripped:
        return True
    body = stripped.split("=")[-1]  # "x = ?" -> "?"
    return all(ch in _NOT_AN_ANSWER for ch in body)


@dataclass
class Row:
    """One problem, and everything we learn about it."""

    problem: Problem
    correct_answer: str | None = None
    # Once the user tells us what they wrote, no model gets to second-guess it.
    answer_source: Literal["read", "user_confirmed"] = "read"
    status: Status = "pending"
    verdict: Review | None = None
    # Set when the row is cleared, so a review already in flight can be cancelled.
    settled: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def label(self) -> str:
        return self.problem.label

    @property
    def needs_user(self) -> bool:
        """Both gates: the reading was shaky *and* the answers disagree."""
        return self.status == "disputed" and not self.problem.read_ok


@dataclass
class PageResult:
    """Everything the two passes concluded about one photo."""

    rows: list[Row]

    @property
    def cleared(self) -> list[Row]:
        return [r for r in self.rows if r.status == "cleared"]

    @property
    def unresolved(self) -> list[Row]:
        return [r for r in self.rows if r.status != "cleared"]


async def _solve_row(row: Row, changed: asyncio.Event) -> None:
    """Fast pass: re-derive, compare, settle or dispute. Never sees their work."""
    try:
        row.correct_answer = await solve(row.problem.statement)
    except Exception as exc:
        # We simply have no second opinion for this row. `review` reads the photo
        # directly and never needed our answer, so hand the row to it rather than
        # dropping it — a degraded check beats a lost page.
        logger.opt(exception=exc).warning("solve failed for {}", row.label)
        row.status = "disputed"
        changed.set()
        return
    if compare(row.problem.student_answer, row.correct_answer) == "agree":
        row.status = "cleared"
        row.settled.set()  # drops any review already running on this row
    else:
        row.status = "disputed"
    changed.set()


def _next_to_review(rows: list[Row], reviewed: set[str]) -> Row | None:
    """Disputed rows first — those are known to need it. Then speculate, in order.

    Rows flagged `read_ok = false` are never speculated on: they either clear, or
    they go to the user. Review is not their next step either way.
    """
    for row in rows:
        if row.status == "disputed" and row.label not in reviewed and row.problem.read_ok:
            return row
    for row in rows:
        if row.status == "pending" and row.label not in reviewed and row.problem.read_ok:
            return row
    return None


async def _review_worker(
    image: bytes, media_type: str, rows: list[Row], changed: asyncio.Event
) -> None:
    """Slow pass: walk the page, dropping every row the fast pass clears."""
    reviewed: set[str] = set()
    while True:
        row = _next_to_review(rows, reviewed)
        if row is None:
            if all(r.status != "pending" for r in rows):
                return  # nothing left that review could be needed for
            changed.clear()
            await changed.wait()  # a solve is still out; wait for it to land
            continue

        reviewed.add(row.label)
        running = asyncio.create_task(
            review(image, row.problem.statement, label=row.label, media_type=media_type)
        )
        cleared = asyncio.create_task(row.settled.wait())
        done, _ = await asyncio.wait({running, cleared}, return_when=asyncio.FIRST_COMPLETED)

        if running in done:
            cleared.cancel()
            if row.status == "cleared":
                continue  # it landed just after the row settled; throw it away
            try:
                row.verdict = running.result()
            except Exception as exc:
                # Review is the only pass that can produce a verdict, so we cannot
                # judge this row at all. Say so, and keep walking the page.
                logger.opt(exception=exc).warning("review failed for {}", row.label)
                row.status = "failed"
                continue
            row.status = _OUTCOME[row.verdict.verdict]
        else:
            running.cancel()  # speculative work on a row that turned out fine


async def check_page(
    image: bytes,
    *,
    media_type: str = "image/jpeg",
    on_read: Callable[[PageResult], Awaitable[None]] | None = None,
    on_fast_pass: Callable[[PageResult], Awaitable[None]] | None = None,
) -> PageResult:
    """Photo → a verdict per problem.

    `on_read` fires as soon as the page is transcribed, `on_fast_pass` the moment
    the fast pass finishes every row. Both exist because reading and solving take
    long enough that silence reads as a crash.
    """
    problems = await read_page(image, media_type=media_type)
    rows = [Row(problem=p) for p in problems]
    # A drawn answer has nothing to compare and nothing to walk. Solving it wastes
    # a call, and handing it to `review` produces a confident critique of a sketch.
    for row in rows:
        if _has_no_statement(row.problem.statement):
            row.status = "unreadable"
            row.settled.set()
        elif row.problem.answer_kind == "drawing":
            row.status = "uncheckable"
            row.settled.set()
        elif row.problem.answer_kind == "missing" or _looks_unanswered(row.problem.student_answer):
            # Nothing to compare and nothing to walk. Asking `review` to find the
            # mistake in unfinished working guarantees it invents one.
            row.status = "unanswered"
            row.settled.set()
    result = PageResult(rows=rows)
    if on_read is not None:
        await on_read(result)
    if not rows:
        return result

    checkable = [r for r in rows if r.status == "pending"]
    if not checkable:
        if on_fast_pass is not None:
            await on_fast_pass(result)
        return result

    changed = asyncio.Event()
    reviewing = asyncio.create_task(_review_worker(image, media_type, rows, changed))
    try:
        # `_solve_row` swallows its own failures; `return_exceptions` is the belt
        # to that brace, so an unforeseen one still cannot cost us the whole page.
        await asyncio.gather(
            *(_solve_row(row, changed) for row in checkable), return_exceptions=True
        )
        changed.set()
        if on_fast_pass is not None:
            await on_fast_pass(result)
        try:
            await reviewing
        except Exception as exc:
            logger.opt(exception=exc).error("review pass died; rows left unjudged")
    finally:
        reviewing.cancel()

    for row in rows:
        if row.needs_user:
            row.status = "awaiting_user"
        elif row.status in ("pending", "disputed"):
            row.status = "failed"  # the review pass never reached it
    return result


async def apply_correction(
    row: Row, answer: str, image: bytes, *, media_type: str = "image/jpeg"
) -> Row:
    """The user has told us what they actually wrote. Re-decide the row.

    Re-runs from `compare`, never from `read_page`: their word is authoritative
    and nothing re-reads it (`docs/failure_modes.md`).
    """
    row.problem = row.problem.model_copy(update={"student_answer": answer, "read_ok": True})
    row.answer_source = "user_confirmed"
    row.verdict = None
    row.settled = asyncio.Event()

    if row.correct_answer is None:  # e.g. a row we skipped as a drawing
        row.correct_answer = await solve(row.problem.statement)

    if compare(answer, row.correct_answer) == "agree":
        row.status = "cleared"
        row.settled.set()
        return row

    row.status = "disputed"
    row.verdict = await review(image, row.problem.statement, label=row.label, media_type=media_type)
    row.status = _OUTCOME[row.verdict.verdict]
    return row
