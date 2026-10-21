# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Non-compensating assertion coordinator with a bounded repair budget."""
from __future__ import annotations
from dataclasses import dataclass,field
from .contracts import AssertionResult, VerificationDecision, VerificationResult

@dataclass(slots=True)
class RepairBudget:
    maximum_repairs:int=2; attempted_signatures:set[str]=field(default_factory=set)
    def authorize(self,signature:str)->bool:
        if signature in self.attempted_signatures or len(self.attempted_signatures)>=self.maximum_repairs:return False
        self.attempted_signatures.add(signature);return True

class VerificationCoordinator:
    def compare(self,assertions:tuple[AssertionResult,...],budget:RepairBudget|None=None,repair_signature:str|None=None)->VerificationResult:
        failed=tuple(a for a in assertions if a.layer=="HARD" and not a.passed)
        if not failed:return VerificationResult(VerificationDecision.CONTINUE,assertions,True,"all mandatory hard assertions pass")
        if budget and repair_signature and budget.authorize(repair_signature):return VerificationResult(VerificationDecision.RETRY_DIFFERENTLY,assertions,False,"bounded materially different repair authorized")
        return VerificationResult(VerificationDecision.ROLLBACK_STOP,assertions,False,"mandatory hard assertion failed")

