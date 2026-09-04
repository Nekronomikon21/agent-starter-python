r"""Turn settled rows into the two messages (wording: `docs/policy.md`).

Plain text on purpose. Maths is full of `*`, `_`, `^` and `\` — exactly
Telegram's Markdown control characters — so a correct solution sent as Markdown
arrives mangled or not at all, and it looks fine in the log
(`docs/failure_modes.md`).
"""

from __future__ import annotations

from agent.mathcheck.pipeline import PageResult, Row

_ESCAPES = ("\\n", "\\t", "\\r")


def _flat(text: str) -> str:
    """A quoted answer must stay on one line.

    Answers come off a photo with real line breaks in them, and sometimes with
    the two-character escape instead — a model writing a multi-line answer may
    emit a literal backslash-n, which no amount of whitespace splitting fixes.
    """
    out = text
    for escape in _ESCAPES:
        out = out.replace(escape, " ")
    return " ".join(out.split())


def _listed(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


def message_1(result: PageResult) -> str:
    """The good news, early. It carries no answers and no verdicts.

    Answers live in message 2, beside the explanation that earns them. Here they
    were an answer key arriving first and short — the back-of-the-book failure
    this project exists to replace (`docs/problem.md`).
    """
    cleared = [r.label for r in result.cleared]
    open_rows = [r.label for r in result.unresolved]

    if not open_rows:
        return "That's right." if len(cleared) == 1 else "All of them look right."
    if cleared:
        return f"{_listed(cleared)} look right. Checking your working on {_listed(open_rows)} now."
    return f"Checking your working on {_listed(open_rows)} now."


def _diagnosis(row: Row) -> str:
    if row.status == "unanswered":
        return f"{row.label} — you haven't answered this one yet. Want me to talk you through it?"
    if row.status == "unreadable":
        return (
            f"{row.label} — I couldn't make out the question itself, so I can't check your "
            "working on it. Can you send me that one again?"
        )
    if row.status == "failed":
        return (
            f"{row.label} — something went wrong on my side and I couldn't finish checking "
            "this one. Send the page again and I'll retry it."
        )
    if row.status == "uncheckable":
        return (
            f"{row.label} — your answer is a drawing, and I can't check one yet. "
            "Send me the working written out and I'll go through it."
        )
    verdict = row.verdict
    if verdict is None or verdict.verdict == "mistake" and not verdict.line:
        return f"{row.label} — I couldn't follow your working. Can you send a clearer photo?"
    if verdict.verdict == "valid":
        return (
            f"Actually, your {row.problem.student_answer} for {row.label} is right — "
            "my first pass had it wrong."
        )
    if verdict.verdict == "wrong_problem":
        return (
            f"Your working for {row.label} doesn't match the question I read. "
            "Did I read it right, or can you retake it?"
        )
    answer = _flat(row.correct_answer or "")
    ours = f" The answer is {answer}." if answer else ""
    return f"{row.label} — wrong. {verdict.line}: {verdict.why}{ours}"


def _question(row: Row) -> str:
    field = row.problem.uncertain_field or "answer"
    read = row.problem.statement if field == "statement" else row.problem.student_answer
    return (
        f"For {row.label} I read your {field} as {_flat(read)} — "
        "is that right, or what did you write?"
    )


def message_2(result: PageResult) -> str | None:
    """The diagnosis, a retraction, or a question. None when nothing is open."""
    parts = [
        _question(row) if row.status == "awaiting_user" else _diagnosis(row)
        for row in result.unresolved
    ]
    return "\n\n".join(parts) if parts else None


def correction_reply(row: Row) -> str:
    """After the user tells us what they wrote. Owns the mistake plainly."""
    answer = _flat(row.problem.student_answer)
    if row.status == "cleared":
        return f"With {answer} for {row.label} — that's right, my mistake."
    return _diagnosis(row)


def reading_note(result: PageResult) -> str:
    """Said once, as soon as the page is read. The first thing that proves we saw it."""
    count = len(result.rows)
    if count == 0:
        return "I can't find a maths problem in that — can you send the exercise?"
    if count == 1:
        return "Got it. Working through it now."
    return f"Got it — {count} problems. Working through them now."
