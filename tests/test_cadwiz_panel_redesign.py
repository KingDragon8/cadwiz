# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""ORDER-2026-10-18-01: the redesigned CADWiz panel's plain values (no Qt needed).

The real panel in real FreeCAD -- workbench switches, the Sketcher, Show Claude,
pop out and dock back -- is scripts/panel_redesign_witness.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from integrations.cadwiz_plugin import panel_host, slim_panel

ROOT = Path(__file__).resolve().parents[1]


def _record(version, kind="edit", diff="", note="", utc="2026-10-18T18:14:00Z", broken=None, restored_from=None, render=""):
    return SimpleNamespace(version=version, kind=kind, diff=diff, note=note, utc=utc, broken=broken or [], restored_from=restored_from,
                           render=render)


def test_the_light_is_green_or_red_and_red_says_what_to_do() -> None:
    assert slim_panel.connection(SimpleNamespace(connected=True)) == {"light": slim_panel.GREEN, "line": "Connected to Claude", "todo": ""}
    off = slim_panel.connection(SimpleNamespace(connected=False))
    assert off["light"] == slim_panel.RED and off["todo"].startswith("Open your assistant app")
    none = slim_panel.connection(None)
    assert none["light"] == slim_panel.RED and "close and reopen FreeCAD" in none["line"] and none["todo"]


def test_just_after_freecad_opens_the_light_is_amber_connecting_not_a_red_error() -> None:
    # ORDER-2026-10-20-01: red for the first half-minute read like something he had to fix.
    waiting = SimpleNamespace(connected=False, last_hello=0.0)
    early = slim_panel.connection(waiting, seconds_open=10)
    assert early["light"] == slim_panel.AMBER and early["line"].startswith("Connecting") and "Nothing to do" in early["todo"]
    late = slim_panel.connection(waiting, seconds_open=slim_panel.CONNECTING_GRACE_S + 1)
    # ORDER-2026-10-23-02: red with the app open is fixed by quitting the app fully; the line says so.
    assert late["light"] == slim_panel.RED and "Quit the app fully" in late["todo"]
    lost = slim_panel.connection(SimpleNamespace(connected=False, last_hello=123.0), seconds_open=10)
    assert lost["light"] == slim_panel.RED                      # it was connected and went away: say so at once


def test_the_time_slider_names_each_stop_and_flags_broken_ones() -> None:
    stops = slim_panel.timeline_stops([
        _record(1, "backup", diff="backup of the model as it was before any change", note="backup"),
        _record(2, diff="wall 1.6 -> 2 mm"),
        _record(3, "backup", note="checkpoint you saved", broken=["Pocket"]),
        _record(4, "restore", diff="restored version 2 exactly", restored_from=2),
    ])
    assert [s["what"] for s in stops] == ["before the assistant's first change", "wall 1.6 -> 2 mm", "your checkpoint", "brought back version 2"]
    assert [s["who"] for s in stops] == ["", "by your assistant", "", ""]
    assert stops[2]["broken"] == ["Pocket"]
    assert slim_panel.stop_caption(stops[1], 4).startswith("Version 2 of 4 — wall 1.6 -> 2 mm, by your assistant — ")
    assert slim_panel.broken_caption(stops[2]) == ("v3 broke (Pocket in error). You can still restore it, or slide past it to a good one.")
    assert slim_panel.broken_caption(stops[1]) == ""


def test_the_header_and_last_change_lines() -> None:
    assert slim_panel.version_line("CoolOff_AI1", 6) == "CoolOff_AI1 — version 6 of 6"
    assert slim_panel.version_line("CoolOff_AI1", 0) == "CoolOff_AI1 — no saved versions yet"
    assert slim_panel.version_line("", 0) == "No model open"
    stop = slim_panel.timeline_stops([_record(2, diff="walls 1.6 -> 2.0 mm")])[0]
    assert slim_panel.last_change_line(stop) == "Last change: walls 1.6 -> 2.0 mm, by your assistant"
    assert slim_panel.last_change_line(slim_panel.timeline_stops([_record(1, "backup")])[0]) == ""


def test_pictures_keep_their_shape_inside_the_screen() -> None:
    assert slim_panel.fit(800, 400, 1.0) == (200.0, 0.0, 400.0, 400.0)
    assert slim_panel.fit(400, 800, 2.0) == (0.0, 300.0, 400.0, 200.0)


def test_a_popped_out_window_returns_to_the_main_screen_when_its_monitor_is_gone() -> None:
    screens = [("PanasonicTV0", (0, 0, 1920, 1040)), ("S34CG50", (-3440, -359, 3440, 1400))]
    primary = screens[0][1]
    remembered = (-3000, 0, 1400, 1100)
    assert panel_host.on_screen(remembered, screens, "S34CG50", primary) == remembered        # still there: same place
    gone = [screens[0]]
    x, y, w, h = panel_host.on_screen(remembered, gone, "S34CG50", primary)
    assert (w, h) == (1400, 980) and 0 <= x and x + w <= 1920 and 0 <= y and y + h <= 1040   # same size, shrunk to fit, on the main screen
    assert panel_host.on_screen((5000, 5000, 900, 700), screens, "PanasonicTV0", primary) == (510, 170, 900, 700)


def test_the_wordmark_and_colours_are_the_approved_ones() -> None:
    assert slim_panel.WORDMARK_BLUE == "#42A5F5"
    source = (ROOT / "CADWiz/src/integrations/cadwiz_plugin/slim_panel.py").read_text(encoding="utf-8")
    assert 'QtWidgets.QLabel("CADWiz", header)' in source and 'QFont("Arial")' in source
    assert slim_panel.FOUNDER_BLUE != slim_panel.CLAUDE_ORANGE
    for removed in ("CADWiz_Key_Measurements", "Requirements", "Comments"):
        assert removed not in source, removed            # founder ruling 2026-10-18: none of these on the screen


