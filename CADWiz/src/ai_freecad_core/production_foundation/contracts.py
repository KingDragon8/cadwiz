# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Immutable contracts for intent, typed feature IR, observation and verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

#: `FeatureProgramIR.schema_version`. Bumped from @1 (the single hardcoded
#: bracket-coupon program) to @2 when M-REACH (M3, 2026-09-07) generalized
#: the IR to an arbitrary sequence of qualified-verb operations and added
#: the operation types below. The mechanical rule stayed the same after
#: that: bump again only when an operation's meaning changes or one is
#: removed -- adding a new, additive operation type does not by itself
#: require a bump, the same rule `ai_freecad_core.result_verifier.
#: VERIFIER_VERSION` follows. Bumped @2 -> @3 anyway by founder ruling,
#: 2026-09-12/13 (M3 PLANNABLE SWEEP): a milestone marker for closing the
#: plannable gap across all 156 PROVEN tools in one sweep, not because any
#: individual addition below needed one under the mechanical rule.
FEATURE_IR_SCHEMA_VERSION = "cadwiz-feature-ir@3"

#: `EngineeringIntentSpecLite.schema_version`. Named "Design Intent Core v1"
#: in the roadmap (M3): the versioned schema every IR feature references,
#: via `FeatureProgramIR.intent_id` naming one `EngineeringIntentSpecLite`.
#: The contract itself predates this name (it shipped in Phase 0 as part of
#: the production-foundation slice); this is the first time it is given a
#: formal version constant rather than an ad hoc literal ("1") at each call
#: site.
DESIGN_INTENT_CORE_VERSION = "design-intent-core@1"


class UnknownClass(str, Enum):
    A_INTENT_CRITICAL = "A_INTENT_CRITICAL"
    B_ENGINEERING_CRITICAL = "B_ENGINEERING_CRITICAL"
    C_PREFERENCE = "C_PREFERENCE"
    D_COSMETIC = "D_COSMETIC"


class IntentGateOutcome(str, Enum):
    PASS = "PASS"
    ASK_USER = "ASK_USER"
    CAPABILITY_BLOCKED = "CAPABILITY_BLOCKED"
    INVALID = "INVALID"


