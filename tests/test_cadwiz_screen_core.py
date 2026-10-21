# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""ORDER-2026-10-18-02 / -03: the domain-neutral pieces of the CADWiz screen --
his preferences (which Claude follows), licences in plain words, problems in plain
words, the concept stage, and the few questions that shape a design."""
from __future__ import annotations

import pytest

from ai_freecad_core.ai_master.design_contract import OBJECTIVE_METRICS
from ai_freecad_core.cadwiz_screen.concepts import ConceptCard, ConceptHistory
from ai_freecad_core.cadwiz_screen.intent import BUILD_RULES, MAX_ASKED, family_for, plan_questions
from ai_freecad_core.cadwiz_screen.licences import allowed_by, read_licence
from ai_freecad_core.cadwiz_screen.preferences import FounderPreferences, Printer
from ai_freecad_core.cadwiz_screen.problems import Problem, from_print_notes, gap_words, summary_line


# ---- preferences --------------------------------------------------------------------------------

def test_defaults_are_his_known_choices_and_become_rules_for_claude() -> None:
    prefs = FounderPreferences()
    assert (prefs.inches_first, prefs.text_px, prefs.explanations, prefs.questions, prefs.big_changes) == (True, 18, "short", "few", "ask")
    rules = " ".join(prefs.rules_for_claude())
    for words in ("short and plain", "at most three", "wait for their yes", "inches first", "My printer", "Printables"):
        assert words in rules, words


def test_each_choice_changes_what_claude_is_told() -> None:
    teach = FounderPreferences(explanations="teach", questions="none", big_changes="go_ahead", licences="sellable_only", inches_first=False)
    rules = " ".join(teach.rules_for_claude())
    assert "teach as you go" in rules and "use sensible defaults" in rules and "go ahead" in rules
    assert "only offer ones the user can sell" in rules and "millimetres first" in rules


def test_bad_values_are_refused_and_a_hand_edited_file_falls_back_per_field() -> None:
    with pytest.raises(ValueError):
        FounderPreferences(text_px=12)                       # under the 18 px standard
    with pytest.raises(ValueError):
        FounderPreferences(explanations="lecture")
    with pytest.raises(ValueError):
        Printer("", 200)
    prefs = FounderPreferences.from_dict({"text_px": 99, "explanations": "teach", "unknown": 1,
                                          "printers": [{"name": "Neptune 4 Pro", "bed_x_mm": 225, "bed_y_mm": 225, "bed_z_mm": 265}],
                                          "default_printer": "Neptune 4 Pro"})
    assert prefs.text_px == 18 and prefs.explanations == "teach" and prefs.printer.name == "Neptune 4 Pro"
    assert FounderPreferences.from_dict(None) == FounderPreferences()
    again = FounderPreferences.from_dict(prefs.to_dict())
    assert again == prefs


# ---- licences ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, can_sell, words", [
    ("CC BY-NC 4.0", False, "not for selling"),                       # the Golden Retriever Wizard's licence
    ("Creative Commons - Attribution - Non-Commercial", False, "not for selling"),
    ("Standard Digital File License", False, "not for selling"),
    ("CC BY 4.0", True, "credit the designer"),
    ("CC0", True, "can be printed and sold"),
    ("CC BY-ND", True, "must not be changed"),
    ("", None, "licence unknown"),
    ("Some shop licence", None, "not recognised"),
])
def test_licences_in_plain_words(text, can_sell, words) -> None:
    reading = read_licence(text)
    assert reading.can_sell is can_sell and words in reading.plain


def test_his_licence_setting_filters_only_sellable() -> None:
    assert allowed_by("personal_ok", read_licence("CC BY-NC")) is True
    assert allowed_by("sellable_only", read_licence("CC BY-NC")) is False
    assert allowed_by("sellable_only", read_licence("unknown thing")) is False      # unknown is never assumed sellable
    assert allowed_by("sellable_only", read_licence("CC BY")) is True


# ---- problems -----------------------------------------------------------------------------------------

def test_problems_say_what_how_and_why_in_plain_words_with_both_units() -> None:
    gap = gap_words("the Stick", "the Jaw", 0.5)
    assert gap == "the Stick doesn't touch the Jaw: a 0.02 in (0.5 mm) gap means it prints as a loose piece"
    problem = Problem("loose", gap, ["Stick"], detail_for_claude="min distance 0.5000 mm")
    founder = problem.for_founder()
    assert founder["heading"] == "A loose piece" and "touches" in founder["how_to_fix"] and "falls over" in founder["explain"] or "fall over" in founder["explain"]
    assert "detail_for_claude" not in founder                         # the founder never sees FreeCAD's own words
    with pytest.raises(ValueError):
        Problem("gremlins", "x")
    assert summary_line([]).startswith("No problems found")
    assert summary_line([problem, problem]) == "2 problems found."


def test_the_print_check_notes_become_problems() -> None:
    notes = ["does not fit the My printer bed (300 mm (11.8 in) x ...)", "wall 0.5 mm (0.02 in) is under the printer's 0.8 mm minimum",
             "steep overhangs found", "size unknown; something else"]
    kinds = [p.kind for p in from_print_notes(notes)]
    assert kinds == ["bed", "thin", "overhang"]


# ---- the concept stage ----------------------------------------------------------------------------------

def _card(title="Dog with a stick", **extra) -> ConceptCard:
    return ConceptCard(title, "a.png", extra.pop("kind", "found"), extra.pop("source", "https://www.thingiverse.com/thing:5190074"),
                       extra.pop("licence", "CC BY-NC"), **extra)


def test_cards_say_where_they_came_from_and_whether_3d_exists() -> None:
    found = _card(has_3d_file=True, model_url="https://www.thingiverse.com/thing:5190074")
    assert found.licence_line().endswith("not for selling") and found.three_d_line().startswith("3D file: yes")
    sketch = ConceptCard("Bone instead", "b.svg", "sketch")
    assert sketch.licence_line() == "Claude's own sketch -- yours to use" and sketch.three_d_line() == "3D file: no -- Claude would model it"
    with pytest.raises(ValueError):
        ConceptCard("No source", "c.png", "found")                  # a found design always names its source
    with pytest.raises(ValueError):
        ConceptCard("x", "c.png", "photoreal")                      # no third kind: Claude does not generate photos


def test_rounds_picks_and_make_it_3d_only_on_his_say_so() -> None:
    history = ConceptHistory()
    with pytest.raises(ValueError):
        history.add_round([_card(), _card(), _card(), _card()])     # at most three
    first = history.add_round([_card("Stick"), _card("Ball")], "two dogs")
    with pytest.raises(ValueError):
        history.request_3d()                                        # nothing picked: nothing becomes 3D
    history.pick(1, 1)
    assert history.summary()["make_3d_requested"] is None           # picking is not making it 3D
    second = history.add_round([ConceptCard("Bone", "bone.svg", "sketch")], "same dog, a bone instead of the stick")
    history.pick(2, 1)
    assert first.picked is None and second.picked == 1              # one choice at a time
    asked = history.request_3d()
    assert asked["title"] == "Bone" and history.summary()["make_3d_requested"]["round"] == 2
    history.add_round([_card("Another")])
    assert history.make_3d is None                                  # a new round is a new choice
    again = ConceptHistory.from_dict(history.to_dict())
    assert [r.note for r in again.rounds] == [r.note for r in history.rounds] and again.rounds[1].picked == 1
    assert len(history.summary()["history"]) == 3 and "Do not build anything in 3D" in history.summary()["rule"]


# ---- guided intent ----------------------------------------------------------------------------------------

def test_a_fishing_lure_asks_about_the_fish_first_and_at_most_three_things() -> None:
    plan = plan_questions("I want a fishing lure", "few", material_default="PETG")
    assert plan["family"] == "fishing lure"
    assert len(plan["ask"]) == MAX_ASKED and plan["ask"][0].startswith("1. What fish is it for?")
    assert all("default:" in line for line in plan["ask"])
    assert any(line.startswith("Floating or sinking: floating") for line in plan["assumed_defaults"])
    assert any("PETG (your Setup choice)" in line for line in plan["assumed_defaults"])
    record = plan["record_with"]
    assert {r["metric"] for r in record["requirements"]} <= OBJECTIVE_METRICS
    assert any(r["name"] == "length" and r["target"] == 76.0 for r in record["requirements"])


def test_just_make_it_and_the_no_questions_setting_ask_nothing() -> None:
    assert plan_questions("a shelf bracket, just make it")["ask"] == []
    plan = plan_questions("a shelf bracket", "none")
    assert plan["ask"] == [] and "say in one line which ones you used" in plan["how_to_ask"]
    assert len(plan["assumed_defaults"]) == len(family_for("a shelf bracket").questions)


def test_each_kind_of_thing_gets_its_own_questions_and_route() -> None:
    assert family_for("a bridge for my train set").name == "bridge"
    assert family_for("a knob for my stove").name == "knob"
    assert family_for("a dog figurine holding a bone").route == "blender"
    assert family_for("a widget").name == "part"
    rules = " ".join(BUILD_RULES)
    for words in ("PartDesign Body", "fillet", "sliding fit 0.3 mm", "two nozzle widths", "45 degrees", "Blender"):
        assert words in rules, words
