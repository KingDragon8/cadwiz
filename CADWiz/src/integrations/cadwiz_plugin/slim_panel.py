# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The CADWiz panel inside FreeCAD: the Visual Communications Screen.

ORDER-2026-10-18-01 (docs/CADWIZ-PANEL-REDESIGN-PROPOSAL.md, revision 2, approved
by the founder on 2026-10-18: "these are very good suggestions, and I want them
all implemented professionally"). It replaces the slim panel of ORDER-2026-10-12-05.

The founder talks to Claude in the Claude app. This panel is where he and Claude
look at the same model, point at it and mark it up. One screen, no tabs:

  header   the Wiz (the approved eye animation) and the CADWiz wordmark; the
           connection light (red says exactly what to do); the model and its
           version; Pop out / Dock back; collapse to a strip
  screen   the open model in any workbench, with Front / Top / Side / Iso /
           Cut-away; his marks in blue and Claude's in orange, anchored to the
           model so they stay put when the view turns
  marking  Point, Circle, Box, Highlight, Lasso, Arrow, Measure, Note, Undo mark,
           Clear -- marks only, never the model -- and Show Claude, which freezes
           the frame Claude reads on his next message ("Claude has it")
  versions a time slider over full saved copies: broken ones red but still
           restorable, Restore never deletes a newer version, Compare with now,
           Save a checkpoint
  footer   Make and Setup (each opens as a full screen) and the build number

No key-measurements card, requirements card or comments box (founder ruling
2026-10-18: comments go in the Claude app). The old chat and voice panel is only
reachable through the hidden developer switch (docs/ARCHIVE-CADWIZ-ASSISTANT.md).

`panel_lines`, `timeline_stops` and `stop_caption` are plain values, tested
without Qt. Everything that touches FreeCAD's view is in `view_link`; the docking,
collapse, pop-out and workbench independence are in `panel_host`.
"""
from __future__ import annotations

import contextlib
import json
import random
import time
from importlib import import_module
from pathlib import Path
from typing import Any, Callable

from ai_freecad_core.visual_communications.anchored import (
    AnchoredMark,
    Camera,
    MarkBook,
    PlacedMark,
    inches_first,
    place,
)
from ai_freecad_core.visual_communications.contracts import VisualMarkAuthor, VisualMarkKind

# ---- colours and words ------------------------------------------------------------------
GREEN, RED, GREY, AMBER = "#1E8E3E", "#D93025", "#8A8F98", "#E37400"
WORDMARK_BLUE = "#42A5F5"           # founder's choice 2026-10-18: the light demo blue
FOUNDER_BLUE = "#1565C0"
CLAUDE_ORANGE = "#E8710A"
BROKEN_RED = "#D93025"
INK = "#162331"
TEXT_PX = 18                        # docs/UI-LAYOUT-STANDARD.md: normal content at least 18 px

CONNECTED = "Connected to Claude"
# ORDER-2026-10-20-01: "It's not connected open in the Claude app. I don't know what
# that means. I thought all I needed to do was open CADWiz when Claude was [open]."
# He was right: that is all. The light was red for the first half-minute after
# FreeCAD opened, before the Claude app's first check-in, and read like an error.
CONNECTING = "Connecting to Claude\u2026"
CONNECTING_TODO = "Nothing to do: the Claude app checks in within 30 seconds."
NOT_CONNECTED = "Not connected to Claude"
NOT_CONNECTED_TODO = ("Open the Claude app on this PC -- that is all; this turns green by itself within 30 seconds. "
                      "If it stays red, quit the Claude app fully and open it again.")
#: How long after FreeCAD opens the light waits (amber) for the first check-in.
CONNECTING_GRACE_S = 45.0
NO_BRIDGE = "Not connected — CADWiz's plug-in did not start; close and reopen FreeCAD"
NO_BRIDGE_TODO = "Close FreeCAD and open it again. If the light stays red, open Setup below."
NO_PICTURE = "A picture of the model appears here after Claude builds or changes it."
NO_MODEL = "Open or create a model in FreeCAD and it appears here, in any workbench."
FROZEN = "Frozen. Now tell Claude what you mean in the Claude app."
CLAUDE_HAS_IT = "Claude has it"

TOOLS = (("point", "Point", "Pin a spot"), ("circle", "Circle", "Circle a region: drag from the middle out"),
         ("box", "Box", "Draw a rectangle around a region"),
         ("highlight", "Highlight", "Click a face to paint it, or drag to paint an area"),
         ("lasso", "Lasso", "Draw free-hand around something"), ("arrow", "Arrow", "Point from one place to another"),
         ("measure", "Measure", "Drag between two points: the distance shows in inches and mm"),
         ("note", "Note", "Pin a short note to a spot"))
VIEWS = (("front", "Front"), ("top", "Top"), ("side", "Side"), ("iso", "Iso"))

# ---- THE BUTTON TABLE (ORDER-2026-10-21-01; how to change it: docs/CUSTOMIZING.md) --------
#: Every main button on the CADWiz panel: key -> (the words on it, its object name,
#: the tooltip). Change the words or the tooltip here and nothing else needs to change.
BUTTONS: dict[str, tuple[str, str, str]] = {
    "pop_out": ("Pop out", "CADWiz_Pop_Out", "Open CADWiz in its own window, for a second screen. Dock back returns it here."),
    "collapse": ("Collapse", "CADWiz_Collapse", "Shrink CADWiz to a thin strip (the Wiz, the light and Show Claude)"),
    "cut_away": ("Cut-away", "CADWiz_View_Cut_Away",
                 "See inside: the half nearest you is cut away in the picture (the model is not changed)"),
    "assembly": ("Assembly", "CADWiz_View_Assembly",
                 "Pull the parts apart in the picture -- a lid lifts off its can (the model is not changed)"),
    "model": ("Model", "CADWiz_Show_Model", "The live picture of the model open in FreeCAD: mark on it and press Show Claude"),
    "designs": ("Designs", "CADWiz_Show_Concepts", "The pictures Claude posts before anything is 3D: pick one, then Make it 3D. "
                                                   "The number is how many rounds of pictures this design has had"),
    "drawing": ("Drawing", "CADWiz_Show_Drawing", "The technical drawing of the model: front, top and side views, a 3D view, "
                                                  "sizes in inches and mm, and a title block. Save it as a PDF to print"),
    "show_claude": ("Show Claude", "CADWiz_Show_Claude",
                    "Freeze this picture, your marks, your selection, the view and the version for Claude to read on your next message"),
    "restore": ("Restore this version", "CADWiz_Restore_Version", ""),
    "compare": ("Compare with now", "CADWiz_Compare_Version", ""),
    "checkpoint": ("Save a checkpoint", "CADWiz_Save_Checkpoint",
                   "Keep a full copy of the model as it is now -- before you let Claude try something risky"),
}

#: Your own buttons, added at the end of the view row on the Creating page. Each is
#: (the words on it, a tooltip, the FreeCAD command it runs) -- any command name from
#: FreeCAD's Tools > Customize > Commands list, for example
#:     ("Fit", "Fit the whole model in the view", "Std_ViewFit"),
EXTRA_BUTTONS: list[tuple[str, str, str]] = []


def _button(QtWidgets: Any, key: str, parent: Any) -> Any:
    """A button from BUTTONS."""
    words, name, tip = BUTTONS[key]
    button = QtWidgets.QPushButton(words, parent)
    button.setObjectName(name)
    if tip:
        button.setToolTip(tip)
    return button


def assistant_word(ai_app: str) -> str:
    """The name on the Show button for the assistant chosen at the top of the panel
    (ORDER-2026-10-21-01: CADWiz works with Claude or ChatGPT; neither is the default)."""
    return {"claude": "Claude", "chatgpt": "ChatGPT"}.get(str(ai_app), "assistant")


def run_freecad_command(command: str) -> None:
    from importlib import import_module

    import_module("FreeCADGui").runCommand(command)
# A click where a drag is needed says so, instead of doing nothing.
DRAG_HINTS = {"circle": "Circle: press and drag from the middle out.", "box": "Box: press and drag from corner to corner.",
              "lasso": "Lasso: hold the button down and draw a loop around it.",
              "arrow": "Arrow: press where it starts and drag to where it points.",
              "measure": "Measure: press on one point and drag to the other."}
ASSEMBLY_NO_MARKS = "Marks go on the model as it really is: turn Assembly off to mark."
NO_FACE_HERE = "Highlight: click on a face of the model (or drag to paint an area)."

# Page 1 on a short panel (ORDER-2026-10-19-01): the picture never goes below
# CANVAS_MIN_HEIGHT; the scrolling part under the marking bar never below
# LOWER_MIN_HEIGHT and never above LOWER_MAX_SHARE of the page, so the picture
# keeps most of the room.
CANVAS_MIN_HEIGHT = 160
LOWER_MIN_HEIGHT = 100
LOWER_MAX_SHARE = 0.4
THUMB_SIZE = (80, 60)
# More room for the picture (ORDER-2026-10-19-05): a smaller header, and the two
# sections under the picture folded to one line each until he opens them.
HEADER_WIZ_PX = 44
# Windows gives every button a least width of about 100 px on his screen, so
# "Top" took the room of "Highlight" and the marking buttons wrapped into four
# rows (FreeCAD's own theme sets that least width; CADWiz's style lifts it for
# these buttons). View and marking buttons are sized to their own words instead.
SNUG_PAD = 9
WORDMARK_PX = 26
FOLDS = {"problems": "Problems and fixes", "versions": "Time machine"}

EXAMPLE_SENTENCES = (
    "What's open in FreeCAD right now, and how big is it?",
    "Look at what I'm showing you. Make this wall thicker.",
    "Measure the inside distance around the bottom opening.",
    "Go back to the version before the last change.",
    "Will this print on my printer? Show me any problems.",
)


# ---- plain values (tested without Qt) ---------------------------------------------------------
def connection(bridge: Any, seconds_open: float | None = None) -> dict[str, str]:
    """The light. `seconds_open`: how long the panel has been open; for the first
    CONNECTING_GRACE_S with no check-in yet it is amber "Connecting", not red."""
    if bridge is None:
        return {"light": RED, "line": NO_BRIDGE, "todo": NO_BRIDGE_TODO}
    if bridge.connected:
        return {"light": GREEN, "line": CONNECTED, "todo": ""}
    if seconds_open is not None and seconds_open < CONNECTING_GRACE_S and not getattr(bridge, "last_hello", 0):
        return {"light": AMBER, "line": CONNECTING, "todo": CONNECTING_TODO}
    return {"light": RED, "line": NOT_CONNECTED, "todo": NOT_CONNECTED_TODO}


def panel_lines(bridge: Any) -> dict[str, Any]:
    """What the header and the version strip show, from the plug-in session."""
    light = connection(bridge)
    if bridge is None:
        return {"light": light["light"], "connection": light["line"], "todo": light["todo"], "working_on": "Nothing yet",
                "measurements": "", "last_change": "", "versions": [], "picture": ""}
    session = getattr(bridge, "session", None)
    state = dict(getattr(session, "state", {}) or {})
    working = state.get("document") or ""
    if working and state.get("object"):
        working = f"{working} / {state['object']}"
    if working:
        working += f", version {state.get('version') or 1}"
    versions: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        executor = next((e for e in session._executors.values() if str(getattr(e, "founder_file", "")) == state.get("file")), None)
        if executor is not None:
            versions = [{"version": v.version, "kind": v.kind, "diff": v.diff} for v in executor.store.list_recent(8)]
    return {"light": light["light"], "connection": light["line"], "todo": light["todo"],
            "working_on": f"Working on: {working}" if working else "Working on: nothing yet -- ask Claude to open or build something",
            "measurements": state.get("measurements") or "", "last_change": f"Last change: {state['last_change']}" if state.get("last_change") else "",
            "versions": versions, "picture": state.get("picture") or ""}


def _local_time(utc: str) -> str:
    try:
        stamp = time.mktime(time.strptime(utc, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        return time.strftime("%b %d, %I:%M %p", time.localtime(stamp)).replace(" 0", " ")
    except (ValueError, OverflowError, TypeError):
        return ""


def timeline_stops(records: list[Any]) -> list[dict[str, Any]]:
    """One stop per saved version, oldest first: what it is, who made it, when,
    and whether it was broken (red, still restorable)."""
    stops = []
    for record in records:
        kind = str(getattr(record, "kind", "edit"))
        note = str(getattr(record, "note", "") or "")
        diff = str(getattr(record, "diff", "") or "")
        if kind == "restore":
            what, who = f"brought back version {getattr(record, 'restored_from', '?')}", ""
        elif kind == "backup":
            what = "your checkpoint" if "checkpoint" in note else ("before Claude's first change" if "before any change" in diff else
                                                                   (note if note and note not in ("backup", "saved on request") else "saved copy"))
            who = ""
        else:
            what, who = (diff or note or "a change"), "by Claude"
        broken = [str(b) for b in (getattr(record, "broken", None) or [])]
        stops.append({"version": int(record.version), "what": what, "who": who, "when": _local_time(str(getattr(record, "utc", "") or "")),
                      "broken": broken, "render": str(getattr(record, "render", "") or ""), "kind": kind,
                      "restored_from": getattr(record, "restored_from", None)})
    return stops


def stop_caption(stop: dict[str, Any], latest: int) -> str:
    parts = [f"Version {stop['version']} of {latest}", stop["what"]]
    if stop["who"]:
        parts[-1] += f", {stop['who']}"
    if stop["when"]:
        parts.append(stop["when"])
    return " — ".join(parts)


def broken_caption(stop: dict[str, Any]) -> str:
    if not stop.get("broken"):
        return ""
    return (f"v{stop['version']} broke ({', '.join(stop['broken'][:4])} in error). "
            "You can still restore it, or slide past it to a good one.")


def version_line(document_label: str, latest: int) -> str:
    if not document_label:
        return "No model open"
    return f"{document_label} — version {latest} of {latest}" if latest else f"{document_label} — no saved versions yet"


def last_change_line(stop: dict[str, Any] | None) -> str:
    if not stop or stop["kind"] == "backup":
        return ""
    return f"Last change: {stop['what']}" + (f", {stop['who']}" if stop["who"] else "")


# ---- drawing marks (the screen and the frozen frame use the same code) -------------------------
def _qt() -> tuple[Any, Any, Any]:
    return import_module("PySide.QtCore"), import_module("PySide.QtGui"), import_module("PySide.QtWidgets")


def paint_marks(painter: Any, rect: Any, marks: list[AnchoredMark], camera: Camera | None, aspect: float, scale: float = 1.0,
                inches_first_labels: bool = True) -> None:
    """Draw `marks` over a picture occupying `rect` that was taken with `camera`."""
    if camera is None:
        return
    QtCore, QtGui, _w = _qt()
    font = QtGui.QFont("Arial")
    font.setPixelSize(max(11, int(16 * scale)))
    font.setBold(True)
    painter.setFont(font)
    for mark in marks:
        placed = place(mark, camera, aspect)
        if placed.visible:
            _paint_one(painter, rect, placed, aspect, scale, QtCore, QtGui, inches_first_labels)


def _paint_one(painter: Any, rect: Any, placed: PlacedMark, aspect: float, scale: float, QtCore: Any, QtGui: Any,
               inches_first_labels: bool) -> None:
    mark = placed.mark
    colour = QtGui.QColor(FOUNDER_BLUE if mark.author is VisualMarkAuthor.USER else CLAUDE_ORANGE)
    pen = QtGui.QPen(colour, max(2.0, 3.0 * scale))
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)

    def at(point: tuple[float, float]) -> Any:
        return QtCore.QPointF(rect.left() + point[0] * rect.width(), rect.top() + point[1] * rect.height())

    pts = [at(p) for p in placed.points]
    kind = mark.kind
    badge_at = pts[0]
    if kind in (VisualMarkKind.POINT, VisualMarkKind.NOTE):
        painter.setBrush(colour)
        painter.drawEllipse(pts[0], 7 * scale, 7 * scale)
        if kind is VisualMarkKind.NOTE:
            _bubble(painter, QtCore.QPointF(pts[0].x() + 12 * scale, pts[0].y() - 30 * scale), f"{mark.number}  {mark.text or 'Note'}",
                    colour, scale, QtCore, QtGui)
            return
    elif kind is VisualMarkKind.CIRCLE:
        radius = placed.radius * rect.height()
        painter.drawEllipse(pts[0], radius, radius)
        badge_at = QtCore.QPointF(pts[0].x() + radius * 0.71, pts[0].y() - radius * 0.71)
    elif kind in (VisualMarkKind.RECTANGLE, VisualMarkKind.HIGHLIGHT):
        xs, ys = [p.x() for p in pts], [p.y() for p in pts]
        box = QtCore.QRectF(QtCore.QPointF(min(xs), min(ys)), QtCore.QPointF(max(xs), max(ys)))
        if kind is VisualMarkKind.HIGHLIGHT:
            fill = QtGui.QColor(colour)
            fill.setAlpha(70)
            painter.setBrush(fill)
        if kind is VisualMarkKind.HIGHLIGHT and len(pts) > 2:
            painter.drawPolygon(QtGui.QPolygonF(pts))            # the face's own outline, as it looks from here
        else:
            painter.drawRect(box)
        badge_at = box.topLeft()
    elif kind is VisualMarkKind.LASSO:
        painter.drawPolygon(QtGui.QPolygonF(pts))
        badge_at = min(pts, key=lambda p: p.y())
    elif kind in (VisualMarkKind.ARROW, VisualMarkKind.MEASUREMENT):
        start, end = pts[0], pts[1]
        painter.drawLine(start, end)
        dx, dy = end.x() - start.x(), end.y() - start.y()
        length = max((dx * dx + dy * dy) ** 0.5, 1e-6)
        ux, uy = dx / length, dy / length
        if kind is VisualMarkKind.ARROW:
            head = 14 * scale
            for side in (1, -1):
                painter.drawLine(end, QtCore.QPointF(end.x() - head * ux + side * head * 0.5 * uy, end.y() - head * uy - side * head * 0.5 * ux))
        else:
            tick = 7 * scale
            for p in (start, end):
                painter.drawLine(QtCore.QPointF(p.x() - tick * uy, p.y() + tick * ux), QtCore.QPointF(p.x() + tick * uy, p.y() - tick * ux))
            mm = mark.length_mm or 0.0
            label = inches_first(mm) if inches_first_labels else f"{mm:.1f} mm ({mm / 25.4:.2f} in)"
            mid = QtCore.QPointF((start.x() + end.x()) / 2, (start.y() + end.y()) / 2)
            _bubble(painter, QtCore.QPointF(mid.x() + 8 * scale, mid.y() - 30 * scale), label, colour, scale, QtCore, QtGui)
    _badge(painter, badge_at, mark.number, colour, scale, QtCore, QtGui)


def _badge(painter: Any, centre: Any, number: int, colour: Any, scale: float, QtCore: Any, QtGui: Any) -> None:
    radius = 11 * scale
    painter.setPen(QtGui.QPen(QtGui.QColor("white"), max(1.5, 2 * scale)))
    painter.setBrush(colour)
    painter.drawEllipse(centre, radius, radius)
    painter.setPen(QtGui.QColor("white"))
    painter.drawText(QtCore.QRectF(centre.x() - radius, centre.y() - radius, 2 * radius, 2 * radius), QtCore.Qt.AlignCenter, str(number))


def _bubble(painter: Any, top_left: Any, text: str, colour: Any, scale: float, QtCore: Any, QtGui: Any) -> None:
    metrics = QtGui.QFontMetricsF(painter.font())
    width = metrics.horizontalAdvance(text) + 16 * scale
    height = metrics.height() + 8 * scale
    box = QtCore.QRectF(top_left.x(), top_left.y(), width, height)
    painter.setPen(QtGui.QPen(colour, max(1.5, 2 * scale)))
    painter.setBrush(QtGui.QColor(255, 255, 255, 235))
    painter.drawRoundedRect(box, 6 * scale, 6 * scale)
    painter.setPen(QtGui.QColor(INK))
    painter.drawText(box, QtCore.Qt.AlignCenter, text)


def fit(width: float, height: float, aspect: float) -> tuple[float, float, float, float]:
    """The largest rectangle of shape `aspect` centred in width x height."""
    if width <= 0 or height <= 0 or aspect <= 0:
        return 0.0, 0.0, 0.0, 0.0
    if width / height > aspect:
        w, h = height * aspect, height
    else:
        w, h = width, width / aspect
    return (width - w) / 2, (height - h) / 2, w, h


# ---- the Wiz in the header (the approved animation, frame for frame) ---------------------------
RESOURCES = Path(__file__).resolve().parent / "resources"
#: Named, configurable idle thresholds (docs/characters/wiz-logo/CLAUDE-UI-ANIMATION-HANDOFF.md section 5).
DROWSY_AFTER_S = 180.0
SLEEP_AFTER_S = 300.0


class WizPlayer:
    """Plays the approved eye animation (resources/wiz-eyes-strip.png: every frame
    of approved-originals/cadwiz-eye-wake-blink-sleep-original.gif, cropped to its
    card and scaled; nothing redrawn). Wakes once when the panel opens, blinks now
    and then while awake, grows drowsy and sleeps after a quiet while, and wakes
    again on activity. If the frames are missing it shows the plain logo."""

    def __init__(self, label: Any, size: int) -> None:
        QtCore, QtGui, _w = _qt()
        self.label = label
        self.size = size
        self.frames: list[Any] = []
        self.durations: list[int] = []
        self.segments: dict[str, list[int]] = {}
        with contextlib.suppress(Exception):
            manifest = json.loads((RESOURCES / "wiz-eyes-strip.json").read_text(encoding="utf-8"))
            strip = QtGui.QPixmap(str(RESOURCES / "wiz-eyes-strip.png"))
            side = int(manifest["frame_size"])
            if not strip.isNull():
                self.frames = [strip.copy(i * side, 0, side, side).scaled(size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                               for i in range(int(manifest["frames"]))]
                self.durations = [int(d) for d in manifest["durations_ms"]]
                self.segments = {k: list(v) for k, v in manifest["segments"].items()}
        if not self.frames:
            logo = Path(__file__).resolve().parents[1] / "freecad_native" / "resources" / "cadwiz-logo.png"
            pixmap = QtGui.QPixmap(str(logo))
            if not pixmap.isNull():
                label.setPixmap(pixmap.scaled(size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            return
        self.state = "blank"
        self.last_activity = time.monotonic()
        self._queue: list[int] = []
        self._timer = QtCore.QTimer(label)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._step)
        self._idle = QtCore.QTimer(label)
        self._idle.setInterval(1000)
        self._idle.timeout.connect(self._tick)
        self._show(0)
        self._idle.start()
        QtCore.QTimer.singleShot(600, lambda: self._play("wake", then="awake"))

    def _show(self, index: int) -> None:
        if 0 <= index < len(self.frames):
            self.label.setPixmap(self.frames[index])

    def _range(self, name: str) -> list[int]:
        first, last = self.segments.get(name, [9, 9])
        return list(range(first, last + 1))

    def _play(self, segment: str, then: str) -> None:
        self._queue = self._range(segment)
        self._after = then
        self._timer.stop()
        self._step()

    def _step(self) -> None:
        if not self._queue:
            self.state = self._after
            return
        index = self._queue.pop(0)
        self._show(index)
        self._timer.start(max(30, self.durations[index] if index < len(self.durations) else 100))

    def _tick(self) -> None:
        if not self.frames or self._queue:
            return
        quiet = time.monotonic() - self.last_activity
        if self.state == "awake":
            if quiet > DROWSY_AFTER_S:
                self._queue = list(range(14, 27))
                self._after = "drowsy"
                self._step()
            elif random.random() < 0.18:
                self._play("blink_twice" if random.random() < 0.25 else "blink", then="awake")
        elif self.state == "drowsy" and quiet > SLEEP_AFTER_S:
            self._queue = list(range(27, 40))
            self._after = "asleep"
            self._step()

    def activity(self) -> None:
        if not self.frames:
            return
        self.last_activity = time.monotonic()
        if self.state in ("drowsy", "asleep") and not self._queue:
            self._play("wake", then="awake")


# ---- the panel -------------------------------------------------------------------------------
def build(dock: Any, QtCore: Any, QtWidgets: Any, bridge_provider: Callable[[], Any]) -> Any:
    """Fill `dock` with the CADWiz panel and keep it current."""
    QtGui = import_module("PySide.QtGui")
    panel = _Panel(dock, QtCore, QtGui, QtWidgets, bridge_provider)
    return panel.content


class _Panel:
    def __init__(self, dock: Any, QtCore: Any, QtGui: Any, QtWidgets: Any, bridge_provider: Callable[[], Any]) -> None:
        self.dock, self.QtCore, self.QtGui, self.QtWidgets = dock, QtCore, QtGui, QtWidgets
        self.bridge_provider = bridge_provider
        self._local_screen: Any = None
        self.tool = ""
        self.picture: Any = None
        self.picture_camera: Camera | None = None
        self.picture_aspect = 1.0
        self.picture_signature: Any = None
        self.pending_signature: Any = None
        self.pending_since = 0.0
        self.compare: dict[str, Any] | None = None
        self.flash_text = ""
        self.flash_until = 0.0
        self.flash_colour = GREEN
        self.seen_read: Any = None
        self.stops: list[dict[str, Any]] = []
        self.selected_stop = -1
        self.latest_version = 0
        self.opened_at = time.monotonic()
        self.settings = _load_settings()
        from integrations.cadwiz_plugin import preferences_store

        self.prefs = preferences_store.load()
        self.NO_MODEL = NO_MODEL
        self.FOUNDER_BLUE = FOUNDER_BLUE

        content = QtWidgets.QWidget(dock)
        content.setObjectName("CADWiz_Slim_Panel")
        content.setStyleSheet(style_sheet(self.prefs.text_px))
        content.setMinimumWidth(120)
        self.content = content
        outer = QtWidgets.QVBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.full = QtWidgets.QWidget(content)
        self.full.setObjectName("CADWiz_Full")
        outer.addWidget(self.full, 1)
        column = QtWidgets.QVBoxLayout(self.full)
        column.setContentsMargins(14, 10, 14, 10)
        column.setSpacing(8)
        column.addWidget(self._build_header())
        column.addWidget(self._build_page_bar())
        from integrations.cadwiz_plugin.panel_pages import PrintingPage, SetupPage

        self.pages = QtWidgets.QStackedWidget(self.full)
        self.pages.addWidget(self._build_screen_page())
        self.printing = PrintingPage(self)
        self.setup = SetupPage(self)
        self.pages.addWidget(self.printing.page)
        self.pages.addWidget(self.setup.page)
        column.addWidget(self.pages, 1)
        self.strip = self._build_strip()
        outer.addWidget(self.strip)
        self.strip.hide()
        dock.setWidget(content)

        screen = self.screen()
        screen.compose = self.compose_now
        screen.current_view = lambda: (self.picture_camera, self.picture_aspect)

        from integrations.cadwiz_plugin import panel_host

        self.host = panel_host.attach(dock, self)
        content._cadwiz_refresh = self.refresh       # type: ignore[attr-defined]
        content._cadwiz_panel = self                 # type: ignore[attr-defined]
        self.fast = QtCore.QTimer(content)
        self.fast.setInterval(200)
        self.fast.timeout.connect(self.watch_view)
        self.fast.start()
        self.slow = QtCore.QTimer(content)
        self.slow.setInterval(1000)
        self.slow.timeout.connect(self.refresh)
        self.slow.start()
        content.installEventFilter(_ActivityFilter.make(QtCore, self))
        self.refresh()

    # ---- shared state ---------------------------------------------------------------------
    def bridge(self) -> Any:
        with contextlib.suppress(Exception):
            return self.bridge_provider()
        return None

    def session(self) -> Any:
        return getattr(self.bridge(), "session", None)

    def screen(self) -> Any:
        session = self.session()
        if session is not None and getattr(session, "screen", None) is not None:
            return session.screen
        if self._local_screen is None:
            from integrations.cadwiz_plugin.screen import ScreenState
            from integrations.cadwiz_plugin.session import plugin_data_dir

            self._local_screen = ScreenState(plugin_data_dir())
        return self._local_screen

    def gui(self) -> Any:
        with contextlib.suppress(Exception):
            return import_module("FreeCADGui")
        return None

    def document(self) -> Any:
        with contextlib.suppress(Exception):
            return import_module("FreeCAD").ActiveDocument
        return None

    def view(self) -> Any:
        from integrations.cadwiz_plugin import view_link

        gui = self.gui()
        return view_link.active_view(gui) if gui is not None else None

    def run_paused(self, work: Callable[[], Any]) -> Any:
        """Run a panel action that calls the plug-in session: Claude's requests wait
        until it finishes (the bridge never runs two at once)."""
        bridge = self.bridge()
        was_busy = bool(getattr(bridge, "busy", False))
        if bridge is not None:
            bridge.busy = True
        self.QtWidgets.QApplication.setOverrideCursor(self.QtCore.Qt.WaitCursor)
        try:
            return work()
        finally:
            self.QtWidgets.QApplication.restoreOverrideCursor()
            if bridge is not None:
                bridge.busy = was_busy

    def _section(self, parent: Any, title: str, name: str = "") -> tuple[Any, Any]:
        """A white card with a bold heading line (Qt's group-box titles overlapped
        the row above them at the docked size)."""
        box = self.QtWidgets.QFrame(parent)
        box.setProperty("role", "section")
        if name:
            box.setObjectName(name)
        column = self.QtWidgets.QVBoxLayout(box)
        column.setContentsMargins(12, 10, 12, 10)
        column.setSpacing(6)
        heading = self.QtWidgets.QLabel(title, box)
        heading.setProperty("role", "heading")
        heading.setWordWrap(True)
        column.addWidget(heading)
        return box, column

    # ---- header ---------------------------------------------------------------------------
    def _build_header(self) -> Any:
        QtCore, QtWidgets = self.QtCore, self.QtWidgets
        header = QtWidgets.QFrame(self.full)
        header.setObjectName("CADWiz_Header")
        row = QtWidgets.QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.wiz = QtWidgets.QLabel(header)
        self.wiz.setObjectName("CADWiz_Wiz")
        # Smaller than it was (64 px, 34 px type) so the picture gets the room (ORDER-2026-10-19-05).
        self.wiz.setFixedSize(HEADER_WIZ_PX, HEADER_WIZ_PX)
        self.wiz.setAccessibleName("the Wiz")
        self.wiz_player = WizPlayer(self.wiz, HEADER_WIZ_PX)
        row.addWidget(self.wiz, 0, QtCore.Qt.AlignTop)
        wordmark = QtWidgets.QLabel("CADWiz", header)
        wordmark.setObjectName("CADWiz_Wordmark")
        font = self.QtGui.QFont("Arial")
        font.setBold(True)
        font.setPixelSize(WORDMARK_PX)
        wordmark.setFont(font)
        wordmark.setStyleSheet(f"color: {WORDMARK_BLUE};")
        row.addWidget(wordmark, 0, QtCore.Qt.AlignTop)
        info = QtWidgets.QVBoxLayout()
        info.setSpacing(2)
        self.light = QtWidgets.QLabel(header)
        self.light.setObjectName("CADWiz_Connection_Light")
        self.light.setProperty("role", "light")
        self.todo = QtWidgets.QLabel(header)
        self.todo.setObjectName("CADWiz_Connection_Todo")
        self.todo.setWordWrap(True)
        self.working = QtWidgets.QLabel(header)
        self.working.setObjectName("CADWiz_Working_On")
        self.working.setWordWrap(True)
        from integrations.cadwiz_plugin.panel_pages import AiChoice

        # One row: the light(s) and the Claude/ChatGPT choice, so the header never grows (ORDER-2026-10-19-02).
        self.ai_choice = AiChoice(self, header)
        self.ai_choice.row.insertWidget(0, self.light)
        # Connect (ORDER-2026-10-20-01): shown while the light is not green; opens the
        # Claude app if it is closed and says plainly what happened.
        self.connect_button = QtWidgets.QPushButton("Connect", header)
        self.connect_button.setObjectName("CADWiz_Connect")
        self.connect_button.setProperty("role", "primary")
        self.connect_button.setToolTip("Get Claude connected: opens the Claude app if it is closed, then waits for it to check in")
        self.connect_button.clicked.connect(self.connect_claude)
        self.connect_button.hide()
        self.connector = None
        self.ai_choice.row.insertWidget(1, self.connect_button)
        info.addLayout(self.ai_choice.row)
        for widget in (self.todo, self.working):
            info.addWidget(widget)
        row.addLayout(info, 1)
        return header

    def _build_page_bar(self) -> Any:
        """Creating · Printing · Setup, and Pop out (section 2.6)."""
        QtWidgets = self.QtWidgets
        bar = QtWidgets.QFrame(self.full)
        bar.setObjectName("CADWiz_Page_Bar")
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.page_buttons = []
        for index, name in enumerate(("Creating", "Printing", "Setup")):
            button = QtWidgets.QPushButton(name, bar)
            button.setObjectName(f"CADWiz_Page_{name}")
            button.setProperty("role", "page")
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, i=index: self.open_page(i))
            row.addWidget(button)
            self.page_buttons.append(button)
        self.page_buttons[0].setChecked(True)
        row.addStretch(1)
        self.pop_button = _button(QtWidgets, "pop_out", bar)
        self.pop_button.clicked.connect(lambda: self.host.toggle_floating())
        row.addWidget(self.pop_button)
        self.collapse_button = _button(QtWidgets, "collapse", bar)
        self.collapse_button.clicked.connect(lambda: self.host.collapse())
        row.addWidget(self.collapse_button)
        return bar

    # ---- the Visual Communications Screen ---------------------------------------------------
    def _build_screen_page(self) -> Any:
        QtCore, QtWidgets = self.QtCore, self.QtWidgets
        page = QtWidgets.QWidget(self.full)
        page.setObjectName("CADWiz_Screen_Page")
        column = QtWidgets.QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        # The view buttons and The model / Choosing a design share one row that
        # wraps only when the panel is narrow (ORDER-2026-10-19-01: one row less).
        top_row = QtWidgets.QWidget(page)
        top_row.setObjectName("CADWiz_View_Row")
        views = _make_flow_layout(QtCore, QtWidgets)(top_row, 6)
        self.view_buttons: dict[str, Any] = {}
        for key, text in VIEWS:
            button = QtWidgets.QPushButton(text, page)
            button.setObjectName(f"CADWiz_View_{text}")
            button.setProperty("role", "view")
            button.clicked.connect(lambda _c=False, k=key: self.turn(k))
            views.addWidget(button)
            self.view_buttons[key] = button
        self.cut_button = _button(QtWidgets, "cut_away", page)
        self.cut_button.setProperty("role", "view")
        self.cut_button.setCheckable(True)
        self.cut_button.clicked.connect(self.toggle_cut_away)
        views.addWidget(self.cut_button)
        self.assembly_button = _button(QtWidgets, "assembly", page)
        self.assembly_button.setProperty("role", "view")
        self.assembly_button.setCheckable(True)
        self.assembly_button.clicked.connect(self.toggle_assembly)
        views.addWidget(self.assembly_button)
        for words, tip, command in EXTRA_BUTTONS:
            extra = QtWidgets.QPushButton(words, page)
            extra.setProperty("role", "view")
            extra.setToolTip(tip)
            extra.clicked.connect(lambda _c=False, c=command: run_freecad_command(c))
            views.addWidget(extra)
        # The screen shows the model, or -- before any 3D -- the designs to choose
        # from (ORDER-2026-10-18-02 A).
        switch = views
        gap = QtWidgets.QWidget(top_row)
        gap.setFixedWidth(12)
        switch.addWidget(gap)
        # Short names so the whole row fits on one line with Assembly added
        # (ORDER-2026-10-19-05); the tooltips say what each one is for.
        self.show_model_button = _button(QtWidgets, "model", page)
        self.show_concepts_button = _button(QtWidgets, "designs", page)
        self.show_drawing_button = _button(QtWidgets, "drawing", page)
        for index, button in enumerate((self.show_model_button, self.show_concepts_button, self.show_drawing_button)):
            button.setProperty("role", "view")
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, i=index: self.show_screen(i))
            switch.addWidget(button)
        column.addWidget(top_row)
        self.screen_stack = QtWidgets.QStackedWidget(page)
        self.canvas = _make_canvas(QtCore, self.QtGui, QtWidgets)(self.screen_stack, self)
        self.canvas.setObjectName("CADWiz_Screen")
        from integrations.cadwiz_plugin.panel_pages import ConceptsView

        self.concepts_view = ConceptsView(self, self.screen_stack)
        self.screen_stack.addWidget(self.canvas)
        self.screen_stack.addWidget(self.concepts_view.widget)
        from integrations.cadwiz_plugin.drawing_screen import DrawingScreen

        self.drawing_screen = DrawingScreen(self, self.screen_stack)
        self.screen_stack.addWidget(self.drawing_screen.widget)
        # A stack is as tall as its tallest page, shown or not: set its least height
        # outright so the design cards never make the whole panel taller.
        self.screen_stack.setMinimumHeight(CANVAS_MIN_HEIGHT)
        column.addWidget(self.screen_stack, 1)
        self.show_model_button.setChecked(True)
        self.mark_toolbar = self._build_mark_toolbar(page)
        column.addWidget(self.mark_toolbar)
        # ORDER-2026-10-19-01: on a short panel (taskbar, a small screen, after
        # Collapse and Open) the bottom of this page was cut off. The picture and
        # the marking bar with Show Claude always stay in view; everything below
        # them scrolls, and takes the room it needs when there is room.
        lower = QtWidgets.QScrollArea(page)
        lower.setObjectName("CADWiz_Screen_Lower")
        lower.setWidgetResizable(True)
        lower.setFrameShape(QtWidgets.QFrame.NoFrame)
        lower.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        lower.setMinimumHeight(LOWER_MIN_HEIGHT)
        holder = QtWidgets.QWidget(lower)
        holder.setObjectName("CADWiz_Screen_Lower_Holder")
        below = QtWidgets.QVBoxLayout(holder)
        below.setContentsMargins(0, 0, 0, 0)
        below.setSpacing(6)
        self.last_change = QtWidgets.QLabel(holder)
        self.last_change.setObjectName("CADWiz_Last_Change")
        self.last_change.setWordWrap(True)
        below.addWidget(self.last_change)
        from integrations.cadwiz_plugin.panel_pages import ProblemsCard

        self.problems_card = ProblemsCard(self, holder)
        below.addWidget(self.problems_card.box)
        self.versions_box = self._build_versions(holder)
        below.addWidget(self.versions_box)
        below.addStretch(1)
        lower.setWidget(holder)
        self.lower = lower
        column.addWidget(lower, 0)
        self.folded: dict[str, bool] = {key: bool((self.settings.get("folded") or {}).get(key, True)) for key in FOLDS}
        self.fold_boxes = {"problems": self.problems_card.box, "versions": self.versions_box}
        self.problem_count = 0
        self.fold_filters = []
        for key, box in self.fold_boxes.items():
            heading = _heading_of(box, QtWidgets)
            if heading is not None:
                heading.setCursor(QtCore.Qt.PointingHandCursor)
                heading.setToolTip("Click to open or fold away")
                click = _FoldClick.make(QtCore, lambda k=key: self.toggle_fold(k))
                heading.installEventFilter(click)
                self.fold_filters.append(click)
        self.snug_buttons()
        self.apply_folds()
        self.lower_share = _LowerShare.make(QtCore, self.fit_lower)
        page.installEventFilter(self.lower_share)
        return page

    def snug_buttons(self) -> None:
        """Each view and marking button exactly as wide as its words."""
        font = self.QtGui.QFont("Arial")
        font.setPixelSize(max(TEXT_PX, int(self.prefs.text_px)))
        metrics = self.QtGui.QFontMetrics(font)
        buttons = list(self.view_buttons.values()) + [self.cut_button, self.assembly_button, self.show_model_button,
                                                      self.show_concepts_button, self.show_drawing_button] + list(self.tool_buttons.values())
        buttons += [b for b in (self.content.findChild(self.QtWidgets.QPushButton, "CADWiz_Undo_Mark"),
                                self.content.findChild(self.QtWidgets.QPushButton, "CADWiz_Clear_Marks")) if b is not None]
        for button in buttons:
            button.setFixedWidth(snug_width(metrics.horizontalAdvance(button.text())))

    # ---- the two folding sections under the picture (ORDER-2026-10-19-05) -------------------------
    def toggle_fold(self, key: str) -> None:
        self.folded[key] = not self.folded[key]
        if key == "problems":
            self.problems_opened_itself = False          # his choice now: left as he set it
        self.settings["folded"] = dict(self.folded)
        _save_settings(self.settings)
        self.apply_folds()

    def apply_folds(self) -> None:
        """Folded: only the heading line shows, with a few words of what is inside.
        Called every second too, because the sections show and hide their own rows."""
        QtWidgets = self.QtWidgets
        count = len(getattr(self.problems_card, "problems", []) or [])
        if count and not self.problem_count and self.folded["problems"]:
            self.folded["problems"] = False              # a new problem opens the section by itself
            self.problems_opened_itself = True
        elif not count and self.problem_count and getattr(self, "problems_opened_itself", False):
            self.folded["problems"] = True               # ...and folds it again once the problems are gone
            self.problems_opened_itself = False
        self.problem_count = count
        words = {key: fold_words(key, count, self.latest_version) for key in FOLDS}
        for key, box in self.fold_boxes.items():
            heading = _heading_of(box, QtWidgets)
            folded = self.folded[key]
            if heading is not None:
                heading.setText(("\u25b8 " if folded else "\u25be ") + words[key])
            for child in box.children():
                if isinstance(child, QtWidgets.QWidget) and child is not heading and not child.isWindow():
                    child.setVisible(not folded and self._shown_when_open(child))
        self.fit_lower()

    def _shown_when_open(self, child: Any) -> bool:
        """Rows a section hides on its own stay hidden when it is opened."""
        if child is getattr(self.problems_card, "scroll", None):
            return bool(getattr(self.problems_card, "problems", None))
        if child is getattr(self, "stop_broken", None):
            return bool(self.stop_broken.text())
        if child is getattr(self, "version_status", None):
            return bool(self.version_status.text())
        return True

    def fit_lower(self) -> None:
        """The part under the marking bar takes only the room its open sections need
        (never more than its share of the page): folded, the picture gets the rest."""
        lower = getattr(self, "lower", None)
        if lower is None:
            return
        parent = lower.parentWidget()
        page_height = parent.height() if parent is not None else 0
        holder = lower.widget()
        if holder.layout() is not None:
            holder.layout().activate()            # rows just opened or folded count now, not on the next pass
        need = holder.sizeHint().height() + 4
        top = min(lower_max_height(page_height), need) if page_height else need
        lower.setMinimumHeight(min(LOWER_MIN_HEIGHT, top))
        lower.setMaximumHeight(max(top, 1))

    def _build_mark_toolbar(self, parent: Any) -> Any:
        QtCore, QtWidgets = self.QtCore, self.QtWidgets
        bar = QtWidgets.QFrame(parent)
        bar.setObjectName("CADWiz_Mark_Toolbar")
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        holder = QtWidgets.QWidget(bar)
        flow = _make_flow_layout(QtCore, QtWidgets)(holder, 6)
        self.tool_buttons: dict[str, Any] = {}
        for key, text, tip in TOOLS:
            button = QtWidgets.QPushButton(text, holder)
            button.setObjectName(f"CADWiz_Mark_{text}")
            button.setProperty("role", "tool")
            button.setCheckable(True)
            button.setToolTip(tip)
            button.clicked.connect(lambda checked=False, k=key: self.choose_tool(k if checked else ""))
            flow.addWidget(button)
            self.tool_buttons[key] = button
        undo = QtWidgets.QPushButton("Undo mark", holder)
        undo.setObjectName("CADWiz_Undo_Mark")
        undo.setProperty("role", "tool")
        undo.setToolTip("Take back your last mark (the model is not touched)")
        undo.clicked.connect(self.undo_mark)
        clear = QtWidgets.QPushButton("Clear", holder)
        clear.setObjectName("CADWiz_Clear_Marks")
        clear.setProperty("role", "tool")
        clear.setToolTip("Take every mark off the screen (the model is not touched)")
        clear.clicked.connect(self.clear_marks)
        flow.addWidget(undo)
        flow.addWidget(clear)
        row.addWidget(holder, 1)
        self.show_claude = _button(QtWidgets, "show_claude", bar)
        self.show_claude.setProperty("role", "primary")
        self.show_claude.clicked.connect(lambda: self.freeze_for_claude())
        row.addWidget(self.show_claude, 0, QtCore.Qt.AlignBottom)
        return bar

    def _build_versions(self, parent: Any) -> Any:
        QtCore, QtWidgets = self.QtCore, self.QtWidgets
        box, column = self._section(parent, "Time machine — every stop is a complete saved copy", "CADWiz_Version_Strip")
        self.timeline = _make_timeline(QtCore, self.QtGui, QtWidgets)(box, self.select_stop)
        self.timeline.setObjectName("CADWiz_Time_Slider")
        column.addWidget(self.timeline)
        # Thumbnail on the left; caption and the three buttons beside it, so the
        # section is one row shorter than it was (ORDER-2026-10-19-01).
        info = QtWidgets.QHBoxLayout()
        self.stop_thumb = QtWidgets.QLabel(box)
        self.stop_thumb.setObjectName("CADWiz_Version_Thumbnail")
        self.stop_thumb.setFixedSize(*THUMB_SIZE)
        self.stop_thumb.setAlignment(QtCore.Qt.AlignCenter)
        info.addWidget(self.stop_thumb, 0, QtCore.Qt.AlignTop)
        words = QtWidgets.QVBoxLayout()
        words.setSpacing(4)
        self.stop_text = QtWidgets.QLabel(box)
        self.stop_text.setObjectName("CADWiz_Version_Caption")
        self.stop_text.setWordWrap(True)
        self.stop_broken = QtWidgets.QLabel(box)
        self.stop_broken.setObjectName("CADWiz_Version_Broken")
        self.stop_broken.setWordWrap(True)
        self.stop_broken.setStyleSheet(f"color: {BROKEN_RED}; font-weight: 700;")
        words.addWidget(self.stop_text)
        words.addWidget(self.stop_broken)
        info.addLayout(words, 1)
        column.addLayout(info)
        buttons = QtWidgets.QWidget(box)
        words.addWidget(buttons)
        flow = _make_flow_layout(QtCore, QtWidgets)(buttons, 6)
        self.restore_button = _button(QtWidgets, "restore", buttons)
        self.restore_button.clicked.connect(self.restore_selected)
        self.compare_button = _button(QtWidgets, "compare", buttons)
        self.compare_button.clicked.connect(self.compare_selected)
        self.checkpoint_button = _button(QtWidgets, "checkpoint", buttons)
        self.checkpoint_button.clicked.connect(self.save_checkpoint)
        for button in (self.restore_button, self.compare_button, self.checkpoint_button):
            flow.addWidget(button)
        self.version_status = QtWidgets.QLabel(box)
        self.version_status.setObjectName("CADWiz_Version_Status")
        self.version_status.setWordWrap(True)
        column.addWidget(self.version_status)
        return box

    # ---- pages ------------------------------------------------------------------------------
    def show_screen(self, index: int) -> None:
        """0: the model; 1: Choosing a design; 2: the technical drawing."""
        self.screen_stack.setCurrentIndex(index)
        self.show_model_button.setChecked(index == 0)
        self.show_concepts_button.setChecked(index == 1)
        self.show_drawing_button.setChecked(index == 2)
        # Choosing a design is about pictures: the marks and the versions are about
        # the model, and step aside so the cards have room.
        self.mark_toolbar.setVisible(index == 0)
        self.versions_box.setVisible(index == 0)
        if index == 1:
            self.concepts_view.render()
        elif index == 2:
            self.drawing_screen.show()
        else:
            self.picture_signature = None

    def open_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for i, button in enumerate(self.page_buttons):
            button.setChecked(i == index)
        if index == 1:
            self.printing.refresh()
        if index == 2:
            self.setup.refresh()

    def connection_now(self) -> dict[str, str]:
        return self.light_now()

    def light_now(self) -> dict[str, str]:
        """The light, with the Connect button's progress when it was pressed."""
        bridge = self.bridge()
        light = connection(bridge, time.monotonic() - self.opened_at)
        connector = getattr(self, "connector", None)
        if connector is not None and bridge is not None:
            stage = connector.poll(bool(bridge.connected))
            if stage == "connected":
                self.connector = None
            elif connector.busy:
                light = {"light": AMBER, "line": CONNECTING, "todo": connector.words}
            else:
                light = {"light": RED, "line": NOT_CONNECTED, "todo": connector.words}
        with contextlib.suppress(Exception):
            self.connect_button.setVisible(light["light"] != GREEN)
            self.connect_button.setEnabled(not (connector is not None and connector.busy))
        return light

    def connect_claude(self) -> None:
        from integrations.cadwiz_plugin.connect_claude import Connector

        self.connector = Connector()
        self.refresh()

    def save_preferences(self) -> None:
        from integrations.cadwiz_plugin import preferences_store

        preferences_store.save(self.prefs)
        self.content.setStyleSheet(style_sheet(self.prefs.text_px))
        self.snug_buttons()
        self.canvas.update()

    def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        session = self.session()
        if session is None:
            return {"ok": False, "say_to_founder": NO_BRIDGE}
        return self.run_paused(lambda: session.call(tool, arguments))

    # ---- problems and fixes ---------------------------------------------------------------------
    def ask_claude_to_fix(self, problem: Any) -> None:
        """Freeze the screen for Claude with this problem as his request: Claude
        reads it on his next message ("fix it")."""
        self.freeze_for_claude(request={"ask": "fix this problem", "problem": problem.to_dict()})
        self.flash("Now tell Claude \u201cfix it\u201d in the Claude app.", FOUNDER_BLUE, seconds=5.0)

    def show_problem(self, problem: Any) -> None:
        from integrations.cadwiz_plugin.problems_watch import show_me

        gui, document = self.gui(), self.document()
        if gui is not None and document is not None:
            show_me(gui, document, problem)
        self.open_page(0)

    def go_back_to_last_good(self) -> None:
        """The newest version before the current one that was not broken."""
        good = [s for s in self.stops[:-1] if not s["broken"]]
        if not good:
            self.version_status.setText("There is no earlier good version to go back to yet.")
            return
        self.selected_stop = self.stops.index(good[-1])
        self.timeline.set_stops(self.stops, self.selected_stop)
        self.show_stop()
        self.restore_selected()

    # ---- the collapsed strip -------------------------------------------------------------------
    def _build_strip(self) -> Any:
        QtCore, QtWidgets = self.QtCore, self.QtWidgets
        strip = QtWidgets.QFrame(self.content)
        strip.setObjectName("CADWiz_Strip")
        column = QtWidgets.QVBoxLayout(strip)
        column.setContentsMargins(6, 10, 6, 10)
        column.setSpacing(10)
        self.strip_wiz = QtWidgets.QLabel(strip)
        self.strip_wiz.setFixedSize(56, 56)
        self.strip_wiz_player = WizPlayer(self.strip_wiz, 56)
        column.addWidget(self.strip_wiz, 0, QtCore.Qt.AlignHCenter)
        self.strip_light = QtWidgets.QLabel("●", strip)
        self.strip_light.setObjectName("CADWiz_Strip_Light")
        self.strip_light.setAlignment(QtCore.Qt.AlignCenter)
        self.strip_light.setStyleSheet("font-size: 28px;")
        column.addWidget(self.strip_light)
        show = QtWidgets.QPushButton("Show\nClaude", strip)
        self.strip_show = show
        show.setObjectName("CADWiz_Strip_Show_Claude")
        show.setProperty("role", "primary")
        show.clicked.connect(lambda: self.freeze_for_claude())
        column.addWidget(show)
        opener = QtWidgets.QPushButton("Open", strip)
        opener.setObjectName("CADWiz_Strip_Open")
        opener.setToolTip("Open the full CADWiz screen")
        opener.clicked.connect(lambda: self.host.expand())
        column.addWidget(opener)
        self.strip_status = QtWidgets.QLabel(strip)
        self.strip_status.setWordWrap(True)
        self.strip_status.setAlignment(QtCore.Qt.AlignCenter)
        column.addWidget(self.strip_status)
        column.addStretch(1)
        return strip

    def show_collapsed(self, collapsed: bool) -> None:
        self.full.setVisible(not collapsed)
        self.strip.setVisible(collapsed)
        self.collapse_button.setText("Collapse")

    # ---- the live picture ----------------------------------------------------------------------
    def _signature(self) -> Any:
        from integrations.cadwiz_plugin import view_link

        view = self.view()
        document = self.document()
        if view is None:
            return None
        camera = view_link.read_camera(view)
        width, height = self.canvas.picture_size()
        with contextlib.suppress(Exception):
            busy = (document.Name, len(document.Objects), tuple(view_link.selection_names(self.gui())))
            return (busy, camera.to_dict() if camera else None, width, height, view_link.is_cut_away(view), view_link.is_exploded(document))
        return (camera.to_dict() if camera else None, width, height)

    def watch_view(self) -> None:
        """Every 200 ms: if the view, the model, the selection or the screen size
        changed, take a new picture once it has been still for 150 ms."""
        if (not self.full.isVisible() or self.pages.currentIndex() != 0 or self.compare is not None
                or self.screen_stack.currentIndex() != 0):
            return
        try:
            signature = self._signature()
        except Exception:  # noqa: BLE001
            signature = None
        if signature is None:
            if self.picture_signature is not None or self.picture is None:
                self.picture_signature = None
                self.picture = None
                self.picture_camera = None
                self.canvas.update()
            return
        now = time.monotonic()
        if signature != self.pending_signature:
            self.pending_signature, self.pending_since = signature, now
            return
        if signature != self.picture_signature and now - self.pending_since >= 0.15:
            self.capture(signature)

    def capture(self, signature: Any = None) -> None:
        from integrations.cadwiz_plugin import view_link

        view = self.view()
        if view is None:
            return
        width, height = self.canvas.picture_size()
        if width < 32 or height < 32:
            return
        path = self.screen().folder.parent / "screen-live.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        camera = view_link.read_camera(view)
        if not view_link.capture(view, str(path), width, height):
            return
        pixmap = self.QtGui.QPixmap(str(path))
        if pixmap.isNull():
            return
        self.picture, self.picture_camera, self.picture_aspect = pixmap, camera, width / float(height)
        self.picture_signature = signature if signature is not None else self._signature()
        self.cut_button.setChecked(view_link.is_cut_away(view))
        exploded = view_link.is_exploded(self.document())
        if exploded != self.assembly_button.isChecked():      # a reload puts the parts back together
            self.assembly_button.setChecked(exploded)
            self._marks_allowed(not exploded)
        self.canvas.update()

    def turn(self, name: str) -> None:
        from integrations.cadwiz_plugin import view_link

        view = self.view()
        if view is None:
            return
        view_link.set_view(view, name)
        self.wiz_player.activity()

    def toggle_cut_away(self) -> None:
        from integrations.cadwiz_plugin import view_link

        view = self.view()
        if view is None:
            self.cut_button.setChecked(False)
            return
        self.cut_button.setChecked(view_link.cut_away(view, self.cut_button.isChecked(), self.document()))
        self.picture_signature = None

    def toggle_assembly(self) -> None:
        """Assembly (ORDER-2026-10-19-05): the parts drawn pulled apart. Marks are
        anchored to the model as it really is, so they wait until it is off."""
        from integrations.cadwiz_plugin import view_link

        wanted = self.assembly_button.isChecked()
        document = self.document()
        why = "Open a model first." if document is None else view_link.explode(document, wanted)
        on = wanted and not why
        self.assembly_button.setChecked(on)
        if wanted and why:
            self.flash(why, FOUNDER_BLUE, seconds=4.0)
        view = self.view()
        if view is not None and not why:
            with contextlib.suppress(Exception):
                view.fitAll()                         # the lifted lid stays in the picture
        self._marks_allowed(not on)
        self.picture_signature = None

    def _marks_allowed(self, allowed: bool) -> None:
        if not allowed:
            self.choose_tool("")
        tips = {key: tip for key, _text, tip in TOOLS}
        for key, button in self.tool_buttons.items():
            button.setEnabled(allowed)
            button.setToolTip(tips[key] if allowed else ASSEMBLY_NO_MARKS)

    # ---- marking ---------------------------------------------------------------------------------
    def choose_tool(self, key: str) -> None:
        self.tool = key
        for name, button in self.tool_buttons.items():
            button.setChecked(name == key)
        self.canvas.set_tool(key)

    def book(self) -> MarkBook:
        screen = self.screen()
        document = self.document()
        screen.active_document = document.Name if document is not None else ""
        return screen.book

    def add_mark(self, kind: str, points: list[tuple[float, float]]) -> None:
        """Place a mark: every defining point of it is found on the model."""
        from integrations.cadwiz_plugin import view_link

        view = self.view()
        camera = self.picture_camera
        if view is None or camera is None:
            return
        text = ""
        if kind == "note":
            text, ok = self.QtWidgets.QInputDialog.getText(self.content, "Note", "What should the note say?")
            if not ok:
                return
        if kind == "lasso" and len(points) > 60:
            step = len(points) / 60.0
            points = [points[int(i * step)] for i in range(60)]
        size = self.canvas.picture_rect()
        anchors = [view_link.pick(view, camera, u, v, self.picture_aspect, picture_px=(size.width(), size.height())) for u, v in points]
        try:
            self.book().add(kind, anchors, author=VisualMarkAuthor.USER, text=text)
        except ValueError:
            return
        self.wiz_player.activity()
        self.canvas.update()

    def highlight_face(self, point: tuple[float, float]) -> None:
        """Highlight by a click: paint the whole face under it, by its own outline,
        so it stays painted on that face from any side."""
        from integrations.cadwiz_plugin import view_link

        view, camera, document = self.view(), self.picture_camera, self.document()
        if view is None or camera is None or document is None:
            return
        anchor = view_link.pick(view, camera, point[0], point[1], self.picture_aspect)   # no corner snap: the face itself
        outline = view_link.face_outline(document, anchor) if anchor.on_model else []
        if len(outline) < 3:
            self.flash(NO_FACE_HERE, FOUNDER_BLUE)
            return
        try:
            self.book().add("highlight", outline, author=VisualMarkAuthor.USER)
        except ValueError:
            return
        self.wiz_player.activity()
        self.canvas.update()

    def click_select(self, u: float, v: float, add: bool) -> None:
        """No marking tool chosen: a click on the picture selects that face in FreeCAD."""
        from integrations.cadwiz_plugin import view_link

        view, camera, document, gui = self.view(), self.picture_camera, self.document(), self.gui()
        if view is None or camera is None or document is None or gui is None:
            return
        anchor = view_link.pick(view, camera, u, v, self.picture_aspect)
        with contextlib.suppress(Exception):
            if not add:
                gui.Selection.clearSelection()
            if anchor.on_model and anchor.obj:
                gui.Selection.addSelection(document.Name, anchor.obj, anchor.element, *anchor.point)

    def zoom(self, steps: int) -> None:
        view = self.view()
        with contextlib.suppress(Exception):
            for _ in range(abs(steps)):
                view.zoomIn() if steps > 0 else view.zoomOut()

    def undo_mark(self) -> None:
        self.book().undo(VisualMarkAuthor.USER)
        self.canvas.update()

    def clear_marks(self) -> None:
        self.book().clear()
        self.canvas.update()

    def marks(self) -> list[AnchoredMark]:
        return list(self.book().marks)

    # ---- Show Claude -------------------------------------------------------------------------------
    def freeze_for_claude(self, request: dict[str, Any] | None = None) -> None:
        from integrations.cadwiz_plugin import view_link

        screen = self.screen()
        view, document, gui = self.view(), self.document(), self.gui()
        self.wiz_player.activity()
        if view is None or document is None:
            self.flash(NO_MODEL, RED)
            return
        if self.picture is None:
            self.capture()
        camera = self.picture_camera or view_link.read_camera(view)
        aspect = self.picture_aspect if self.picture is not None else 4 / 3.0
        width = 1280
        height = max(64, int(round(width / aspect)))
        clean = screen.picture_path("clean")
        marked = screen.picture_path("marked")
        if not view_link.capture(view, str(clean), width, height):
            self.flash("CADWiz could not take the picture. Try again in a moment.", RED)
            return
        image = self.QtGui.QImage(str(clean))
        painter = self.QtGui.QPainter(image)
        painter.setRenderHint(self.QtGui.QPainter.Antialiasing, True)
        paint_marks(painter, self.QtCore.QRectF(0, 0, image.width(), image.height()), self.marks(), camera, aspect,
                    scale=image.width() / max(1.0, float(self.canvas.picture_rect().width())) if self.picture is not None else 1.5,
                    inches_first_labels=self.prefs.inches_first)
        painter.end()
        image.save(str(marked))
        store = self._store()
        latest = store.latest() if store is not None else 0
        screen.freeze(picture=str(marked), clean_picture=str(clean), camera=camera, aspect=aspect, selection=view_link.selection(gui),
                      view=("cut-away, " if view_link.is_cut_away(view) else "")
                      + ("parts pulled apart (Assembly), " if view_link.is_exploded(document) else "") + view_link.view_name(camera),
                      cut_away=view_link.is_cut_away(view),
                      document=str(document.Label), file=str(getattr(document, "FileName", "") or ""), version=latest, latest_version=latest,
                      broken=view_link.broken_objects(document), request=request)
        self.seen_read = None
        self.flash(FROZEN, FOUNDER_BLUE, seconds=4.0)

    def compose_now(self) -> str:
        """The screen as it is now -- picture and every mark -- for Claude's
        mark_for_user reply."""
        if self.picture is None:
            self.capture()
        if self.picture is None:
            return ""
        image = self.picture.toImage()
        painter = self.QtGui.QPainter(image)
        painter.setRenderHint(self.QtGui.QPainter.Antialiasing, True)
        paint_marks(painter, self.QtCore.QRectF(0, 0, image.width(), image.height()), self.marks(), self.picture_camera,
                    self.picture_aspect, scale=max(1.0, image.width() / 800.0), inches_first_labels=self.prefs.inches_first)
        painter.end()
        path = self.screen().folder.parent / "screen-now.png"
        image.save(str(path))
        self.canvas.update()
        return str(path)

    def flash(self, text: str, colour: str, seconds: float = 3.0) -> None:
        self.flash_text, self.flash_colour, self.flash_until = text, colour, time.monotonic() + seconds
        self.canvas.update()
        self.strip_status.setText(text if len(text) < 40 else "")
        self.QtCore.QTimer.singleShot(int(seconds * 1000) + 50, self.canvas.update)

    def frozen_badge(self) -> str:
        shown = self.screen().shown
        if not shown:
            return ""
        frozen = _local_time(shown["frozen_at_utc"])
        if shown.get("read_by_claude_utc"):
            return f"Showing Claude frame {shown['frame']} ({frozen}) — Claude has it"
        return f"Showing Claude frame {shown['frame']} ({frozen}) — waiting for your next message to Claude"

    # ---- versions ---------------------------------------------------------------------------------
    def _store(self) -> Any:
        session, document = self.session(), self.document()
        if session is None or document is None:
            return None
        with contextlib.suppress(Exception):
            return session.store_for(document)
        return None

    def refresh_versions(self) -> None:
        store = self._store()
        records = []
        if store is not None:
            with contextlib.suppress(Exception):
                latest = store.latest()
                records = store.list_recent(max(1, latest))
        stops = timeline_stops(records)[-max(1, int(self.prefs.versions_shown)):]
        changed = [s["version"] for s in stops] != [s["version"] for s in self.stops]
        self.stops = stops
        self.latest_version = stops[-1]["version"] if stops else 0
        if changed:
            self.selected_stop = len(stops) - 1
        self.timeline.set_stops(stops, self.selected_stop)
        self.show_stop()

    def select_stop(self, index: int) -> None:
        self.selected_stop = index
        self.show_stop()
        self.wiz_player.activity()

    def show_stop(self) -> None:
        has = 0 <= self.selected_stop < len(self.stops)
        self.restore_button.setEnabled(has and self.selected_stop != len(self.stops) - 1)
        self.compare_button.setEnabled(has)
        self.checkpoint_button.setEnabled(self.document() is not None)
        if not has:
            self.stop_text.setText("No saved versions of this model yet. Save a checkpoint to start, or ask Claude to change it." if self.document()
                                   else NO_MODEL)
            self.stop_broken.setText("")
            self.stop_thumb.clear()
            self.stop_thumb.hide()
            return
        stop = self.stops[self.selected_stop]
        self.stop_text.setText(stop_caption(stop, self.latest_version))
        self.stop_broken.setText(broken_caption(stop))
        pixmap = self.QtGui.QPixmap(stop["render"]) if stop["render"] and Path(stop["render"]).is_file() else None
        if pixmap is not None and not pixmap.isNull():
            self.stop_thumb.setPixmap(pixmap.scaled(*THUMB_SIZE, self.QtCore.Qt.KeepAspectRatio, self.QtCore.Qt.SmoothTransformation))
            self.stop_thumb.show()
        else:
            self.stop_thumb.clear()
            self.stop_thumb.hide()

    def restore_selected(self) -> None:
        if not 0 <= self.selected_stop < len(self.stops):
            return
        document = self.document()
        stop = self.stops[self.selected_stop]
        answer = self.QtWidgets.QMessageBox.question(
            self.content, "Restore a version",
            f"Bring back version {stop['version']}?\n\nYour model as it is now is kept as a version first, and no newer "
            "version is deleted: you can slide forward again at any time.")
        if answer != self.QtWidgets.QMessageBox.Yes or document is None:
            return
        reply = self._call("versions", {"action": "restore", "version": stop["version"], "document": document.Name})
        if reply.get("ok"):
            self.version_status.setText(f"Brought back version {stop['version']} as version {reply.get('version')}. "
                                        "Nothing was deleted.")
        else:
            self.version_status.setText(reply.get("say_to_founder") or "That did not work; nothing was changed.")
        self.picture_signature = None
        self.refresh_versions()

    def save_checkpoint(self) -> None:
        document = self.document()
        if document is None:
            return
        if not getattr(document, "FileName", ""):
            self.version_status.setText("Save the model in FreeCAD first (File, then Save), then save a checkpoint.")
            return
        reply = self._call("versions", {"action": "save", "document": document.Name, "note": "checkpoint you saved"})
        self.version_status.setText(f"Checkpoint saved as version {reply.get('version')}." if reply.get("ok")
                                    else reply.get("say_to_founder") or "The checkpoint was not saved.")
        self.refresh_versions()

    def compare_selected(self) -> None:
        if not 0 <= self.selected_stop < len(self.stops):
            return
        document, session = self.document(), self.session()
        if document is None or session is None:
            return
        stop = self.stops[self.selected_stop]
        self.version_status.setText(f"Making pictures of version {stop['version']} and of now…")
        self.QtWidgets.QApplication.processEvents()
        try:
            result = self.run_paused(lambda: session.version_pictures(document, stop["version"]))
        except Exception as error:  # noqa: BLE001 - one plain line, never a traceback
            self.version_status.setText(str(error) if type(error).__name__ == "PlainError" else "The comparison pictures could not be made.")
            return
        before = self.QtGui.QPixmap(result.get("before") or "")
        now = self.QtGui.QPixmap(result.get("now") or "")
        if before.isNull() or now.isNull():
            self.version_status.setText("The comparison pictures could not be made.")
            return
        self.compare = {"before": before, "now": now, "version": stop["version"], "mode": "overlay", "diff": result.get("diff", "")}
        self.version_status.setText(f"Version {stop['version']} compared with now: {result.get('diff')}")
        self.canvas.show_compare(True)

    def end_compare(self) -> None:
        self.compare = None
        self.canvas.show_compare(False)
        self.picture_signature = None

    # ---- the slow refresh -----------------------------------------------------------------------
    def refresh(self) -> None:
        light = self.light_now()
        self.light.setText(f"● {light['line']}")
        self.light.setStyleSheet(f"color: {light['light']}; font-weight: 700;")
        self.todo.setText(light["todo"])
        self.todo.setVisible(bool(light["todo"]))
        self.strip_light.setStyleSheet(f"color: {light['light']}; font-size: 28px;")
        self.strip_light.setToolTip(light["line"])
        self.ai_choice.refresh()
        with contextlib.suppress(Exception):
            word = assistant_word(self.prefs.ai_app)
            self.show_claude.setText(f"Show {word}")
            self.strip_show.setText(f"Show\n{word}")
        with contextlib.suppress(Exception):
            self.problems_card.watch()
        with contextlib.suppress(Exception):
            rounds = len(self.screen().concepts.rounds)
            designs = f"Designs ({rounds})" if rounds else "Designs"
            if self.show_concepts_button.text() != designs:
                self.show_concepts_button.setText(designs)
                self.snug_buttons()
            if self.concepts_view.watch():           # Claude just posted new designs: show them
                self.open_page(0)
                self.show_screen(1)
                self.flash("Claude posted designs to choose from.", FOUNDER_BLUE, seconds=3.0)
        with contextlib.suppress(Exception):
            showing = self.pages.currentIndex() == 0 and self.screen_stack.currentIndex() == 2 and self.full.isVisible()
            if self.drawing_screen.watch(showing):       # Claude just made a drawing: show it
                self.open_page(0)
                self.show_screen(2)
                self.flash("Claude made a drawing.", FOUNDER_BLUE, seconds=3.0)
        document = self.document()
        self.screen().active_document = document.Name if document is not None else ""
        self.refresh_versions()
        self.working.setText(version_line(str(document.Label) if document is not None else "", self.latest_version))
        self.last_change.setText(last_change_line(self.stops[-1] if self.stops else None))
        self.last_change.setVisible(bool(self.last_change.text()))
        self.apply_folds()
        shown = self.screen().shown
        read = shown.get("read_by_claude_utc") if shown else None
        if read and read != self.seen_read:
            self.seen_read = read
            self.flash(CLAUDE_HAS_IT, GREEN, seconds=3.0)
            self.wiz_player.activity()
        banner = self.content.findChild(self.QtWidgets.QLabel, "CADWiz_Install_Changed_Banner")
        if banner is not None and banner.parent() is self.content:
            layout = self.content.layout()
            layout.removeWidget(banner)
            banner.setParent(self.full)
            self.full.layout().insertWidget(1, banner)
        self.pop_button.setText("Dock back" if self.dock.isFloating() else "Pop out")
        if time.monotonic() >= self.flash_until:
            self.strip_status.setText("")
        self.canvas.update()


# ---- small widgets ------------------------------------------------------------------------------
def style_sheet(text_px: int = TEXT_PX) -> str:
    """The panel's look; text size from Setup (18 px at the least, UI-LAYOUT-STANDARD)."""
    px = max(TEXT_PX, int(text_px))
    return f"""
QWidget#CADWiz_Slim_Panel {{ background: #F4F5FD; color: {INK}; font-size: {px}px; font-family: Arial; }}
QWidget#CADWiz_Slim_Panel QLabel {{ font-size: {px}px; }}
QWidget#CADWiz_Slim_Panel QCheckBox {{ font-size: {px}px; }}
QWidget#CADWiz_Slim_Panel QSpinBox, QWidget#CADWiz_Slim_Panel QDoubleSpinBox {{ font-size: {px}px; padding: 2px 4px; }}
QWidget#CADWiz_Slim_Panel QPushButton {{ font-size: {px}px; padding: 6px 12px; border: 1px solid #C7CBE8; border-radius: 6px;
    background: white; min-height: 28px; }}
QWidget#CADWiz_Slim_Panel QPushButton:hover {{ border-color: {FOUNDER_BLUE}; }}
QWidget#CADWiz_Slim_Panel QPushButton:checked {{ background: {FOUNDER_BLUE}; color: white; border-color: {FOUNDER_BLUE}; }}
QWidget#CADWiz_Slim_Panel QPushButton:disabled {{ color: #9AA0A6; }}
QWidget#CADWiz_Slim_Panel QPushButton[role='primary'] {{ background: {FOUNDER_BLUE}; color: white; font-weight: 700; padding: 10px 18px; }}
QWidget#CADWiz_Slim_Panel QPushButton[role='view'], QWidget#CADWiz_Slim_Panel QPushButton[role='tool'] {{ padding: 6px {SNUG_PAD}px; min-width: 0px; }}
QWidget#CADWiz_Slim_Panel QPushButton[role='page'] {{ font-weight: 700; padding: 6px 16px; border-radius: 16px; }}
QWidget#CADWiz_Slim_Panel QPushButton[role='link'] {{ border: none; background: transparent; color: {FOUNDER_BLUE};
    text-decoration: underline; padding: 4px 2px; }}
QWidget#CADWiz_Slim_Panel QLabel[role='title'] {{ font-size: {px + 8}px; font-weight: 700; }}
QFrame[role='section'] {{ background: white; border: 1px solid #C7CBE8; border-radius: 8px; }}
QFrame[role='problem'] {{ background: #FFF8F6; border: 1px solid #F2B8B5; border-radius: 6px; }}
QWidget#CADWiz_Slim_Panel QLabel[role='heading'] {{ font-weight: 700; border: none; }}
QFrame[role='section'] QLabel, QFrame[role='problem'] QLabel {{ border: none; background: transparent; }}
QWidget#CADWiz_Slim_Panel QLineEdit, QWidget#CADWiz_Slim_Panel QComboBox {{ font-size: {px}px; padding: 4px 6px; }}
QFrame#CADWiz_Strip {{ background: #F4F5FD; }}
"""


_STYLE = style_sheet()


class _ActivityFilter:
    """Any mouse movement or press over the panel wakes the Wiz."""

    @staticmethod
    def make(QtCore: Any, panel: _Panel) -> Any:
        class Filter(QtCore.QObject):  # type: ignore[misc]
            def eventFilter(self, _obj: Any, event: Any) -> bool:  # noqa: N802
                if event.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.Enter, QtCore.QEvent.KeyPress):
                    panel.wiz_player.activity()
                    panel.strip_wiz_player.activity()
                return False

        return Filter(panel.content)