class FeatureOperationType(str, Enum):
    CREATE_DOCUMENT = "create_document"
    CREATE_BODY_OR_CONTAINER = "create_body_or_container"
    DEFINE_NAMED_PARAMETER = "define_named_parameter"
    CREATE_SKETCH_ON_NAMED_PLANE = "create_sketch_on_named_plane"
    CREATE_NAMED_DATUM_PLANE = "create_named_datum_plane"
    ADD_RECTANGLE_OR_CLOSED_PROFILE = "add_rectangle_or_closed_profile"
    ADD_CIRCLE = "add_circle"
    APPLY_DIMENSIONAL_CONSTRAINTS = "apply_dimensional_constraints"
    APPLY_BASIC_GEOMETRIC_CONSTRAINTS = "apply_basic_geometric_constraints"
    PAD = "pad"
    POCKET = "pocket"
    HOLE = "hole"
    FILLET = "fillet"
    SAVE_CHECKPOINT = "save_checkpoint"
    OBSERVE_DOCUMENT = "observe_document"
    RESTORE_CHECKPOINT = "restore_checkpoint"
    CREATE_CLAMP_BASE = "create_clamp_base"
    CUT_DESK_OPENING = "cut_desk_opening"
    ADD_CLAMP_SCREW_BOSS = "add_clamp_screw_boss"
    CUT_M8_NUT_CAPTURE = "cut_m8_nut_capture"
    CUT_M8_SCREW_PATH = "cut_m8_screw_path"
    ADD_PIVOT_1_BOSS = "add_pivot_1_boss"
    CUT_PIVOT_1_BORE = "cut_pivot_1_bore"
    ADD_CLAMP_FILLET = "add_clamp_fillet"
    ADD_INDEX_FACE_COUPONS = "add_index_face_coupons"
    ADD_ARM_PROFILE_COUPON = "add_arm_profile_coupon"
    CREATE_PRINTABLE_ARMS = "create_printable_arms"
    CREATE_PHONE_MOUNT_INTERFACE = "create_phone_mount_interface"
    CREATE_S3_ASSEMBLY_BACKEND = "create_s3_assembly_backend"
    SET_S3_ASSEMBLY_POSE = "set_s3_assembly_pose"

    # -- M-REACH (M3), added 2026-09-07, schema bumped to @2. Each one maps to
    # a vendored tool ToolInvokerFeatureExecutor actually calls -- added only
    # because a real TEST-ISO-001 target needs it, not speculatively. See
    # docs/reports/2026-09-07-m-reach.md for which target needs which.
    CREATE_PRIMITIVE_BOX = "create_primitive_box"
    CREATE_PRIMITIVE_CYLINDER = "create_primitive_cylinder"
    CREATE_PRIMITIVE_SPHERE = "create_primitive_sphere"
    CREATE_PRIMITIVE_CONE = "create_primitive_cone"
    ADD_LINE_SEGMENT = "add_line_segment"
    ADD_SLOT_PROFILE = "add_slot_profile"
    ADD_POINT = "add_point"
    SET_PLACEMENT = "set_placement"
    CHAMFER = "chamfer"
    BOOLEAN_UNION = "boolean_union"
    BOOLEAN_CUT = "boolean_cut"
    DEFINE_SPREADSHEET_PARAMETER = "define_spreadsheet_parameter"
    BIND_SPREADSHEET_PARAMETER = "bind_spreadsheet_parameter"

    # -- Layer 3, added 2026-09-07. Each maps to a tool qualified 8/8 (or, for
    # mesh repair, 7/8 with one honestly BLOCKED point) against real FreeCAD
    # 1.1.3 in docs/reports/2026-09-07-freecad-coverage.md's own follow-on
    # work -- see tests/freecad_integration/runtime_layer3_qualification.py.
    # No schema-version bump: per this file's own rule above, an additive
    # operation type does not require one, and none of these change the
    # meaning of an existing operation.
    CREATE_HELIX_ADDITIVE = "create_helix_additive"
    CREATE_HELIX_SUBTRACTIVE = "create_helix_subtractive"
    CONVERT_TO_BSPLINE = "convert_to_bspline"
    INCREASE_BSPLINE_DEGREE = "increase_bspline_degree"
    CREATE_SUBSHAPE_BINDER = "create_subshape_binder"
    ADD_DRAFT_LINE = "add_draft_line"
    ADD_DRAFT_CIRCLE = "add_draft_circle"
    ADD_DRAFT_RECTANGLE = "add_draft_rectangle"
    APPLY_DRAFT_ANGLE = "apply_draft_angle"

    # -- M2b Group 1 (founder priority order), added 2026-09-08. Four of
    # five already had a vendored tool (qualified, not built); HOLE_ADVANCED
    # is the one genuine gap (create_hole never exposed counterbore/
    # countersink despite the M2a inventory's claim otherwise) and got a
    # new thin tool, create_hole_advanced. See
    # tests/freecad_integration/runtime_m2b_qualification.py, all five 8/8.
    LINEAR_PATTERN = "linear_pattern"
    POLAR_PATTERN = "polar_pattern"
    SHELL_THICKNESS = "shell_thickness"
    REVOLVE = "revolve"
    MIRROR_FEATURE = "mirror_feature"
    HOLE_ADVANCED = "hole_advanced"

    # -- M2b Group 2 (downloaded-STL rescue), added 2026-09-08. Mesh_
    # Evaluation/Mesh_FillupHoles/Mesh_HarmonizeNormals/Mesh_FlipNormals
    # already had IR coverage indirectly reachable through tool calls this
    # compiler does not yet expose as its own operations (repair_mesh,
    # check_mesh_manifold -- Layer 3); only the two genuinely new tools get
    # operations here. 7/8 and 5/8+3-blocked respectively, not 8/8 -- see
    # runtime_m2b_group2_qualification.py for the honest reasons.
    SCALE_MESH = "scale_mesh"
    CONVERT_MESH_TO_SOLID = "convert_mesh_to_solid"

    # -- M2b Group 3, added 2026-09-08: Part_Tube, Sketcher_
    # ConstrainSymmetric (a real bug in the vendored add_sketch_constraint's
    # own Symmetric branch, not just a missing tool), Sketcher_
    # CompCreateFillets. All three 8/8.
    CREATE_TUBE = "create_tube"
    CONSTRAIN_SKETCH_SYMMETRIC = "constrain_sketch_symmetric"
    FILLET_SKETCH_GEOMETRY = "fillet_sketch_geometry"

    # -- FILLET-PRO, added 2026-09-08: the layer above FILLET (capability 6,
    # already in this enum). Query-based edge selection (re-resolved every
    # recompute, not a frozen edge-name list), feasibility pre-check,
    # bisection search, and honest plain-language reporting when a request
    # is not fully met. 7/8 against real FreeCAD 1.1.3, provenance BLOCKED
    # for the same measured reason every tool-created object in this
    # program is -- see runtime_fillet_pro_qualification.py.
    CREATE_SMART_FILLET = "create_smart_fillet"
    INSERT_HOLE_BEFORE_FILLETS = "insert_hole_before_fillets"

    # -- PRINT-PREP, added 2026-09-08/09 (T1): M6 Print Readiness's first
    # deliverable, assembly to expert plate layout. SPLIT (a PartDesign
    # Body's own Tip -> one frozen printable solid), ORIENT+ARRANGE+ADVISE
    # (least-support-volume orientation, first-fit-decreasing plate
    # packing, measured brim/support/wall/infill advice), EXPORT (STL per
    # part, read back and verified). Qualified against the real named
    # target, CADW-S3-PIVOT3-PHONE-PLANE-20260830T234002Z -- see
    # runtime_print_prep_qualification.py.
    SPLIT_PRINTABLE_PARTS = "split_printable_parts"
    PLAN_PRINT_LAYOUT = "plan_print_layout"
    EXPORT_PRINT_PLATES = "export_print_plates"

    # -- M3 PLANNABLE SWEEP (founder ruling, 2026-09-12): every one of the
    # 156 PROVEN tools, not just the 47 the IR happened to need for
    # TEST-ISO-001/PRINT-PREP, gets its own operation type here -- closing
    # the plannable gap (114 tools) rather than leaving the IR's coverage
    # an accident of which parts got built first. No schema-version bump
    # per this file's own additive rule above; the founder still asked for
    # one (see FEATURE_IR_SCHEMA_VERSION below) as a milestone marker for
    # this specific sweep, not because the mechanism requires it.

    # ---- datum features (capability 9) --------------------------------
    CREATE_DATUM_PLANE = "create_datum_plane"
    CREATE_DATUM_LINE = "create_datum_line"
    CREATE_DATUM_POINT = "create_datum_point"

    # ---- sketch constraints extra (capabilities 3, 33, 36-38, 40, 42) --
    CONSTRAIN_DISTANCE_X = "constrain_distance_x"
    CONSTRAIN_HORIZONTAL = "constrain_horizontal"
    CONSTRAIN_VERTICAL = "constrain_vertical"
    CONSTRAIN_RADIUS = "constrain_radius"
    CONSTRAIN_DISTANCE = "constrain_distance"
    CONSTRAIN_DISTANCE_Y = "constrain_distance_y"
    CONSTRAIN_ANGLE = "constrain_angle"
    ADD_ARC = "add_arc"
    CONSTRAIN_COINCIDENT = "constrain_coincident"
    ADD_POLYGON = "add_polygon"
    CONSTRAIN_EQUAL = "constrain_equal"
    # TOOL FACTORY, 2026-09-16 (cracked-egg set, first two): add_sketch_ellipse
    # (the egg profile) and add_sketch_bspline (a freeform/jagged crack
    # profile) -- both PROVEN in docs/TOOL-REGISTER.json but never given a
    # compiler path. No schema bump: additive, per this file's own rule above.
    ADD_ELLIPSE = "add_ellipse"
    ADD_BSPLINE = "add_bspline"
    CONSTRAIN_PARALLEL = "constrain_parallel"
    CONSTRAIN_PERPENDICULAR = "constrain_perpendicular"
    CONSTRAIN_TANGENT = "constrain_tangent"
    # TOOL FACTORY, 2026-09-25: the general-purpose fallback constraint tool
    # itself (PROVEN since 2026-09-11, never given a compiler path -- every
    # CONSTRAIN_* op above maps to a dedicated wrapper tool, not this one).
    # Covers constraint types with no dedicated wrapper, e.g. "Block".
    ADD_SKETCH_CONSTRAINT = "add_sketch_constraint"

    # ---- export/import/validation HARD-predicate family (41, 50, 59, 60)
    VALIDATE_OBJECT = "validate_object"
    VALIDATE_DOCUMENT = "validate_document"
    EXPORT_STEP = "export_step"
    EXPORT_STL = "export_stl"
    EXPORT_3MF = "export_3mf"
    EXPORT_3MF_NATIVE = "export_3mf_native"
    EXPORT_OBJ = "export_obj"
    EXPORT_IGES = "export_iges"
    IMPORT_STEP_IR = "import_step"
    IMPORT_STL = "import_stl"
    SPREADSHEET_EXPORT_CSV = "spreadsheet_export_csv"
    SPREADSHEET_IMPORT_CSV = "spreadsheet_import_csv"
    CHECK_BED_FIT = "check_bed_fit"
    CHECK_MESH_MANIFOLD = "check_mesh_manifold"
    CHECK_WALL_THICKNESS = "check_wall_thickness"

    # ---- Part-workbench primitives extra (capability 43) ---------------
    CREATE_ELLIPSE = "create_ellipse"
    CREATE_HELIX_PRIMITIVE = "create_helix_primitive"
    CREATE_LINE_PRIMITIVE = "create_line_primitive"
    CREATE_PLANE_PRIMITIVE = "create_plane_primitive"
    CREATE_PRISM = "create_prism"
    CREATE_REGULAR_POLYGON = "create_regular_polygon"
    CREATE_WEDGE = "create_wedge"
    CREATE_TORUS = "create_torus"

    # ---- object editing / shape-compound (capabilities 45, 46, 47) -----
    COPY_OBJECT = "copy_object"
    DELETE_OBJECT = "delete_object"
    MIRROR_OBJECT = "mirror_object"
    OFFSET_3D = "offset_3d"
    SCALE_OBJECT = "scale_object"
    SHELL_OBJECT = "shell_object"
    EDIT_OBJECT = "edit_object"
    ROTATE_OBJECT = "rotate_object"
    COMMON_ALL = "common_all"
    EXPLODE_COMPOUND = "explode_compound"
    MAKE_COMPOUND = "make_compound"
    MAKE_FACE = "make_face"
    MAKE_WIRE = "make_wire"
    SECTION_SHAPE = "section_shape"
    SLICE_SHAPE = "slice_shape"
    #: TOOL FACTORY, 2026-09-26 -- capability 49 (PART_EXTRUDE_REVOLVE)'s
    #: `extrude_shape` half. Not a duplicate of PAD/T.REVOLVE: PAD requires a
    #: Sketcher sketch inside a PartDesign Body and extrudes only normal to
    #: the sketch plane; this extrudes ANY existing wire/face/shape object
    #: along an arbitrary XYZ direction vector, into a frozen Part::Feature.
    #: `revolve_shape` (this capability's other half) really was a duplicate
    #: of T.REVOLVE/revolution_sketch and was resolved-with-reason instead --
    #: see tools/tool_factory_state.json. This one is genuinely additive.
    EXTRUDE = "extrude"
    #: TOOL FACTORY, 2026-09-25 -- `fuse_all`, sibling of COMMON_ALL. Not a
    #: duplicate of BOOLEAN_UNION: that dispatches `boolean_operation`
    #: (operation="fuse") on exactly two named objects (`base`/`tool`) and
    #: produces boolean_operation's own frozen result; this fuses an
    #: arbitrary-length `object_names` list in one step through LIVE-RESULT
    #: (src/integrations/mcp_tools/live_result.py), producing a live
    #: Part::FeaturePython that re-fuses every recompute -- COMMON_ALL's own
    #: intersection counterpart, union instead.
    FUSE_ALL = "fuse_all"
    #: TOOL FACTORY, 2026-09-25 -- `part_loft`, sibling of FUSE_ALL/COMMON_ALL
    #: in the same LIVE-RESULT family (src/integrations/mcp_tools/
    #: live_result.py): blends an ordered list of profile wires/faces into
    #: one live Part::FeaturePython that re-lofts every recompute. Not a
    #: PartDesign::AdditiveLoft (a separate, sketch-in-Body feature this repo
    #: does not yet expose through this IR) -- this operates on any existing
    #: wire/face objects, frozen-solid or live, already in the document.
    PART_LOFT = "part_loft"
    #: TOOL FACTORY, 2026-09-25 -- `part_sweep`, sibling of PART_LOFT/FUSE_ALL/
    #: COMMON_ALL in the same LIVE-RESULT family (src/integrations/mcp_tools/
    #: live_result.py): sweeps one profile wire/face along a spine wire/path
    #: into a live Part::FeaturePython that re-sweeps every recompute. Not a
    #: PartDesign::AdditivePipe (a separate, sketch-in-Body feature this repo
    #: does not yet expose through this IR) -- this operates on any existing
    #: wire/face objects, frozen-solid or live, already in the document.
    PART_SWEEP = "part_sweep"
    #: TOOL FACTORY, 2026-09-25 -- `loft_sketches`, PROVEN (8/8, 2026-09-11)
    #: but never given a compiler path. Not a duplicate of PAD: PAD extrudes
    #: exactly one sketch normal to its own plane; LOFT blends N>=2 sketches
    #: that already live in the same PartDesign Body into one
    #: PartDesign::AdditiveLoft solid, none of them necessarily parallel.
    #: `part_loft` (Part-workbench, profiles outside a Body) is a distinct,
    #: still-not-plannable tool this does not cover.
    LOFT = "loft"
    #: TOOL FACTORY, 2026-09-25 -- `sweep_sketch`, PROVEN 8/8 (2026-09-11,
    #: PartDesign::AdditivePipe) but never given a compiler path. Not a
    #: duplicate of LOFT (blends N>=2 sketches already in a Body) or of
    #: PART_SWEEP (`part_sweep`, Part-workbench, an arbitrary wire/face
    #: outside any Body via LIVE-RESULT): SWEEP extrudes exactly one profile
    #: sketch along a second (spine/path) sketch, both already living in the
    #: same PartDesign Body, into one PartDesign::AdditivePipe solid.
    SWEEP = "sweep"
    #: TOOL FACTORY, 2026-09-26 -- `groove_sketch`, PROVEN 8/8 (2026-09-11,
    #: PartDesign::Groove, capability 48) but never given a compiler path
    #: before this. The subtractive counterpart to REVOLVE/`revolution_sketch`
    #: (capability 20): REVOLVE spins a sketch profile into new material,
    #: GROOVE spins a sketch profile and cuts that material away from
    #: whatever solid the Body's Tip already is.
    GROOVE = "groove"


