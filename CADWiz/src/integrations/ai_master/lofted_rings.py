# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Ring-level editing of a lofted solid (ORDER-2026-10-12-03 item 5).

Runs inside the headless worker (freecadcmd). Some of the founder's models are
fixed solids with no feature history, built as ONE continuous loft through a few
rings per wall surface. CoolOff_AI1's "Aligned Five-Ring Shell" is four wall
surfaces (head-side skin, water-chamber inner and outer walls, outer skin), each
a loft through five rings (the head-side one extended past both ends and
trimmed), a flat bottom, a top tilted 6 degrees, a water chamber and drain ports.
Scaling the solid would scale the walls too, and a boolean script cannot reach
the rings. So CADWiz edits it at the level it was built:

  1. detect: the lofted wall surfaces (their pole rows are the ring outlines),
     the flat bottom, the tilted tops, the chamber, the ports;
  2. reshape the head-side surface: its bottom ring is scaled about its own
     centre to the asked distance around, fading smoothly (zero slope at both
     ends) to no change at the top ring -- top fit and height unchanged;
  3. regenerate the other walls from their own rings, moved with the head side
     and widened exactly as much as the flare tilts them, so the inner wall,
     bladder and outer wall keep their thickness (1.6 / 8 / 1.6 mm on this
     helmet); move the ports with the floor; rebuild the solid, the chamber and
     the cut-away views. (True 3D offsets were tried first, 2026-10-12: they
     moved the top -- 358 -> 376 mm around with no size change asked -- because
     the original walls were offset ring by ring, not along the surface normal.)

Nothing here decides what the founder wants: the master asks for the target and
CADWiz carries it out and measures before and after.
"""
from __future__ import annotations

import bisect
import math
import statistics

BIG = 2000.0


def _vec(x, y, z):
    import FreeCAD

    return FreeCAD.Vector(x, y, z)


def _tight(shape):
    from integrations.ai_master.shape_box import tight_box

    return tight_box(shape)


#: Lofted walls are B-spline surfaces; a regenerated wall is an exact offset of one.
_WALL_SURFACES = ("BSplineSurface", "OffsetSurface")


def _bspline_skins(shape, min_area_share=0.05):
    total = sum(f.Area for f in shape.Faces) or 1.0
    return [f for f in shape.Faces if type(f.Surface).__name__ in _WALL_SURFACES and f.Area / total >= min_area_share]


def _cut_loop(surface, z):
    """Edges of the (untrimmed) surface's horizontal cut at z."""
    import Part

    return Part.Face(surface).section(Part.makePlane(2 * BIG, 2 * BIG, _vec(-BIG, -BIG, z))).Edges


def _loop_area(surface, z):
    import Part

    edges = _cut_loop(surface, z)
    if not edges:
        return 0.0
    try:
        wire = Part.Wire(Part.__sortEdges__(edges))
        return abs(Part.Face(wire).Area) if wire.isClosed() else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def _planes(shape):
    """(bottom, floor, tops): the lowest horizontal plane, the next horizontal plane
    above it (a chamber floor), and the tilted planes highest first."""
    flat = sorted((f for f in shape.Faces if type(f.Surface).__name__ == "Plane" and abs(f.Surface.Axis.z) > 0.999 and f.Area > 100),
                  key=lambda f: f.BoundBox.ZMin)
    tilted = sorted((f for f in shape.Faces if type(f.Surface).__name__ == "Plane" and 0.5 < abs(f.Surface.Axis.z) <= 0.999 and f.Area > 100),
                    key=lambda f: -f.BoundBox.ZMax)
    bottom = flat[0] if flat else None
    floor = flat[1] if len(flat) > 1 else None
    return bottom, floor, tilted


def _ordered_skins(shape):
    """Wall surfaces, inside out (smallest enclosed area at mid height first)."""
    box = _tight(shape)
    z_mid = (box.ZMin + box.ZMax) / 2.0
    skins = _bspline_skins(shape)
    areas = {id(f): _loop_area(f.Surface, z_mid) for f in skins}
    if any(a <= 0 for a in areas.values()):
        return []
    return sorted(skins, key=lambda f: areas[id(f)])


ROLES = {2: ["head-side skin", "outer skin"], 4: ["head-side skin", "water-chamber inner wall", "water-chamber outer wall", "outer skin"]}


