r"""Turn settled rows into the two messages (wording: `docs/policy.md`).

Plain text on purpose. Maths is full of `*`, `_`, `^` and `\` — exactly
Telegram's Markdown control characters — so a correct solution sent as Markdown
arrives mangled or not at all, and it looks fine in the log
(`docs/failure_modes.md`).
"""

from __future__ import annotations

from agent.mathcheck.pipeline import PageResult, Row


def _flat(text: str) -> str:
    """Answers come off a photo with line breaks in them; a quote must stay one line."""
    return " ".join(text.split())


def _listed(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


def message_1(result: PageResult) -> str:
    """What `solve` got. It reports; it does not judge — the review hasn't run."""
    cleared = [r.label for r in result.cleared]
    open_rows = result.unresolved

    if not open_rows:
        return "That's right." if len(cleared) == 1 else "All of them look right."

    answered = [r for r in open_rows if r.correct_answer]
    if not answered:
        return "Give me a moment with these."
    ours = ", ".join(f"for {r.label} I get {_flat(r.correct_answer or '')}" for r in answered)
    if cleared:
        return f"{_listed(cleared)} look right. But {ours} — checking your working now."
    return f"{ours[0].upper()}{ours[1:]} — checking your working now."


def _diagnosis(row: Row) -> str:
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
    return f"{row.label} — wrong. {verdict.line}: {verdict.why}"


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
