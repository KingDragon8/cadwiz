# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Continuous assisted recovery from broken evidence to validated health."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from uuid import uuid4

from .contracts import CauseClassification, DiagnosisReport


class RecoveryState(str, Enum):
    DIAGNOSING = "diagnosing"
    NEEDS_INFORMATION = "needs_information"
    REPAIR_READY = "repair_ready"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    VALIDATING = "validating"
    HEALTHY = "healthy"
    RETRYING = "retrying"
    BLOCKED_EXTERNAL = "blocked_external"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RecoveryEvent:
    sequence: int
    state: RecoveryState
    summary: str


@dataclass(frozen=True, slots=True)
class RecoveryCase:
    identifier: str
    document_id: str
    state: RecoveryState
    cycle: int
    diagnosis: DiagnosisReport
    question: str | None = None
    answer: str | None = None
    strategy_id: str | None = None
    approved: bool = False
    events: tuple[RecoveryEvent, ...] = ()

    @property
    def complete(self) -> bool:
        return self.state in {
            RecoveryState.HEALTHY,
            RecoveryState.BLOCKED_EXTERNAL,
            RecoveryState.CANCELLED,
        }


class AssistedRecoveryService:
    """Never call a model healthy without independent post-repair validation."""

    def __init__(self, maximum_cycles: int = 8) -> None:
        if maximum_cycles < 1:
            raise ValueError("maximum recovery cycles must be positive")
        self._maximum_cycles = maximum_cycles

    def start(self, report: DiagnosisReport) -> RecoveryCase:
        case = RecoveryCase(
            f"recovery-{uuid4().hex}",
            report.document_id,
            RecoveryState.DIAGNOSING,
            1,
            report,
        )
        return self._after_diagnosis(case, report)

    def answer(self, case: RecoveryCase, answer: str) -> RecoveryCase:
        self._require(case, RecoveryState.NEEDS_INFORMATION)
        if not answer.strip():
            raise ValueError("recovery answer must not be empty")
        updated = replace(
            case,
            state=RecoveryState.DIAGNOSING,
            answer=answer.strip(),
            question=None,
        )
        return self._event(updated, f"User supplied repair intent: {answer.strip()}")

    def rediagnose(self, case: RecoveryCase, report: DiagnosisReport) -> RecoveryCase:
        self._require(case, RecoveryState.DIAGNOSING, RecoveryState.RETRYING)
        if report.document_id != case.document_id:
            raise ValueError("recovery diagnosis changed documents")
        updated = replace(case, diagnosis=report)
        return self._after_diagnosis(updated, report)

    def choose_repair(self, case: RecoveryCase, strategy_id: str) -> RecoveryCase:
        self._require(case, RecoveryState.REPAIR_READY)
        known = {item.identifier for item in case.diagnosis.repair_strategies}
        if strategy_id not in known:
            raise ValueError("repair strategy is not supported by this diagnosis")
        updated = replace(
            case,
            state=RecoveryState.AWAITING_APPROVAL,
            strategy_id=strategy_id,
        )
        return self._event(updated, f"Repair selected: {strategy_id}")

    def approve(self, case: RecoveryCase, approved: bool) -> RecoveryCase:
        self._require(case, RecoveryState.AWAITING_APPROVAL)
        if not approved:
            return self._event(
                replace(case, state=RecoveryState.NEEDS_INFORMATION, strategy_id=None),
                "Repair rejected; asking what outcome the user prefers",
                question="What should the repaired model do differently?",
            )
        return self._event(
            replace(case, state=RecoveryState.EXECUTING, approved=True),
            "Repair approved for protected execution",
        )

    def execution_result(
        self, case: RecoveryCase, *, succeeded: bool, rollback_succeeded: bool = False
    ) -> RecoveryCase:
        self._require(case, RecoveryState.EXECUTING)
        if succeeded:
            return self._event(
                replace(case, state=RecoveryState.VALIDATING),
                "Protected repair executed; independent validation required",
            )
        summary = (
            "Repair failed and rollback restored the checkpoint"
            if rollback_succeeded
            else "Repair failed; recovery evidence requires inspection"
        )
        return self._retry_or_block(case, summary)

    def validation_result(
        self, case: RecoveryCase, *, healthy: bool, evidence: tuple[str, ...]
    ) -> RecoveryCase:
        self._require(case, RecoveryState.VALIDATING)
        if not evidence:
            raise ValueError("independent validation evidence is required")
        if healthy:
            return self._event(
                replace(case, state=RecoveryState.HEALTHY),
                "Model is independently validated as healthy: " + "; ".join(evidence),
            )
        return self._retry_or_block(
            case,
            "Validation found remaining problems: " + "; ".join(evidence),
        )

    def cancel(self, case: RecoveryCase) -> RecoveryCase:
        if case.complete:
            raise ValueError("completed recovery cannot be cancelled")
        return self._event(
            replace(case, state=RecoveryState.CANCELLED),
            "Recovery cancelled; the last protected model remains preserved",
        )

    def _after_diagnosis(
        self, case: RecoveryCase, report: DiagnosisReport
    ) -> RecoveryCase:
        if report.root_cause is None:
            return self._event(
                replace(case, state=RecoveryState.HEALTHY, diagnosis=report),
                "Diagnosis found no supported failure; model health is confirmed for this scope",
            )
        if report.repair_strategies:
            return self._event(
                replace(case, state=RecoveryState.REPAIR_READY, diagnosis=report),
                "Evidence-supported repair is ready for review",
            )
        question = self._question(report.classification)
        return self._event(
            replace(
                case,
                state=RecoveryState.NEEDS_INFORMATION,
                diagnosis=report,
                question=question,
            ),
            "More design intent is required before a safe repair",
        )

    def _retry_or_block(self, case: RecoveryCase, summary: str) -> RecoveryCase:
        next_cycle = case.cycle + 1
        if next_cycle > self._maximum_cycles:
            return self._event(
                replace(case, state=RecoveryState.BLOCKED_EXTERNAL),
                summary + "; bounded attempts exhausted—human FreeCAD review is required",
            )
        return self._event(
            replace(
                case,
                state=RecoveryState.RETRYING,
                cycle=next_cycle,
                approved=False,
                strategy_id=None,
            ),
            summary + "; returning to diagnosis",
        )

    @staticmethod
    def _question(classification: CauseClassification | None) -> str:
        questions = {
            CauseClassification.BROKEN_REFERENCE: (
                "Which face, edge, or object should this feature reference now?"
            ),
            CauseClassification.SKETCH_CONSTRAINT: (
                "Which dimension or geometric relationship must the sketch preserve?"
            ),
            CauseClassification.POCKET: "Where should the pocket cut, and in which direction?",
            CauseClassification.BOOLEAN: (
                "Which bodies should intersect, and what result is intended?"
            ),
            CauseClassification.MULTIPLE_SOLIDS: (
                "Should these solids be joined or remain separate?"
            ),
            CauseClassification.PARAMETER: "What value and unit should this parameter use?",
            CauseClassification.THICKNESS: "Which wall thickness and opening faces are intended?",
            CauseClassification.LOFT: "Which profiles belong in the loft, and in what order?",
            CauseClassification.SWEEP: "Which profile and path should define the sweep?",
            CauseClassification.EXPRESSION: "What relationship should this expression represent?",
            CauseClassification.DEPENDENCY: "Which feature should this object depend on?",
            CauseClassification.EXPORT: "Which format and object should be exported?",
        }
        if classification is None:
            return "What should this feature do when the model is healthy?"
        fallback = "What should this feature do when the model is healthy?"
        return questions.get(classification, fallback)

    @staticmethod
    def _require(case: RecoveryCase, *states: RecoveryState) -> None:
        if case.state not in states:
            expected = ", ".join(item.value for item in states)
            raise ValueError(f"recovery action requires {expected}; current={case.state.value}")

    @staticmethod
    def _event(
        case: RecoveryCase, summary: str, *, question: str | None = None
    ) -> RecoveryCase:
        updated = replace(case, question=question if question is not None else case.question)
        event = RecoveryEvent(len(updated.events) + 1, updated.state, summary)
        return replace(updated, events=(*updated.events, event))