def _ports(shape):
    """Round vertical through-holes as tool cylinders: centre, radius, z from/to."""
    groups = {}
    for face in shape.Faces:
        surface = face.Surface
        if type(surface).__name__ != "Cylinder" or abs(abs(surface.Axis.z) - 1.0) > 1e-6:
            continue
        key = (round(surface.Center.x, 3), round(surface.Center.y, 3), round(surface.Radius, 3))
        entry = groups.setdefault(key, {"x": surface.Center.x, "y": surface.Center.y, "radius": surface.Radius,
                                        "z0": min(surface.Center.z, face.BoundBox.ZMin), "z1": face.BoundBox.ZMax})
        entry["z0"] = min(entry["z0"], surface.Center.z, face.BoundBox.ZMin)
        entry["z1"] = max(entry["z1"], face.BoundBox.ZMax)
    return list(groups.values())


def detect(obj):
    """How this object was built, in facts. {} when it is not a lofted ring body."""
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull() or len(shape.Solids) != 1:
        return {}
    skins = _ordered_skins(shape)
    bottom, floor, tops = _planes(shape)
    if len(skins) < 2 or bottom is None or not tops:
        return {}
    roles = ROLES.get(len(skins), [f"wall surface {i + 1}" for i in range(len(skins))])
    ports = _ports(shape)
    tilt = round(math.degrees(math.acos(min(1.0, abs(tops[0].Surface.Axis.z)))), 1)
    source_rings = int(getattr(obj, "SourceRingCount", 0) or 0) or min(f.Surface.NbVPoles for f in skins)
    chamber = len(skins) == 4 and floor is not None and len(tops) >= 2
    return {
        "kind": "lofted ring body",
        "object": obj.Label,
        "feature_history": False,
        "wall_surfaces_inside_out": roles,
        "rings_per_wall": source_rings,
        "flat_bottom": True,
        "top_tilt_deg": tilt,
        "water_chamber": chamber,
        "ports": {"count": len(ports), "diameter_mm": round(2 * ports[0]["radius"], 2)} if ports else {"count": 0},
        "edit_with": "reshape_rings",
        "plain": (f"{obj.Label} is a fixed solid (no feature history) built as one continuous loft through {source_rings} rings "
                  f"per wall: {len(skins)} wall surfaces ({', '.join(roles)}, inside out), a flat bottom, a top tilted {tilt:g} degrees"
                  + (", a water chamber between the walls" if chamber else "")
                  + (f" and {len(ports)} drain ports {2 * ports[0]['radius']:g} mm across" if ports else "")
                  + ". CADWiz edits it at the ring level (reshape_rings)."),
    }


class _PolarTable:
    """r(theta, z) of the head-side surface around a fixed centre, from horizontal cuts."""

    def __init__(self, surface, cx, cy, z_from, z_to, step=2.0, samples=360):
        self.levels, self.tables = [], []
        n = max(2, int(math.ceil((z_to - z_from) / step)) + 1)
        for i in range(n):
            z = z_from + (z_to - z_from) * i / (n - 1)
            edges = _cut_loop(surface, z)
            if not edges:
                continue
            total = sum(e.Length for e in edges) or 1.0
            points = [p for e in edges for p in e.discretize(max(16, int(samples * e.Length / total)))]
            polar = sorted((math.atan2(p.y - cy, p.x - cx), math.hypot(p.x - cx, p.y - cy)) for p in points)
            self.levels.append(z)
            self.tables.append(([a for a, _ in polar], [r for _, r in polar]))
        if not self.levels:
            raise ValueError("the head-side surface has no horizontal cut in the edited range")

    @staticmethod
    def _r_at(table, theta):
        angles, radii = table
        i = bisect.bisect_left(angles, theta)
        a0, r0 = (angles[i - 1], radii[i - 1]) if i > 0 else (angles[-1] - 2 * math.pi, radii[-1])
        a1, r1 = (angles[i], radii[i]) if i < len(angles) else (angles[0] + 2 * math.pi, radii[0])
        t = 0.0 if a1 == a0 else (theta - a0) / (a1 - a0)
        return r0 + (r1 - r0) * t

    def r(self, theta, z):
        if z <= self.levels[0]:
            return self._r_at(self.tables[0], theta)
        if z >= self.levels[-1]:
            return self._r_at(self.tables[-1], theta)
        j = bisect.bisect_left(self.levels, z)
        z0, z1 = self.levels[j - 1], self.levels[j]
        t = (z - z0) / (z1 - z0)
        return self._r_at(self.tables[j - 1], theta) * (1 - t) + self._r_at(self.tables[j], theta) * t


