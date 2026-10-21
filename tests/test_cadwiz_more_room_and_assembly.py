# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""ORDER-2026-10-19-05: more room for the picture, and an Assembly view.

Founder, 2026-10-19: "make a little more real estate for the screen ... add one
called assembly where it splits it apart."
"""
from __future__ import annotations

from pathlib import Path

from integrations.cadwiz_plugin import slim_panel, view_link

ROOT = Path(__file__).resolve().parents[1]


def test_a_lid_lifts_straight_off_its_can_and_the_can_stays_put() -> None:
    # his trash can A: the can (big) centred low, the lid (small) centred at the top
    parts = [("Can", (0.0, 0.0, 88.0), 400_000.0, 230.0), ("Lid", (0.0, 0.0, 190.0), 90_000.0, 160.0)]
    offsets = view_link.exploded_offsets(parts)
    assert set(offsets) == {"Lid"}                                     # the biggest part never moves
    x, y, z = offsets["Lid"]
    assert x == 0 and y == 0 and z == 230.0 * view_link.EXPLODE_SHARE   # straight up, by a share of the model's size


def test_parts_move_away_from_the_biggest_one_in_their_own_direction() -> None:
    parts = [("Body", (0.0, 0.0, 0.0), 1000.0, 100.0), ("Left", (-30.0, 0.0, 0.0), 10.0, 20.0), ("Front", (0.0, -40.0, 0.0), 10.0, 20.0)]
    offsets = view_link.exploded_offsets(parts)
    assert offsets["Left"][0] < 0 and offsets["Left"][1] == 0
    assert offsets["Front"][1] < 0 and offsets["Front"][0] == 0


def test_a_part_centred_on_the_big_one_goes_up_and_one_part_has_nothing_to_split() -> None:
    assert view_link.exploded_offsets([("A", (1.0, 2.0, 3.0), 50.0, 10.0), ("B", (1.0, 2.0, 3.0), 5.0, 4.0)])["B"][2] > 0
    assert view_link.exploded_offsets([("Ball", (0.0, 0.0, 0.0), 1.0, 66.0)]) == {}


def test_the_folded_headings_say_what_is_inside() -> None:
    assert slim_panel.fold_words("problems", 0, 3) == "Problems and fixes — none found"
    assert slim_panel.fold_words("problems", 2, 3) == "Problems and fixes — 2 to look at"
    assert slim_panel.fold_words("versions", 0, 0) == "Time machine — no saved versions yet"
    assert "version 3" in slim_panel.fold_words("versions", 0, 3)


def test_the_header_is_smaller_and_assembly_sits_beside_cut_away() -> None:
    assert slim_panel.HEADER_WIZ_PX < 64 and slim_panel.WORDMARK_PX < 34
    source = (ROOT / "CADWiz/src/integrations/cadwiz_plugin/slim_panel.py").read_text(encoding="utf-8")
    assert source.index('"Cut-away"') < source.index('"Assembly"') < source.index('"Model"')
    assert '_button(QtWidgets, "collapse", bar)' in source              # on the Creating/Printing/Setup row now
