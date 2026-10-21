# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Typed feature IR validation and deterministic bracket-coupon program."""

from __future__ import annotations
import re
from .contracts import EngineeringIntentSpecLite, FEATURE_IR_SCHEMA_VERSION, FeatureOperationIR, FeatureOperationType as T, FeatureProgramIR, NormalizedValue

_SEMANTIC=re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
_CONVERSIONS={"mm":1.0,"cm":10.0,"m":1000.0,"in":25.4,"inch":25.4,"inches":25.4}

def normalize_length(value:float, unit:str|None) -> NormalizedValue:
    if unit is None or not unit.strip(): raise ValueError("ambiguous unitless engineering dimension")
    factor=_CONVERSIONS.get(unit.casefold())
    if factor is None: raise ValueError(f"unsupported length unit: {unit}")
    if isinstance(value,bool) or value<=0: raise ValueError("engineering dimension must be positive")
    return NormalizedValue(float(value)*factor,float(value),unit,f"{value} {unit} * {factor} = {float(value)*factor} mm")

def _op(index:int,target:str,kind:T,parameters:dict[str,object],*,pre:tuple[str,...]=(),post:tuple[str,...]=(),checkpoint:str="start") -> FeatureOperationIR:
    if not _SEMANTIC.fullmatch(target): raise ValueError(f"invalid semantic target: {target}")
    return FeatureOperationIR(f"op-{index:02d}",target,kind,parameters,{k:"mm" for k,v in parameters.items() if isinstance(v,(int,float)) and not isinstance(v,bool)},pre,post,checkpoint,("observation","validator","viewport"))


def feature_name(semantic_target_id: str) -> str:
    """The FreeCAD object name one semantic target deterministically means.

    Always the last dot-segment: `"Part.BasePlate"` -> `"BasePlate"`,
    `"Part.BossLeft"` -> `"BossLeft"`. Deterministic because it is a pure
    function of the target id and nothing else -- no counter, no "auto"
    suffix a tool might pick differently on a second run. A caller building
    an `IRProgramBuilder` program is responsible for choosing target ids
    whose last segment is already the name it wants and that no other
    operation in the same program reuses; `feature_name` does not check
    uniqueness itself; `IRProgramBuilder` does, once, at build time.
    """
    if not _SEMANTIC.fullmatch(semantic_target_id):
        raise ValueError(f"invalid semantic target: {semantic_target_id}")
    return semantic_target_id.rsplit(".", 1)[-1]

