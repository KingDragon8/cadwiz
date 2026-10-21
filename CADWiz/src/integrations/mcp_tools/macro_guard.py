# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The gate in front of every tool that can execute model-written Python.

Four of the 152 vendored tools run code rather than perform a modelling
operation. Verified against `vendor/robust-mcp` on 2026-09-05:

    execute_python(code)              runs code in FreeCAD's Python context
    safe_execute(code, ...)           the same, with its own validate/rollback
    create_macro(name, code, ...)     writes code to the user's macro directory
    run_macro(macro_name, args)       runs a macro already on disk, by name

Founder decision 4 (2026-09-05) blocked this route until a prohibited-operations
review existed. The review now exists, and the founder ruling of 2026-09-06
replaced the blanket block with **review-then-allow**: the source is read and
checked, and it runs only if nothing prohibited is found. Blanket refusal is now
reserved for the case where the review itself cannot be carried out - source
that will not parse, a macro that cannot be read, or review switched off.

This is the enforcement half; the review itself is
`ai_freecad_core.macro_review`, which knows nothing about FreeCAD or tools.

**`run_macro` is the interesting one.** It carries no source - only a name - so
there is nothing to review in the arguments. The honest options were to refuse
it outright or to fetch what it is about to run and review that. It fetches, via
the vendored `read_macro` tool, which returns ``{"name", "code", "path"}``. If
the source cannot be fetched, the call is refused rather than allowed: an
unreadable macro is an unreviewed macro. That closes the obvious way around the
gate, which is to write a macro through some other route and then ask CADWiz to
run it by name.

`create_macro_from_template` is not guarded: its `template` argument selects one
of the vendored templates and no caller-supplied code reaches disk through it.
`delete_macro` is not guarded either - it destroys a file rather than executing
one, which is a different risk and not the one this gate names. Both are
recorded here so the next reader knows they were considered rather than missed.

**The one other place the product executes source**, checked 2026-09-05 so a
future reader who greps for `exec(` does not have to re-derive it:
`workbench_ui.py:5526` runs `exec(compile(...))` over
`scripts/timetravel/CADWizTimeTravel.FCMacro`. That is CADWiz's own file, at a
fixed path, under version control, loaded to reuse its checkpoint logic rather
than reimplement it. No model writes it and no argument selects it, so it is not
part of the generated-macro route and is deliberately not gated here. If that
path ever takes a caller-supplied filename, it becomes this module's problem.

Tool selection is not a second control. A guarded tool may still be offered to
the model and then refused here, which costs a round trip and produces a clear
reason. Withholding the tools from the catalogue as well would be a second
mechanism that could drift out of step with this one, and the gate is the half
that has to be right.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping

from ai_freecad_core.ai_gateway.audit import (
    AuditRecorder,
    EventKind,
    FilesystemAuditSink,
    default_audit_log_root,
)
from ai_freecad_core.flags import is_enabled
from ai_freecad_core.macro_review import MacroReview, ReviewOutcome, review_source

#: Defaults ON: review the source, then allow it if nothing prohibited is
#: found (founder ruling 2026-09-06, replacing decision 4's blanket block).
#: Turning it OFF refuses outright rather than allowing unreviewed code - there
#: is no setting in which model-written Python runs unchecked. See
#: `ai_freecad_core.flags` for the default/OFF-meaning distinction.
MACRO_REVIEW_FLAG = "cadw.exec.macro_review"

#: Tool -> the argument carrying inline source to review.
CODE_ARGUMENT: Mapping[str, str] = {
    "execute_python": "code",
    "safe_execute": "code",
    "create_macro": "code",
}

#: Tool -> the argument naming a macro whose source must be fetched first.
REFERENCED_MACRO_ARGUMENT: Mapping[str, str] = {
    "run_macro": "macro_name",
}

#: Everything this gate stands in front of.
GUARDED_TOOLS: frozenset[str] = frozenset(CODE_ARGUMENT) | frozenset(
    REFERENCED_MACRO_ARGUMENT
)


def is_guarded(tool_name: str) -> bool:
    """Whether a tool may execute model-written Python."""
    return tool_name in GUARDED_TOOLS


