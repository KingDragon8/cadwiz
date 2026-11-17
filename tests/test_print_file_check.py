# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Beta 1.0 report E-15 / I-7: check a print file before it goes to the printer.

The cases are the ones that happened on 2026-10-24/25: a Cura project (3MF zip)
saved as `v9.gcode` (firmware error), Cura's TPU defaults with the bed at 0 C
(the print came loose), and the good file that followed.
"""
from __future__ import annotations

import zipfile

from ai_freecad_core.export_check import check_print_file

GOOD_HEAD = """;FLAVOR:Marlin
;TIME:119255
;Filament used: 103.81m
;Layer height: 0.2
;MINX:47.272
;MINY:96.1
;MINZ:0.2
;MAXX:381.732
;MAXY:311.2
;MAXZ:89
;Generated with Cura_SteamEngine 5.8.0
;ELEGOO NEPTUNE 4 MAX
M220 S100
M104 S140
M190 S60
G90
G28
M109 S230
G92 E0
;LAYER_COUNT:445
;LAYER:0
G1 F900 X100 Y100 Z0.2 E1.2
"""
GOOD_TAIL = """G1 X150 Y150 E5000.1
;End of Gcode
M140 S0
M104 S0
M84
"""


def _write(path, head, tail=GOOD_TAIL):
    path.write_text(head + "G1 X1 Y1 E1\n" * 2000 + tail, encoding="utf-8")
    return path


def test_the_good_tpu_file_reads_as_ready(tmp_path) -> None:
    report = check_print_file(_write(tmp_path / "EN4MAX_Head60ShellVisor.gcode", GOOD_HEAD), material="TPU",
                              expect_bed_c=60, expect_nozzle_c=230)
    assert report.kind == "gcode" and report.printable and not report.problems
    assert (report.bed_c, report.nozzle_c, report.layers) == (60, 230, 445)     # the 140 C preheat is not the print temperature
    assert report.time_s == 119255 and report.filament_m == 103.81
    assert report.size_mm == (334.5, 215.1, 89.0)
    assert "ready to print" in report.say() and "about 33 h 8 min" in report.say()


def test_a_project_zip_named_gcode_is_caught(tmp_path) -> None:
    fake = tmp_path / "v9.gcode"
    with zipfile.ZipFile(fake, "w") as z:
        z.writestr("3D/3dmodel.model", "<model/>")
        z.writestr("Metadata/thumbnail.png", b"\x89PNG")
    report = check_print_file(fake)
    assert report.kind == "project_zip" and not report.printable
    assert "not G-code" in report.say() and "Save to Disk" in report.say()


def test_a_bed_at_zero_and_a_cut_off_file_are_problems(tmp_path) -> None:
    cold = _write(tmp_path / "cold.gcode", GOOD_HEAD.replace("M190 S60", "M190 S0"))
    report = check_print_file(cold, material="TPU")
    assert not report.printable and any("0 C (heater off)" in p for p in report.problems)
    cut = _write(tmp_path / "cut.gcode", GOOD_HEAD, tail="G1 X1 Y1 E1\n")
    report = check_print_file(cut)
    assert not report.printable and any("cut short" in p for p in report.problems)


def test_a_pla_temperature_on_tpu_and_a_missing_file(tmp_path) -> None:
    pla = _write(tmp_path / "pla.gcode", GOOD_HEAD.replace("M109 S230", "M109 S250"))
    report = check_print_file(pla, material="TPU")
    assert any("outside the usual" in p for p in report.problems)
    assert not report.printable
    assert check_print_file(tmp_path / "nope.gcode").kind == "missing"
