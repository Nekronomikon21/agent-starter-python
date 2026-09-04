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
]


# What each review verdict does to the row.
_OUTCOME: dict[str, Status] = {
    "mistake": "diagnosed",
    "valid": "exonerated",
    "wrong_problem": "wrong_problem",
}


@dataclass
class Row:
    """One problem, and everything we learn about it."""

    problem: Problem
    correct_answer: str | None = None
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
    row.correct_answer = await solve(row.problem.statement)
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
            row.verdict = running.result()
            row.status = _OUTCOME[row.verdict.verdict]
        else:
            running.cancel()  # speculative work on a row that turned out fine


async def check_page(
    image: bytes,
    *,
    media_type: str = "image/jpeg",
    on_fast_pass: Callable[[PageResult], Awaitable[None]] | None = None,
) -> PageResult:
    """Photo → a verdict per problem.

    `on_fast_pass` fires the moment the fast pass finishes every row — that is
    message 1, sent while the review is still running.
    """
    problems = await read_page(image, media_type=media_type)
    rows = [Row(problem=p) for p in problems]
    # A drawn answer has nothing to compare and nothing to walk. Solving it wastes
    # a call, and handing it to `review` produces a confident critique of a sketch.
    for row in rows:
        if row.problem.answer_kind == "drawing":
            row.status = "uncheckable"
            row.settled.set()
    result = PageResult(rows=rows)
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
        await asyncio.gather(*(_solve_row(row, changed) for row in checkable))
        changed.set()
        if on_fast_pass is not None:
            await on_fast_pass(result)
        await reviewing
    finally:
        reviewing.cancel()

    for row in rows:
        if row.needs_user:
            row.status = "awaiting_user"
    return result