def _fade(z, z_bottom, z_top):
    """1 at and below the bottom ring, 0 at and above the top ring, smooth between."""
    if z <= z_bottom:
        return 1.0
    if z >= z_top:
        return 0.0
    return 0.5 * (1.0 + math.cos(math.pi * (z - z_bottom) / (z_top - z_bottom)))


def _fade_slope(z, z_bottom, z_top):
    if z <= z_bottom or z >= z_top:
        return 0.0
    span = z_top - z_bottom
    return -0.5 * math.pi / span * math.sin(math.pi * (z - z_bottom) / span)


def _solid_from_skin(surface):
    """A lofted wall surface + its two flat end rings -> a closed solid."""
    import Part

    side = Part.Face(surface)
    caps = [Part.Face(Part.Wire(surface.vIso(v).toShape())) for v in (surface.getVKnots()[0], surface.getVKnots()[-1])]
    shell = Part.Shell([side] + caps)
    shell.sewShape()
    solid = Part.Solid(shell)
    if solid.Volume < 0:
        solid.reverse()
    return solid


def _refined(surface, rows=16):
    """The same surface with more rings of control points (knot insertion leaves
    the shape exactly as it was). Five rings control a whole wall, so moving one
    moves the top too; with rings every few millimetres an edit stays local."""
    out = surface.copy()
    knots = out.getVKnots()
    v0, v1 = knots[0], knots[-1]
    for i in range(1, rows):
        v = v0 + (v1 - v0) * i / rows
        if all(abs(v - k) > 1e-3 for k in knots):
            out.insertVKnot(v, 1, 1e-6)
    return out


#: The fade ends this far below the lowest point of the top ring, so control
#: points that shape the top ring and the top opening never move.
TOP_KEEP_MM = 15.0


