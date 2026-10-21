# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Compile canonical feature IR into the existing StructuredCommand contract."""
from __future__ import annotations
from ai_freecad_core.execution.contracts import CommandArgument,CommandRisk,CommandTarget,StructuredCommand
from .contracts import FeatureProgramIR

CAPABILITY_PREFIX="production_feature_"

class TypedFeatureIRCompiler:
    def compile(self,program:FeatureProgramIR,expected_model_revision:int=0)->tuple[StructuredCommand,...]:
        commands=[]
        seen=set()
        for operation in program.operations:
            if operation.operation_id in seen:raise ValueError("operation identifiers must be unique")
            seen.add(operation.operation_id)
            args=tuple(CommandArgument(k,v,operation.units.get(k)) for k,v in operation.parameters.items())
            commands.append(StructuredCommand(operation.operation_id,CAPABILITY_PREFIX+operation.operation_type.value,CommandTarget(program.document_id,expected_model_revision),CommandRisk.LOW,30,args,validation_profile_ids=operation.evidence_requirements,preconditions=operation.preconditions,expected_postconditions=operation.expected_postconditions,affected_object_ids=(operation.semantic_target_id,)))
        return tuple(commands)

