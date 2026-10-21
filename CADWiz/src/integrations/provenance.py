# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Provenance properties that survive save and reopen.

One mechanism, two callers. `App::PropertyString` on the object itself is
what already worked for imported geometry
(`integrations.freecad_native.workbench_ui.WorkbenchShell._attach_import_provenance`,
proven to persist correctly on FreeCAD 1.1.3 by capability 7's
`downstream_feature_survival` point) -- a real document property lives in the
`.FCStd` file, unlike the audit ledger, which is a side channel that never
touches the document at all. Per the founder's 2026-09-07 Phase 1 closeout
ruling, this module extracts that mechanism so `ToolInvoker` can stamp every
tool-created object with it too, instead of a second, parallel one.

`attach_properties` is the shared primitive. `build_tool_provenance` and
`attach_tool_provenance` are the tool-call-specific half: the v1 schema for
"what created this, from what request, verified how" -- distinct from
import's vocabulary (source URL, license, attribution), which stays exactly
as it was.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

#: Bumps only when the *stamp's own shape* changes -- a field renamed, added,
#: or dropped. Independent of `ai_freecad_core.result_verifier.VERIFIER_VERSION`,
#: which versions the verifier's judgement, not the record format.
PROVENANCE_SCHEMA_VERSION = "1"

#: The property group every tool-created stamp is filed under, parallel to
#: (never mixed with) "CADWiz Import".
TOOL_PROVENANCE_GROUP = "CADWiz Provenance"

#: What an absent value becomes in the stamp. Matches
#: `ai_freecad_core.ai_gateway.audit.UNKNOWN` in spelling and intent: a value
#: nobody measured is recorded as unknown, never as an empty string that
#: reads as "measured, and it was blank".
UNKNOWN = "UNKNOWN"


def attach_properties(item: Any, group: str, values: dict[str, str]) -> None:
    """Add or refresh string properties on `item`, filed under `group`.

    The whole mechanism, extracted so it has exactly one implementation.
    `_attach_import_provenance` calls this for the import case; every
    mutating tool call calls it through `attach_tool_provenance` below.
    Silently does nothing for an object that cannot carry properties (a
    fresh `hasattr` check, matching the caller this was extracted from) --
    a provenance stamp that cannot be attached is not a reason to fail the
    operation that already succeeded.
    """
    if not hasattr(item, "addProperty"):
        return
    properties = set(getattr(item, "PropertiesList", ()))
    for name, value in values.items():
        if name not in properties:
            item.addProperty("App::PropertyString", name, group)
        setattr(item, name, value)


def summarize_verification(verification: Any) -> str:
    """A compact, JSON-encoded predicate summary for the provenance record.

    `verification` is a `RenderVerification | None`
    (`integrations.mcp_tools.verification`). Kept to plain dict/str/bool so
    the summary is exactly what `json.dumps` needs, not a hope that the
    verdict's dataclasses happen to serialize.
    """
    if verification is None:
        return json.dumps({"decision": "not_run"}, sort_keys=True)
    verdict = getattr(verification, "result_verdict", None)
    summary: dict[str, Any] = {
        "ok": bool(getattr(verification, "ok", False)),
        "recomputed": bool(getattr(verification, "recomputed", False)),
        "render_skipped": bool(getattr(verification, "render_skipped", False)),
    }
    if verdict is not None:
        summary["decision"] = getattr(verdict, "decision").value
        summary["mandatory_passed"] = bool(getattr(verdict, "mandatory_passed", False))
        summary["assertions"] = [
            {"id": assertion.assertion_id, "passed": bool(assertion.passed)}
            for assertion in getattr(verdict, "assertions", ())
        ]
    else:
        summary["decision"] = "not_run"
    return json.dumps(summary, sort_keys=True)


def build_tool_provenance(
    *,
    tool_name: str,
    tool_version: str,
    session_id: str,
    intent_id: str,
    user_request: str,
    parameters: dict[str, Any],
    verification: Any,
    verifier_version: str,
    created_at: str = "",
) -> dict[str, str]:
    """The v1 schema for a tool-created object, as string property values.

    `parameters` is JSON-encoded rather than split into one property per
    argument: tool argument shapes vary per tool and per call, and a fixed
    property list could not hold an arbitrary one without either dropping
    fields or growing unboundedly. `App::PropertyString` already has no size
    concept smaller than "the whole document", so one JSON string costs
    nothing a per-argument property would have saved.
    """
    return {
        "ProvenanceSchemaVersion": PROVENANCE_SCHEMA_VERSION,
        "ProvenanceCreatedBy": f"{tool_name}@{tool_version or UNKNOWN}",
        "ProvenanceSessionId": session_id or UNKNOWN,
        "ProvenanceIntentId": intent_id or UNKNOWN,
        "ProvenanceCreatedAt": created_at or datetime.now(UTC).isoformat(),
        "ProvenanceUserRequest": user_request or UNKNOWN,
        "ProvenanceParameters": json.dumps(parameters, sort_keys=True, default=str),
        "ProvenanceVerification": summarize_verification(verification),
        "ProvenanceVerifierVersion": verifier_version or UNKNOWN,
    }


def attach_tool_provenance(
    doc: Any,
    object_names: tuple[str, ...],
    values: dict[str, str],
) -> tuple[str, ...]:
    """Stamp `values` onto every named object that exists in `doc`.

    Returns the names actually stamped, so a caller (a test, or telemetry)
    can tell a real stamp from a mutation whose subject could not be found --
    silence here would look identical to success.
    """
    stamped: list[str] = []
    for name in object_names:
        item = doc.getObject(name) if doc is not None else None
        if item is None:
            continue
        attach_properties(item, TOOL_PROVENANCE_GROUP, values)
        stamped.append(name)
    return tuple(stamped)
