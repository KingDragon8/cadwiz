# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Feature flags for pathways that are not yet the default.

The Master Program's rule is that every new pathway ships behind a flag that
defaults OFF and leaves the incumbent live. This is the one mechanism for that,
so a later phase does not grow a second one.

Environment-driven, like every other piece of configuration in the core
(`CADW_LLM_*`, `CADW_CJ_*`). A flag named ``cadw.exec.macro_review`` reads the
variable ``CADW_FLAG_EXEC_MACRO_REVIEW``.

Read at call time, never cached at import. A cached flag cannot be changed by a
settings screen without a restart, and cannot be varied by a test without
reaching into module state.

**A flag has both a default and an OFF meaning, and they are separate
questions.** `default_enabled` says what an unset variable does;
`off_meaning` says what happens when the guarded pathway is not active.

`cadw.exec.macro_review` is the case that needs both. It now defaults to
**on** - review the generated code, then allow it if it passes (founder ruling,
2026-09-06) - and its OFF meaning is still **DENY**. Turning review off does not
buy unreviewed execution; it refuses instead. There is deliberately no
configuration in which model-written Python runs unreviewed, which is a stronger
property than the original blanket block and the reason the default could be
flipped at all.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

#: Values that mean "on". Anything else, including an empty string, means off.
#: Deliberately small: a flag set to "maybe" is off, not an error, because a
#: typo in an environment variable must never turn a guard off by surprise.
_TRUTHY = frozenset({"1", "true", "yes", "on", "enabled"})


class OffMeaning(StrEnum):
    """What the OFF state of a flag actually does."""

    #: Off leaves the incumbent production behaviour untouched. The usual case.
    INCUMBENT = "incumbent"
    #: Off refuses the guarded operation outright. Used where the guarded thing
    #: is the risk, so falling through to current behaviour would be the bug.
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class FlagDeclaration:
    """One flag: what an unset variable does, and what OFF means."""

    name: str
    off_meaning: OffMeaning
    summary: str
    #: What an unset environment variable means. The Master Program's rule is
    #: that a new pathway defaults OFF; a flag defaulting on is an explicit
    #: founder decision and should say so in its summary.
    default_enabled: bool = False

    @property
    def environment_variable(self) -> str:
        """The variable that sets this flag."""
        return environment_variable_for(self.name)


def environment_variable_for(name: str) -> str:
    """Map a dotted flag name onto its environment variable.

    ``cadw.exec.macro_review`` -> ``CADW_FLAG_EXEC_MACRO_REVIEW``. The leading
    ``cadw.`` is dropped rather than doubled, so the variable reads as one
    prefix and not as ``CADW_FLAG_CADW_...``.
    """
    stem = name[5:] if name.startswith("cadw.") else name
    return "CADW_FLAG_" + stem.replace(".", "_").replace("-", "_").upper()


#: Every flag this codebase honours, so `docs` and a settings screen have one
#: place to read rather than a grep. A flag absent from here still works -
#: `is_enabled` does not consult the registry - but it will not be documented
#: or surfaced, which is a good reason to add it.
FLAG_REGISTRY: tuple[FlagDeclaration, ...] = (
    FlagDeclaration(
        "cadw.exec.macro_review",
        OffMeaning.DENY,
        "Generated-macro route. ON reviews the source and permits it only if "
        "nothing prohibited is found; OFF refuses every code-executing tool "
        "outright. Defaults ON per the founder ruling of 2026-09-06, which "
        "replaced the blanket block of decision 4 (2026-09-05) with "
        "review-then-allow. Turning it off never yields unreviewed execution.",
        default_enabled=True,
    ),
    FlagDeclaration(
        "cadw.pipeline.intent",
        OffMeaning.INCUMBENT,
        "Intent interpretation in front of a build. OFF leaves the live "
        "conversational tool loop exactly as it is and consults no "
        "interpreter, even an installed one. Phase 0.5, founder decision 1.",
    ),
)


def declaration(name: str) -> FlagDeclaration | None:
    """The registry entry for a flag, when it has one."""
    return next((item for item in FLAG_REGISTRY if item.name == name), None)


def is_enabled(name: str, *, default: bool | None = None) -> bool:
    """Return whether the flag is on right now.

    When the variable is unset, the answer comes from the registry's
    `default_enabled` - one source of truth, rather than each call site
    remembering its own default and one of them eventually disagreeing. Pass
    `default` explicitly to override that, which is mostly useful for a flag
    that is not registered.

    An explicitly empty value is an answer - off - not an absence.
    """
    raw = os.environ.get(environment_variable_for(name))
    if raw is None:
        if default is not None:
            return default
        entry = declaration(name)
        return entry.default_enabled if entry else False
    return raw.strip().casefold() in _TRUTHY
