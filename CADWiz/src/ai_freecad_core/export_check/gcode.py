# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Is this print file really G-code, and does it say what the print needs?

Beta 1.0 report E-15 / I-7 (2026-10-25): a Cura project file (a 3MF zip) saved
with a `.gcode` name reached the founder's printer, which stopped with a
firmware error. Before that, Cura's TPU defaults had the bed at 0 C. This reads a
print file -- never changes it, never talks to the printer -- and says in plain
words what it is and what it will do: bed and nozzle temperature, layers, time,
filament, and whether the file looks complete.

Domain-neutral: no FreeCAD, no slicer, no network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: How much of each end of the file is read (a 45 MB file is not read whole).
HEAD_BYTES = 256 * 1024
TAIL_BYTES = 64 * 1024

#: Usual temperature ranges (nozzle, bed), in C, for a quick sanity check. Wide on
#: purpose: they catch a 0 C bed or a PLA temperature on TPU, not fine tuning.
MATERIAL_RANGES: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {
    "PLA": ((185, 230), (40, 75)),
    "PETG": ((215, 260), (55, 95)),
    "TPU": ((200, 245), (25, 70)),
    "ABS": ((225, 270), (85, 115)),
    "ASA": ((230, 270), (85, 115)),
}

_ZIP = b"PK\x03\x04"
_SETTING = re.compile(r"^;(FLAVOR|TIME|Filament used|LAYER_COUNT|Generated with|MINX|MAXX|MINY|MAXY|MAXZ)[: ]\s*(.+)$",
                      re.MULTILINE)
_TEMP = re.compile(r"^(M190|M140|M109|M104)\s+S(\d+(?:\.\d+)?)", re.MULTILINE)
_MOVE = re.compile(r"^G[01]\s", re.MULTILINE)
_END = re.compile(r"^(M84|M18|;End of Gcode|;END|M104 S0|M140 S0)", re.MULTILINE | re.IGNORECASE)


@dataclass
class PrintFileReport:
    path: str
    kind: str                           # gcode | project_zip | binary | empty | missing
    printable: bool
    bed_c: float | None = None
    nozzle_c: float | None = None
    layers: int | None = None
    time_s: int | None = None
    filament_m: float | None = None
    flavor: str = ""
    generator: str = ""
    size_mm: tuple[float, float, float] | None = None
    looks_complete: bool = False
    problems: list[str] = field(default_factory=list)

    def say(self) -> str:
        """One short paragraph for the founder."""
        name = Path(self.path).name
        if self.kind == "missing":
            return f"I can't find {name}."
        if self.kind == "project_zip":
            return (f"{name} is not G-code: it is a slicer project file (a 3MF zip) with a .gcode name, so the printer "
                    f"can't read it. In the slicer use Save to Disk / Export G-code and choose the G-code file type.")
        if self.kind in ("binary", "empty"):
            return f"{name} is not plain G-code ({'empty' if self.kind == 'empty' else 'binary data'}): " + " ".join(self.problems)
        parts = [f"{name} is G-code"]
        if self.bed_c is not None and self.nozzle_c is not None:
            parts.append(f"bed {self.bed_c:g} C, nozzle {self.nozzle_c:g} C")
        if self.layers:
            parts.append(f"{self.layers} layers")
        if self.time_s:
            hours, minutes = divmod(round(self.time_s / 60), 60)
            parts.append(f"about {hours} h {minutes} min")
        if self.filament_m:
            parts.append(f"{self.filament_m:g} m of filament")
        line = ", ".join(parts) + "."
        if self.problems:
            line += " Check before printing: " + " ".join(self.problems)
        else:
            line += " It looks ready to print."
        return line

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "kind": self.kind, "printable": self.printable, "bed_c": self.bed_c,
                "nozzle_c": self.nozzle_c, "layers": self.layers, "time_s": self.time_s, "filament_m": self.filament_m,
                "flavor": self.flavor, "generator": self.generator, "size_mm": self.size_mm,
                "looks_complete": self.looks_complete, "problems": list(self.problems), "say_to_founder": self.say()}


