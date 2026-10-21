# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Typed, host-neutral contracts for the first governed CAD production slice."""

from .contracts import *
from .intent_gate import evaluate_intent
from .ir import compile_coupon_program, feature_name, normalize_length
from .program_builder import IRProgramBuilder
from .verification import RepairBudget, VerificationCoordinator
from .evidence import AppendOnlyEvidenceLedger
from .assembly import AssemblyAdapter
from .compiler import TypedFeatureIRCompiler
from .request_boundary import *
from .public_surface import PublicIntentDecision, evaluate_public_request
