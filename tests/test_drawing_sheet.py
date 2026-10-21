# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""ORDER-2026-10-19-06: the technical drawing sheet (layout only, no FreeCAD).

Founder ruling 2026-10-19: a Drawings button, "like a technical drawing".
"""
from __future__ import annotations

import re
from xml.etree import ElementTree

from ai_freecad_core.drawings import sheet


def _rect(u0: float, u1: float, v0: float, v1: float) -> list[list[tuple[float, float]]]:
    return [[(u0, v0), (u1, v0), (u1, v1), (u0, v1), (u0, v0)]]


def _can() -> dict[str, sheet.View]:
    # his trash can A as the views arrive: 185 wide with handles, 156 deep, 210 tall (mm)
    return {"front": sheet.View("front", _rect(-92.5, 92.5, 0, 210)), "top": sheet.View("top", _rect(-92.5, 92.5, -78, 78)),
            "section": sheet.View("section", _rect(-92.5, 92.5, 0, 210), hatch=[_rect(-75, 75, 190, 200)]),
            "iso": sheet.View("iso", _rect(0, 100, 0, 120))}


def test_the_largest_standard_scale_that_fits_a_letter_page_is_chosen() -> None:
    assert sheet.choose_scale(185, 156, 210) == 1 / 3                   # the 8 in trash can
    assert sheet.choose_scale(40, 25, 12) == 2.0                        # a small bracket is drawn bigger than life
    assert sheet.scale_label(1 / 3) == "1:3" and sheet.scale_label(2.0) == "2:1"


def test_the_sheet_is_valid_svg_with_every_view_its_sizes_and_a_title_block() -> None:
    svg, scale = sheet.compose(_can(), title="Trash can A", version=2, date="2026-10-20")
    ElementTree.fromstring(svg)                                          # well-formed
    words = " ".join(re.findall(r">([^<]+)</text>", svg))
    for expected in ("FRONT", "TOP", "SECTION", "3D VIEW", "Trash can A", "Scale 1:3", "Version v2", "2026-10-20", "in (mm)"):
        assert expected in words, expected
    # the overall sizes, inches first with millimetres beside them
    assert "7.28 in (185 mm)" in words and "8.27 in (210 mm)" in words and "6.14 in (156 mm)" in words
    assert 'class="cut"' in svg and 'id="hatch"' in svg                 # the section's cut face is hatched
    assert scale == 1 / 3


def test_a_dimension_claude_adds_is_drawn_with_its_distance_or_his_words() -> None:
    dims = [sheet.Dimension("front", (-75.0, 175.0), (75.0, 175.0)), sheet.Dimension("front", (0.0, 0.0), (0.0, 90.0), "Lid height")]
    svg, _ = sheet.compose(_can(), title="Trash can A", dimensions=dims)
    words = re.findall(r">([^<]+)</text>", svg)
    assert "5.91 in (150 mm)" in words and "Lid height" in words


def test_nothing_is_drawn_off_the_page() -> None:
    svg, _ = sheet.compose(_can(), title="Trash can A")
    for x, y in re.findall(r"([-\d.]+),([-\d.]+)", svg):
        assert -1 <= float(x) <= sheet.SHEET_W + 1 and -1 <= float(y) <= sheet.SHEET_H + 1
