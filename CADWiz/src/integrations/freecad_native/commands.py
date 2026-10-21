# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Small structured FreeCAD command allowlist behind one thread dispatcher."""

from __future__ import annotations

import re
from collections.abc import Callable
from importlib import import_module
from typing import Any

from ai_freecad_core.execution.contracts import Command, PrivilegedPythonCommand, StructuredCommand
from ai_freecad_core.production_foundation.contracts import FeatureOperationType

from .dispatch import FreeCADGuiThreadDispatcher


class FreeCADStructuredCommandAdapter:
    """Translate approved structured commands into a narrow native allowlist."""

    def __init__(
        self,
        dispatcher: FreeCADGuiThreadDispatcher | None = None,
        app_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._dispatcher = dispatcher or FreeCADGuiThreadDispatcher()
        self._app_provider = app_provider or (lambda: import_module("FreeCAD"))
        self._handlers = {
            "create_parametric_replacement_part": self._create_parametric_replacement_part,
            "create_parametric_flanged_tube_bracket": (
                self._create_parametric_flanged_tube_bracket
            ),
            "create_primitive": self._create_primitive,
            "create_parametric_primitive": self._create_parametric_primitive,
            "create_boolean_cut": self._create_boolean_cut,
            "create_boolean_union": self._create_boolean_union,
            "create_fillet": self._create_fillet,
            "create_parameter_sheet": self._create_parameter_sheet,
            "set_spreadsheet_cell": self._set_spreadsheet_cell,
            "set_expression": self._set_expression,
            "create_axisymmetric_profile": self._create_axisymmetric_profile,
            "create_revolution": self._create_revolution,
            "create_helix": self._create_helix,
            "create_sweep": self._create_sweep,
            "create_loft": self._create_loft,
            "create_thickness": self._create_thickness,
            "create_assembly": self._create_assembly,
            "insert_assembly_component": self._insert_assembly_component,
            "create_screw_joint": self._create_screw_joint,
            "create_multi_start_helix": self._create_multi_start_helix,
            "set_placement": self._set_placement,
            "set_property": self._set_property,
            "recompute": self._recompute,
            "save_version": self._save_version,
        }
        for operation in FeatureOperationType:
            self._handlers[f"production_feature_{operation.value}"] = self._production_feature

    def _create_parametric_flanged_tube_bracket(
        self, command: StructuredCommand
    ) -> tuple[str, ...]:
        """Build the unattended Wizard benchmark through the protected adapter."""
        builder = import_module(
            "integrations.freecad_native.wizard_bracket"
        ).build_parametric_flanged_tube_bracket
        return builder(self._document(command), self._arguments(command))

    def _create_parametric_replacement_part(self, command: StructuredCommand) -> tuple[str, ...]:
        builder = import_module(
            "integrations.freecad_native.replacement_parts"
        ).build_parametric_replacement_part
        return builder(self._document(command), self._arguments(command))

    def execute(self, command: Command) -> tuple[str, ...]:
        """Dispatch one structured command; privileged Python is never accepted."""
        if isinstance(command, PrivilegedPythonCommand):
            raise PermissionError("privileged Python has no native handler")
        handler = self._handlers.get(command.capability)
        if handler is None:
            raise ValueError(f"Unsupported structured capability: {command.capability}")
        return self._dispatcher.dispatch(lambda: handler(command))

    def _production_feature(self, command: StructuredCommand) -> tuple[str, ...]:
        """Route typed feature IR through one governed native implementation."""
        executor = import_module("integrations.freecad_native.production_features").execute
        return executor(self._app_provider(), command)

    def _document(self, command: StructuredCommand) -> Any:
        app = self._app_provider()
        name = command.target.document_id.removeprefix("freecad:")
        document = app.getDocument(name)
        if document is None:
            raise LookupError(f"Document not found: {command.target.document_id}")
        return document

    @staticmethod
    def _arguments(command: StructuredCommand) -> dict[str, object]:
        return {item.name: item.value for item in command.arguments}

    def _create_primitive(self, command: StructuredCommand) -> tuple[str, ...]:
        document = self._document(command)
        arguments = self._arguments(command)
        primitive = str(arguments.get("primitive_type", ""))
        allowed = {"box": "Part::Box", "cylinder": "Part::Cylinder", "sphere": "Part::Sphere"}
        type_id = allowed.get(primitive.casefold())
        if type_id is None:
            raise ValueError(f"Unsupported primitive type: {primitive}")
        name = str(arguments.get("name", primitive.title()))
        native = document.addObject(type_id, name)
        return (f"{command.target.document_id}:{native.Name}",)

    def _create_parametric_primitive(self, command: StructuredCommand) -> tuple[str, ...]:
        document = self._document(command)
        arguments = self._arguments(command)
        primitive = str(arguments.get("primitive_type", "")).casefold()
        if primitive not in {"box", "cylinder"}:
            raise ValueError(f"Unsupported parametric primitive type: {primitive}")
        fields = ("length", "width", "height") if primitive == "box" else ("radius", "height")
        dimensions = {}
        for name in fields:
            value = arguments.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"Parametric primitive {name} must be a positive number")
            dimensions[name] = float(value)
        name = str(arguments.get("name", "ParametricSolid"))
        native = document.addObject("Part::Box" if primitive == "box" else "Part::Cylinder", name)
        if primitive == "box":
            native.Length = dimensions["length"]
            native.Width = dimensions["width"]
            native.Height = dimensions["height"]
        else:
            native.Radius = dimensions["radius"]
            native.Height = dimensions["height"]
        document.recompute()
        errors = [
            state
            for item in document.Objects
            for state in item.State
            if state not in {"Touched", "Up-to-date"}
        ]
        if errors or native.Shape.isNull() or not native.Shape.isValid():
            raise RuntimeError("Parametric primitive failed recompute or shape validation")
        return (f"{command.target.document_id}:{native.Name}",)

    def _create_parameter_sheet(self, command: StructuredCommand) -> tuple[str, ...]:
        """Create one native FreeCAD spreadsheet for editable design parameters."""
        document = self._document(command)
        arguments = self._arguments(command)
        name = str(arguments.get("name", "DesignParameters"))
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError("Spreadsheet name must be a valid FreeCAD object identifier")
        if document.getObject(name) is not None:
            raise ValueError(f"Spreadsheet object already exists: {name}")
        native = document.addObject("Spreadsheet::Sheet", name)
        document.recompute()
        return (f"{command.target.document_id}:{native.Name}",)

    def _set_spreadsheet_cell(self, command: StructuredCommand) -> tuple[str, ...]:
        """Set a unit-bearing value or FreeCAD formula and optional stable alias."""
        document = self._document(command)
        arguments = self._arguments(command)
        sheet_name = str(arguments.get("sheet_name", ""))
        cell = str(arguments.get("cell", "")).upper()
        value = arguments.get("value")
        alias = str(arguments.get("alias", ""))
        if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]*", cell):
            raise ValueError("Spreadsheet cell must use A1 notation")
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError("Spreadsheet value must be text or numeric")
        text = str(value)
        if not text.strip() or len(text) > 512 or "\n" in text or "\r" in text:
            raise ValueError("Spreadsheet value is empty or too long")
        if alias and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
            raise ValueError("Spreadsheet alias must be a valid expression identifier")
        sheet = document.getObject(sheet_name)
        if sheet is None or getattr(sheet, "TypeId", "") != "Spreadsheet::Sheet":
            raise LookupError(f"Spreadsheet was not found: {sheet_name}")
        sheet.set(cell, text)
        if alias:
            sheet.setAlias(cell, alias)
        document.recompute()
        return (f"{command.target.document_id}:{sheet.Name}",)

    def _set_expression(self, command: StructuredCommand) -> tuple[str, ...]:
        """Bind an editable native property to a unit-aware FreeCAD expression."""
        document = self._document(command)
        arguments = self._arguments(command)
        object_name = str(arguments.get("object_name", ""))
        property_name = str(arguments.get("property_name", ""))
        expression = str(arguments.get("expression", ""))
        native = document.getObject(object_name)
        if native is None:
            raise LookupError(f"Expression object was not found: {object_name}")
        if property_name not in native.PropertiesList:
            raise AttributeError(f"Expression property was not found: {property_name}")
        if not expression.strip() or len(expression) > 512 or "\n" in expression:
            raise ValueError("Expression is empty or too long")
        native.setExpression(property_name, expression)
        self._validate_recompute(document, native, "Expression binding")
        return (f"{command.target.document_id}:{native.Name}",)

    def _create_axisymmetric_profile(self, command: StructuredCommand) -> tuple[str, ...]:
        """Create a closed R/Z profile consumed by a linked native revolution."""
        document = self._document(command)
        arguments = self._arguments(command)
        name = str(arguments.get("name", "RevolveProfile"))
        point_text = str(arguments.get("points", ""))
        points: list[tuple[float, float]] = []
        try:
            for pair in point_text.split(";"):
                radius, axial = (float(item.strip()) for item in pair.split(","))
                if radius < 0:
                    raise ValueError
                points.append((radius, axial))
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Profile points must be semicolon-separated non-negative R,Z pairs"
            ) from error
        if len(points) < 3 or len(set(points)) < 3:
            raise ValueError("Axisymmetric profile requires at least three distinct points")
        if points[0] != points[-1]:
            points.append(points[0])
        app = self._app_provider()
        part = import_module("Part")
        native = document.addObject("Part::Feature", name)
        native.addProperty("App::PropertyString", "ProfilePoints", "Parameters")
        native.ProfilePoints = ";".join(f"{r:g},{z:g}" for r, z in points)
        native.Shape = part.makePolygon(tuple(app.Vector(r, 0.0, z) for r, z in points))
        self._validate_recompute(document, native, "Axisymmetric profile")
        return (f"{command.target.document_id}:{native.Name}",)

    def _create_revolution(self, command: StructuredCommand) -> tuple[str, ...]:
        """Revolve a linked closed profile around the global optical/Z axis."""
        document = self._document(command)
        arguments = self._arguments(command)
        source_name = str(arguments.get("source_name", ""))
        angle = arguments.get("angle", 360.0)
        if isinstance(angle, bool) or not isinstance(angle, (int, float)) or not 0 < angle <= 360:
            raise ValueError("Revolution angle must be in the range (0, 360]")
        source = document.getObject(source_name)
        if source is None:
            raise LookupError(f"Revolution profile was not found: {source_name}")
        name = str(arguments.get("name", f"{source_name}_Revolution"))
        app = self._app_provider()
        native = document.addObject("Part::Revolution", name)
        native.Source = source
        native.Axis = app.Vector(0.0, 0.0, 1.0)
        native.Angle = float(angle)
        native.Solid = bool(arguments.get("solid", True))
        self._validate_recompute(document, native, "Revolution")
        return (f"{command.target.document_id}:{native.Name}",)

    def _create_helix(self, command: StructuredCommand) -> tuple[str, ...]:
        """Create FreeCAD's native editable helix for threads and motion paths."""
        document = self._document(command)
        arguments = self._arguments(command)
        values: dict[str, float] = {}
        for field in ("pitch", "height", "radius"):
            value = arguments.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"Helix {field} must be a positive number")
            values[field] = float(value)
        name = str(arguments.get("name", "Helix"))
        native = document.addObject("Part::Helix", name)
        native.Pitch = values["pitch"]
        native.Height = values["height"]
        native.Radius = values["radius"]
        angle = arguments.get("cone_angle", 0.0)
        if isinstance(angle, bool) or not isinstance(angle, (int, float)):
            raise ValueError("Helix cone angle must be numeric")
        native.Angle = float(angle)
        self._validate_recompute(document, native, "Helix")
        return (f"{command.target.document_id}:{native.Name}",)

    def _create_sweep(self, command: StructuredCommand) -> tuple[str, ...]:
        """Create a linked native sweep from existing section and spine objects."""
        document = self._document(command)
        arguments = self._arguments(command)
        section_names = tuple(
            item.strip()
            for item in str(arguments.get("section_names", "")).split(",")
            if item.strip()
        )
        spine_name = str(arguments.get("spine_name", ""))
        if not section_names:
            raise ValueError("Sweep requires at least one section object")
        sections = tuple(document.getObject(name) for name in section_names)
        spine = document.getObject(spine_name)
        if any(item is None for item in sections) or spine is None:
            raise LookupError("Sweep section or spine object was not found")
        name = str(arguments.get("name", "Sweep"))
        native = document.addObject("Part::Sweep", name)
        native.Sections = sections
        native.Spine = (spine, ("Edge1",))
        native.Solid = bool(arguments.get("solid", True))
        native.Frenet = bool(arguments.get("frenet", True))
        self._validate_recompute(document, native, "Sweep")
        return (f"{command.target.document_id}:{native.Name}",)

    def _create_loft(self, command: StructuredCommand) -> tuple[str, ...]:
        """Create a linked native loft between two or more existing sections.

        Added after the Three User Test found `ModelingStrategy.LOFT` declared
        with no executor behind it — a planner could route a user to lofting and
        then fail, which is the same shape of defect as a route with no adapter.
        """
        document = self._document(command)
        arguments = self._arguments(command)
        section_names = tuple(
            item.strip()
            for item in str(arguments.get("section_names", "")).split(",")
            if item.strip()
        )
        if len(section_names) < 2:
            raise ValueError(
                "Loft requires at least two sections to blend between; "
                f"received {len(section_names)}"
            )
        sections = tuple(document.getObject(name) for name in section_names)
        missing = tuple(
            name for name, item in zip(section_names, sections, strict=False) if item is None
        )
        if missing:
            raise LookupError(f"Loft section object was not found: {', '.join(missing)}")
        name = str(arguments.get("name", "Loft"))
        native = document.addObject("Part::Loft", name)
        native.Sections = list(sections)
        native.Solid = bool(arguments.get("solid", True))
        native.Ruled = bool(arguments.get("ruled", False))
        native.Closed = bool(arguments.get("closed", False))
        self._validate_recompute(document, native, "Loft")
        return (f"{command.target.document_id}:{native.Name}",)

    def _create_thickness(self, command: StructuredCommand) -> tuple[str, ...]:
        """Hollow a solid to a wall thickness, opening the named faces.

        Added after the Three User Test found `ModelingStrategy.SHELL_THICKNESS`
        and `OperationKind.THICKEN` declared with no executor. Every enclosure
        needs this.

        A zero thickness is refused rather than passed through: FreeCAD accepts
        it and produces a degenerate shape that fails later, far from the cause.
        """
        document = self._document(command)
        arguments = self._arguments(command)
        source_name = str(arguments.get("source_name", ""))
        source = document.getObject(source_name)
        if source is None:
            raise LookupError(f"Thickness source object was not found: {source_name}")
        raw_thickness = arguments.get("thickness_mm", 0.0)
        if not isinstance(raw_thickness, (int, float, str)):
            raise TypeError("thickness_mm must be a number")
        thickness = float(raw_thickness)
        if thickness == 0.0:
            raise ValueError(
                "Wall thickness cannot be zero; give a positive value to hollow "
                "inwards or a negative value to grow outwards"
            )
        face_names = tuple(
            item.strip() for item in str(arguments.get("face_names", "")).split(",") if item.strip()
        )
        if not face_names:
            raise ValueError(
                "Thickness requires at least one face to open; hollowing a solid "
                "with no opening would produce a sealed void the user cannot see"
            )
        name = str(arguments.get("name", "Thickness"))
        native = document.addObject("Part::Thickness", name)
        native.Faces = (source, face_names)
        native.Value = thickness
        native.Mode = str(arguments.get("mode", "Skin"))
        native.Join = str(arguments.get("join", "Arc"))
        self._validate_recompute(document, native, "Thickness")
        return (f"{command.target.document_id}:{native.Name}",)

    def _create_assembly(self, command: StructuredCommand) -> tuple[str, ...]:
        """Create FreeCAD's native assembly container and required joint group."""
        document = self._document(command)
        arguments = self._arguments(command)
        name = str(arguments.get("name", "Assembly"))
        if document.getObject(name) is not None:
            raise ValueError(f"Assembly object already exists: {name}")
        assembly = document.addObject("Assembly::AssemblyObject", name)
        joints = assembly.newObject("Assembly::JointGroup", f"{name}_Joints")
        document.recompute()
        return (
            f"{command.target.document_id}:{assembly.Name}",
            f"{command.target.document_id}:{joints.Name}",
        )

    def _insert_assembly_component(self, command: StructuredCommand) -> tuple[str, ...]:
        """Insert a linked component so source feature geometry stays independently editable."""
        document = self._document(command)
        arguments = self._arguments(command)
        assembly_name = str(arguments.get("assembly_name", ""))
        source_name = str(arguments.get("source_name", ""))
        assembly = document.getObject(assembly_name)
        source = document.getObject(source_name)
        if assembly is None or getattr(assembly, "TypeId", "") != "Assembly::AssemblyObject":
            raise LookupError(f"Assembly was not found: {assembly_name}")
        if source is None:
            raise LookupError(f"Assembly component source was not found: {source_name}")
        name = str(arguments.get("name", f"{source_name}_Link"))
        native = assembly.newObject("App::Link", name)
        native.LinkedObject = source
        document.recompute()
        if native.LinkedObject is not source:
            raise RuntimeError("Assembly component link did not retain its source")
        return (f"{command.target.document_id}:{native.Name}",)

    def _create_screw_joint(self, command: StructuredCommand) -> tuple[str, ...]:
        """Create a solved native screw joint coupling rotation and axial motion."""
        document = self._document(command)
        arguments = self._arguments(command)
        assembly_name = str(arguments.get("assembly_name", ""))
        first_name = str(arguments.get("first_component_name", ""))
        second_name = str(arguments.get("second_component_name", ""))
        pitch = arguments.get("pitch")
        if isinstance(pitch, bool) or not isinstance(pitch, (int, float)) or pitch <= 0:
            raise ValueError("Screw-joint pitch must be a positive number")
        assembly = document.getObject(assembly_name)
        first = document.getObject(first_name)
        second = document.getObject(second_name)
        if assembly is None or getattr(assembly, "TypeId", "") != "Assembly::AssemblyObject":
            raise LookupError(f"Assembly was not found: {assembly_name}")
        if first is None or second is None or first is second:
            raise LookupError("Screw joint requires two distinct existing components")
        joint_group = next(
            (
                item
                for item in getattr(assembly, "Group", ())
                if getattr(item, "TypeId", "") == "Assembly::JointGroup"
            ),
            None,
        )
        if joint_group is None:
            raise RuntimeError("Assembly does not contain its required joint group")
        name = str(arguments.get("name", "ScrewJoint"))
        joint = joint_group.newObject("App::FeaturePython", name)
        joint_module = import_module("JointObject")
        joint_module.Joint(joint, 10)
        joint.Distance = float(pitch)
        first_element = str(arguments.get("first_element", "Face3"))
        second_element = str(arguments.get("second_element", "Face3"))
        first_vertex = str(arguments.get("first_vertex", ""))
        second_vertex = str(arguments.get("second_vertex", ""))
        joint.Proxy.setJointConnectors(
            joint,
            [
                [first, [first_element, first_vertex]],
                [second, [second_element, second_vertex]],
            ],
        )
        document.recompute()
        if joint.JointType != "Screw" or joint.Reference1 is None or joint.Reference2 is None:
            raise RuntimeError("Native screw joint failed connector validation")
        return (f"{command.target.document_id}:{joint.Name}",)

    def _create_multi_start_helix(self, command: StructuredCommand) -> tuple[str, ...]:
        """Create phase-indexed native helix paths sharing one mechanical lead."""
        document = self._document(command)
        arguments = self._arguments(command)
        values: dict[str, float] = {}
        for field in ("lead", "height", "radius"):
            value = arguments.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"Multi-start helix {field} must be a positive number")
            values[field] = float(value)
        starts = arguments.get("starts")
        if isinstance(starts, bool) or not isinstance(starts, int) or not 1 <= starts <= 8:
            raise ValueError("Multi-start helix starts must be an integer in the range 1..8")
        name = str(arguments.get("name", "MultiStartHelix"))
        if document.getObject(name) is not None:
            raise ValueError(f"Multi-start helix object already exists: {name}")
        group = document.addObject("App::Part", name)
        group.addProperty("App::PropertyLength", "Lead", "Helicoid")
        group.addProperty("App::PropertyLength", "ThreadPitch", "Helicoid")
        group.addProperty("App::PropertyInteger", "Starts", "Helicoid")
        group.addProperty("App::PropertyLength", "MeanRadius", "Helicoid")
        group.Lead = values["lead"]
        group.ThreadPitch = values["lead"] / starts
        group.Starts = starts
        group.MeanRadius = values["radius"]
        app = self._app_provider()
        changed = [f"{command.target.document_id}:{group.Name}"]
        for index in range(starts):
            helix = group.newObject("Part::Helix", f"{name}_Start_{index + 1}")
            helix.Pitch = values["lead"]
            helix.Height = values["height"]
            helix.Radius = values["radius"]
            helix.Placement = app.Placement(
                app.Vector(0.0, 0.0, 0.0),
                app.Rotation(app.Vector(0.0, 0.0, 1.0), 360.0 * index / starts),
            )
            changed.append(f"{command.target.document_id}:{helix.Name}")
        document.recompute()
        if any(item.Shape.isNull() or not item.Shape.isValid() for item in group.Group):
            raise RuntimeError("Multi-start helix path generation failed")
        return tuple(changed)

    def _create_boolean_cut(self, command: StructuredCommand) -> tuple[str, ...]:
        document = self._document(command)
        arguments = self._arguments(command)
        base_name, tool_name = (
            str(arguments.get("base_name", "")),
            str(arguments.get("tool_name", "")),
        )
        if not base_name or not tool_name or base_name == tool_name:
            raise ValueError("Boolean cut requires distinct base and tool names")
        base, tool = document.getObject(base_name), document.getObject(tool_name)
        if base is None or tool is None:
            raise LookupError("Boolean cut base or tool object was not found")
        name = str(arguments.get("name", f"{base_name}_Cut"))
        native = document.addObject("Part::Cut", name)
        native.Base, native.Tool = base, tool
        self._validate_recompute(document, native, "Boolean cut")
        return (f"{command.target.document_id}:{native.Name}",)

    def _create_boolean_union(self, command: StructuredCommand) -> tuple[str, ...]:
        document = self._document(command)
        arguments = self._arguments(command)
        names = tuple(
            item.strip()
            for item in str(arguments.get("object_names", "")).split(",")
            if item.strip()
        )
        if len(names) < 2 or len(set(names)) != len(names):
            raise ValueError("Boolean union requires at least two distinct object names")
        objects = tuple(document.getObject(name) for name in names)
        if any(item is None for item in objects):
            raise LookupError("Boolean union object was not found")
        name = str(arguments.get("name", "Union"))
        native = document.addObject("Part::MultiFuse", name)
        native.Shapes = objects
        self._validate_recompute(document, native, "Boolean union")
        return (f"{command.target.document_id}:{native.Name}",)

    def _set_placement(self, command: StructuredCommand) -> tuple[str, ...]:
        document = self._document(command)
        arguments = self._arguments(command)
        object_name = str(arguments.get("object_name", ""))
        native = document.getObject(object_name)
        if native is None:
            raise LookupError(f"Placement object was not found: {object_name}")
        values = {}
        for name in ("x", "y", "z", "yaw", "pitch", "roll"):
            value = arguments.get(name, 0.0)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Placement {name} must be numeric")
            values[name] = float(value)
        app = self._app_provider()
        native.Placement = app.Placement(
            app.Vector(values["x"], values["y"], values["z"]),
            app.Rotation(values["yaw"], values["pitch"], values["roll"]),
        )
        self._validate_recompute(document, native, "Placement")
        return (f"{command.target.document_id}:{native.Name}",)

    def _create_fillet(self, command: StructuredCommand) -> tuple[str, ...]:
        document = self._document(command)
        arguments = self._arguments(command)
        base_name = str(arguments.get("base_name", ""))
        radius = arguments.get("radius")
        edge_text = str(arguments.get("edge_indices", ""))
        if isinstance(radius, bool) or not isinstance(radius, (int, float)) or radius <= 0:
            raise ValueError("Fillet radius must be a positive number")
        try:
            indices = tuple(
                sorted({int(item.strip()) for item in edge_text.split(",") if item.strip()})
            )
        except ValueError as error:
            raise ValueError("Fillet edge indices must be comma-separated integers") from error
        if not indices or any(item < 1 for item in indices):
            raise ValueError("Fillet requires positive one-based edge indices")
        base = document.getObject(base_name)
        if base is None:
            raise LookupError(f"Fillet base object was not found: {base_name}")
        edge_count = len(base.Shape.Edges)
        if any(item > edge_count for item in indices):
            raise ValueError("Fillet edge index exceeds the base shape")
        name = str(arguments.get("name", f"{base_name}_Fillet"))
        native = document.addObject("Part::Fillet", name)
        native.Base = base
        native.Edges = tuple((item, float(radius), float(radius)) for item in indices)
        self._validate_recompute(document, native, "Fillet")
        return (f"{command.target.document_id}:{native.Name}",)

    @staticmethod
    def _validate_recompute(document: Any, native: Any, operation: str) -> None:
        document.recompute()
        errors = [
            state
            for item in document.Objects
            for state in item.State
            if state not in {"Touched", "Up-to-date"}
        ]
        invalid_shape = False
        if hasattr(native, "Shape"):
            invalid_shape = native.Shape.isNull() or not native.Shape.isValid()
        if errors or invalid_shape:
            raise RuntimeError(f"{operation} failed recompute or shape validation")

    def _set_property(self, command: StructuredCommand) -> tuple[str, ...]:
        document = self._document(command)
        arguments = self._arguments(command)
        object_name = str(arguments["object_name"])
        property_name = str(arguments["property_name"])
        native = document.getObject(object_name)
        if native is None:
            raise LookupError(f"Object not found: {object_name}")
        if property_name not in native.PropertiesList:
            raise AttributeError(f"Property not found: {property_name}")
        setattr(native, property_name, arguments["value"])
        return (f"{command.target.document_id}:{native.Name}",)

    def _recompute(self, command: StructuredCommand) -> tuple[str, ...]:
        document = self._document(command)
        document.recompute()
        errors = [
            item
            for item in document.Objects
            if any(state not in {"Touched", "Up-to-date"} for state in item.State)
        ]
        if errors:
            raise RuntimeError("FreeCAD recompute failed")
        return tuple(command.affected_object_ids)

    def _save_version(self, command: StructuredCommand) -> tuple[str, ...]:
        document = self._document(command)
        path = str(self._arguments(command)["path"])
        if not path.casefold().endswith(".fcstd"):
            raise ValueError("FreeCAD version path must end with .FCStd")
        document.saveCopy(path)
        return ()