def lower_max_height(page_height: int) -> int:
    """How tall the scrolling part of page 1 may be on a page this tall."""
    return max(LOWER_MIN_HEIGHT, int(page_height * LOWER_MAX_SHARE))


class _LowerShare:
    """Keeps the scrolling part of page 1 to its share as the page is resized."""

    @staticmethod
    def make(QtCore: Any, fit: Callable[[], None]) -> Any:
        class Filter(QtCore.QObject):  # type: ignore[misc]
            def eventFilter(self, _obj: Any, event: Any) -> bool:  # noqa: N802
                if event.type() == QtCore.QEvent.Resize:
                    fit()
                return False

        return Filter()


class _FoldClick:
    """A click on a section's heading opens or folds it."""

    @staticmethod
    def make(QtCore: Any, toggle: Callable[[], None]) -> Any:
        class Filter(QtCore.QObject):  # type: ignore[misc]
            def eventFilter(self, _obj: Any, event: Any) -> bool:  # noqa: N802
                if event.type() == QtCore.QEvent.MouseButtonPress:
                    toggle()
                    return True
                return False

        return Filter()


def _heading_of(box: Any, QtWidgets: Any) -> Any:
    for label in box.findChildren(QtWidgets.QLabel):
        if label.property("role") == "heading" and label.parent() is box:
            return label
    return None


