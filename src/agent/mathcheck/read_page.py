"""Read a photo of homework into typed rows.

The whole pipeline hangs off this: 87% of grading errors in the literature are
transcription errors (`docs/learnings.md`), not reasoning ones. It transcribes
and nothing else — it does not solve, and it does not read the student's working
(`review` does that from the photo itself).
"""

from __future__ import annotations

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
    "If the answer is a drawing, a graph or words, say so in plain words instead of inventing "
    "notation.\n"
    "read_ok = false whenever a character is genuinely ambiguous (1 vs 7, x vs ×), crossed out, or "
    "cut off — and set uncertain_field to the field it affects. Never guess a character to make "
    "the problem look complete. Guessing is worse than admitting."
)

DEFAULT_MODEL = "google/gemini-3.8-flash"


async def read_page(
    image: bytes, *, media_type: str = "image/jpeg", model: str = DEFAULT_MODEL
) -> list[Problem]:
    """Photo → one row per problem. `model` is a tier name or an OpenRouter slug."""
    reader = Agent(build_model(model), output_type=Page, instructions=INSTRUCTIONS)
    result = await reader.run(
        [
            "Transcribe every problem on this page.",
            BinaryContent(data=image, media_type=media_type),
        ]
    )
    return result.output.problems
