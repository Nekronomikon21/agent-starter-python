"""Read a photo of homework into typed rows.

The whole pipeline hangs off this: 87% of grading errors in the literature are
transcription errors (`docs/learnings.md`), not reasoning ones. It transcribes
and nothing else — it does not solve, and it does not read the student's working
(`review` does that from the photo itself).

It is also the one step that can fail *invisibly*: a reader that returns nothing
looks exactly like a page with nothing on it. So this module says what it did —
which model, how long, what it found — and treats an empty read as a question
rather than a verdict (`journal.md` 2026-09-04 19:05).
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from loguru import logger
from pydantic_ai import Agent, BinaryContent

from agent.mathcheck.models import Page, Problem
from agent.services.llm import build_model

INSTRUCTIONS = (
    "You transcribe a photo of a student's maths homework. Transcribe only — never solve, "
    "never correct, never comment.\n"
    "For each problem on the page give: its label as written ('1', '3a', '№2'), the problem "
    "statement, and the student's FINAL answer only.\n"
    "Their FINAL answer is the last line they committed to, not the working above it.\n"
    "Write plain text exactly as it appears — NEVER LaTeX. Use the characters ± ∈ √ themselves, "
    "never \\pm, \\in, \\sqrt or \\begin{cases}. A comma decimal stays a comma (4,5 is not 4.5) "
    "and a set stays a set. Strip a leading answer label like 'Отв:' or 'Answer:'.\n"
    "Set answer_kind: 'value' for a number, expression or set; 'words' when they wrote it "
    "in words ('no solution'); 'drawing' when the answer IS a graph or sketch with "
    "nothing written to check; 'missing' when they have NOT answered it — blank, 'x = ?', a "
    "question mark, or working that stops partway. An unanswered problem is not a wrong "
    "answer. Describe a drawing plainly; never invent notation for it.\n"
    "read_ok = false whenever a character is genuinely ambiguous (1 vs 7, x vs ×), crossed out, or "
    "cut off — and set uncertain_field to the field it affects. Never guess a character to make "
    "the problem look complete. Guessing is worse than admitting."
)

DEFAULT_MODEL = "google/gemini-3.8-flash"
# Tried only when the first reader comes back empty. A different family on the
# second look, because the failure being covered is one model shrugging at a
# page — not a page that is genuinely blank.
FALLBACK_MODEL = "balanced"

# Where a page nobody could read is kept, so it can be re-run offline. A vision
# failure is not reproducible from a log line; it is reproducible from the photo.
UNREAD_DIR = Path("logs/unread")


def _keep_for_diagnosis(image: bytes, media_type: str) -> Path | None:
    """Save a page both readers gave up on. Best effort — never break the reply."""
    suffix = {"image/png": ".png", "image/webp": ".webp"}.get(media_type, ".jpg")
    path = UNREAD_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}{suffix}"
    try:
        UNREAD_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image)
    except OSError as exc:  # a full or read-only disk must not cost the user their answer
        logger.warning("could not keep the unread page: {}", exc)
        return None
    return path


def _summarise(problems: list[Problem]) -> str:
    """One compact line for the whole read, so a bad one is legible afterwards."""
    return " | ".join(
        f"{p.label}: {p.statement[:40]!r} -> {p.student_answer[:30]!r}"
        f" ({p.answer_kind}{'' if p.read_ok else ', unsure'})"
        for p in problems
    )


async def _read_once(image: bytes, *, media_type: str, model: str) -> list[Problem]:
    reader = Agent(build_model(model), output_type=Page, instructions=INSTRUCTIONS)
    started = time.monotonic()
    result = await reader.run(
        [
            "Transcribe every problem on this page.",
            BinaryContent(data=image, media_type=media_type),
        ]
    )
    problems = result.output.problems
    logger.info(
        "read_page: {} found {} problem(s) in {:.1f}s from {} bytes",
        model,
        len(problems),
        time.monotonic() - started,
        len(image),
    )
    if problems:
        logger.info("read_page: {}", _summarise(problems))
    return problems


async def read_page(
    image: bytes,
    *,
    media_type: str = "image/jpeg",
    model: str = DEFAULT_MODEL,
    fallback: str | None = FALLBACK_MODEL,
) -> list[Problem]:
    """Photo → one row per problem. `model` is a tier name or an OpenRouter slug.

    An empty result is retried once on `fallback`. "I found nothing" and "there is
    nothing on this page" are different claims, and only the second is worth
    telling the user: the cost of telling them the first is that they conclude the
    bot never saw their page.
    """
    problems = await _read_once(image, media_type=media_type, model=model)
    if problems or fallback is None:
        return problems

    logger.warning("read_page: {} found nothing; retrying on {}", model, fallback)
    problems = await _read_once(image, media_type=media_type, model=fallback)
    if not problems:
        kept = _keep_for_diagnosis(image, media_type)
        logger.error(
            "read_page: neither {} nor {} found a problem on this page{}",
            model,
            fallback,
            f"; kept at {kept}" if kept else "",
        )
    return problems
