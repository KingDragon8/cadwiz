# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Evidence-first causal ordering for broken FreeCAD models."""

from __future__ import annotations

from .contracts import (
    CauseClassification,
    DiagnosisConfidence,
    DiagnosisEvidence,
    DiagnosisReport,
    DiagnosticObjectState,
    DiagnosticSnapshot,
    RepairStrategy,
)

# Plain-language, third-grade-reading-level explanations of each cause. Written
# for someone who has never opened FreeCAD before: no jargon like "recompute,"
# "constraint," or "expression" without saying what that actually means for
# their model.
_PLAIN_LANGUAGE_CAUSES: dict[CauseClassification, str] = {
    CauseClassification.RECOMPUTE: (
        "FreeCAD tried to rebuild this part and the rebuild failed."
    ),
    CauseClassification.BROKEN_REFERENCE: (
        "this part points to another part, edge, or face that isn't there anymore, "
        "so FreeCAD doesn't know where to build it"
    ),
    CauseClassification.SKETCH_CONSTRAINT: (
        "the flat 2D sketch this part is built from has rules that contradict each "
        "other (for example, two lines both told to be a certain length that can't "
        "both be true at once), so it can't be solved"
    ),
    CauseClassification.NULL_SHAPE: "this part didn't produce any 3D shape at all",
    CauseClassification.INVALID_SHAPE: (
        "FreeCAD built a shape here, but the shape itself is broken — like a surface "
        "with a gap in it that shouldn't be there"
    ),
    CauseClassification.MULTIPLE_SOLIDS: (
        "this part accidentally split into more than one separate solid piece, when "
        "it's supposed to be a single connected piece"
    ),
    CauseClassification.BOOLEAN: (
        "a cut, join, or overlap step here doesn't actually touch the other shape "
        "it's supposed to combine with"
    ),
    CauseClassification.POCKET: (
        "a pocket (a shape cut into the part) here doesn't actually reach into the "
        "solid it's supposed to cut"
    ),
    CauseClassification.PARAMETER: (
        "a number used to build this part — like a length or an angle — is outside "
        "the range that's actually possible"
    ),
    CauseClassification.FILLET: (
        "a rounded edge (fillet) or angled edge (chamfer) here is too big to fit on "
        "the part it's on"
    ),
    CauseClassification.THICKNESS: (
        "an operation that hollows out this part to a wall thickness couldn't do it "
        "the way it was set up"
    ),
    CauseClassification.LOFT: (
        "a shape built by blending between multiple outlines couldn't be blended "
        "the way it was set up"
    ),
    CauseClassification.SWEEP: (
        "a shape built by sliding an outline along a path couldn't follow that path"
    ),
    CauseClassification.DEPENDENCY: (
        "this part depends on another part that isn't set up correctly, so it can't "
        "build either"
    ),
    CauseClassification.EXPRESSION: (
        "a formula controlling a number on this part is broken — maybe it's using "
        "the wrong units, or pointing at something that changed or was deleted"
    ),
    CauseClassification.EXPORT: "this part was being saved out to a file, and that failed",
    CauseClassification.MESH: (
        "this part came from an imported 3D scan or mesh file (like an STL). Those "
        "files are just a surface made of triangles — they don't come with the "
        "\"build recipe\" that parts made inside FreeCAD have, so FreeCAD can't "
        "automatically resize or repair it the same way"
    ),
    CauseClassification.UNKNOWN: (
        "something about this part isn't building correctly, but it isn't a "
        "problem FreeCAD recognizes a specific reason for yet"
    ),
}

_PLAIN_LANGUAGE_CONFIDENCE: dict[DiagnosisConfidence, str] = {
    DiagnosisConfidence.CONFIRMED: "This is confirmed — not a guess.",
    DiagnosisConfidence.HIGHLY_LIKELY: "This is very likely the reason.",
    DiagnosisConfidence.POSSIBLE: "This is a possible reason, but it isn't certain.",
    DiagnosisConfidence.UNKNOWN: "The exact reason isn't clear yet.",
}