def snug_width(text_width: int) -> int:
    """A view or marking button's width: its words, its padding, its border."""
    return int(text_width) + 2 * SNUG_PAD + 4


def fold_words(key: str, problems: int, latest_version: int) -> str:
    """The heading of a folding section: its name and a few words of what is in it."""
    if key == "problems":
        return f"{FOLDS[key]} \u2014 " + ("none found" if not problems else f"{problems} to look at")
    return f"{FOLDS[key]} \u2014 " + (f"version {latest_version}, every stop a complete saved copy" if latest_version
                                         else "no saved versions yet")


def _make_canvas(QtCore: Any, QtGui: Any, QtWidgets: Any) -> Any:
    class ScreenCanvas(QtWidgets.QWidget):  # type: ignore[misc]
        """The picture of the model, the marks on it, and the marking itself."""

        def __init__(self, parent: Any, panel: _Panel) -> None:
            super().__init__(parent)
            self.panel = panel
            self.tool = ""
            self.drag: list[tuple[float, float]] = []
            self.setMinimumHeight(CANVAS_MIN_HEIGHT)
            self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            self.setMouseTracking(True)
            self.setAccessibleName("CADWiz Visual Communications Screen")
            self.compare_bar = QtWidgets.QWidget(self)
            row = QtWidgets.QHBoxLayout(self.compare_bar)
            row.setContentsMargins(8, 8, 8, 8)
            self.compare_buttons = {}
            for key, text in (("before", "That version"), ("overlay", "Overlay"), ("now", "Now")):
                button = QtWidgets.QPushButton(text, self.compare_bar)
                button.setCheckable(True)
                button.clicked.connect(lambda _c=False, k=key: self.compare_mode(k))
                row.addWidget(button)
                self.compare_buttons[key] = button
            close = QtWidgets.QPushButton("Close compare", self.compare_bar)
            close.clicked.connect(panel.end_compare)
            row.addWidget(close)
            row.addStretch(1)
            self.compare_bar.hide()

        def picture_size(self) -> tuple[int, int]:
            ratio = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
            return int(self.width() * ratio), int(self.height() * ratio)

        def picture_rect(self) -> Any:
            pixmap = self.panel.picture
            aspect = self.panel.picture_aspect if pixmap is not None else (self.width() / max(1, self.height()))
            x, y, w, h = fit(self.width(), self.height(), aspect)
            return QtCore.QRectF(x, y, w, h)

        def set_tool(self, tool: str) -> None:
            self.tool = tool
            self.drag = []
            self.setCursor(QtCore.Qt.CrossCursor if tool else QtCore.Qt.PointingHandCursor)

        def show_compare(self, on: bool) -> None:
            self.compare_bar.setVisible(on)
            if on:
                self.compare_mode("overlay")
            self.update()

        def compare_mode(self, mode: str) -> None:
            if self.panel.compare is not None:
                self.panel.compare["mode"] = mode
            for key, button in self.compare_buttons.items():
                button.setChecked(key == mode)
            self.update()

        def _uv(self, event: Any) -> tuple[float, float] | None:
            rect = self.picture_rect()
            if rect.width() <= 0:
                return None
            position = event.position() if hasattr(event, "position") else event.pos()
            u = (position.x() - rect.left()) / rect.width()
            v = (position.y() - rect.top()) / rect.height()
            return (u, v) if 0.0 <= u <= 1.0 and 0.0 <= v <= 1.0 else None

        def mousePressEvent(self, event: Any) -> None:  # noqa: N802
            point = self._uv(event)
            if point is None or self.panel.compare is not None or self.panel.picture is None:
                return
            if not self.tool:
                add = bool(event.modifiers() & QtCore.Qt.ControlModifier)
                self.panel.click_select(point[0], point[1], add)
                return
            if self.tool in ("point", "note"):
                self.panel.add_mark(self.tool, [point])
                return
            self.drag = [point]

        def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
            if not self.drag:
                return
            point = self._uv(event)
            if point is None:
                return
            if self.tool == "lasso":
                last = self.drag[-1]
                if abs(point[0] - last[0]) + abs(point[1] - last[1]) > 0.006:
                    self.drag.append(point)
            else:
                self.drag = [self.drag[0], point]
            self.update()

        def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
            if not self.drag:
                return
            drag, self.drag = self.drag, []
            moved = len(drag) == 2 and abs(drag[0][0] - drag[1][0]) + abs(drag[0][1] - drag[1][1]) > 0.004
            if self.tool == "lasso":
                if len(drag) >= 3:
                    self.panel.add_mark("lasso", drag)
                else:
                    self.panel.flash(DRAG_HINTS["lasso"], FOUNDER_BLUE)
            elif moved:
                self.panel.add_mark(self.tool, drag)
            elif self.tool == "highlight":
                self.panel.highlight_face(drag[0])       # a click paints the face under it
            elif self.tool in DRAG_HINTS:
                self.panel.flash(DRAG_HINTS[self.tool], FOUNDER_BLUE)
            self.update()

        def wheelEvent(self, event: Any) -> None:  # noqa: N802
            delta = event.angleDelta().y()
            if delta:
                self.panel.zoom(1 if delta > 0 else -1)
            event.accept()

        def paintEvent(self, _event: Any) -> None:  # noqa: N802
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
            painter.fillRect(self.rect(), QtGui.QColor("white"))
            panel = self.panel
            font = QtGui.QFont("Arial")
            font.setPixelSize(TEXT_PX)
            painter.setFont(font)
            compare = panel.compare
            if compare is not None:
                self._paint_compare(painter, compare)
            elif panel.picture is None:
                painter.setPen(QtGui.QColor("#5A6270"))
                painter.drawText(self.rect().adjusted(24, 24, -24, -24), QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap,
                                 NO_MODEL if panel.document() is None else NO_PICTURE)
            else:
                rect = self.picture_rect()
                painter.drawPixmap(rect, panel.picture, QtCore.QRectF(panel.picture.rect()))
                paint_marks(painter, rect, panel.marks(), panel.picture_camera, panel.picture_aspect,
                            inches_first_labels=panel.prefs.inches_first)
                self._paint_drag(painter)
            painter.setPen(QtGui.QPen(QtGui.QColor("#C7CBE8"), 1))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            badge = panel.frozen_badge()
            if badge and compare is None:
                self._label(painter, QtCore.QPointF(10, 10), badge, GREEN if "has it" in badge else FOUNDER_BLUE)
            if panel.flash_text and time.monotonic() < panel.flash_until:
                self._flash(painter, panel.flash_text, panel.flash_colour)
            painter.end()

        def _paint_compare(self, painter: Any, compare: dict[str, Any]) -> None:
            before, now = compare["before"], compare["now"]
            aspect = now.width() / float(max(1, now.height()))
            x, y, w, h = fit(self.width(), self.height() - 56, aspect)
            rect = QtCore.QRectF(x, y + 56, w, h)
            mode = compare["mode"]
            if mode in ("now", "overlay"):
                painter.drawPixmap(rect, now, QtCore.QRectF(now.rect()))
            if mode == "before":
                painter.drawPixmap(rect, before, QtCore.QRectF(before.rect()))
            if mode == "overlay":
                painter.setOpacity(0.5)
                painter.drawPixmap(rect, before, QtCore.QRectF(before.rect()))
                painter.setOpacity(1.0)
            legend = {"before": f"Version {compare['version']}", "now": "Now",
                      "overlay": f"Version {compare['version']} and now, one over the other"}[mode]
            self._label(painter, QtCore.QPointF(10, self.height() - 40), legend, FOUNDER_BLUE)

        def _paint_drag(self, painter: Any) -> None:
            if not self.drag or not self.tool:
                return
            rect = self.picture_rect()
            pts = [QtCore.QPointF(rect.left() + u * rect.width(), rect.top() + v * rect.height()) for u, v in self.drag]
            pen = QtGui.QPen(QtGui.QColor(FOUNDER_BLUE), 2, QtCore.Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            if self.tool == "lasso":
                painter.drawPolyline(QtGui.QPolygonF(pts))
            elif len(pts) == 2:
                if self.tool == "circle":
                    dx, dy = pts[1].x() - pts[0].x(), pts[1].y() - pts[0].y()
                    radius = (dx * dx + dy * dy) ** 0.5
                    painter.drawEllipse(pts[0], radius, radius)
                elif self.tool in ("box", "highlight"):
                    painter.drawRect(QtCore.QRectF(pts[0], pts[1]).normalized())
                else:
                    painter.drawLine(pts[0], pts[1])

        def _label(self, painter: Any, at: Any, text: str, colour: str) -> None:
            metrics = QtGui.QFontMetricsF(painter.font())
            box = QtCore.QRectF(at.x(), at.y(), min(self.width() - 20, metrics.horizontalAdvance(text) + 20), metrics.height() + 10)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(colour))
            painter.drawRoundedRect(box, 6, 6)
            painter.setPen(QtGui.QColor("white"))
            painter.drawText(box, QtCore.Qt.AlignCenter, metrics.elidedText(text, QtCore.Qt.ElideRight, box.width() - 12))

        def _flash(self, painter: Any, text: str, colour: str) -> None:
            font = QtGui.QFont("Arial")
            font.setPixelSize(28)
            font.setBold(True)
            painter.setFont(font)
            metrics = QtGui.QFontMetricsF(font)
            width = min(self.width() - 40, metrics.horizontalAdvance(text) + 60)
            lines = 1 if metrics.horizontalAdvance(text) + 60 <= width else 2
            height = metrics.height() * lines + 30
            box = QtCore.QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)
            painter.setPen(QtCore.Qt.NoPen)
            fill = QtGui.QColor(colour)
            fill.setAlpha(230)
            painter.setBrush(fill)
            painter.drawRoundedRect(box, 12, 12)
            painter.setPen(QtGui.QColor("white"))
            painter.drawText(box.adjusted(16, 8, -16, -8), QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap, text)

        def resizeEvent(self, event: Any) -> None:  # noqa: N802
            super().resizeEvent(event)
            self.compare_bar.setGeometry(0, 0, self.width(), 52)

    return ScreenCanvas


