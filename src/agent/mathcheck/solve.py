"""Solve the problem, blind to the student.

Receives the statement and nothing else. It never sees their working or their
answer, so it cannot be talked into agreeing with a wrong one — the wall is
structural, not an instruction the model could drift from
(`docs/architecture.md`).

`balanced`, not `fast`: measured, not assumed. The fast tier scored 1/3 on
page01's problems — real maths errors, not formatting (`docs/learnings.md`).
A slip here can only ever open a dispute, never issue a verdict, but message 1
announces this answer before `review` has run, so a wrong one sends a kid off to
retry against a wrong number.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agent.services.llm import build_model


class Solution(BaseModel):
    """Our own answer to one problem."""

    answer: str = Field(
        description=(
            "The final answer only, plain text. A single value: '17'. Several: '{18.5, -22.5}'. "
            "When the answer isn't a value, say it plainly: 'infinitely many solutions', "
            "'no solution'."
        )
    )


INSTRUCTIONS = (
    "Solve the maths problem you are given. Return the final answer only.\n"
    "Plain text, never LaTeX: write ± ∈ √ as those characters, never \\pm or \\sqrt.\n"
    "Give every solution, not just one — if squaring or an absolute value produces two branches, "
    "both belong in the answer, as a set: {18.5, -22.5}.\n"
    "Some answers are not values. A system whose equations reduce to the same line has "
    "'infinitely many solutions'; say that rather than inventing a particular pair. Say "
    "'no solution' when there is none.\n"
    "This is school-level maths, but not always routine: x^x = 27 is solved by seeing that "
    "3³ = 27, not by taking a square root. Check that your answer actually satisfies the "
    "original problem before giving it."
)

DEFAULT_MODEL = "balanced"


async def solve(statement: str, *, model: str = DEFAULT_MODEL) -> str:
    """Statement → our answer. Never give this function the student's work."""
    solver = Agent(build_model(model), output_type=Solution, instructions=INSTRUCTIONS)
    result = await solver.run(statement)
    return result.output.answer