def _number(text: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def check_print_file(path: str | Path, material: str = "", expect_bed_c: float | None = None,
                     expect_nozzle_c: float | None = None) -> PrintFileReport:
    """Read a print file's start and end and report what it is (see the module text)."""
    target = Path(path)
    if not target.is_file():
        return PrintFileReport(str(target), "missing", False, problems=["The file is not there."])
    size = target.stat().st_size
    if size == 0:
        return PrintFileReport(str(target), "empty", False, problems=["The file has nothing in it."])
    with target.open("rb") as handle:
        head = handle.read(HEAD_BYTES)
        handle.seek(max(0, size - TAIL_BYTES))
        tail = handle.read(TAIL_BYTES)
    if head.startswith(_ZIP):
        return PrintFileReport(str(target), "project_zip", False)
    if b"\x00" in head[:4096]:
        return PrintFileReport(str(target), "binary", False,
                               problems=["It may be binary G-code (.bgcode); only print it if your printer says it supports that."])
    text = head.decode("utf-8", errors="replace")
    end_text = tail.decode("utf-8", errors="replace")
    report = PrintFileReport(str(target), "gcode", True)
    settings = {key: value.strip() for key, value in _SETTING.findall(text)}
    report.flavor = settings.get("FLAVOR", "")
    report.generator = settings.get("Generated with", "")
    if "TIME" in settings:
        number = _number(settings["TIME"])
        report.time_s = int(number) if number is not None else None
    if "Filament used" in settings:
        report.filament_m = _number(settings["Filament used"])
    if "LAYER_COUNT" in settings:
        number = _number(settings["LAYER_COUNT"])
        report.layers = int(number) if number is not None else None
    if all(k in settings for k in ("MINX", "MAXX", "MINY", "MAXY", "MAXZ")):
        nums = {k: _number(settings[k]) or 0.0 for k in ("MINX", "MAXX", "MINY", "MAXY", "MAXZ")}
        report.size_mm = (round(nums["MAXX"] - nums["MINX"], 1), round(nums["MAXY"] - nums["MINY"], 1), round(nums["MAXZ"], 1))
    temps: dict[str, list[float]] = {}
    for code, value in _TEMP.findall(text):
        temps.setdefault(code, []).append(float(value))
    bed = (temps.get("M190") or temps.get("M140") or [None])[0]
    nozzle = (temps.get("M109") or [None])[0]
    if nozzle is None and temps.get("M104"):
        nozzle = max(temps["M104"])            # no wait-for-temperature line: the highest early setting
    report.bed_c, report.nozzle_c = bed, nozzle
    has_moves = bool(_MOVE.search(text))
    report.looks_complete = bool(_END.search(end_text))
    problems = report.problems
    if not has_moves:
        problems.append("I found no movement lines at its start, so it may not be a real print.")
    if not report.looks_complete:
        problems.append("Its end has no finishing commands: it may be cut short (for example, the USB stick removed while "
                        "it was still being written). Save it again.")
    if bed is None:
        problems.append("It never sets the bed temperature.")
    elif bed <= 0:
        problems.append("The bed is set to 0 C (heater off), so the print will likely come loose.")
    if nozzle is None:
        problems.append("It never sets the nozzle temperature.")
    ranges = MATERIAL_RANGES.get(material.strip().upper())
    if ranges and nozzle is not None and not ranges[0][0] <= nozzle <= ranges[0][1]:
        problems.append(f"{nozzle:g} C is outside the usual {ranges[0][0]}-{ranges[0][1]} C for {material.upper()}.")
    if ranges and bed is not None and bed > 0 and not ranges[1][0] <= bed <= ranges[1][1]:
        problems.append(f"A {bed:g} C bed is outside the usual {ranges[1][0]}-{ranges[1][1]} C for {material.upper()}.")
    if expect_bed_c is not None and bed is not None and abs(bed - expect_bed_c) > 0.5:
        problems.append(f"The bed is {bed:g} C, not the {expect_bed_c:g} C expected.")
    if expect_nozzle_c is not None and nozzle is not None and abs(nozzle - expect_nozzle_c) > 0.5:
        problems.append(f"The nozzle is {nozzle:g} C, not the {expect_nozzle_c:g} C expected.")
    report.printable = has_moves and report.looks_complete and not problems
    return report