def reshape(shell_obj, target_inner_bottom_mm, *, chamber_obj=None, cutaways=(), progress=lambda text: None):
    """Scale the head-side bottom ring to `target_inner_bottom_mm` around, fading to
    no change below the top ring; move every other wall with the wall inside it,
    keeping each wall's thickness; rebuild the solid from the reshaped rings.

    Each wall surface is a loft whose pole rows are its rings. Radii are read
    around the bottom ring's centre, at each angle theta and height z:
      head side        R0'(theta, z) = R0 (1 + (s - 1) f(z))
      wall k (outward) Rk' = R(k-1)' + (Rk - R(k-1)) * K(k-1)
      K = sqrt(1 + (dR'/dz)^2) / sqrt(1 + (dR/dz)^2) of the wall inside it
    -- every gap widens exactly as much as the wall inside it now leans further,
    so each wall keeps its true thickness. A control point moves by (Rk' - Rk).
    Where f = 0 (from TOP_KEEP_MM below the top ring up) nothing moves."""
    import Part

    shape = shell_obj.Shape
    progress("Finding how the shell was built")
    skins = _ordered_skins(shape)
    bottom, _floor, tops = _planes(shape)
    if len(skins) not in (2, 4) or bottom is None or not tops:
        raise ValueError("this is not a lofted ring body CADWiz can reshape (expected 2 or 4 lofted walls, a flat bottom and a top plane)")
    z_bottom = bottom.BoundBox.ZMin
    z_top_ring = min(t.BoundBox.ZMin for t in tops)
    z_fade = max(z_bottom + 10.0, z_top_ring - TOP_KEEP_MM)

    progress("Measuring the bottom opening")
    head = skins[0].Surface
    edges = _cut_loop(head, z_bottom)
    before = sum(e.Length for e in edges)
    if before <= 0:
        raise ValueError("could not find the inside outline at the bottom ring")
    centre = Part.Face(Part.Wire(Part.__sortEdges__(edges))).CenterOfMass
    cx, cy = centre.x, centre.y
    target = float(target_inner_bottom_mm)
    progress("Measuring every wall")
    tables = [_PolarTable(f.Surface, cx, cy, z_bottom, z_fade + 2.0, step=3.0, samples=240) for f in skins]

    def r_old(k, theta, z):
        return tables[k].r(theta, min(max(z, z_bottom), z_fade + 2.0))

    def r_new(k, theta, z, scale):
        if k == 0:
            return r_old(0, theta, z) * (1.0 + (scale - 1.0) * _fade(z, z_bottom, z_fade))
        inner_new = r_new(k - 1, theta, z, scale)
        gap = r_old(k, theta, z) - r_old(k - 1, theta, z)
        lo, hi = max(z_bottom, z - 1.0), z + 1.0
        d_old = (r_old(k - 1, theta, hi) - r_old(k - 1, theta, lo)) / (hi - lo)
        d_new = (r_new(k - 1, theta, hi, scale) - r_new(k - 1, theta, lo, scale)) / (hi - lo)
        return inner_new + gap * math.sqrt(1.0 + d_new * d_new) / math.sqrt(1.0 + d_old * d_old)

    def move(k, p, scale):
        if _fade(p.z, z_bottom, z_fade) <= 0.0:
            return p
        theta = math.atan2(p.y - cy, p.x - cx)
        grow = r_new(k, theta, p.z, scale) - r_old(k, theta, p.z)
        return _vec(p.x + grow * math.cos(theta), p.y + grow * math.sin(theta), p.z)

    refined = [_refined(f.Surface) for f in skins]

    def morphed(k, scale):
        out = refined[k].copy()
        for u in range(1, out.NbUPoles + 1):
            for v in range(1, out.NbVPoles + 1):
                out.setPole(u, v, move(k, out.getPole(u, v), scale), out.getWeight(u, v))
        return out

    # The ring's control points sit just off the curve, so the first pass lands a
    # fraction of a percent away; the growth is linear in the scale, so one or two
    # corrections put the bottom ring on the target.
    progress("Reshaping the bottom ring")
    scale = target / before
    new_head = morphed(0, scale)
    for _ in range(3):
        got = sum(e.Length for e in _cut_loop(new_head, z_bottom))
        if abs(got - target) < 0.05 or abs(got - before) < 1e-9:
            break
        scale = 1.0 + (scale - 1.0) * (target - before) / (got - before)
        new_head = morphed(0, scale)
    walls = [new_head]
    if len(skins) == 4:
        names = ("Rebuilding the water chamber's inner wall", "Rebuilding the water chamber's outer wall", "Rebuilding the outer wall")
    else:
        names = ("Rebuilding the outer wall",)
    for k, name in enumerate(names, start=1):
        progress(name)
        walls.append(morphed(k, scale))

    progress("Rebuilding the solid")
    shell = _solid_from_skin(walls[-1]).cut(_solid_from_skin(walls[0]))
    chamber = None
    if len(walls) == 4:
        chamber = _solid_from_skin(walls[2]).cut(_solid_from_skin(walls[1]))
        shell = shell.cut(chamber)
    ports = _ports(shape)
    if ports:
        progress("Moving the drain ports with the floor")
    for port in ports:
        # A port sits in the chamber floor: it moves with the middle of the chamber.
        k = 2 if len(walls) == 4 else len(walls) - 1
        theta = math.atan2(port["y"] - cy, port["x"] - cx)
        grow = r_new(k, theta, z_bottom, scale) - r_old(k, theta, z_bottom)
        if len(walls) == 4:
            grow = 0.5 * (grow + r_new(1, theta, z_bottom, scale) - r_old(1, theta, z_bottom))
        x, y = port["x"] + grow * math.cos(theta), port["y"] + grow * math.sin(theta)
        shell = shell.cut(Part.makeCylinder(port["radius"], port["z1"] - port["z0"], _vec(x, y, port["z0"])))
    shell = shell.removeSplitter()
    if not shell.isValid() or len(shell.Solids) != 1:
        raise ValueError(f"the rebuilt shell is not one valid solid (valid={shell.isValid()}, solids={len(shell.Solids)})")

    progress("Checking thickness")
    old_shell = shape.copy()
    old_chamber = chamber_obj.Shape.copy() if chamber_obj is not None else None
    shell_obj.Shape = shell
    if chamber_obj is not None and chamber is not None:
        chamber_obj.Shape = chamber
        if hasattr(chamber_obj, "Capacity"):
            chamber_obj.Capacity = chamber.Volume
    for cut_obj, new_base in _cutaway_targets(cutaways, old_shell, old_chamber, shell, chamber):
        x_cut = _tight(cut_obj.Shape).XMax
        bb = _tight(new_base)
        box = Part.makeBox(x_cut - bb.XMin + 10, bb.YLength + 20, bb.ZLength + 20, _vec(bb.XMin - 10, bb.YMin - 10, bb.ZMin - 10))
        cut_obj.Shape = new_base.common(box)
    return {"scale_at_bottom": round(scale, 4), "fade_from_mm": round(z_bottom, 2), "fade_to_mm": round(z_fade, 2),
            "inner_bottom_before_mm": round(before, 2), "inner_bottom_after_mm": round(sum(e.Length for e in _cut_loop(new_head, z_bottom)), 2),
            "walls_moved": len(walls), "ports_moved": len(ports)}