class BrokenModelDiagnosisService:
    """Find the earliest supported failure; never mutates or invents model facts."""

    def diagnose(self, snapshot: DiagnosticSnapshot) -> DiagnosisReport:
        ordered = self._causal_order(snapshot.objects)
        failures = tuple(item for item in ordered if self._is_failure(item))
        warnings = tuple(
            f"{item.label}: sketch is under-constrained"
            for item in ordered
            if "under-constrained" in self._text(item) and item not in failures
        )
        if not failures:
            return DiagnosisReport(
                snapshot.run_id,
                snapshot.document_id,
                None,
                None,
                DiagnosisConfidence.CONFIRMED,
                (),
                (),
                (),
                warnings,
                (),
                False,
                True,
                "No supported model failure was found. No repair is proposed.",
            )
        root = failures[0]
        classification, confidence, reason = self._classify(root)
        downstream = tuple(
            item.label for item in failures[1:] if self._depends_on(item, root, ordered)
        )
        path = (root.object_id,) + tuple(
            item.object_id for item in failures[1:] if item.label in downstream
        )
        evidence = (
            DiagnosisEvidence(root.object_id, "What FreeCAD reported", reason),
            DiagnosisEvidence(
                root.object_id,
                "Why we start here",
                f'We checked every part in build order, and "{root.label}" is the '
                "first one that actually breaks. Anything that breaks after it is a "
                "side effect, not a separate problem to fix.",
            ),
        )
        return DiagnosisReport(
            snapshot.run_id,
            snapshot.document_id,
            root,
            classification,
            confidence,
            path,
            evidence,
            downstream,
            warnings,
            self._strategies(classification),
            False,
            True,
            self._summary(root, classification, confidence, downstream),
        )

    @staticmethod
    def _text(item: DiagnosticObjectState) -> str:
        return " ".join((*item.states, item.error_text, item.type_id, item.name)).casefold()

    def _is_failure(self, item: DiagnosticObjectState) -> bool:
        text = self._text(item)
        bad_state = any(word in text for word in ("error", "invalid", "failed", "exception"))
        stated_failure = bool(item.error_text.strip()) and "under-constrained" not in text
        return (
            bad_state
            or stated_failure
            or not item.shape_available
            or item.shape_valid is False
            or (item.solid_count is not None and item.solid_count > 1)
            or "over-constrained" in text
            or "missing support" in text
            or "broken reference" in text
        )

    def _classify(
        self, item: DiagnosticObjectState
    ) -> tuple[CauseClassification, DiagnosisConfidence, str]:
        text = self._text(item)
        rules = (
            (("mesh::", "mesh issue"), CauseClassification.MESH),
            (("export failed", "export failure"), CauseClassification.EXPORT),
            (("circular dependency", "cyclic"), CauseClassification.DEPENDENCY),
            (("body tip", "invalid attachment"), CauseClassification.DEPENDENCY),
            (("expression", "unit mismatch"), CauseClassification.EXPRESSION),
            (
                ("missing support", "broken reference", "no support", "external geometry"),
                CauseClassification.BROKEN_REFERENCE,
            ),
            (("over-constrained", "conflicting constraint"), CauseClassification.SKETCH_CONSTRAINT),
            (("partdesign::fillet", "chamfer", "radius too large"), CauseClassification.FILLET),
            (("thickness",), CauseClassification.THICKNESS),
            (("loft",), CauseClassification.LOFT),
            (("sweep", "additivepipe", "subtractivepipe"), CauseClassification.SWEEP),
            (("pocket", "does not intersect", "wrong direction"), CauseClassification.POCKET),
            (
                ("boolean", "part::cut", "part::multicommon", "nonintersect"),
                CauseClassification.BOOLEAN,
            ),
            (("multiple solid",), CauseClassification.MULTIPLE_SOLIDS),
            (("parameter", "out of range", "negative length"), CauseClassification.PARAMETER),
            (("recompute", "execute failed"), CauseClassification.RECOMPUTE),
        )
        for terms, classification in rules:
            if any(term in text for term in terms):
                return (
                    classification,
                    DiagnosisConfidence.HIGHLY_LIKELY,
                    item.error_text or terms[0],
                )
        if not item.shape_available:
            return (
                CauseClassification.NULL_SHAPE,
                DiagnosisConfidence.CONFIRMED,
                "the feature has no shape",
            )
        if item.shape_valid is False:
            return (
                CauseClassification.INVALID_SHAPE,
                DiagnosisConfidence.CONFIRMED,
                "FreeCAD reports an invalid shape",
            )
        if item.solid_count is not None and item.solid_count > 1:
            return (
                CauseClassification.MULTIPLE_SOLIDS,
                DiagnosisConfidence.CONFIRMED,
                f"the feature contains {item.solid_count} solids",
            )
        return (
            CauseClassification.UNKNOWN,
            DiagnosisConfidence.POSSIBLE,
            item.error_text or "unsupported failure state",
        )

    @staticmethod
    def _causal_order(
        objects: tuple[DiagnosticObjectState, ...],
    ) -> tuple[DiagnosticObjectState, ...]:
        by_id = {item.object_id: item for item in objects}
        visited: set[str] = set()
        result: list[DiagnosticObjectState] = []

        def visit(item: DiagnosticObjectState) -> None:
            if item.object_id in visited:
                return
            visited.add(item.object_id)
            for dependency in sorted(item.dependencies):
                if dependency in by_id:
                    visit(by_id[dependency])
            result.append(item)

        for item in sorted(objects, key=lambda value: (value.order, value.object_id)):
            visit(item)
        return tuple(result)

    @staticmethod
    def _depends_on(
        item: DiagnosticObjectState,
        root: DiagnosticObjectState,
        objects: tuple[DiagnosticObjectState, ...],
    ) -> bool:
        by_id = {value.object_id: value for value in objects}
        pending = list(item.dependencies)
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current == root.object_id:
                return True
            if current not in seen and current in by_id:
                seen.add(current)
                pending.extend(by_id[current].dependencies)
        return False

    @staticmethod
    def _strategies(classification: CauseClassification) -> tuple[RepairStrategy, ...]:
        if classification is CauseClassification.RECOMPUTE:
            return (
                RepairStrategy(
                    "guarded-recompute", "Recompute safely", "The model may only be stale.", "low"
                ),
            )
        if classification is CauseClassification.FILLET:
            return (
                RepairStrategy(
                    "reduce-radius",
                    "Reduce the radius",
                    "Find and approve a feasible radius.",
                    "medium",
                ),
            )
        if classification in {
            CauseClassification.BROKEN_REFERENCE,
            CauseClassification.SKETCH_CONSTRAINT,
        }:
            return (
                RepairStrategy(
                    "review-reference",
                    "Review the exact reference",
                    "A unique intended reference must be proven before repair.",
                    "high",
                ),
            )
        return ()

    @staticmethod
    def _summary(
        root: DiagnosticObjectState,
        classification: CauseClassification,
        confidence: DiagnosisConfidence,
        downstream: tuple[str, ...],
    ) -> str:
        cause = _PLAIN_LANGUAGE_CAUSES.get(
            classification, _PLAIN_LANGUAGE_CAUSES[CauseClassification.UNKNOWN]
        )
        confidence_phrase = _PLAIN_LANGUAGE_CONFIDENCE.get(
            confidence, _PLAIN_LANGUAGE_CONFIDENCE[DiagnosisConfidence.UNKNOWN]
        )
        others = "one other part" if len(downstream) == 1 else f"{len(downstream)} other parts"
        symptom = (
            f" Because of this, {others} further along in your model also show "
            f"errors ({', '.join(downstream)}) — but those are just knock-on effects "
            "of this one problem, not separate things to fix."
            if downstream
            else ""
        )
        return (
            f'The first thing that goes wrong in your model is one part, called '
            f'"{root.label}" — not your whole model. Here\'s the problem with it: '
            f"{cause}. {confidence_phrase}{symptom} Nothing has been changed — your "
            "saved file is exactly as it was."
        )