def _make_timeline(QtCore: Any, QtGui: Any, QtWidgets: Any) -> Any:
    class VersionTimeline(QtWidgets.QWidget):  # type: ignore[misc]
        """The time slider: one stop per saved version, oldest on the left. Broken
        versions are red rings; the chosen stop is large. Drag, click or use the
        arrow keys."""

        def __init__(self, parent: Any, on_select: Callable[[int], None]) -> None:
            super().__init__(parent)
            self.stops: list[dict[str, Any]] = []
            self.selected = -1
            self.on_select = on_select
            self.setMinimumHeight(56)
            self.setFocusPolicy(QtCore.Qt.StrongFocus)
            self.setAccessibleName("Version time slider")

        def set_stops(self, stops: list[dict[str, Any]], selected: int) -> None:
            self.stops, self.selected = stops, selected
            self.update()

        def _x(self, index: int) -> float:
            if len(self.stops) <= 1:
                return self.width() / 2.0
            return 20 + index * (self.width() - 40) / (len(self.stops) - 1)

        def _nearest(self, x: float) -> int:
            if not self.stops:
                return -1
            return min(range(len(self.stops)), key=lambda i: abs(self._x(i) - x))

        def _choose(self, index: int) -> None:
            if 0 <= index < len(self.stops) and index != self.selected:
                self.selected = index
                self.on_select(index)
                self.update()

        def mousePressEvent(self, event: Any) -> None:  # noqa: N802
            position = event.position() if hasattr(event, "position") else event.pos()
            self._choose(self._nearest(position.x()))

        def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
            if event.buttons():
                position = event.position() if hasattr(event, "position") else event.pos()
                self._choose(self._nearest(position.x()))

        def keyPressEvent(self, event: Any) -> None:  # noqa: N802
            if event.key() == QtCore.Qt.Key_Left:
                self._choose(max(0, self.selected - 1))
            elif event.key() == QtCore.Qt.Key_Right:
                self._choose(min(len(self.stops) - 1, self.selected + 1))
            else:
                super().keyPressEvent(event)

        def paintEvent(self, _event: Any) -> None:  # noqa: N802
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            middle = 20.0
            if not self.stops:
                painter.setPen(QtGui.QPen(QtGui.QColor("#C7CBE8"), 3))
                painter.drawLine(QtCore.QPointF(20, middle), QtCore.QPointF(self.width() - 20, middle))
                painter.end()
                return
            painter.setPen(QtGui.QPen(QtGui.QColor("#9AA5C8"), 3))
            painter.drawLine(QtCore.QPointF(self._x(0), middle), QtCore.QPointF(self._x(len(self.stops) - 1), middle))
            font = QtGui.QFont("Arial")
            font.setPixelSize(14)
            painter.setFont(font)
            room = (self.width() - 40) / max(1, len(self.stops) - 1)
            for index, stop in enumerate(self.stops):
                x = self._x(index)
                chosen = index == self.selected
                radius = 10.0 if chosen else 6.5
                colour = QtGui.QColor(BROKEN_RED if stop["broken"] else (FOUNDER_BLUE if chosen else "#5C6BC0"))
                painter.setPen(QtGui.QPen(colour, 3))
                painter.setBrush(QtGui.QColor("white") if stop["broken"] else colour)
                painter.drawEllipse(QtCore.QPointF(x, middle), radius, radius)
                if chosen or room >= 34 or index in (0, len(self.stops) - 1):
                    painter.setPen(QtGui.QColor(BROKEN_RED if stop["broken"] else INK))
                    label = f"v{stop['version']}" + (" broke" if stop["broken"] and (chosen or room >= 60) else "")
                    left = min(max(0.0, x - 45), self.width() - 90.0)       # never cut off at either end
                    painter.drawText(QtCore.QRectF(left, middle + 13, 90, 20), QtCore.Qt.AlignCenter, label)
            painter.end()

    return VersionTimeline


