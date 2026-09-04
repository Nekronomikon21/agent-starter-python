"""`compare` decides whether a kid's answer is our answer.

The project's #1 risk: marking a correct answer wrong because it's written
differently. Pure logic — no model, no photo, no credentials.

    uv run pytest scripts/tests/test_compare.py
"""

import os

import pytest

os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-real")

from agent.mathcheck.compare import compare  # noqa: E402

# Every one of these is a *correct* kid who must not be failed.
SAME = [
    ("17", "17"),
    ("x = 17", "17"),
    ("17 = x", "x = 17"),
    ("x=17", "17"),
    ("0.75", "3/4"),
    ("2/4", "1/2"),
    ("0.5", "1/2"),
    ("x = 17 cm", "17"),
    ("11/12", "11/12"),
    ("-3", "−3"),  # U+2212, straight off a photo
    ("2*sqrt(2)", "sqrt(8)"),
    ("2√2", "√8"),
    ("3^2", "9"),
    ("2x", "2*x"),
    ("{1, 3}", "{3, 1}"),
    ("x = 1 or x = -3", "{1, -3}"),
    ("1; -3", "{-3, 1}"),
    ("17.", "17"),
    ("  17  ", "17"),
    ("1/3", "1/3"),
]

DIFFERENT = [
    ("9", "17"),
    ("3/7", "11/12"),
    ("0.333", "1/3"),  # rounded is not equal
    ("{1, 3}", "{1, 4}"),
    ("{1, 3}", "{1, 3, 5}"),
    ("x = 9", "17"),
    ("-17", "17"),
    ("2/3", "3/2"),
]

UNREADABLE = [
    ("", "17"),
    ("   ", "17"),
    ("17", ""),
    ("see the graph", "17"),
    ("a straight line through the origin", "y = x"),
]


@pytest.mark.parametrize(("student", "correct"), SAME)
def test_same_answer_written_differently(student: str, correct: str) -> None:
    assert compare(student, correct) == "agree", f"{student!r} vs {correct!r}"


@pytest.mark.parametrize(("student", "correct"), DIFFERENT)
def test_genuinely_different(student: str, correct: str) -> None:
    assert compare(student, correct) == "differ", f"{student!r} vs {correct!r}"


@pytest.mark.parametrize(("student", "correct"), UNREADABLE)
def test_unreadable_is_never_wrong(student: str, correct: str) -> None:
    # Never "differ": failing a kid because sympy couldn't parse them is the
    # exact failure this module exists to prevent.
    assert compare(student, correct) == "uncomparable", f"{student!r} vs {correct!r}"


def test_symmetric() -> None:
    for student, correct in SAME + DIFFERENT:
        assert compare(student, correct) == compare(correct, student)
