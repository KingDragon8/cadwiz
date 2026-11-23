from types import SimpleNamespace as NS
import importlib.util
from pathlib import Path

import pytest

from integrations.cadwiz_plugin.gear_quality import lofted_gears


def test_detects_hidden_loft_used_by_visible_gear_without_geometry_calls():
    gear = NS(NumberOfTeeth=20, Modules=2)
    body = NS(TypeId="PartDesign::Body", ViewObject=NS(Visibility=True))
    loft = NS(TypeId="PartDesign::AdditiveLoft", Profile=gear, Sections=[],
              getParentGeoFeatureGroup=lambda: body, ViewObject=NS(Visibility=False))
    body.Tip = NS(OutListRecursive=[loft])
    assert lofted_gears([loft]) == [loft]
    body.Tip.OutListRecursive = []
    assert lofted_gears([loft]) == []  # unused historical feature
    body.Tip.OutListRecursive = [loft]
    body.ViewObject.Visibility = False
    assert lofted_gears([loft]) == []  # another hidden revision


def test_ordinary_loft_and_native_helix_are_not_reported():
    common = dict(ViewObject=NS(Visibility=True), Sections=[], Profile=NS())
    assert lofted_gears([NS(TypeId="PartDesign::AdditiveLoft", **common)]) == []
    common["Profile"] = NS(NumberOfTeeth=60, Modules=2)
    assert lofted_gears([NS(TypeId="PartDesign::AdditiveHelix", **common)]) == []


def test_warning_reaches_existing_problem_panel(monkeypatch):
    from integrations.cadwiz_plugin import problems_watch

    loft = NS(Name="GearLoft", Label="Gear teeth", TypeId="PartDesign::AdditiveLoft",
              Profile=NS(NumberOfTeeth=20, Modules=2), Sections=[],
              ViewObject=NS(Visibility=True))
    monkeypatch.setattr(problems_watch, "_in_freecad_window", lambda: False)
    monkeypatch.setattr(problems_watch, "_loose_and_overlapping", lambda objects: [])
    found = problems_watch.find_problems(NS(Objects=[loft]))
    warning = next(p for p in found if p.kind == "gear_profile")
    assert warning.objects == ["GearLoft"]
    assert "Check the gear tooth shape" == warning.for_founder()["heading"]


def checker():
    path = Path(__file__).resolve().parents[1] / "scripts/check_gear_tooth_sections.py"
    spec = importlib.util.spec_from_file_location("gear_section_checker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_sections


def samples():
    # A zero-twist extrusion has identical sections throughout its width.
    outline = [[-2, -1], [2, -1], [2, 1], [-2, 1], [-2, -1]]
    return {"test": {"reference": outline, "height_mm": 8,
                     "sampling_deflection_mm": .005, "twist_deg": 0,
                     "sections": [{"z": z, "points": [outline]} for z in (1, 3, 5, 7)]}}


def test_section_check_rejects_distorted_intermediate_shape():
    check = checker()
    data = samples()
    assert check(data)["passed"]
    data["test"]["sections"][1]["points"] = [[[-2, -1], [2, -1], [2, .5], [-2, .5], [-2, -1]]]
    assert not check(data)["passed"]


def test_missing_intermediate_samples_and_coarse_sampling_cannot_pass():
    check = checker()
    data = samples()
    data["test"]["sections"].pop()
    with pytest.raises(ValueError, match="missing intermediate"):
        check(data)
    with pytest.raises(ValueError, match="too coarse"):
        check(samples(), .001)


def test_missing_sample_file_returns_an_explicit_failure(monkeypatch, tmp_path, capsys):
    import json
    import sys

    main = checker().__globals__["main"]
    monkeypatch.setattr(sys, "argv", ["check", str(tmp_path / "absent.json")])
    assert main() == 2
    assert json.loads(capsys.readouterr().out)["passed"] is False