def _make_flow_layout(QtCore: Any, QtWidgets: Any) -> Any:
    class FlowLayout(QtWidgets.QLayout):  # type: ignore[misc]
        """Buttons in rows that wrap when the panel is narrow (never clipped)."""

        def __init__(self, parent: Any, spacing: int) -> None:
            super().__init__(parent)
            self._items: list[Any] = []
            self._spacing = spacing
            self.setContentsMargins(0, 0, 0, 0)

        def addItem(self, item: Any) -> None:  # noqa: N802
            self._items.append(item)

        def count(self) -> int:
            return len(self._items)

        def itemAt(self, index: int) -> Any:  # noqa: N802
            return self._items[index] if 0 <= index < len(self._items) else None

        def takeAt(self, index: int) -> Any:  # noqa: N802
            return self._items.pop(index) if 0 <= index < len(self._items) else None

        def expandingDirections(self) -> Any:  # noqa: N802
            return QtCore.Qt.Orientations(0)

        def hasHeightForWidth(self) -> bool:  # noqa: N802
            return True

        def heightForWidth(self, width: int) -> int:  # noqa: N802
            return self._layout(QtCore.QRect(0, 0, width, 0), apply=False)

        def setGeometry(self, rect: Any) -> None:  # noqa: N802
            super().setGeometry(rect)
            self._layout(rect, apply=True)

        def sizeHint(self) -> Any:  # noqa: N802
            return self.minimumSize()

        def minimumSize(self) -> Any:  # noqa: N802
            size = QtCore.QSize(0, 0)
            for item in self._items:
                size = size.expandedTo(item.minimumSize())
            # Once it has a width, its least height is every row it wraps into at that
            # width: reporting one row let a short panel squeeze the second row of
            # marking buttons over the picture (ORDER-2026-10-19-01).
            width = self.geometry().width()
            if width > 0:
                size.setHeight(max(size.height(), self.heightForWidth(width)))
            return size

        def _layout(self, rect: Any, apply: bool) -> int:
            x, y, line = rect.x(), rect.y(), 0
            for item in self._items:
                hint = item.sizeHint()
                if x + hint.width() > rect.right() + 1 and line > 0:
                    x, y, line = rect.x(), y + line + self._spacing, 0
                if apply:
                    item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
                x += hint.width() + self._spacing
                line = max(line, hint.height())
            return y + line - rect.y()

    return FlowLayout


