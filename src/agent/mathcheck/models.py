"""The typed row every module works from (see `docs/architecture.md`)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

UncertainField = Literal["statement", "answer"]


class Problem(BaseModel):
    """One problem found on a page, as read. `read_page`'s unit of output."""

    label: str = Field(description="As written on the page: '1', '3a', '№2'.")
    statement: str = Field(description="The problem itself, without the student's working.")
    student_answer: str = Field(
        description="Their final answer only, verbatim. Keep their notation: 4,5 stays 4,5."
    )
    # A bool, not Literal[0, 1]: that reaches some providers as a string enum
    # ("0"/"1") and then fails validation. Booleans survive every provider.
    read_ok: bool = Field(
        description="true = read cleanly. false = a character is ambiguous, crossed out or cut off."
    )
    uncertain_field: UncertainField | None = Field(
        default=None, description="Which field is shaky. Set only when read_ok is 0."
    )


class Page(BaseModel):
    """Everything `read_page` found on one photo."""

    problems: list[Problem]