class VerificationDecision(str, Enum):
    CONTINUE = "CONTINUE"
    RETRY_DIFFERENTLY = "RETRY_DIFFERENTLY"
    REPLAN_STAGE = "REPLAN_STAGE"
    ASK_USER = "ASK_USER"
    CAPABILITY_BLOCKED = "CAPABILITY_BLOCKED"
    ROLLBACK_STOP = "ROLLBACK_STOP"


@dataclass(frozen=True, slots=True)
class Unknown:
    identifier: str
    classification: UnknownClass
    question: str
    resolved: bool = False
    value: object | None = None


@dataclass(frozen=True, slots=True)
class DerivedEngineeringValue:
    identifier: str
    value: float
    unit: str
    formula: str
    assumptions: tuple[str, ...]
    source: str
    confidence: float


@dataclass(frozen=True, slots=True)
class EngineeringIntentSpecLite:
    schema_version: str
    intent_id: str
    artifact_name: str
    user_goal: str
    source_references: tuple[str, ...] = ()
    source_hashes: Mapping[str, str] = field(default_factory=dict)
    required_components: tuple[str, ...] = ()
    required_interfaces: tuple[str, ...] = ()
    mandatory_requirements: Mapping[str, object] = field(default_factory=dict)
    manufacturing_constraints: Mapping[str, object] = field(default_factory=dict)
    observed_facts: Mapping[str, object] = field(default_factory=dict)
    founder_locked_facts: Mapping[str, object] = field(default_factory=dict)
    derived_engineering_values: tuple[DerivedEngineeringValue, ...] = ()
    assumptions: tuple[str, ...] = ()
    unresolved_unknowns: tuple[Unknown, ...] = ()
    acceptance_assertions: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    current_gate_outcome: IntentGateOutcome = IntentGateOutcome.PASS
    provenance: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IntentGateResult:
    outcome: IntentGateOutcome
    spec: EngineeringIntentSpecLite
    reasons: tuple[str, ...]
    geometry_authorized: bool