def test_the_wiz_frames_are_the_approved_animation_frame_for_frame() -> None:
    manifest = json.loads((ROOT / "CADWiz/src/integrations/cadwiz_plugin/resources/wiz-eyes-strip.json").read_text(encoding="utf-8"))
    assert manifest["source_sha256"] == "127688CF208264B7C59A235BAA01C17F7F9B9BD1B4A598D15B690788128EC990"   # APPROVED-BASELINE.md
    assert manifest["frames"] == 45 and sum(manifest["durations_ms"]) == 6700
    from PIL import Image

    strip = Image.open(ROOT / "CADWiz/src/integrations/cadwiz_plugin/resources/wiz-eyes-strip.png")
    assert strip.size == (45 * manifest["frame_size"], manifest["frame_size"])


def test_the_toolbar_names_the_eight_marks_in_the_approved_order() -> None:
    assert [t[1] for t in slim_panel.TOOLS] == ["Point", "Circle", "Box", "Highlight", "Lasso", "Arrow", "Measure", "Note"]
    assert [v[1] for v in slim_panel.VIEWS] == ["Front", "Top", "Side", "Iso"]
    assert len(slim_panel.EXAMPLE_SENTENCES) == 5


# ---- ORDER-2026-10-19-01: page 1 on a short panel, Tasks on the left, marks that never fail silently ----
def test_the_scrolling_part_of_page_one_keeps_to_its_share() -> None:
    assert slim_panel.lower_max_height(1000) == 400            # the picture keeps most of a tall page
    assert slim_panel.lower_max_height(200) == slim_panel.LOWER_MIN_HEIGHT   # never squeezed to nothing
    assert slim_panel.CANVAS_MIN_HEIGHT < 220                    # the picture may shrink further than before


def test_every_drag_tool_says_how_when_it_is_only_clicked() -> None:
    drag_tools = {"circle", "box", "lasso", "arrow", "measure"}
    assert set(slim_panel.DRAG_HINTS) == drag_tools
    assert {key for key, _t, _tip in slim_panel.TOOLS} == drag_tools | {"point", "note", "highlight"}
    assert "Click a face" in dict((k, tip) for k, _t, tip in slim_panel.TOOLS)["highlight"]


class _FakeDock:
    def __init__(self, name: str) -> None:
        self.name, self.raised, self.floating = name, False, False

    def isFloating(self) -> bool:  # noqa: N802
        return self.floating

    def setFloating(self, on: bool) -> None:  # noqa: N802
        self.floating = on

    def raise_(self) -> None:
        self.raised = True


class _FakeWindow:
    LEFT, RIGHT = 1, 2

    def __init__(self) -> None:
        self.docks = {panel_host.TASKS_DOCK: _FakeDock(panel_host.TASKS_DOCK), panel_host.MODEL_DOCK: _FakeDock(panel_host.MODEL_DOCK)}
        self.area = {panel_host.TASKS_DOCK: self.RIGHT, panel_host.MODEL_DOCK: self.LEFT}
        self.tabbed: list[tuple[str, str]] = []

    def findChild(self, _cls, name):  # noqa: N802
        return self.docks.get(name)

    def dockWidgetArea(self, dock):  # noqa: N802
        return self.area[dock.name]

    def addDockWidget(self, area, dock):  # noqa: N802
        self.area[dock.name] = area

    def tabifyDockWidget(self, first, second):  # noqa: N802
        self.tabbed.append((first.name, second.name))

    def tabifiedDockWidgets(self, dock):  # noqa: N802
        return [self.docks[b] for a, b in self.tabbed if a == dock.name] + [self.docks[a] for a, b in self.tabbed if b == dock.name]


def _host_with(window: _FakeWindow, settings: dict) -> panel_host.PanelHost:
    host = panel_host.PanelHost.__new__(panel_host.PanelHost)
    host.window, host.settings = window, settings
    host.QtCore = SimpleNamespace(Qt=SimpleNamespace(LeftDockWidgetArea=_FakeWindow.LEFT))
    host.QtWidgets = SimpleNamespace(QDockWidget=object)
    host._save_timer = SimpleNamespace(start=lambda: None)
    return host


def test_tasks_goes_beside_model_at_every_start_until_it_is_there() -> None:
    # ORDER-2026-10-20-01: once was not enough -- Tasks ended up in a strip under the
    # property view, and he had asked "several times" for it beside Model.
    window, settings = _FakeWindow(), {}
    host = _host_with(window, settings)
    assert host.move_tasks_left() is True
    assert window.area[panel_host.TASKS_DOCK] == _FakeWindow.LEFT
    assert window.tabbed == [(panel_host.MODEL_DOCK, panel_host.TASKS_DOCK)]
    assert window.docks[panel_host.MODEL_DOCK].raised                  # Model stays in front
    assert host.move_tasks_left() is True and len(window.tabbed) == 1  # already beside Model: left alone
    window.tabbed.clear()                                               # next start: on the left, but its own strip
    assert host.move_tasks_left() is True
    assert window.tabbed == [(panel_host.MODEL_DOCK, panel_host.TASKS_DOCK)]


def test_no_tasks_panel_no_move_and_nothing_remembered() -> None:
    window, settings = _FakeWindow(), {}
    del window.docks[panel_host.TASKS_DOCK]
    assert _host_with(window, settings).move_tasks_left() is False
    assert panel_host.TASKS_MOVED_KEY not in settings
