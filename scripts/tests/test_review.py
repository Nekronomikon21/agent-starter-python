"""`review` finds the first wrong line — and is allowed to say there isn't one.

Live tests: they hit a real model and cost money.

    uv run pytest -m integration scripts/tests/test_review.py -s
"""

from pathlib import Path

import pytest

# No fake OPENROUTER_API_KEY here, unlike the offline test modules: setting one
# before .env loads wins (load_dotenv doesn't override), and every test in this
# file needs the real key.
from agent.mathcheck.review import review

PAGE01 = Path(__file__).parent / "pages" / "page01.jpg"

# Ground truth in pages/page01.md. We assert the *line* it names, compared with
# spaces stripped -- the quoting is stable, the explanation's wording is not.
FIRST_DIVERGENCE = [
    ("1", "(2(x+7))^2 = 81", "2(x+7)=9", "dropped the negative branch of ±9"),
    ("2", "|4(x+2)| = 82", "x+2=±21", "82/4 is 20,5 — they used 21"),
    ("5", "2^(x^x) = 2^27", "x=√27", "treated x^x as x², giving √27"),
]


def _squash(text: str) -> str:
    return text.replace(" ", "").replace("*", "").lower()


@pytest.mark.integration
@pytest.mark.parametrize(("label", "statement", "want_line", "expected"), FIRST_DIVERGENCE)
async def test_finds_a_mistake(label: str, statement: str, want_line: str, expected: str) -> None:
    result = await review(PAGE01.read_bytes(), statement, label=label)
    print(f"\n№{label} → {result.verdict} | line={result.line!r} | why={result.why}")
    print(f"     expected: {expected}")
    assert result.verdict == "mistake", f"№{label}: {result}"
    assert result.why, "a mistake must come with the rule that was broken"
    # The one that matters: the *first* divergence, not a later consequence.
    assert _squash(want_line) in _squash(result.line or ""), (
        f"№{label}: named {result.line!r}, expected the line {want_line!r}"
    )


@pytest.mark.integration
async def test_working_for_another_problem_is_wrong_problem() -> None:
    # This statement is nowhere on the page. Nothing here is a student mistake,
    # so inventing one would be the failure this exit exists to prevent.
    result = await review(PAGE01.read_bytes(), "Solve for x: 5x + 3 = 18")
    print(f"\nabsent statement → {result.verdict} | line={result.line!r} | why={result.why}")
    assert result.verdict == "wrong_problem", f"got {result}"


@pytest.mark.integration
@pytest.mark.skip(reason="needs a page of fully correct work — page01 has none. See page01.md.")
async def test_correct_working_is_exonerated() -> None:
    """The test that matters most: correct work must come back `valid`.

    `review` only ever runs on disputed rows, so this is the case where it is
    most tempted to manufacture a mistake. A failure here is a release blocker
    (`docs/scenarios.md`, the false-accusation set).
    """
    raise AssertionError("unreachable until a correct-work page exists")