@dataclass(frozen=True, slots=True)
class NormalizedValue:
    value_mm: float
    original_value: float
    original_unit: str
    conversion: str


@dataclass(frozen=True, slots=True)
class FeatureOperationIR:
    operation_id: str
    semantic_target_id: str
    operation_type: FeatureOperationType
    parameters: Mapping[str, object]
    units: Mapping[str, str]
    preconditions: tuple[str, ...]
    expected_postconditions: tuple[str, ...]
    rollback_checkpoint: str
    evidence_requirements: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FeatureProgramIR:
    schema_version: str
    intent_id: str
    document_id: str
    operations: tuple[FeatureOperationIR, ...]


@dataclass(frozen=True, slots=True)
class ObservedState:
    document_id: str
    object_tree: tuple[Mapping[str, object], ...]
    object_count: int
    body_count: int
    solid_count: int
    parameters: Mapping[str, object]
    sketches: Mapping[str, object]
    shape_valid: bool
    errors: tuple[str, ...]
    bounding_box: Mapping[str, float]
    volume_mm3: float | None
    dependencies: tuple[Mapping[str, str], ...]
    active_subject: str | None
    viewport_center_offset_pct: float | None
    viewport_occupancy_pct: float | None
    clipping: bool | None
    screenshot_path: str | None
    save_reopen_state: str


