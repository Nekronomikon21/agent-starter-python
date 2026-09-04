"""Decide whether two answers are the same answer.

This is the project's #1 risk (`docs/failure_modes.md`): a kid writes `2/4`, the
solver writes `1/2`, and a correct answer gets failed. Everything here exists to
stop that. Plain code, no model — deterministic, free, and the most-run step in
the system.

`uncomparable` is a real outcome, not a failure: a word answer, a proof or a
sketch routes to `review` instead of being guessed at.
"""

from __future__ import annotations

import re
from typing import Literal

import sympy
from sympy import Expr, simplify
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    rationalize,
    standard_transformations,
)

Verdict = Literal["agree", "differ", "uncomparable"]

# `rationalize` makes 0.75 parse as 3/4, so decimals and fractions compare
# exactly instead of through float noise. `convert_xor` reads ^ as a power,
# which is how a kid writes it.
_TRANSFORMS = standard_transformations + (
    convert_xor,
    implicit_multiplication_application,
    rationalize,
)

# Handwriting and OCR produce these; sympy doesn't read them.
_SYMBOLS = {
    "−": "-",  # U+2212 minus, not a hyphen
    "–": "-",
    "—": "-",
    "×": "*",
    "·": "*",
    "⋅": "*",
    "÷": "/",
    "²": "**2",
    "³": "**3",
    "⁴": "**4",
    "π": "pi",
    "∞": "oo",
}

# √8 -> sqrt(8). Plain replacement gives "sqrt8", which parses as a symbol.
_ROOT_CALL = re.compile(r"√\s*\(")
_ROOT_TERM = re.compile(r"√\s*(\d+(?:\.\d+)?|[a-zA-Z]\w*)")

# Function names an answer may legitimately contain. Anything else with three or
# more letters in a row is prose, not maths -- and prose parses *silently* as a
# product of symbols ("see the graph" -> see*the*graph), which would come back
# `differ` and fail a kid for writing words. Reject it instead.
_FUNCTIONS = frozenset(
    {
        "sqrt",
        "sin",
        "cos",
        "tan",
        "cot",
        "sec",
        "csc",
        "asin",
        "acos",
        "atan",
        "sinh",
        "cosh",
        "tanh",
        "log",
        "ln",
        "exp",
        "abs",
        "pi",
        "inf",
        "nan",
        "oo",
        "gcd",
        "lcm",
        "mod",
        "max",
        "min",
        "sum",
    }
)
_WORD = re.compile(r"[a-zA-Z]{3,}")

# Stripped only when they trail a number: "17 cm" is 17, but `m` alone is a symbol.
_UNIT = re.compile(
    r"(?<=[\d)])\s*(cm|mm|km|kg|ml|sec|min|hours?|hrs?|degrees?|deg|[cmk]?m|[gls]|h|°)"
    r"\s*(\^?\d|²|³)?\s*$",
    re.IGNORECASE,
)
_BARE_SYMBOL = re.compile(r"^[a-zA-Z]'?\d?$")

# parse_expr eval()s its input, and this input came from a model reading a photo.
# The parser's generated code needs sympy's names, so we hand it exactly those
# and nothing else -- builtins are the thing that would make eval dangerous.
_NAMESPACE: dict[str, object] = {
    name: value for name, value in vars(sympy).items() if not name.startswith("_")
}
_NAMESPACE["__builtins__"] = {}
_SPLIT = re.compile(r"\s+or\s+|[;,]", re.IGNORECASE)


def _normalise(text: str) -> str:
    """Text as written by a kid → text sympy can parse."""
    out = text.strip().rstrip(".").strip()
    for bad, good in _SYMBOLS.items():
        out = out.replace(bad, good)
    out = _ROOT_CALL.sub("sqrt(", out)
    out = _ROOT_TERM.sub(r"sqrt(\1)", out)
    out = _UNIT.sub("", out).strip()
    return out


def _is_prose(text: str) -> bool:
    return any(word.lower() not in _FUNCTIONS for word in _WORD.findall(text))


def _drop_label(text: str) -> str:
    """`x = 17` and `17 = x` are both the answer 17."""
    parts = text.split("=")
    if len(parts) != 2:
        return text
    left, right = (p.strip() for p in parts)
    if _BARE_SYMBOL.match(left):
        return right
    if _BARE_SYMBOL.match(right):
        return left
    return text


def _split(text: str) -> list[str]:
    """`{1, 3}` and `x = 1 or x = -3` are both two-element answers."""
    body = text.strip()
    if body.startswith("{") and body.endswith("}"):
        body = body[1:-1]
    return [part for part in (p.strip() for p in _SPLIT.split(body)) if part]


def _parse(text: str) -> Expr | None:
    try:
        return parse_expr(
            text, transformations=_TRANSFORMS, global_dict=dict(_NAMESPACE), evaluate=True
        )
    except Exception:  # sympy raises a wide and undocumented set here
        return None


def _parse_answer(raw: str) -> list[Expr] | None:
    """One written answer → the values it states, or None if unreadable."""
    if not raw or not raw.strip():
        return None
    normalised = _normalise(raw)
    if _is_prose(normalised):
        return None
    parts = _split(normalised)
    values: list[Expr] = []
    for part in parts:
        parsed = _parse(_drop_label(part))
        if parsed is None:
            return None
        values.append(parsed)
    return values or None


def _same(a: Expr, b: Expr) -> bool:
    try:
        return bool(simplify(a - b) == 0)
    except (TypeError, AttributeError):
        return False


def compare(student: str, correct: str) -> Verdict:
    """Is the student's answer the same answer as ours?

    Order never matters (`{1, 3}` == `{3, 1}`) and neither does form
    (`2/4` == `0.5`). Anything we can't read is `uncomparable`, never `differ` —
    failing a kid because sympy couldn't parse them is the failure this module exists to prevent.
    """
    left = _parse_answer(student)
    right = _parse_answer(correct)
    if left is None or right is None:
        return "uncomparable"
    if len(left) != len(right):
        return "differ"

    unmatched = list(right)
    for value in left:
        match = next((other for other in unmatched if _same(value, other)), None)
        if match is None:
            return "differ"
        unmatched.remove(match)
    return "agree"
