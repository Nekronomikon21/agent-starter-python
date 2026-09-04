"""Which vision model should `read_page` use? Decide it on our pages, not a leaderboard.

The research says image capture and transcription dominate everything else
(`docs/learnings.md`), so the only sample that matters is our own handwriting.
This runs every page in `scripts/tests/pages/` through each candidate model and
scores the transcription against the hand-written ground truth beside it.

    uv run python scripts/bakeoff.py
    uv run python scripts/bakeoff.py --models google/gemini-3.8-flash smart

**This spends money** — one vision call per page per model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import NotRequired, TypedDict

from rich.console import Console
from rich.table import Table

from agent.mathcheck.compare import compare
from agent.mathcheck.models import Problem
from agent.mathcheck.read_page import read_page

PAGES = Path(__file__).parent / "tests" / "pages"
CANDIDATES = [
    "google/gemini-3.8-flash",
    "google/gemini-3.7-flash",
    "anthropic/claude-opus-4.8",
]
console = Console()


class Truth(TypedDict):
    """One hand-written ground-truth row from a page's .json."""

    label: str
    statement: str
    student_answer: str
    # The answer is a drawing or words, so any sensible description counts.
    prose: NotRequired[bool]


def _norm(text: str) -> str:
    """Compare transcriptions, not whitespace and decoration."""
    out = text.strip().lower().replace("№", "").replace(" ", "")
    out = out.replace("−", "-").replace("·", "*").replace("×", "*")
    return re.sub(r"[{}()\[\]]", "", out)


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _answer_matches(got: str, want: str, *, prose: bool = False) -> bool:
    """Equivalent answers count as read correctly.

    When the answer is a drawing or words, any sensible description counts.
    Scoring "graph of a straight line" against "a drawn graph" by string
    similarity would fail every model for agreeing with us.
    """
    if prose:
        return compare(got, "1") == "uncomparable"
    if compare(got, want) == "agree":
        return True
    return _similar(got, want) >= 0.8


class Score:
    """How well one model read one page."""

    def __init__(self, model: str, page: str) -> None:
        self.model = model
        self.page = page
        self.found = 0
        self.expected = 0
        self.labels = 0
        self.answers = 0
        self.statements: list[float] = []
        self.flagged = 0
        self.seconds = 0.0
        self.error: str | None = None
        # (label, what it read, ground truth, matched)
        self.detail: list[tuple[str, str, str, bool]] = []

    @property
    def statement_score(self) -> float:
        return sum(self.statements) / len(self.statements) if self.statements else 0.0


def _score(model: str, page: str, got: list[Problem], truth: list[Truth]) -> Score:
    score = Score(model, page)
    score.expected = len(truth)
    score.found = len(got)
    score.flagged = sum(1 for p in got if not p.read_ok)

    by_label = {_norm(p.label): p for p in got}
    for want in truth:
        problem = by_label.get(_norm(want["label"]))
        if problem is None:
            continue
        score.labels += 1
        score.statements.append(_similar(problem.statement, want["statement"]))
        matched = _answer_matches(
            problem.student_answer, want["student_answer"], prose=bool(want.get("prose"))
        )
        score.answers += int(matched)
        score.detail.append(
            (want["label"], problem.student_answer, want["student_answer"], matched)
        )
    return score


async def _run_one(model: str, image: Path, truth: list[Truth]) -> Score:
    started = time.monotonic()
    try:
        data = await asyncio.to_thread(image.read_bytes)
        problems = await read_page(data, model=model)
    except Exception as exc:  # a candidate may not support vision, or may be down
        score = Score(model, image.name)
        score.expected = len(truth)
        score.error = f"{type(exc).__name__}: {exc}"[:60]
        return score
    score = _score(model, image.name, problems, truth)
    score.seconds = time.monotonic() - started
    return score


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=CANDIDATES)
    parser.add_argument("--pages", nargs="+", default=None, help="page stems, e.g. page01")
    parser.add_argument("--show", action="store_true", help="print every answer read vs expected")
    args = parser.parse_args()

    truths = sorted(PAGES.glob("*.json"))
    if args.pages:
        truths = [t for t in truths if t.stem in args.pages]
    if not truths:
        console.print(f"[red]No ground-truth .json files in {PAGES}[/red]")
        return

    calls = len(truths) * len(args.models)
    console.print(f"[yellow]{calls} vision calls[/yellow] — this spends money.\n")

    scores: list[Score] = []
    for truth_file in truths:
        raw = await asyncio.to_thread(truth_file.read_text, encoding="utf-8")
        truth: dict[str, object] = json.loads(raw)
        image = truth_file.with_name(str(truth["image"]))
        problems: list[Truth] = truth["problems"]  # type: ignore[assignment]
        console.print(f"[bold]{image.name}[/bold] — {len(problems)} problems")
        scores.extend(await asyncio.gather(*(_run_one(m, image, problems) for m in args.models)))

    table = Table(title="read_page bake-off", show_lines=False)
    for column in ("model", "page", "found", "labels", "answers", "statement", "flagged", "s"):
        table.add_column(column)
    for score in sorted(scores, key=lambda s: (-s.answers, s.seconds)):
        if score.error:
            table.add_row(score.model, score.page, f"[red]{score.error}[/red]", "", "", "", "", "")
            continue
        table.add_row(
            score.model,
            score.page,
            f"{score.found}/{score.expected}",
            f"{score.labels}/{score.expected}",
            f"{score.answers}/{score.expected}",
            f"{score.statement_score:.2f}",
            str(score.flagged),
            f"{score.seconds:.1f}",
        )
    console.print(table)

    if args.show:
        for score in scores:
            if not score.detail:
                continue
            console.print(f"\n[bold]{score.model}[/bold]")
            for label, got, want, ok in score.detail:
                mark = "[green]ok[/green]" if ok else "[red]no[/red]"
                console.print(f"  {mark} {label}: read {got!r}  vs  expected {want!r}")

    console.print(
        "\n[dim]answers = the column that decides it: how often the student's answer was read "
        "correctly. flagged counts rows the model marked read_ok=false — flagging a genuine "
        "ambiguity beats confidently guessing.[/dim]"
    )


if __name__ == "__main__":
    asyncio.run(main())
