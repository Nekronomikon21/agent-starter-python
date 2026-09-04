"""The whole slice on a real photo: read → race → two messages.

    uv run pytest -m integration scripts/tests/test_pipeline_live.py -s

Costs one read, one solve per problem, and a review per disputed row.
"""

from pathlib import Path

import pytest

from agent.mathcheck.pipeline import PageResult, check_page
from agent.mathcheck.respond import message_1, message_2

PAGE01 = Path(__file__).parent / "pages" / "page01.jpg"


@pytest.mark.integration
async def test_page01_end_to_end() -> None:
    sent: list[str] = []

    async def on_fast_pass(result: PageResult) -> None:
        sent.append(message_1(result))

    result = await check_page(PAGE01.read_bytes(), on_fast_pass=on_fast_pass)

    print("\n--- message 1 ---")
    print(sent[0])
    print("\n--- message 2 ---")
    print(message_2(result))
    print("\n--- rows ---")
    for row in result.rows:
        print(
            f"  {row.label}: {row.status}  ours={row.correct_answer!r}  "
            f"theirs={row.problem.student_answer!r}"
        )

    # Message 1 must exist and must not have judged anyone.
    assert sent and "wrong" not in sent[0].lower()
    # page01 has no fully correct problem, so nothing should have cleared.
    assert result.cleared == [], "page01 has no correct answers; a clear here is a false pass"
    assert message_2(result), "there are unresolved rows, so there must be a second message"
