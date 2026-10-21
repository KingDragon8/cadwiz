# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Controlled optional Blender and MeshLab process adapters."""

import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from json import dumps
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

from ai_freecad_core.workflow.mesh_component_swap import (
    ComponentIndexSelector,
    ComponentSelector,
)
from ai_freecad_core.workflow.semantic_mesh_edit import (
    SemanticMeshEditPlan,
    SemanticMeshTool,
)


class MeshOperation(StrEnum):
    INSPECT = "inspect"
    NORMALIZE = "normalize"
    REPAIR_NORMALS = "repair_normals"
    REMOVE_DEGENERATE = "remove_degenerate"
    SIMPLIFY = "simplify"


@dataclass(frozen=True, slots=True)
class ToolCapability:
    tool: str
    available: bool
    version: str | None
    path: Path | None
    explanation: str


@dataclass(frozen=True, slots=True)
class MeshToolRequest:
    operation: MeshOperation
    source: Path
    output_name: str
    timeout_seconds: int = 60
    maximum_bytes: int = 250_000_000


@dataclass(frozen=True, slots=True)
class MeshToolResult:
    succeeded: bool
    tool: str
    version: str | None
    output: Path | None
    evidence: tuple[str, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class MeshAdaptationRequest:
    source: Path
    destination: Path
    operations: tuple[MeshOperation, ...]
    scale_xyz: tuple[float, float, float] = (1.0, 1.0, 1.0)
    target_face_count: int | None = None
    maximum_hole_edges: int = 30
    maximum_bytes: int = 250_000_000


@dataclass(frozen=True, slots=True)
class MeshAdaptationReport:
    succeeded: bool
    source_hash: str
    output_hash: str | None
    vertices_before: int
    vertices_after: int
    faces_before: int
    faces_after: int
    bounds_before: tuple[float, float, float]
    bounds_after: tuple[float, float, float]
    operations_applied: tuple[str, ...]
    validation: tuple[str, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class SemanticToolchainReadiness:
    ready: bool
    required_tools: tuple[str, ...]
    available_tools: tuple[str, ...]
    missing_tools: tuple[str, ...]
    optional_tools: tuple[str, ...]
    explanation: str


def assess_semantic_toolchain(
    plan: SemanticMeshEditPlan,
    capabilities: tuple[ToolCapability, ...],
    *,
    freecad_available: bool,
) -> SemanticToolchainReadiness:
    """Verify the planned specialist chain before any protected mutation starts."""
    available = {item.tool for item in capabilities if item.available}
    if freecad_available:
        available.add(SemanticMeshTool.FREECAD.value)
    required = tuple(
        dict.fromkeys(
            stage.tool.value for stage in plan.tool_stages if stage.required
        )
    )
    optional = tuple(
        dict.fromkeys(
            stage.tool.value for stage in plan.tool_stages if not stage.required
        )
    )
    missing = tuple(item for item in required if item not in available)
    return SemanticToolchainReadiness(
        not missing,
        required,
        tuple(item for item in (*required, *optional) if item in available),
        missing,
        optional,
        (
            "Required semantic mesh specialists are ready."
            if not missing
            else "Protected semantic modification is blocked; missing: "
            + ", ".join(missing)
        ),
    )


Runner = Callable[..., subprocess.CompletedProcess[str]]


class ControlledMeshToolAdapter:
    def __init__(self, tool: str, executable: Path, runner: Runner = subprocess.run) -> None:
        if tool not in {"blender", "meshlab", "meshlabserver"}:
            raise ValueError("unsupported external mesh tool")
        self.tool, self.executable, self._runner = tool, executable, runner

    def detect(self) -> ToolCapability:
        argument = "--version" if self.tool == "blender" else "-v"
        try:
            result = self._runner(
                [str(self.executable), argument],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                shell=False,
            )
            text = (result.stdout or result.stderr).strip().splitlines()
            version = text[0][:120] if text else None
            available = result.returncode == 0 and bool(version)
            return ToolCapability(
                self.tool,
                available,
                version,
                self.executable if available else None,
                (
                    "Ready for controlled trials."
                    if available
                    else "Installed executable did not pass its functional version check."
                ),
            )
        except (OSError, subprocess.TimeoutExpired):
            return ToolCapability(
                self.tool,
                False,
                None,
                None,
                (
                    "This optional free, open-source tool is not available. "
                    "Continue without it or install it from its official website, then retry."
                ),
            )

    def run(self, request: MeshToolRequest) -> MeshToolResult:
        capability = self.detect()
        if not capability.available:
            return MeshToolResult(False, self.tool, None, None, (), capability.explanation)
        if not request.source.is_file() or request.source.stat().st_size > request.maximum_bytes:
            return MeshToolResult(
                False, self.tool, capability.version, None, (), "Input is missing or too large."
            )
        safe_name = Path(request.output_name).name
        if safe_name != request.output_name or not safe_name:
            return MeshToolResult(
                False, self.tool, capability.version, None, (), "Unsafe output name refused."
            )
        with TemporaryDirectory(prefix="ai-freecad-mesh-") as temporary:
            workspace = Path(temporary)
            copied = workspace / request.source.name
            copied.write_bytes(request.source.read_bytes())
            # M46 is a trial boundary: arbitrary scripts and plugin arguments are refused.
            return MeshToolResult(
                False,
                self.tool,
                capability.version,
                None,
                (
                    f"operation={request.operation.value}",
                    f"input_bytes={copied.stat().st_size}",
                    "original_preserved=true",
                ),
                "Capability detected; production geometry invocation remains disabled "
                "until corpus and native-output validation pass.",
            )


def discover_windows_mesh_tools() -> tuple[tuple[str, Path], ...]:
    """Find supported executables in known Windows locations without executing them."""
    candidates = (
        (
            "blender",
            Path("C:/Program Files/Blender Foundation/Blender 5.2/blender.exe"),
        ),
        ("meshlab", Path("C:/Program Files/VCG/MeshLab/meshlab.exe")),
        ("meshlabserver", Path("C:/Program Files/VCG/MeshLab/meshlabserver.exe")),
    )
    return tuple((name, path) for name, path in candidates if path.is_file())


def detect_pymeshlab() -> ToolCapability:
    """Functionally verify the managed PyMeshLab API, not merely its package name."""
    try:
        module = import_module("pymeshlab")
        mesh_set = module.MeshSet()
        if mesh_set.mesh_number() != 0:
            raise RuntimeError("new MeshSet is unexpectedly non-empty")
        package_version = version("pymeshlab")
        return ToolCapability(
            "pymeshlab",
            True,
            package_version,
            None,
            "Core mesh API is ready; optional plugin availability is validated per operation.",
        )
    except (ImportError, OSError, RuntimeError, PackageNotFoundError) as error:
        return ToolCapability(
            "pymeshlab",
            False,
            None,
            None,
            f"PyMeshLab core capability check failed: {type(error).__name__}.",
        )


class PyMeshLabAdaptationAdapter:
    """Perform an allowlisted repair/transform pipeline and independently reopen output."""

    _CLEANUP = (
        "meshing_remove_duplicate_vertices",
        "meshing_remove_duplicate_faces",
        "meshing_remove_unreferenced_vertices",
        "meshing_repair_non_manifold_edges",
        "meshing_repair_non_manifold_vertices",
        "meshing_re_orient_faces_coherently",
    )

    def adapt(self, request: MeshAdaptationRequest) -> MeshAdaptationReport:
        source_hash = _hash_file(request.source) if request.source.is_file() else ""
        empty = MeshAdaptationReport(
            False,
            source_hash,
            None,
            0,
            0,
            0,
            0,
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            (),
            (),
            "Adaptation refused.",
        )
        if not detect_pymeshlab().available:
            return empty
        if (
            not request.source.is_file()
            or request.source.stat().st_size > request.maximum_bytes
            or request.destination.exists()
            or request.source.resolve() == request.destination.resolve()
        ):
            return empty
        if any(value <= 0 or value > 100 for value in request.scale_xyz):
            return empty
        module = import_module("pymeshlab")
        with TemporaryDirectory(prefix="ai-freecad-pymeshlab-job-") as temporary:
            working = Path(temporary) / request.source.name
            output = Path(temporary) / request.destination.name
            shutil.copy2(request.source, working)
            mesh_set = module.MeshSet()
            try:
                mesh_set.load_new_mesh(str(working))
                before = mesh_set.current_mesh()
                before_vertices, before_faces = (
                    before.vertex_number(),
                    before.face_number(),
                )
                before_bounds = _mesh_bounds(before)
                applied: list[str] = []
                for operation in request.operations:
                    if operation is MeshOperation.REMOVE_DEGENERATE:
                        for filter_name in self._CLEANUP:
                            mesh_set.apply_filter(filter_name)
                        applied.append(operation.value)
                    elif operation is MeshOperation.REPAIR_NORMALS:
                        mesh_set.apply_filter("meshing_re_orient_faces_coherently")
                        applied.append(operation.value)
                    elif operation is MeshOperation.NORMALIZE:
                        x, y, z = request.scale_xyz
                        mesh_set.apply_filter(
                            "compute_matrix_from_scaling_or_normalization",
                            axisx=x,
                            axisy=y,
                            axisz=z,
                            uniformflag=False,
                            freeze=True,
                        )
                        applied.append(operation.value)
                    elif operation is MeshOperation.SIMPLIFY:
                        if request.target_face_count is None:
                            raise ValueError("simplification requires target face count")
                        mesh_set.apply_filter(
                            "meshing_decimation_quadric_edge_collapse",
                            targetfacenum=request.target_face_count,
                            preservenormal=True,
                            preservetopology=True,
                        )
                        applied.append(operation.value)
                    elif operation is MeshOperation.INSPECT:
                        applied.append(operation.value)
                    else:
                        raise ValueError(f"unsupported operation: {operation.value}")
                if (
                    request.maximum_hole_edges > 0
                    and MeshOperation.REMOVE_DEGENERATE in request.operations
                ):
                    mesh_set.apply_filter(
                        "meshing_close_holes", maxholesize=request.maximum_hole_edges
                    )
                    applied.append("close_holes")
                mesh_set.save_current_mesh(str(output))
                verify = module.MeshSet()
                verify.load_new_mesh(str(output))
                after = verify.current_mesh()
                after_bounds = _mesh_bounds(after)
                request.destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(output, request.destination)
            except Exception as error:
                return MeshAdaptationReport(
                    False,
                    source_hash,
                    None,
                    before_vertices if "before_vertices" in locals() else 0,
                    0,
                    before_faces if "before_faces" in locals() else 0,
                    0,
                    (before_bounds if "before_bounds" in locals() else (0.0, 0.0, 0.0)),
                    (0.0, 0.0, 0.0),
                    tuple(applied) if "applied" in locals() else (),
                    (),
                    f"PyMeshLab adaptation failed safely: {type(error).__name__}.",
                )
        original_preserved = _hash_file(request.source) == source_hash
        validation = (
            "output reopened successfully",
            "output contains faces" if after.face_number() > 0 else "output has no faces",
            "original preserved" if original_preserved else "original changed",
        )
        succeeded = after.face_number() > 0 and original_preserved
        return MeshAdaptationReport(
            succeeded,
            source_hash,
            _hash_file(request.destination),
            before_vertices,
            after.vertex_number(),
            before_faces,
            after.face_number(),
            before_bounds,
            after_bounds,
            tuple(applied),
            validation,
            "Validated PyMeshLab adaptation." if succeeded else "Validation failed.",
        )


_BLENDER_ADAPT_SCRIPT = """
import bpy, sys
source, output, sx, sy, sz = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
if source.lower().endswith(".stl"):
    bpy.ops.wm.stl_import(filepath=source)
elif source.lower().endswith(".obj"):
    bpy.ops.wm.obj_import(filepath=source)
else:
    raise RuntimeError("unsupported input format")
objects = [item for item in bpy.context.scene.objects if item.type == "MESH"]
if not objects:
    raise RuntimeError("no mesh objects imported")
for item in objects:
    item.scale = (float(sx), float(sy), float(sz))
    bpy.context.view_layer.objects.active = item
    item.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
if output.lower().endswith(".stl"):
    bpy.ops.wm.stl_export(filepath=output, export_selected_objects=False)
elif output.lower().endswith(".obj"):
    bpy.ops.wm.obj_export(filepath=output, export_selected_objects=False)
else:
    raise RuntimeError("unsupported output format")
print("AI_FREECAD_BLENDER_ADAPT_OK", len(objects))
"""


class BlenderAdaptationAdapter:
    """Run fixed import/scale/export logic in Blender's isolated process."""

    def __init__(self, executable: Path, runner: Runner = subprocess.run) -> None:
        self.executable, self._runner = executable, runner

    def adapt(self, request: MeshAdaptationRequest) -> MeshAdaptationReport:
        source_hash = _hash_file(request.source) if request.source.is_file() else ""
        refused = MeshAdaptationReport(
            False,
            source_hash,
            None,
            0,
            0,
            0,
            0,
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            (),
            (),
            "Blender adaptation refused.",
        )
        allowed_operations = {MeshOperation.INSPECT, MeshOperation.NORMALIZE}
        if (
            not request.source.is_file()
            or request.destination.exists()
            or request.source.suffix.casefold() not in {".stl", ".obj"}
            or request.destination.suffix.casefold() not in {".stl", ".obj"}
            or not set(request.operations) <= allowed_operations
            or any(value <= 0 or value > 100 for value in request.scale_xyz)
        ):
            return refused
        before = _inspect_with_pymeshlab(request.source)
        with TemporaryDirectory(prefix="ai-freecad-blender-job-") as temporary:
            output = Path(temporary) / request.destination.name
            command = [
                str(self.executable),
                "--background",
                "--factory-startup",
                "--python-expr",
                _BLENDER_ADAPT_SCRIPT,
                "--",
                str(request.source.resolve()),
                str(output),
                *(str(value) for value in request.scale_xyz),
            ]
            try:
                result = self._runner(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                    shell=False,
                )
                if result.returncode or "AI_FREECAD_BLENDER_ADAPT_OK" not in result.stdout:
                    return refused
                after = _inspect_with_pymeshlab(output)
                request.destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(output, request.destination)
            except (OSError, subprocess.TimeoutExpired, ValueError):
                return refused
        preserved = _hash_file(request.source) == source_hash
        succeeded = after[1] > 0 and preserved
        return MeshAdaptationReport(
            succeeded,
            source_hash,
            _hash_file(request.destination) if succeeded else None,
            before[0],
            after[0],
            before[1],
            after[1],
            before[2],
            after[2],
            tuple(item.value for item in request.operations),
            (
                "output reopened successfully",
                "original preserved" if preserved else "original changed",
                "fixed internal Blender script only",
            ),
            "Validated Blender adaptation." if succeeded else "Blender validation failed.",
        )


def _hash_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _mesh_bounds(mesh: Any) -> tuple[float, float, float]:
    matrix = mesh.vertex_matrix()
    spans = matrix.max(axis=0) - matrix.min(axis=0)
    return (float(spans[0]), float(spans[1]), float(spans[2]))


def _inspect_with_pymeshlab(
    path: Path,
) -> tuple[int, int, tuple[float, float, float]]:
    module = import_module("pymeshlab")
    mesh_set = module.MeshSet()
    mesh_set.load_new_mesh(str(path))
    mesh = mesh_set.current_mesh()
    return mesh.vertex_number(), mesh.face_number(), _mesh_bounds(mesh)


@dataclass(frozen=True, slots=True)
class MeshComponentSwapRequest:
    """Remove a selected target, optionally attach a replacement mesh.

    ``replacement_source=None`` makes "remove only" a first-class call
    rather than a special case. The replacement, when given, is placed as a
    separate solid at its own authored position — this does not attempt a
    CSG boolean union (Phase 2 concern; pymeshlab's boolean plugin was
    confirmed non-functional in this environment).
    """

    source: Path
    destination: Path
    selector: ComponentSelector
    replacement_source: Path | None = None
    transition_fill_holes: bool = True
    maximum_bytes: int = 250_000_000


@dataclass(frozen=True, slots=True)
class MeshComponentSwapReport:
    succeeded: bool
    source_hash: str
    output_hash: str | None
    faces_before: int
    faces_after: int
    faces_removed: int
    replacement_faces: int
    bounds_before: tuple[float, float, float]
    bounds_after: tuple[float, float, float]
    validation: tuple[str, ...]
    explanation: str


_BLENDER_SWAP_SCRIPT = """
import bmesh, bpy, json, sys
from mathutils import Vector

source, replacement, output, params_path = sys.argv[sys.argv.index("--") + 1:]
with open(params_path, "r", encoding="utf-8") as handle:
    params = json.load(handle)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=source)
source_objects = [item for item in bpy.context.scene.objects if item.type == "MESH"]
if not source_objects:
    raise RuntimeError("no mesh objects imported")

if params["kind"] == "component_index":
    bpy.ops.object.select_all(action="DESELECT")
    for item in source_objects:
        item.select_set(True)
    bpy.context.view_layer.objects.active = source_objects[0]
    bpy.ops.mesh.separate(type="LOOSE")
    parts = sorted(
        (item for item in bpy.context.scene.objects if item.type == "MESH"),
        key=lambda item: item.name,
    )
    index = int(params["component_index"])
    if index >= len(parts):
        raise RuntimeError(
            f"component index {index} does not exist ({len(parts)} parts found)"
        )
    target = parts[index]
    faces_removed = len(target.data.polygons)
    bpy.data.objects.remove(target, do_unlink=True)
else:
    target_object = max(source_objects, key=lambda item: len(item.data.polygons))
    bpy.context.view_layer.objects.active = target_object
    target_object.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    mesh = bmesh.from_edit_mesh(target_object.data)
    mesh.faces.ensure_lookup_table()
    center = Vector(params["center"])
    axis = Vector(params["axis"]).normalized()
    radial_radius = float(params["radial_radius_mm"])
    axial_half_length = float(params["axial_half_length_mm"])
    selected = []
    for face in mesh.faces:
        offset = face.calc_center_median() - center
        axial = offset.dot(axis)
        radial = (offset - axial * axis).length
        if abs(axial) <= axial_half_length and radial <= radial_radius:
            face.select_set(True)
            selected.append(face)
    if not selected:
        raise RuntimeError("geometric region selector matched zero faces")
    faces_removed = len(selected)
    bmesh.update_edit_mesh(target_object.data)
    bpy.ops.mesh.delete(type="FACE")
    if params.get("fill_holes", True):
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.mesh.select_non_manifold()
        bpy.ops.mesh.edge_face_add()
    bpy.ops.object.mode_set(mode="OBJECT")

replacement_faces = 0
if replacement:
    existing_names = {item.name for item in bpy.context.scene.objects}
    bpy.ops.wm.stl_import(filepath=replacement)
    for item in bpy.context.scene.objects:
        if item.type == "MESH" and item.name not in existing_names:
            replacement_faces += len(item.data.polygons)

bpy.ops.object.select_all(action="DESELECT")
remaining = [item for item in bpy.context.scene.objects if item.type == "MESH"]
if not remaining:
    raise RuntimeError("no mesh objects remain to export")
for item in remaining:
    item.select_set(True)
bpy.context.view_layer.objects.active = remaining[0]
bpy.ops.wm.stl_export(filepath=output, export_selected_objects=True)
print("AI_FREECAD_BLENDER_SWAP_OK", faces_removed, replacement_faces)
"""


def _selector_payload(request: MeshComponentSwapRequest) -> dict[str, Any]:
    selector = request.selector
    if isinstance(selector, ComponentIndexSelector):
        return {"kind": "component_index", "component_index": selector.component_index}
    return {
        "kind": "geometric_region",
        "center": list(selector.center),
        "axis": list(selector.axis),
        "radial_radius_mm": selector.radial_radius_mm,
        "axial_half_length_mm": selector.axial_half_length_mm,
        "fill_holes": request.transition_fill_holes,
    }


class BlenderComponentSwapAdapter:
    """Remove a selected target region/component in Blender's isolated process.

    Generalizes the geometry technique proven manually in
    ``scripts/replace_mouth_object_with_bone.py`` (bmesh region-based face
    deletion, hole-fill, place a replacement) with parameters instead of
    mesh-specific hardcoded constants. Does not attempt a CSG boolean union;
    the replacement, when given, is exported as a separate solid — matching
    what was actually proven, not a promised-but-unverified capability.
    """

    def __init__(self, executable: Path, runner: Runner = subprocess.run) -> None:
        self.executable, self._runner = executable, runner

    def swap(self, request: MeshComponentSwapRequest) -> MeshComponentSwapReport:
        source_hash = _hash_file(request.source) if request.source.is_file() else ""
        refused = MeshComponentSwapReport(
            False, source_hash, None, 0, 0, 0, 0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (),
            "Component swap refused.",
        )
        if (
            not request.source.is_file()
            or request.destination.exists()
            or request.source.suffix.casefold() != ".stl"
            or request.destination.suffix.casefold() != ".stl"
            or request.source.stat().st_size > request.maximum_bytes
            or (
                request.replacement_source is not None
                and not request.replacement_source.is_file()
            )
        ):
            return refused
        before = _inspect_with_pymeshlab(request.source)
        with TemporaryDirectory(prefix="ai-freecad-blender-swap-") as temporary:
            workspace = Path(temporary)
            output = workspace / request.destination.name
            params_path = workspace / "selector.json"
            params_path.write_text(dumps(_selector_payload(request)), encoding="utf-8")
            command = [
                str(self.executable),
                "--background",
                "--factory-startup",
                "--python-expr",
                _BLENDER_SWAP_SCRIPT,
                "--",
                str(request.source.resolve()),
                str(request.replacement_source.resolve())
                if request.replacement_source
                else "",
                str(output),
                str(params_path),
            ]
            try:
                result = self._runner(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    check=False,
                    shell=False,
                )
                match = re.search(r"AI_FREECAD_BLENDER_SWAP_OK (\d+) (\d+)", result.stdout)
                if result.returncode or match is None:
                    return refused
                faces_removed, replacement_faces = int(match.group(1)), int(match.group(2))
                after = _inspect_with_pymeshlab(output)
                request.destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(output, request.destination)
            except (OSError, subprocess.TimeoutExpired, ValueError):
                return refused
        preserved = _hash_file(request.source) == source_hash
        succeeded = after[1] > 0 and preserved
        return MeshComponentSwapReport(
            succeeded,
            source_hash,
            _hash_file(request.destination) if succeeded else None,
            before[1],
            after[1],
            faces_removed,
            replacement_faces,
            before[2],
            after[2],
            (
                "output reopened successfully",
                "original preserved" if preserved else "original changed",
                f"faces_removed={faces_removed}",
                f"replacement_faces={replacement_faces}",
            ),
            "Validated component swap." if succeeded else "Component swap validation failed.",
        )


@dataclass(frozen=True, slots=True)
class MeshBooleanUnionRequest:
    """Merge two originally-separate solids into one via Blender's EXACT
    boolean solver. Only ``UNION`` is supported — the go/no-go spike
    (scripts/spike_blender_boolean_union.py) only proved union, not
    difference/intersect, and PyMeshLab has no working fallback in this
    environment (its boolean plugin fails to load).
    """

    source_a: Path
    source_b: Path
    destination: Path
    maximum_bytes: int = 250_000_000


@dataclass(frozen=True, slots=True)
class MeshBooleanUnionReport:
    succeeded: bool
    source_a_hash: str
    source_b_hash: str
    output_hash: str | None
    faces_before_a: int
    faces_before_b: int
    faces_after: int
    connected_components_after: int | None
    watertight_after: bool | None
    bounds_after: tuple[float, float, float]
    validation: tuple[str, ...]
    explanation: str


_BLENDER_UNION_SCRIPT = """
import bpy, sys
source_a, source_b, output = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=source_a)
a = [item for item in bpy.context.scene.objects if item.type == "MESH"][0]
bpy.ops.wm.stl_import(filepath=source_b)
b = [item for item in bpy.context.scene.objects if item.type == "MESH" and item is not a][0]
bpy.context.view_layer.objects.active = a
modifier = a.modifiers.new(name="Union", type="BOOLEAN")
modifier.operation = "UNION"
modifier.solver = "EXACT"
modifier.object = b
bpy.ops.object.modifier_apply(modifier=modifier.name)
bpy.data.objects.remove(b, do_unlink=True)
a.select_set(True)
bpy.context.view_layer.objects.active = a
bpy.ops.wm.stl_export(filepath=output, export_selected_objects=True)
print("AI_FREECAD_BLENDER_UNION_OK", len(a.data.polygons))
"""


class BlenderBooleanUnionAdapter:
    """Merge two originally-separate solids into one watertight solid.

    Proven feasible only after a real go/no-go spike (pymeshlab's boolean
    plugin fails to load in this environment; Blender's EXACT solver was the
    only candidate and was independently verified against both a simple and
    a denser overlapping-geometry case before this adapter was written).
    """

    def __init__(self, executable: Path, runner: Runner = subprocess.run) -> None:
        self.executable, self._runner = executable, runner

    def union(self, request: MeshBooleanUnionRequest) -> MeshBooleanUnionReport:
        hash_a = _hash_file(request.source_a) if request.source_a.is_file() else ""
        hash_b = _hash_file(request.source_b) if request.source_b.is_file() else ""
        refused = MeshBooleanUnionReport(
            False, hash_a, hash_b, None, 0, 0, 0, None, None, (0.0, 0.0, 0.0), (),
            "Boolean union refused.",
        )
        if (
            not request.source_a.is_file()
            or not request.source_b.is_file()
            or request.destination.exists()
            or request.source_a.suffix.casefold() != ".stl"
            or request.source_b.suffix.casefold() != ".stl"
            or request.destination.suffix.casefold() != ".stl"
            or request.source_a.stat().st_size > request.maximum_bytes
            or request.source_b.stat().st_size > request.maximum_bytes
        ):
            return refused
        before_a = _inspect_with_pymeshlab(request.source_a)
        before_b = _inspect_with_pymeshlab(request.source_b)
        with TemporaryDirectory(prefix="ai-freecad-blender-union-") as temporary:
            output = Path(temporary) / request.destination.name
            command = [
                str(self.executable),
                "--background",
                "--factory-startup",
                "--python-expr",
                _BLENDER_UNION_SCRIPT,
                "--",
                str(request.source_a.resolve()),
                str(request.source_b.resolve()),
                str(output),
            ]
            try:
                result = self._runner(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    check=False,
                    shell=False,
                )
                if result.returncode or "AI_FREECAD_BLENDER_UNION_OK" not in result.stdout:
                    return refused
                connected_components, watertight, faces_after, after_bounds = (
                    _independent_manifold_check(output)
                )
                request.destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(output, request.destination)
            except (OSError, subprocess.TimeoutExpired, ValueError):
                return refused
        preserved_a = _hash_file(request.source_a) == hash_a
        preserved_b = _hash_file(request.source_b) == hash_b
        succeeded = (
            faces_after > 0
            and connected_components == 1
            and bool(watertight)
            and preserved_a
            and preserved_b
        )
        return MeshBooleanUnionReport(
            succeeded,
            hash_a,
            hash_b,
            _hash_file(request.destination) if succeeded else None,
            before_a[1],
            before_b[1],
            faces_after,
            connected_components,
            watertight,
            after_bounds,
            (
                "output reopened successfully",
                "both sources preserved" if preserved_a and preserved_b else "a source changed",
                f"connected_components={connected_components}",
                f"watertight={watertight}",
            ),
            "Validated boolean union." if succeeded else "Boolean union validation failed.",
        )


def _independent_manifold_check(path: Path) -> tuple[int, bool, int, tuple[float, float, float]]:
    """Reopen with pymeshlab and independently measure manifoldness.

    Deliberately re-checks manifoldness rather than trusting Blender's own
    report of success — the same independent-reopen principle every other
    adapter in this module already applies.
    """
    module = import_module("pymeshlab")
    mesh_set = module.MeshSet()
    mesh_set.load_new_mesh(str(path))
    mesh = mesh_set.current_mesh()
    measures = mesh_set.get_topological_measures()
    watertight = bool(measures["is_mesh_two_manifold"]) and measures["number_holes"] == 0
    return (
        int(measures["connected_components_number"]),
        watertight,
        mesh.face_number(),
        _mesh_bounds(mesh),
    )
