"""`solve` re-derives the answer from the statement alone.

Scored with `compare`, the same code the pipeline uses to clear a row — so a
pass here means the row would actually clear.

    uv run pytest -m integration scripts/tests/test_solve.py -s
"""

import pytest

from agent.mathcheck.compare import compare
from agent.mathcheck.solve import solve

# page01, hand-checked (scripts/tests/pages/page01.md).
PROBLEMS = [
    ("1", "(2(x+7))^2 = 81", "{-2.5, -11.5}"),
    ("2", "|4(x+2)| = 82", "{18.5, -22.5}"),
    ("5", "2^(x^x) = 2^27", "3"),
]


@pytest.mark.integration
@pytest.mark.parametrize(("label", "statement", "expected"), PROBLEMS)
async def test_solves(label: str, statement: str, expected: str) -> None:
    answer = await solve(statement)
    print(f"\n№{label}: {answer!r}  (expected {expected!r})")
    assert compare(answer, expected) == "agree", f"№{label}: got {answer!r}, wanted {expected!r}"


@pytest.mark.integration
async def test_degenerate_system_says_so() -> None:
    """№3: both equations reduce to x = y+1. A particular pair would be wrong."""
    answer = await solve("Solve the system: x + 7 = y + 8; x = y + 1")
    print(f"\n№3: {answer!r}")
    assert "infinit" in answer.lower() or "many" in answer.lower(), answer
    # It must not come back as a value, or `compare` would clear a row it can't judge.
    assert compare(answer, "6") == "uncomparable", answer
