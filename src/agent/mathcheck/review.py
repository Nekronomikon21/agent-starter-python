"""Find the first wrong line in a student's working — reading it off the photo.

The one module that decides accusations, so it is also the one allowed to say
the student is right. It only ever runs on rows where the answers already
differ, and a model told to "find the mistake" in flawless work will invent one
(`docs/failure_modes.md`). Hence `valid` and `wrong_problem`: not a second
opinion on the maths, an escape hatch on a call that is happening anyway.

It never sees `correct_answer`. Being handed the expected answer would hand it
its conclusion.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, BinaryContent

from agent.services.llm import build_model

Verdict = Literal["mistake", "valid", "wrong_problem"]


class Review(BaseModel):
    """What `review` found in one student's working."""

    verdict: Verdict = Field(
        description=(
            "'mistake' = the first wrong line, below. 'valid' = every step is fine. "
            "'wrong_problem' = this working isn't for the statement I was given."
        )
    )
    line: str | None = Field(
        default=None,
        description="The first wrong line, quoted as they wrote it. Only for 'mistake'.",
    )
    line_number: int | None = Field(
        default=None, description="Which line of their working it is, counting from 1."
    )
    why: str | None = Field(
        default=None,
        description=(
            "The rule they broke, in a form they can reuse: 'the -4 gets multiplied too', "
            "not 'you should have written 3x - 12'. One or two sentences. Only for 'mistake'."
        ),
    )


INSTRUCTIONS = (
    "You are looking at a photo of a student's handwritten maths, and one problem statement from "
    "that page. Find their working for THAT problem and check it line by line.\n"
    "Read their working off the photo yourself. Do not assume it matches any transcription.\n"
    "\n"
    "Report the FIRST line that is wrong, and nothing after it. One slip makes every later line "
    "wrong too, but there is still only one mistake — everything after it follows correctly from "
    "where they were. Say what rule they broke, in a form they can reuse next time.\n"
    "\n"
    "You are being asked because their answer differs from ours. That does NOT mean they are "
    "wrong — our answer may be wrong, or their answer may have been misread. So:\n"
    "- If every step is sound, return 'valid'. Do not manufacture a mistake to explain the "
    "disagreement. Saying 'their working is fine' is a correct and expected answer.\n"
    "- If the working on the page isn't for the statement you were given, return 'wrong_problem' — "
    "the statement was probably misread.\n"
    "\n"
    "An incomplete answer is a mistake: a lost root (taking only the + branch of a ±) is a real "
    "error and its line is where the branch was dropped. An answer in a different but equivalent "
    "form, or reached by a different valid method, is NOT a mistake."
)

DEFAULT_MODEL = "smart"


async def review(
    image: bytes,
    statement: str,
    *,
    label: str | None = None,
    media_type: str = "image/jpeg",
    model: str = DEFAULT_MODEL,
) -> Review:
    """Check one problem's working. `label` locates it on a multi-problem page."""
    reviewer = Agent(build_model(model), output_type=Review, instructions=INSTRUCTIONS)
    which = f"problem {label}" if label else "this problem"
    result = await reviewer.run(
        [
            f"Check the student's working for {which}: {statement}",
            BinaryContent(data=image, media_type=media_type),
        ]
    )
    return result.output
