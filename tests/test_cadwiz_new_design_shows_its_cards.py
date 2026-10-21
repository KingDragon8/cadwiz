# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Founder, 2026-10-19: "I don't see the three options."

FreeCAD opened with the tennis-ball designs (one round) on the screen. Claude then
posted three trash-can sketches as a NEW design, which starts its history again
at round 1. The panel switched to "Choosing a design" only when the NUMBER of
rounds went up, so it stayed on the model and he never saw the cards.

The real ConceptHistory; a stand-in panel (render needs Qt).
"""
from __future__ import annotations

from types import SimpleNamespace

from ai_freecad_core.cadwiz_screen.concepts import ConceptCard, ConceptHistory
from integrations.cadwiz_plugin.panel_pages import ConceptsView


def _cards(*titles: str) -> list[ConceptCard]:
    return [ConceptCard(title=t, picture=f"{t}.svg", kind="sketch") for t in titles]


def _view(history: ConceptHistory) -> ConceptsView:
    view = ConceptsView.__new__(ConceptsView)          # no Qt: only the watching is under test
    view.panel = SimpleNamespace(screen=lambda: SimpleNamespace(concepts=history))
    view.seen_rounds, view.showing = -1, 0
    view.render = lambda: None
    return view


def test_a_new_design_after_an_old_one_switches_the_screen_even_at_round_one() -> None:
    history = ConceptHistory()
    history.add_round(_cards("A. Classic: seam as a groove", "B. Raised white seam", "C. Two halves"))
    view = _view(history)
    assert view.watch() is False                       # what was there when FreeCAD opened: no switch

    history.rounds.clear()                             # new_design: the history starts again
    history.add_round(_cards("A. Classic galvanized", "B. Plain and simple", "C. Lid tipped open"))
    assert len(history.rounds) == 1                    # the same count as before
    assert view.watch() is True                        # ...and still the screen switches
    assert view.watch() is False                       # once


def test_a_further_round_of_the_same_design_still_switches() -> None:
    history = ConceptHistory()
    history.add_round(_cards("A", "B"))
    view = _view(history)
    view.watch()
    history.add_round(_cards("A, taller"))
    assert view.watch() is True and view.showing == 2


def test_an_empty_history_never_switches() -> None:
    view = _view(ConceptHistory())
    assert view.watch() is False
    assert view.watch() is False