def compile_coupon_program(spec:EngineeringIntentSpecLite, document_id:str="freecad:ParametricBracketCoupon") -> FeatureProgramIR:
    if spec.current_gate_outcome.value!="PASS": raise ValueError("intent gate must PASS before IR compilation")
    p={k:float(v) for k,v in spec.mandatory_requirements.items() if isinstance(v,(int,float)) and not isinstance(v,bool)}
    required=("overall_width_mm","overall_height_mm","base_thickness_mm","pocket_width_mm","pocket_height_mm","pocket_depth_mm","hole_diameter_mm","hole_spacing_mm","fillet_radius_mm")
    missing=[k for k in required if k not in p]
    if missing: raise ValueError("missing coupon parameters: "+", ".join(missing))
    for k in required:
        if p[k]<=0: raise ValueError(f"{k} must be positive")
    if p["pocket_width_mm"]>=p["overall_width_mm"] or p["pocket_height_mm"]>=p["overall_height_mm"]: raise ValueError("pocket must fit inside base")
    if p["pocket_depth_mm"]>=p["base_thickness_mm"]: raise ValueError("pocket depth must leave material")
    if p["fillet_radius_mm"]>=p["base_thickness_mm"]/2: raise ValueError("fillet radius exceeds the governed thickness limit")
    ops:list[FeatureOperationIR]=[]
    def add(target:str,kind:T,params:dict[str,object],**kw:object)->None: ops.append(_op(len(ops)+1,target,kind,params,**kw))
    add("Document.Root",T.CREATE_DOCUMENT,{"name":"ParametricBracketCoupon"},post=("document exists",))
    add("Part.Body",T.CREATE_BODY_OR_CONTAINER,{"name":"BracketBody"},pre=("Document.Root exists",),post=("body exists",))
    for name in required: add(f"Part.Parameters.{name}",T.DEFINE_NAMED_PARAMETER,{"name":name,"value":p[name]},checkpoint="document")
    add("Part.BaseSketch",T.CREATE_SKETCH_ON_NAMED_PLANE,{"body":"BracketBody","plane":"XY_Plane"},checkpoint="parameters")
    add("Part.BaseSketch.Profile",T.ADD_RECTANGLE_OR_CLOSED_PROFILE,{"sketch":"BaseSketch","width":p["overall_width_mm"],"height":p["overall_height_mm"],"centered":True},checkpoint="parameters")
    add("Part.BaseSketch.Constraints",T.APPLY_BASIC_GEOMETRIC_CONSTRAINTS,{"sketch":"BaseSketch","profile":"rectangle"},checkpoint="parameters")
    add("Part.BaseSketch.Dimensions",T.APPLY_DIMENSIONAL_CONSTRAINTS,{"sketch":"BaseSketch","width":p["overall_width_mm"],"height":p["overall_height_mm"]},checkpoint="parameters",post=("sketch fully constrained",))
    add("Part.BasePad",T.PAD,{"body":"BracketBody","sketch":"BaseSketch","length":p["base_thickness_mm"],"width":p["overall_width_mm"],"height":p["overall_height_mm"]},checkpoint="base-sketch",post=("one valid solid",))
    add("Part.TopDatum",T.CREATE_NAMED_DATUM_PLANE,{"body":"BracketBody","offset":p["base_thickness_mm"]},checkpoint="base-pad")
    add("Part.PocketSketch",T.CREATE_SKETCH_ON_NAMED_PLANE,{"body":"BracketBody","plane":"TopDatum"},checkpoint="base-pad")
    add("Part.PocketSketch.Profile",T.ADD_RECTANGLE_OR_CLOSED_PROFILE,{"sketch":"PocketSketch","width":p["pocket_width_mm"],"height":p["pocket_height_mm"],"centered":True},checkpoint="base-pad")
    add("Part.PocketSketch.Constraints",T.APPLY_BASIC_GEOMETRIC_CONSTRAINTS,{"sketch":"PocketSketch","profile":"rectangle"},checkpoint="base-pad")
    add("Part.PocketSketch.Dimensions",T.APPLY_DIMENSIONAL_CONSTRAINTS,{"sketch":"PocketSketch","width":p["pocket_width_mm"],"height":p["pocket_height_mm"]},checkpoint="base-pad",post=("sketch fully constrained",))
    add("Part.Pocket",T.POCKET,{"body":"BracketBody","base":"BasePad","width":p["pocket_width_mm"],"height":p["pocket_height_mm"],"depth":p["pocket_depth_mm"],"base_width":p["overall_width_mm"],"base_height":p["overall_height_mm"],"base_thickness":p["base_thickness_mm"]},checkpoint="base-pad",post=("one valid solid",))
    for side,x in (("Left",-p["hole_spacing_mm"]/2),("Right",p["hole_spacing_mm"]/2)):
        add(f"Part.MountingHole{side}",T.ADD_CIRCLE,{"center_x":x,"center_y":0.0,"diameter":p["hole_diameter_mm"]},checkpoint="pocket")
    add("Part.MountingHoles",T.HOLE,{"body":"BracketBody","base":"Pocket","diameter":p["hole_diameter_mm"],"spacing":p["hole_spacing_mm"],"through":True},checkpoint="pocket",post=("two through holes",))
    add("Part.OuterEdgeFilletSet",T.FILLET,{"body":"BracketBody","base":"MountingHoles","radius":p["fillet_radius_mm"],"selector":"vertical_outer_edges"},checkpoint="holes",post=("one valid solid",))
    add("Document.Checkpoint",T.SAVE_CHECKPOINT,{"name":"accepted-baseline"},checkpoint="fillet")
    add("Document.Observation",T.OBSERVE_DOCUMENT,{"active_subject":"OuterEdgeFilletSet"},checkpoint="fillet")
    return FeatureProgramIR(FEATURE_IR_SCHEMA_VERSION,spec.intent_id,document_id,tuple(ops))