@dataclass(frozen=True, slots=True)
class AssertionResult:
    assertion_id: str
    layer: str
    passed: bool
    expected: object
    observed: object
    detail: str = ""
    #: Requirements this assertion verifies, by identifier.
    #:
    #: Empty means "not linked to a requirement", which is what every check
    #: that predates the Design Intent Graph produces - a render check or a
    #: recompute check answers "did the document survive", not "was the user
    #: served". Phase 4 asks the harder question, "did an unrelated
    #: requirement stop holding?", and that is only answerable once an
    #: assertion says which requirements it was about. Empty is honest here;
    #: a fabricated link would not be.
    requirement_ids: tuple[str, ...] = ()

    def concerns(self, requirement_id: str) -> bool:
        """Whether this assertion was checking the named requirement."""
        return requirement_id in self.requirement_ids


@dataclass(frozen=True, slots=True)
class VerificationResult:
    decision: VerificationDecision
    assertions: tuple[AssertionResult, ...]
    mandatory_passed: bool
    reason: str

    def assertions_for(self, requirement_id: str) -> tuple[AssertionResult, ...]:
        """Every assertion that was checking one requirement."""
        return tuple(item for item in self.assertions if item.concerns(requirement_id))

    def failed_requirement_ids(self) -> tuple[str, ...]:
        """Requirements with at least one failed assertion against them.

        Sorted and de-duplicated, so a caller comparing two runs compares the
        same thing twice rather than two orderings of it.
        """
        return tuple(
            sorted(
                {
                    requirement_id
                    for item in self.assertions
                    if not item.passed
                    for requirement_id in item.requirement_ids
                }
            )
        )

    def verified_requirement_ids(self) -> tuple[str, ...]:
        """Requirements whose every linked assertion passed.

        A requirement with no assertions at all is absent from this: nothing
        checked it, which is not the same as it holding.
        """
        checked: dict[str, bool] = {}
        for item in self.assertions:
            for requirement_id in item.requirement_ids:
                checked[requirement_id] = checked.get(requirement_id, True) and item.passed
        return tuple(sorted(key for key, passed in checked.items() if passed))