# ---- settings the panel keeps for itself ---------------------------------------------------------
def _settings_path() -> Path:
    from integrations.cadwiz_plugin.session import plugin_data_dir

    return plugin_data_dir() / "panel.json"


def _load_settings() -> dict[str, Any]:
    with contextlib.suppress(Exception):
        return dict(json.loads(_settings_path().read_text(encoding="utf-8")))
    return {}


def _save_settings(settings: dict[str, Any]) -> None:
    with contextlib.suppress(Exception):
        _settings_path().write_text(json.dumps(settings, indent=1), encoding="utf-8")


def _build_line() -> str:
    """The build number, as M-CASH-REGISTER asks: the SHA `tools/ship.py` wrote, or
    this checkout's own commit when CADWiz runs from a developer copy."""
    with contextlib.suppress(Exception):
        from integrations.install_build_info import build_info_line

        line = build_info_line()
        if line:
            return line
    root = Path(__file__).resolve().parents[3]
    head = root / ".git" / "HEAD"
    with contextlib.suppress(OSError):
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref:"):
            ref = (root / ".git" / ref.split(" ", 1)[1]).read_text(encoding="utf-8").strip()
        return f"Build: {ref[:7]} (developer copy)"
    return ""


__all__ = ["build", "panel_lines", "timeline_stops", "stop_caption", "broken_caption", "version_line", "last_change_line",
           "connection", "paint_marks", "fit", "WizPlayer"]
