# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Deterministic request-to-command workflow contracts and compiler."""

from importlib import import_module as _import_module

#: name -> (submodule, attribute). Loaded on first use, so importing one submodule
#: (say `.audit`) does not load the whole package (ORDER-2026-10-21-01: keeps the
#: model-routing code out of the Claude plug-in, which only needs the audit log).
_LAZY = {
    'BuildDisposition': ('build', 'BuildDisposition'),
    'ProtectedBuildResult': ('build', 'ProtectedBuildResult'),
    'ProtectedBuildService': ('build', 'ProtectedBuildService'),
    'VerticalSliceCompiler': ('compiler', 'VerticalSliceCompiler'),
    'CompilationArtifact': ('contracts', 'CompilationArtifact'),
    'ParametricPartRequest': ('contracts', 'ParametricPartRequest'),
    'RequestedParameter': ('contracts', 'RequestedParameter'),
    'SupportedPrimitive': ('contracts', 'SupportedPrimitive'),
    'BoundedRepairService': ('repair', 'BoundedRepairService'),
    'RepairAttemptEvidence': ('repair', 'RepairAttemptEvidence'),
    'RepairFailureCategory': ('repair', 'RepairFailureCategory'),
    'RepairProposal': ('repair', 'RepairProposal'),
    'RepairWorkflowResult': ('repair', 'RepairWorkflowResult'),
    'classify_validation_failure': ('repair', 'classify_validation_failure'),
    'RequestWorkflowResult': ('request', 'RequestWorkflowResult'),
    'RequestWorkflowService': ('request', 'RequestWorkflowService'),
}


def __getattr__(name: str):
    try:
        module, attribute = _LAZY[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(_import_module(f".{module}", __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY))

__all__ = [
    "CompilationArtifact",
    "BuildDisposition",
    "BoundedRepairService",
    "ParametricPartRequest",
    "ProtectedBuildResult",
    "ProtectedBuildService",
    "RepairAttemptEvidence",
    "RepairFailureCategory",
    "RepairProposal",
    "RepairWorkflowResult",
    "RequestWorkflowResult",
    "RequestWorkflowService",
    "RequestedParameter",
    "SupportedPrimitive",
    "VerticalSliceCompiler",
    "classify_validation_failure",
]
