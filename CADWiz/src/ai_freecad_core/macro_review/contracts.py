# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Immutable contracts for the prohibited-operations review of generated code."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ReviewOutcome(StrEnum):
    """The four things a review can conclude. There is no fifth."""

    #: Parsed, and nothing prohibited was found.
    ALLOWED = "allowed"
    #: Parsed, and at least one prohibited construct was found.
    PROHIBITED = "prohibited"
    #: Could not be parsed as Python. Refused: code that cannot be read cannot
    #: be reviewed, and "it did not parse" is not evidence that it is safe.
    UNPARSEABLE = "unparseable"
    #: No review happened - the guard was off, or the source could not be
    #: obtained. Never treated as permission.
    NOT_REVIEWED = "not_reviewed"


@dataclass(frozen=True, slots=True)
class Finding:
    """One prohibited construct, said twice: once for a log, once for a person.

    `message` is for whoever is debugging CADWiz. `plain` is for the tester who
    just asked for a phone stand and needs to know what happened and whether
    their model is safe. Founder ruling, 2026-09-06: a refusal must state its
    reason in language a tester understands.
    """

    rule_id: str
    symbol: str
    line: int
    message: str
    plain: str = ""

    def __post_init__(self) -> None:
        """A finding with no plain wording would reach a user as jargon."""
        if not self.plain.strip():
            raise ValueError(f"finding {self.rule_id} has no plain-language explanation")


@dataclass(frozen=True, slots=True)
class MacroReview:
    """The verdict on one piece of generated source."""

    outcome: ReviewOutcome
    findings: tuple[Finding, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        """Keep the outcome and the findings from being able to disagree."""
        if self.outcome is ReviewOutcome.PROHIBITED and not self.findings:
            raise ValueError("a PROHIBITED review must carry at least one finding")
        if self.outcome is ReviewOutcome.ALLOWED and self.findings:
            raise ValueError("an ALLOWED review must carry no findings")

    @property
    def allowed(self) -> bool:
        """Permission is one outcome, not the absence of a problem.

        Written as an identity check rather than as ``not self.findings`` on
        purpose: NOT_REVIEWED and UNPARSEABLE both have no findings, and a
        truthiness test on findings would read either of them as permission.
        """
        return self.outcome is ReviewOutcome.ALLOWED

    def summary(self) -> str:
        """One technical line, for a log or a developer."""
        if self.allowed:
            return "reviewed: no prohibited operations found"
        if self.outcome is ReviewOutcome.PROHIBITED:
            first = self.findings[0]
            extra = f" (+{len(self.findings) - 1} more)" if len(self.findings) > 1 else ""
            return f"refused at line {first.line}: {first.message}{extra}"
        return self.reason or f"refused: {self.outcome.value}"

    def plain_summary(self) -> str:
        """What a tester is told. No rule ids, no line numbers, no jargon.

        Deliberately does not list every finding: someone who asked for a
        bracket does not need an itemised audit, they need to know what
        happened, that their model is untouched, and what to do next. The full
        list stays in `findings` for the log.
        """
        if self.allowed:
            return "The generated step was checked and looked safe to run."
        if self.outcome is ReviewOutcome.PROHIBITED:
            first = self.findings[0]
            others = (
                f" There were {len(self.findings) - 1} other problems like it."
                if len(self.findings) > 1
                else ""
            )
            return f"{first.plain}{others}"
        if self.outcome is ReviewOutcome.UNPARSEABLE:
            return (
                "CADWiz could not read the code it generated well enough to check it, "
                "so it did not run it."
            )
        return (
            "CADWiz could not check the code it generated, so it did not run it."
        )