#: ORDER-2026-09-27-06 founder ruling 3: every refused line, with its
#: reason, must be logged -- not just returned to the caller for the
#: tester-facing message. Same on-disk location and JSON-Lines shape as
#: the rest of the app's audit trail (`ai_gateway.audit`), so a developer
#: or the founder finds refusals in the one place they already know to
#: look, rather than a second, bespoke log file.
def _log_refusal(tool_name: str, review: MacroReview) -> None:
    if review.outcome is ReviewOutcome.ALLOWED:
        return
    recorder = AuditRecorder(FilesystemAuditSink(default_audit_log_root()))
    if review.findings:
        for finding in review.findings:
            recorder.record(
                EventKind.FAILURE,
                stage="macro_review",
                tool=tool_name,
                outcome=review.outcome.value,
                rule_id=finding.rule_id,
                symbol=finding.symbol,
                line=finding.line,
                reason=finding.message,
            )
    else:
        recorder.record(
            EventKind.FAILURE,
            stage="macro_review",
            tool=tool_name,
            outcome=review.outcome.value,
            reason=review.reason,
        )


async def review_tool_call(
    tool_name: str,
    arguments: Mapping[str, Any],
    *,
    fetch_macro_source: Callable[[str], Awaitable[str | None]],
) -> MacroReview:
    """Decide whether one guarded call may proceed.

    Returns a review in every case, including the ones where no review could
    happen. `MacroReview.allowed` is an identity check on the outcome, so a
    NOT_REVIEWED verdict cannot be mistaken for permission by a caller that
    only looks for findings. Every non-ALLOWED outcome is logged
    (`_log_refusal`) before it is returned.
    """
    review = await _decide(tool_name, arguments, fetch_macro_source=fetch_macro_source)
    _log_refusal(tool_name, review)
    return review


async def _decide(
    tool_name: str,
    arguments: Mapping[str, Any],
    *,
    fetch_macro_source: Callable[[str], Awaitable[str | None]],
) -> MacroReview:
    if not is_guarded(tool_name):  # pragma: no cover - callers check first
        return MacroReview(ReviewOutcome.ALLOWED)

    if not is_enabled(MACRO_REVIEW_FLAG):
        # Review switched off explicitly. That refuses; it does not permit.
        return MacroReview(
            ReviewOutcome.NOT_REVIEWED,
            reason=(
                "prohibited-operations review is switched off, so no code-executing "
                "tool may run; nothing runs unreviewed"
            ),
        )

    inline = CODE_ARGUMENT.get(tool_name)
    if inline is not None:
        return review_source(str(arguments.get(inline, "") or ""))

    reference = REFERENCED_MACRO_ARGUMENT[tool_name]
    macro_name = str(arguments.get(reference, "") or "").strip()
    if not macro_name:
        return MacroReview(
            ReviewOutcome.NOT_REVIEWED,
            reason=f"{tool_name} was called without {reference}, so nothing could be reviewed",
        )
    try:
        source = await fetch_macro_source(macro_name)
    except Exception as error:  # noqa: BLE001 - a failed read is a refusal, not a crash
        return MacroReview(
            ReviewOutcome.NOT_REVIEWED,
            reason=f"could not read macro {macro_name!r} to review it: {error}",
        )
    if source is None:
        return MacroReview(
            ReviewOutcome.NOT_REVIEWED,
            reason=(
                f"could not read macro {macro_name!r} to review it; "
                "an unreadable macro is an unreviewed macro"
            ),
        )
    return review_source(source)


def refusal_message(tool_name: str, review: MacroReview) -> str:
    """What a tester is told when a code step is refused.

    Plain language first, because this reaches the panel and the person reading
    it asked for a bracket, not a security report. The technical half is
    appended in parentheses so a developer reading the same string still has
    the tool name, the rule and the line - one string, two audiences, neither
    of them served by the other's version alone.

    Founder ruling 2026-09-06: refusal messages must state the reason in plain
    language a tester understands.
    """
    return f"{review.plain_summary()} (refused: {tool_name} — {review.summary()})"