def _cutaway_targets(cutaways, old_shell, old_chamber, new_shell, new_chamber):
    """A cut-away view follows whichever body it was cut from (by volume overlap)."""
    for obj in cutaways:
        if obj is None:
            continue
        try:
            on_shell = obj.Shape.common(old_shell).Volume
            on_chamber = obj.Shape.common(old_chamber).Volume if old_chamber is not None else 0.0
        except Exception:  # noqa: BLE001
            continue
        if on_chamber > on_shell and new_chamber is not None:
            yield obj, new_chamber
        elif on_shell > 0:
            yield obj, new_shell


# ---- measuring: before and after -------------------------------------------------

def _sampled_gap(face_a, face_b, n_u=24, n_v=6):
    """3D spacing between two walls: points across A to the nearest point on B's
    surface. Points whose nearest point is on B's edge (past where B ends) are not
    a wall thickness and are skipped."""
    import Part

    u0, u1, v0, v1 = face_a.ParameterRange
    gaps = []
    for i in range(n_u):
        for j in range(n_v):
            u = u0 + (u1 - u0) * (i + 0.5) / n_u
            v = v0 + (v1 - v0) * (j + 0.5) / n_v
            point = face_a.Surface.value(u, v)
            if not face_a.isInside(point, 1e-3, True):
                continue
            distance, _pairs, infos = face_b.distToShape(Part.Vertex(point))
            if infos and infos[0][0] != "Face":
                continue
            gaps.append(distance)
    if not gaps:
        return {}
    return {"min_mm": round(min(gaps), 3), "median_mm": round(statistics.median(gaps), 3), "max_mm": round(max(gaps), 3), "samples": len(gaps)}


def measure(shell_obj):
    """The numbers the founder asked about: inside bottom distance around and size,
    wall and bladder spacing, height, top opening, ports."""
    shape = shell_obj.Shape
    box = _tight(shape)
    record = {"height_mm": round(box.ZLength, 2), "overall_mm": [round(box.XLength, 2), round(box.YLength, 2), round(box.ZLength, 2)],
              "volume_mm3": round(shape.Volume, 1), "valid_solid": shape.isValid(), "solids": len(shape.Solids)}
    bottom, _floor, tops = _planes(shape)
    if bottom is not None:
        inner = min((w for w in bottom.Wires if w.Length > 50), key=lambda w: w.Length)
        bb = inner.BoundBox
        record["inner_bottom"] = {"around_mm": round(inner.Length, 2), "width_mm": round(bb.XLength, 2), "depth_mm": round(bb.YLength, 2)}
        outer = max(bottom.Wires, key=lambda w: w.Length)
        record["outer_bottom"] = {"around_mm": round(outer.Length, 2), "width_mm": round(outer.BoundBox.XLength, 2), "depth_mm": round(outer.BoundBox.YLength, 2)}
    if tops:
        loops = sorted(tops[0].Wires, key=lambda w: w.Length)
        record["top_opening"] = {"inside_around_mm": round(loops[0].Length, 2), "outside_around_mm": round(loops[-1].Length, 2),
                                 "inside_width_mm": round(loops[0].BoundBox.XLength, 2), "inside_depth_mm": round(loops[0].BoundBox.YLength, 2)}
    skins = _ordered_skins(shape)
    if len(skins) == 4:
        head, chamber_in, chamber_out, outer_skin = skins
        record["inner_wall_mm"] = _sampled_gap(chamber_in, head)
        record["bladder_mm"] = _sampled_gap(chamber_out, chamber_in)
        record["outer_wall_mm"] = _sampled_gap(outer_skin, chamber_out)
    elif len(skins) == 2:
        record["wall_mm"] = _sampled_gap(skins[1], skins[0])
    ports = _ports(shape)
    if ports:
        record["ports"] = {"count": len(ports), "diameter_mm": round(2 * ports[0]["radius"], 2)}
    return record
