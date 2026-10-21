# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The Problems-and-fixes card and the Printing and Setup pages of the CADWiz panel
(ORDER-2026-10-18-03, docs/CADWIZ-PANEL-REDESIGN-PROPOSAL.md section 2.6).

Kept apart from `slim_panel.py` (the Creating page and the screen itself) because
these hold behaviour the founder can't check by eye: what counts as a problem,
the settings Claude reads and follows, exports and the print check. Slow lane.
"""
from __future__ import annotations

import contextlib
import json
import time
from importlib import import_module
from pathlib import Path
from typing import Any

from ai_freecad_core.cadwiz_screen.licences import read_licence
from ai_freecad_core.cadwiz_screen.preferences import (
    BIG_CHANGES,
    EXPLANATIONS,
    LICENCE_CHOICES,
    MODEL_SITES,
    QUALITIES,
    QUESTIONS,
    TEXT_SIZES,
    FounderPreferences,
    Printer,
)
from ai_freecad_core.cadwiz_screen.problems import Problem, from_print_notes, summary_line
from ai_freecad_core.visual_communications.anchored import inches_first

CONCEPTS_MIN_HEIGHT = 160          # the design cards scroll; never sets the panel's height (ORDER-2026-10-19-01)
ASK_CLAUDE = "Now tell Claude “fix it” in the Claude app."
PRINT_TIME_HONEST = ("Print time and filament: your slicer shows these when you open the file in it. "
                     "CADWiz can't read them from {slicer} yet.")


CLAUDE_USAGE_LINE = ("Your talks with Claude come out of your Claude subscription -- there is no charge per question. "
                     "Claude doesn't tell CADWiz how much of it you have used; to see that, open the Claude app: "
                     "Settings > Usage.")


def usage_lines(rows: list[dict[str, Any]]) -> list[str]:
    """The Setup page's Usage section (ORDER-2026-10-19-02), from the one local log
    of paid AI calls CADWiz itself made (`spend_guard.log_path()`). Only what the
    log holds: it records replies and tokens, never cost or project, so neither is
    ever shown as a number."""
    mine = [r for r in rows if r.get("made_by") == "founder" and r.get("event") == "usage"]
    if not mine:
        return [CLAUDE_USAGE_LINE, "CADWiz itself has made no paid AI calls on this computer, so it has cost you nothing."]
    providers = sorted({str(r.get("provider") or "an AI service") for r in mine})
    tokens_in = sum(int(r.get("input_tokens") or 0) for r in mine)
    tokens_out = sum(int(r.get("output_tokens") or 0) for r in mine)
    first, last = min(r.get("utc", "") for r in mine)[:10], max(r.get("utc", "") for r in mine)[:10]
    when = f"on {last}" if first == last else f"from {first} to {last}"
    return [
        CLAUDE_USAGE_LINE,
        f"CADWiz's own paid AI calls (its old built-in assistant, using your {', '.join(providers)} key): "
        f"{len(mine):,} answers {when}, {tokens_in:,} tokens sent and {tokens_out:,} received. None since {last}.",
        f"CADWiz never recorded what those cost or which project they were for; your {', '.join(providers)} "
        "account's usage page shows the bill.",
    ]


CHATGPT_CONNECTED = "ChatGPT connected"
CHATGPT_NOT_CONNECTED = "ChatGPT not connected"
CHATGPT_TODO = ("The ChatGPT app can't reach programs on your PC yet. Codex, signed in with your ChatGPT account, "
                "can -- see Setup > Connection.")
CODEX_STEPS = ("To use ChatGPT instead: the ChatGPT app can't connect to programs on your PC yet, but "
               "Codex (signed in with your ChatGPT account) can. Ask Claude or a helper to add CADWiz to Codex's "
               "settings file (.codex\\config.toml) the same way it is in Claude's. The ChatGPT light turns green "
               "only when Codex has really connected.")


def ai_lights(bridge: Any, choice: str) -> list[dict[str, str]]:
    """The connection lines at the top of the Creating page (ORDER-2026-10-19-02),
    for the AI app he picked ("auto", "claude" or "chatgpt"). A line is green only
    when that app's own copy of the CADWiz server said hello lately."""
    from integrations.cadwiz_plugin.slim_panel import CONNECTED, GREEN, NOT_CONNECTED, NOT_CONNECTED_TODO, RED, connection

    if bridge is None:
        return [connection(None)]
    claude_on = bridge.connected_to("claude") if hasattr(bridge, "connected_to") else bool(bridge.connected)
    chatgpt_on = bridge.connected_to("chatgpt") if hasattr(bridge, "connected_to") else False
    claude = ({"light": GREEN, "line": CONNECTED, "todo": ""} if claude_on
              else {"light": RED, "line": NOT_CONNECTED, "todo": NOT_CONNECTED_TODO})
    chatgpt = ({"light": GREEN, "line": CHATGPT_CONNECTED, "todo": ""} if chatgpt_on
               else {"light": RED, "line": CHATGPT_NOT_CONNECTED, "todo": CHATGPT_TODO})
    if choice == "claude":
        return [claude]
    if choice == "chatgpt":
        return [chatgpt]
    lights = [light for light, on in ((claude, claude_on), (chatgpt, chatgpt_on)) if on]
    return lights or [claude]


class AiChoice:
    """Top of the Creating page: which AI app he talks to -- Claude, ChatGPT, or
    whichever he has open -- and a light per app. Saved in his preferences."""

    def __init__(self, panel: Any, parent: Any) -> None:
        from ai_freecad_core.cadwiz_screen.preferences import AI_APPS

        self.panel = panel
        QtWidgets = panel.QtWidgets
        # One row (the panel puts its own light first): [light] [second light] ... Talk to [choice].
        self.row = QtWidgets.QHBoxLayout()
        self.row.setSpacing(10)
        self.second = QtWidgets.QLabel(parent)
        self.second.setObjectName("CADWiz_Connection_Light_2")
        self.second.setProperty("role", "light")
        self.second.setVisible(False)
        self.row.addWidget(self.second)
        self.row.addStretch(1)
        self.row.addWidget(QtWidgets.QLabel("Talk to", parent))
        self.combo = QtWidgets.QComboBox(parent)
        self.combo.setObjectName("CADWiz_AI_App")
        self.combo.addItems(list(AI_APPS.values()))
        self.keys = list(AI_APPS)
        self.combo.setCurrentIndex(self.keys.index(panel.prefs.ai_app))
        self.combo.currentIndexChanged.connect(self.choose)
        self.row.addWidget(self.combo)

    def choose(self, index: int) -> None:
        self.panel.prefs.ai_app = self.keys[index]
        self.panel.save_preferences()
        self.refresh()

    def refresh(self) -> None:
        """Repaint the panel's light lines (and the strip light) for his choice."""
        panel = self.panel
        lights = ai_lights(panel.bridge(), panel.prefs.ai_app)
        first = lights[0]
        panel.light.setText(f"● {first['line']}")
        panel.light.setStyleSheet(f"color: {first['light']}; font-weight: 700;")
        panel.todo.setText(first["todo"])
        panel.todo.setVisible(bool(first["todo"]))
        panel.strip_light.setStyleSheet(f"color: {first['light']}; font-size: 28px;")
        panel.strip_light.setToolTip("\n".join(light["line"] for light in lights))
        if len(lights) > 1:
            self.second.setText(f"● {lights[1]['line']}")
            self.second.setStyleSheet(f"color: {lights[1]['light']}; font-weight: 700;")
        self.second.setVisible(len(lights) > 1)


def licence_line(document: Any) -> str:
    """The Printing page's licence line: from the record CADWiz keeps beside an
    imported model (`<file>.source.json`), else 'your own design'."""
    file_name = str(getattr(document, "FileName", "") or "")
    if file_name:
        record = Path(file_name).with_suffix(".source.json")
        with contextlib.suppress(OSError, ValueError):
            data = json.loads(record.read_text(encoding="utf-8"))
            reading = read_licence(str(data.get("licence") or ""))
            source = str(data.get("source") or "")
            return f"Licence: {reading.plain}" + (f" (from {source})" if source else "")
    return "Licence: your own design -- yours to print and sell."


def visible_size_mm(document: Any) -> tuple[float, float, float] | None:
    """The size of what would print: visible solids and meshes only -- never
    FreeCAD's origin planes and axes, which are endless (found by eye 2026-10-18:
    they turned the bed-fit line into a 300-digit number)."""
    from integrations.cadwiz_plugin.problems_watch import _parts, _visible

    box = None
    with contextlib.suppress(Exception):
        for _name, _label, solid in _parts(list(document.Objects)):
            bound = solid.BoundBox
            box = bound if box is None else box.united(bound)
        for obj in document.Objects:
            if str(getattr(obj, "TypeId", "")) == "Mesh::Feature" and _visible(obj):
                mesh = obj.Mesh.copy()
                with contextlib.suppress(Exception):
                    mesh.transform(obj.Placement.toMatrix())
                box = mesh.BoundBox if box is None else box.united(mesh.BoundBox)
    if box is None or max(box.XLength, box.YLength, box.ZLength) > 1e6:
        return None
    return (box.XLength, box.YLength, box.ZLength)


def bed_fit_line(size: tuple[float, float, float] | None, printer: Printer) -> str:
    if size is None:
        return "Fits the bed: nothing solid to measure yet."
    bed = sorted((printer.bed_x_mm, printer.bed_y_mm))
    footprint = sorted(size[:2])
    fits = footprint[0] <= bed[0] and footprint[1] <= bed[1] and size[2] <= printer.bed_z_mm
    words = " x ".join(inches_first(v) for v in size)
    return (f"Fits the {printer.name} bed: {'yes' if fits else 'NO'} -- the model is {words}; the bed is "
            f"{printer.bed_x_mm:g} x {printer.bed_y_mm:g} x {printer.bed_z_mm:g} mm.")


def _clear(layout: Any) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


class ProblemsCard:
    """Problems and fixes, on the Creating page."""

    def __init__(self, panel: Any, parent: Any) -> None:
        self.panel = panel
        QtWidgets = panel.QtWidgets
        self.box, column = panel._section(parent, "Problems and fixes", "CADWiz_Problems")
        self.summary = QtWidgets.QLabel(self.box)
        self.summary.setObjectName("CADWiz_Problems_Summary")
        self.summary.setWordWrap(True)
        column.addWidget(self.summary)
        self.scroll = QtWidgets.QScrollArea(self.box)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setMaximumHeight(230)
        holder = QtWidgets.QWidget(self.scroll)
        self.rows = QtWidgets.QVBoxLayout(holder)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.scroll.setWidget(holder)
        column.addWidget(self.scroll)
        self.scroll.hide()
        self.problems: list[Problem] = []
        self.keys: tuple[str, ...] | None = None
        self.signature: Any = None
        self.checked_at = 0.0

    def watch(self) -> None:
        """Called every second: look again only when the document or the connection changed."""
        from integrations.cadwiz_plugin.problems_watch import find_problems, signature

        document = self.panel.document()
        bridge = self.panel.bridge()
        connected = bool(bridge is not None and bridge.connected)
        current = signature(document, connected)
        if current == self.signature and time.monotonic() - self.checked_at < 30:
            return
        self.signature, self.checked_at = current, time.monotonic()
        try:
            problems = find_problems(document, connected)
        except Exception:  # noqa: BLE001 - a failed look leaves the last list up
            return
        self.show(problems)

    def show(self, problems: list[Problem]) -> None:
        self.problems = problems
        self.summary.setText(summary_line(problems))
        keys = tuple(p.key + p.what for p in problems)
        if keys == self.keys:
            return
        self.keys = keys
        _clear(self.rows)
        for problem in problems:
            self.rows.addWidget(problem_row(self.panel, self.box, problem, with_show_me=True, with_go_back=True))
        self.scroll.setVisible(bool(problems))
        if problems:
            self.scroll.widget().adjustSize()
            self.scroll.setFixedHeight(min(260, self.scroll.widget().sizeHint().height() + 6))


def problem_row(panel: Any, parent: Any, problem: Problem, *, with_show_me: bool, with_go_back: bool) -> Any:
    """One problem: what, how to fix, and its buttons."""
    QtCore, QtWidgets = panel.QtCore, panel.QtWidgets
    row = QtWidgets.QFrame(parent)
    row.setObjectName("CADWiz_Problem")
    row.setProperty("role", "problem")
    column = QtWidgets.QVBoxLayout(row)
    column.setContentsMargins(8, 6, 8, 6)
    heading = QtWidgets.QLabel(problem.heading, row)
    heading.setStyleSheet("font-weight: 700; color: #B3261E;")
    what = QtWidgets.QLabel(problem.what, row)
    what.setWordWrap(True)
    fix = QtWidgets.QLabel("How to fix: " + problem.how_to_fix, row)
    fix.setWordWrap(True)
    more = QtWidgets.QLabel(problem.explanation, row)
    more.setWordWrap(True)
    more.setObjectName("CADWiz_Problem_Explanation")
    more.hide()
    for widget in (heading, what, fix, more):
        column.addWidget(widget)
    buttons = QtWidgets.QWidget(row)
    from integrations.cadwiz_plugin.slim_panel import _make_flow_layout

    flow = _make_flow_layout(QtCore, QtWidgets)(buttons, 6)
    ask = QtWidgets.QPushButton("Ask Claude to fix", buttons)
    ask.setObjectName("CADWiz_Problem_Ask_Claude")
    ask.clicked.connect(lambda: panel.ask_claude_to_fix(problem))
    explain = QtWidgets.QPushButton("Explain", buttons)
    explain.setObjectName("CADWiz_Problem_Explain")
    explain.setCheckable(True)
    explain.toggled.connect(more.setVisible)
    flow.addWidget(ask)
    flow.addWidget(explain)
    if with_show_me and problem.objects:
        show = QtWidgets.QPushButton("Show me", buttons)
        show.setObjectName("CADWiz_Problem_Show_Me")
        show.clicked.connect(lambda: panel.show_problem(problem))
        flow.addWidget(show)
    if with_go_back and problem.kind in ("rebuild", "sketch_open", "sketch_broken", "mesh_holes", "loose", "overlap"):
        back = QtWidgets.QPushButton("Go back to the last good version", buttons)
        back.setObjectName("CADWiz_Problem_Go_Back")
        back.clicked.connect(panel.go_back_to_last_good)
        flow.addWidget(back)
    column.addWidget(buttons)
    return row


class PrintingPage:
    """Printing: will it print, printer/material/quality, preview figures, export."""

    def __init__(self, panel: Any) -> None:
        self.panel = panel
        QtCore, QtWidgets = panel.QtCore, panel.QtWidgets
        self.last_export = ""
        self.page = QtWidgets.QWidget(panel.full)
        self.page.setObjectName("CADWiz_Printing_Page")
        scroll = QtWidgets.QScrollArea(self.page)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget(scroll)
        column = QtWidgets.QVBoxLayout(inner)
        column.setSpacing(10)

        check, c_col = panel._section(inner, "Will it print?", "CADWiz_Will_It_Print")
        button = QtWidgets.QPushButton("Check now", check)
        button.setObjectName("CADWiz_Check_Print")
        button.clicked.connect(self.check)
        self.verdict = QtWidgets.QLabel("Checks overhangs, thin parts, bed fit, whether it is a closed solid, and loose pieces.", check)
        self.verdict.setObjectName("CADWiz_Print_Verdict")
        self.verdict.setWordWrap(True)
        self.print_rows = QtWidgets.QVBoxLayout()
        c_col.addWidget(button)
        c_col.addWidget(self.verdict)
        c_col.addLayout(self.print_rows)
        column.addWidget(check)

        choice, p_col = panel._section(inner, "Printer, material and quality")
        form = QtWidgets.QFormLayout()
        p_col.addLayout(form)
        self.printer_choice = QtWidgets.QComboBox(choice)
        self.printer_choice.setObjectName("CADWiz_Print_Printer")
        self.material_choice = QtWidgets.QComboBox(choice)
        self.material_choice.setObjectName("CADWiz_Print_Material")
        self.quality_choice = QtWidgets.QComboBox(choice)
        self.quality_choice.setObjectName("CADWiz_Print_Quality")
        self.quality_choice.addItems(list(QUALITIES.values()))
        form.addRow("Printer", self.printer_choice)
        form.addRow("Material", self.material_choice)
        form.addRow("Quality", self.quality_choice)
        for combo in (self.printer_choice, self.material_choice, self.quality_choice):
            combo.activated.connect(self.save_choice)
        column.addWidget(choice)

        preview, v_col = panel._section(inner, "Print preview")
        self.bed_line = QtWidgets.QLabel(preview)
        self.bed_line.setObjectName("CADWiz_Print_Bed_Fit")
        self.bed_line.setWordWrap(True)
        self.time_line = QtWidgets.QLabel(preview)
        self.time_line.setObjectName("CADWiz_Print_Time")
        self.time_line.setWordWrap(True)
        v_col.addWidget(self.bed_line)
        v_col.addWidget(self.time_line)
        column.addWidget(preview)

        export, e_col = panel._section(inner, "Export")
        holder = QtWidgets.QWidget(export)
        from integrations.cadwiz_plugin.slim_panel import _make_flow_layout

        flow = _make_flow_layout(QtCore, QtWidgets)(holder, 6)
        for fmt in ("3MF", "STL", "STEP"):
            fmt_button = QtWidgets.QPushButton(f"Export {fmt}", holder)
            fmt_button.setObjectName(f"CADWiz_Export_{fmt}")
            fmt_button.clicked.connect(lambda _c=False, f=fmt.lower(): self.export(f))
            flow.addWidget(fmt_button)
        folder = QtWidgets.QPushButton("Open the folder", holder)
        folder.setObjectName("CADWiz_Open_Export_Folder")
        folder.clicked.connect(self.open_folder)
        slicer = QtWidgets.QPushButton("Open in slicer", holder)
        slicer.setObjectName("CADWiz_Open_Slicer")
        slicer.clicked.connect(self.open_in_slicer)
        flow.addWidget(folder)
        flow.addWidget(slicer)
        self.export_result = QtWidgets.QLabel("Files go to CADWiz's project folder; nothing of yours is overwritten.", export)
        self.export_result.setObjectName("CADWiz_Export_Result")
        self.export_result.setWordWrap(True)
        self.licence = QtWidgets.QLabel(export)
        self.licence.setObjectName("CADWiz_Licence_Line")
        self.licence.setWordWrap(True)
        e_col.addWidget(holder)
        e_col.addWidget(self.export_result)
        e_col.addWidget(self.licence)
        column.addWidget(export)
        column.addStretch(1)
        scroll.setWidget(inner)
        layout = QtWidgets.QVBoxLayout(self.page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def refresh(self) -> None:
        prefs = self.panel.prefs
        self._fill(self.printer_choice, [p.name for p in prefs.printers], prefs.default_printer)
        materials = [m.strip() for m in prefs.materials_on_hand.split(",") if m.strip()] or [prefs.print_material]
        self._fill(self.material_choice, materials, prefs.print_material)
        self.quality_choice.setCurrentIndex(list(QUALITIES).index(prefs.print_quality))
        document = self.panel.document()
        self.bed_line.setText(bed_fit_line(visible_size_mm(document) if document is not None else None, prefs.printer))
        self.time_line.setText(PRINT_TIME_HONEST.format(slicer=prefs.slicer or "your slicer"))
        self.licence.setText(licence_line(document) if document is not None else "")

    @staticmethod
    def _fill(combo: Any, items: list[str], current: str) -> None:
        blocked = combo.blockSignals(True)
        combo.clear()
        combo.addItems(items)
        if current in items:
            combo.setCurrentIndex(items.index(current))
        combo.blockSignals(blocked)

    def save_choice(self, *_args: Any) -> None:
        prefs = self.panel.prefs
        prefs.default_printer = self.printer_choice.currentText() or prefs.default_printer
        prefs.print_material = self.material_choice.currentText() or prefs.print_material
        prefs.print_quality = list(QUALITIES)[self.quality_choice.currentIndex()]
        self.panel.save_preferences()
        self.refresh()

    def check(self) -> None:
        panel = self.panel
        document = panel.document()
        if document is None:
            self.verdict.setText(panel.NO_MODEL)
            return
        self.verdict.setText("Checking…")
        panel.QtWidgets.QApplication.processEvents()
        reply = panel._call("check_print", {"document": document.Name})
        from integrations.cadwiz_plugin.problems_watch import find_problems

        extra = [p for p in find_problems(document, True) if p.kind in ("loose", "mesh_holes")]
        _clear(self.print_rows)
        if not reply.get("ok"):
            self.verdict.setText(reply.get("say_to_founder") or "The check did not finish.")
            return
        problems = from_print_notes([str(n) for n in reply.get("notes") or []]) + extra
        printer = reply.get("printer") or "your printer"
        if reply.get("ready") and not problems:
            self.verdict.setText(f"Ready to print on {printer}.")
        else:
            self.verdict.setText(f"Not ready to print on {printer} yet: {len(problems)} thing{'s' if len(problems) != 1 else ''} to look at.")
        for problem in problems:
            self.print_rows.addWidget(problem_row(panel, self.page, problem, with_show_me=False, with_go_back=False))
        self.refresh()

    def export(self, fmt: str) -> None:
        panel = self.panel
        document = panel.document()
        if document is None:
            self.export_result.setText(panel.NO_MODEL)
            return
        self.export_result.setText("Exporting…")
        reply = panel._call("export", {"format": fmt, "document": document.Name})
        if reply.get("ok") and reply.get("path"):
            self.last_export = str(reply["path"])
            self.export_result.setText(f"Saved {self.last_export}")
        else:
            self.export_result.setText(reply.get("say_to_founder") or "The export did not finish.")

    def open_folder(self) -> None:
        folder = Path(self.last_export).parent if self.last_export else None
        session = self.panel.session()
        if folder is None and session is not None:
            folder = Path(session.project.folder) / "exports"
        if folder is not None:
            folder.mkdir(parents=True, exist_ok=True)
            self.panel.QtGui.QDesktopServices.openUrl(self.panel.QtCore.QUrl.fromLocalFile(str(folder)))

    def open_in_slicer(self) -> None:
        if not self.last_export or not Path(self.last_export).is_file():
            self.export_result.setText("Export a 3MF or STL first, then open it in the slicer.")
            return
        slicer = str(self.panel.prefs.slicer or "")
        if slicer.lower().endswith(".exe") and Path(slicer).is_file():
            import subprocess

            subprocess.Popen([slicer, self.last_export])  # noqa: S603 - his own slicer, on his own file
        else:
            self.panel.QtGui.QDesktopServices.openUrl(self.panel.QtCore.QUrl.fromLocalFile(self.last_export))
        self.export_result.setText(f"Opened {Path(self.last_export).name} in your slicer.")


class SetupPage:
    """Setup: connection, my workshop, how Claude works with you, models and
    licences, saving and versions, help, the build number."""

    def __init__(self, panel: Any) -> None:
        self.panel = panel
        QtCore, QtWidgets = panel.QtCore, panel.QtWidgets
        self.page = QtWidgets.QWidget(panel.full)
        self.page.setObjectName("CADWiz_Setup_Page")
        scroll = QtWidgets.QScrollArea(self.page)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget(scroll)
        column = QtWidgets.QVBoxLayout(inner)
        column.setSpacing(10)

        link, l_col = panel._section(inner, "Connection")
        self.light = QtWidgets.QLabel(link)
        self.light.setObjectName("CADWiz_Setup_Light")
        self.tools = QtWidgets.QLabel(link)
        self.tools.setObjectName("CADWiz_Setup_Tool_Count")
        steps = QtWidgets.QLabel(
            "When the light is red:\n"
            "1. Quit the Claude app fully: right-click its icon by the clock and choose Quit, then open it again.\n"
            "2. Keep FreeCAD open: CADWiz starts with it.\n"
            "3. In a Claude chat, check that CADWiz is switched on under the + (Search and tools) button.\n"
            "4. The first time Claude uses CADWiz it asks; choose Allow always.", link)
        steps.setWordWrap(True)
        codex = QtWidgets.QLabel(CODEX_STEPS, link)
        codex.setObjectName("CADWiz_Setup_ChatGPT_Steps")
        codex.setWordWrap(True)
        for widget in (self.light, self.tools, steps, codex):

            l_col.addWidget(widget)
        column.addWidget(link)

        shop, s_col = panel._section(inner, "My workshop", "CADWiz_My_Workshop")
        form = QtWidgets.QFormLayout()
        s_col.addLayout(form)
        printers_row = QtWidgets.QHBoxLayout()
        self.printer_list = QtWidgets.QComboBox(shop)
        self.printer_list.setObjectName("CADWiz_Setup_Printers")
        self.printer_list.currentIndexChanged.connect(self._show_printer)
        add = QtWidgets.QPushButton("Add a printer", shop)
        add.clicked.connect(self.add_printer)
        printers_row.addWidget(self.printer_list, 1)
        printers_row.addWidget(add)
        form.addRow("Printers", printers_row)
        self.printer_name = QtWidgets.QLineEdit(shop)
        self.bed = [QtWidgets.QDoubleSpinBox(shop) for _ in range(3)]
        bed_row = QtWidgets.QHBoxLayout()
        for spin in self.bed:
            spin.setRange(10, 2000)
            spin.setSuffix(" mm")
            bed_row.addWidget(spin)
        self.nozzle = QtWidgets.QDoubleSpinBox(shop)
        self.nozzle.setRange(0.1, 2.0)
        self.nozzle.setSingleStep(0.1)
        self.nozzle.setSuffix(" mm")
        self.default_box = QtWidgets.QCheckBox("This is my default printer", shop)
        form.addRow("Name", self.printer_name)
        form.addRow("Bed (width, depth, height)", bed_row)
        form.addRow("Nozzle", self.nozzle)
        form.addRow("", self.default_box)
        self.materials = QtWidgets.QLineEdit(shop)
        self.materials.setPlaceholderText("PLA, PETG, TPU")
        self.slicer = QtWidgets.QLineEdit(shop)
        self.slicer.setPlaceholderText("A slicer's name, or the full path of its .exe")
        self.units = QtWidgets.QComboBox(shop)
        self.units.addItems(["Inches first (mm beside)", "Millimetres first (inches beside)"])
        self.text_size = QtWidgets.QComboBox(shop)
        self.text_size.addItems([f"{px} px" for px in TEXT_SIZES])
        form.addRow("Materials on hand", self.materials)
        form.addRow("Slicer", self.slicer)
        form.addRow("Units", self.units)
        form.addRow("Text size", self.text_size)
        column.addWidget(shop)

        how, h_col = panel._section(inner, "How Claude works with you", "CADWiz_How_Claude_Works")
        note = QtWidgets.QLabel("Claude reads these through CADWiz and follows them. For lessons, ask Claude in the Claude app "
                                "(“teach me how fillets work”).", how)
        note.setWordWrap(True)
        h_col.addWidget(note)
        how_form = QtWidgets.QFormLayout()
        h_col.addLayout(how_form)
        self.explanations = self._combo(how, EXPLANATIONS, "CADWiz_Setup_Explanations")
        self.questions = self._combo(how, QUESTIONS, "CADWiz_Setup_Questions")
        self.big_changes = self._combo(how, BIG_CHANGES, "CADWiz_Setup_Big_Changes")
        how_form.addRow("Explanations", self.explanations)
        how_form.addRow("Questions before building", self.questions)
        how_form.addRow("Before big changes", self.big_changes)
        column.addWidget(how)

        models, m_col = panel._section(inner, "Models and licences")
        models_form = QtWidgets.QFormLayout()
        m_col.addLayout(models_form)
        self.licences = self._combo(models, LICENCE_CHOICES, "CADWiz_Setup_Licences")
        models_form.addRow("Downloaded models", self.licences)
        sites = QtWidgets.QHBoxLayout()
        self.sites = {}
        for site in MODEL_SITES:
            box = QtWidgets.QCheckBox(site, models)
            sites.addWidget(box)
            self.sites[site] = box
        sites.addStretch(1)
        models_form.addRow("Sites Claude searches", sites)
        column.addWidget(models)

        saving, v_col = panel._section(inner, "Saving and versions")
        folder_row = QtWidgets.QHBoxLayout()
        self.folder = QtWidgets.QLabel(saving)
        self.folder.setWordWrap(True)
        choose = QtWidgets.QPushButton("Choose…", saving)
        choose.clicked.connect(self.choose_folder)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(choose)
        v_col.addLayout(folder_row)
        shown_row = QtWidgets.QHBoxLayout()
        self.versions_shown = QtWidgets.QSpinBox(saving)
        self.versions_shown.setRange(1, 500)
        shown_row.addWidget(QtWidgets.QLabel("Versions on the time slider", saving))
        shown_row.addWidget(self.versions_shown)
        shown_row.addStretch(1)
        v_col.addLayout(shown_row)
        always = QtWidgets.QLabel("Always on: a version is saved before every change Claude makes. CADWiz never deletes a version.", saving)
        always.setWordWrap(True)
        v_col.addWidget(always)
        column.addWidget(saving)

        usage, u_col = panel._section(inner, "Usage", "CADWiz_Setup_Usage")
        self.usage = QtWidgets.QLabel(usage)
        self.usage.setObjectName("CADWiz_Setup_Usage_Lines")
        self.usage.setWordWrap(True)
        u_col.addWidget(self.usage)
        column.addWidget(usage)

        save_row = QtWidgets.QHBoxLayout()
        save = QtWidgets.QPushButton("Save settings", inner)
        save.setObjectName("CADWiz_Save_Settings")
        save.setProperty("role", "primary")
        save.clicked.connect(self.save)
        self.saved = QtWidgets.QLabel(inner)
        save_row.addWidget(save)
        save_row.addWidget(self.saved, 1)
        column.addLayout(save_row)

        help_box, x_col = panel._section(inner, "Help")
        from integrations.cadwiz_plugin.slim_panel import EXAMPLE_SENTENCES

        x_col.addWidget(QtWidgets.QLabel("Five things to say to Claude:", help_box))
        for sentence in EXAMPLE_SENTENCES:
            row = QtWidgets.QHBoxLayout()
            words = QtWidgets.QLabel(f"“{sentence}”", help_box)
            words.setWordWrap(True)
            copy = QtWidgets.QPushButton("Copy", help_box)
            copy.clicked.connect(lambda _c=False, s=sentence: QtWidgets.QApplication.clipboard().setText(s))
            row.addWidget(words, 1)
            row.addWidget(copy)
            x_col.addLayout(row)
        self.report_note = QtWidgets.QLineEdit(help_box)
        self.report_note.setPlaceholderText("What went wrong, in a few words")
        report = QtWidgets.QPushButton("Report a problem", help_box)
        report.setObjectName("CADWiz_Report_Problem")
        report.clicked.connect(self.report)
        self.report_result = QtWidgets.QLabel("Saves a picture of FreeCAD and your note, and copies a report to paste into the Claude chat.",
                                              help_box)
        self.report_result.setWordWrap(True)
        # ORDER-2026-10-21-01 (Addendum One B3): Get help opens cadwiz.app/feedback with the
        # form filled in -- versions, and the report id when there is a recent report.
        get_help = QtWidgets.QPushButton("Get help", help_box)
        get_help.setObjectName("CADWiz_Get_Help")
        get_help.setToolTip("Opens cadwiz.app/feedback in your browser with CADWiz's versions (and your latest report's id) filled in")
        get_help.clicked.connect(self.get_help)
        self.last_report_id = ""
        x_col.addWidget(self.report_note)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(report)
        buttons.addWidget(get_help)
        x_col.addLayout(buttons)
        x_col.addWidget(self.report_result)
        column.addWidget(help_box)

        from integrations.cadwiz_plugin.slim_panel import _build_line

        self.build = QtWidgets.QLabel(_build_line(), inner)
        self.build.setObjectName("CADWiz_Build")
        self.build.setStyleSheet("color: #5F6368;")
        column.addWidget(self.build)
        column.addStretch(1)
        scroll.setWidget(inner)
        layout = QtWidgets.QVBoxLayout(self.page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)
        self._printers: list[Printer] = []

    def _combo(self, parent: Any, choices: dict[str, str], name: str) -> Any:
        combo = self.panel.QtWidgets.QComboBox(parent)
        combo.setObjectName(name)
        combo.addItems(list(choices.values()))
        return combo

    def refresh(self) -> None:
        prefs: FounderPreferences = self.panel.prefs
        from integrations.cadwiz_plugin.session import TOOL_NAMES

        lights = ai_lights(self.panel.bridge(), prefs.ai_app)
        light = lights[0]
        self.light.setText("\n".join(f"● {each['line']}" for each in lights))
        self.light.setStyleSheet(f"color: {light['light']}; font-weight: 700;")
        self.tools.setText(f"{len(TOOL_NAMES)} CADWiz tools are available to Claude.")
        self._printers = [Printer(p.name, p.bed_x_mm, p.bed_y_mm, p.bed_z_mm, p.nozzle_mm) for p in prefs.printers]
        self._default = prefs.default_printer
        blocked = self.printer_list.blockSignals(True)
        self.printer_list.clear()
        self.printer_list.addItems([p.name for p in self._printers])
        self.printer_list.setCurrentIndex([p.name for p in self._printers].index(prefs.default_printer))
        self.printer_list.blockSignals(blocked)
        self._current = self.printer_list.currentIndex()
        self._load_printer(self._current)
        self.materials.setText(prefs.materials_on_hand)
        self.slicer.setText(prefs.slicer)
        self.units.setCurrentIndex(0 if prefs.inches_first else 1)
        self.text_size.setCurrentIndex(TEXT_SIZES.index(prefs.text_px))
        self.explanations.setCurrentIndex(list(EXPLANATIONS).index(prefs.explanations))
        self.questions.setCurrentIndex(list(QUESTIONS).index(prefs.questions))
        self.big_changes.setCurrentIndex(list(BIG_CHANGES).index(prefs.big_changes))
        self.licences.setCurrentIndex(list(LICENCE_CHOICES).index(prefs.licences))
        for site, box in self.sites.items():
            box.setChecked(site in prefs.model_sites)
        session = self.panel.session()
        folder = prefs.project_folder or (str(session.project.folder) if session is not None else "")
        self.folder.setText(f"Project folder: {folder}")
        self._folder = prefs.project_folder
        self.versions_shown.setValue(prefs.versions_shown)
        self.saved.setText("")
        from ai_freecad_core.ai.spend_guard import _log_rows

        self.usage.setText("\n\n".join(usage_lines(_log_rows())))

    def _load_printer(self, index: int) -> None:
        if not 0 <= index < len(self._printers):
            return
        printer = self._printers[index]
        self.printer_name.setText(printer.name)
        for spin, value in zip(self.bed, (printer.bed_x_mm, printer.bed_y_mm, printer.bed_z_mm)):
            spin.setValue(value)
        self.nozzle.setValue(printer.nozzle_mm)
        self.default_box.setChecked(printer.name == self.panel.prefs.default_printer)

    def _keep_printer(self, index: int) -> None:
        if not 0 <= index < len(self._printers):
            return
        name = self.printer_name.text().strip() or self._printers[index].name
        self._printers[index] = Printer(name, self.bed[0].value(), self.bed[1].value(), self.bed[2].value(), self.nozzle.value())
        if self.default_box.isChecked():
            self._default = name

    def _show_printer(self, index: int) -> None:
        self._keep_printer(getattr(self, "_current", index))
        self._current = index
        self._load_printer(index)

    def add_printer(self) -> None:
        self._keep_printer(self._current)
        name = f"Printer {len(self._printers) + 1}"
        self._printers.append(Printer(name))
        self.printer_list.addItem(name)
        self.printer_list.setCurrentIndex(len(self._printers) - 1)

    def choose_folder(self) -> None:
        chosen = self.panel.QtWidgets.QFileDialog.getExistingDirectory(self.page, "Project folder", self._folder or str(Path.home()))
        if chosen:
            self._folder = chosen
            self.folder.setText(f"Project folder: {chosen}")

    def save(self) -> None:
        self._keep_printer(self._current)
        try:
            prefs = FounderPreferences(
                printers=self._printers, default_printer=self._default, materials_on_hand=self.materials.text().strip() or "PLA",
                print_material=self.panel.prefs.print_material, print_quality=self.panel.prefs.print_quality,
                slicer=self.slicer.text().strip(), inches_first=self.units.currentIndex() == 0,
                text_px=TEXT_SIZES[self.text_size.currentIndex()], explanations=list(EXPLANATIONS)[self.explanations.currentIndex()],
                questions=list(QUESTIONS)[self.questions.currentIndex()], big_changes=list(BIG_CHANGES)[self.big_changes.currentIndex()],
                licences=list(LICENCE_CHOICES)[self.licences.currentIndex()],
                model_sites=[site for site, box in self.sites.items() if box.isChecked()] or list(MODEL_SITES),
                project_folder=self._folder or "", versions_shown=self.versions_shown.value())
        except ValueError as error:
            self.saved.setText(f"Not saved: {error}.")
            return
        self.panel.prefs = prefs
        self.panel.save_preferences()
        self.saved.setText("Saved. Claude follows these from its next message.")
        self.refresh()

    def report(self) -> None:
        panel = self.panel
        from integrations.cadwiz_plugin.session import plugin_data_dir
        from integrations.cadwiz_plugin.slim_panel import _build_line, connection

        folder = plugin_data_dir() / "reports"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        picture = folder / f"report-{stamp}.png"
        with contextlib.suppress(Exception):
            import_module("FreeCADGui").getMainWindow().grab().save(str(picture))
        lines = ["CADWiz problem report", f"What went wrong: {self.report_note.text().strip() or '(no note)'}",
                 _build_line() or "Build: not recorded", f"Connection: {connection(panel.bridge())['line']}"]
        with contextlib.suppress(Exception):
            lines.append("FreeCAD " + ".".join(import_module("FreeCAD").Version()[:3]))
        document = panel.document()
        lines.append(f"Open model: {document.Label if document is not None else 'none'}")
        session = panel.session()
        log = Path(getattr(session, "log_path", "") or "") if session is not None else None
        if log is not None and log.is_file():
            with contextlib.suppress(Exception):
                for row in log.read_text(encoding="utf-8").splitlines()[-10:]:
                    entry = json.loads(row)
                    lines.append(f"{entry.get('utc')} {entry.get('tool')} {'ok' if entry.get('ok') else 'FAILED: ' + str(entry.get('detail', ''))[:160]}")
        if picture.is_file():
            lines.append(f"Picture: {picture}")
        from integrations.cadwiz_plugin.error_report import write_report

        def copy_picture(path: Path) -> bool:
            if not picture.is_file():
                return False
            path.write_bytes(picture.read_bytes())
            return True

        if log is not None:
            self.last_report_id = write_report(
                plugin_data_dir(), error_code="CW-PANEL-REPORT", message=self.report_note.text().strip() or "(no note)",
                tool="report_a_problem", log_path=log, grab_window=copy_picture,
                model_file=str(getattr(document, "FileName", "") or ""), version_info=self._versions())
        if self.last_report_id:
            lines.insert(1, f"Report id: {self.last_report_id}")
        text = "\n".join(lines)
        (folder / f"report-{stamp}.txt").write_text(text, encoding="utf-8")
        panel.QtWidgets.QApplication.clipboard().setText(text)
        self.report_result.setText("Copied. Paste it into the Claude chat" + (f" and attach the picture {picture.name} from {folder}." if picture.is_file() else ".")
                                   + (f" Or press Get help to send report {self.last_report_id} on cadwiz.app." if self.last_report_id else ""))

    @staticmethod
    def _versions() -> dict[str, str]:
        import platform

        from integrations.cadwiz_plugin import CADWIZ_VERSION

        freecad = ""
        with contextlib.suppress(Exception):
            freecad = ".".join(import_module("FreeCAD").Version()[:3])
        return {"cadwiz": CADWIZ_VERSION, "freecad": freecad or "unknown", "os": platform.platform(terse=True),
                "claude_desktop": "unknown"}

    def get_help(self) -> None:
        from integrations.cadwiz_plugin.error_report import load_report
        from integrations.cadwiz_plugin.feedback import get_help_url
        from integrations.cadwiz_plugin.session import plugin_data_dir

        versions = self._versions()
        report = load_report(plugin_data_dir(), self.last_report_id) if self.last_report_id else None
        url = get_help_url(freecad_version=versions["freecad"], os_name=versions["os"],
                           error_code=str((report or {}).get("error_code", "")), report_id=self.last_report_id if report else "")
        qt_gui = import_module("PySide.QtGui")
        qt_core = import_module("PySide.QtCore")
        qt_gui.QDesktopServices.openUrl(qt_core.QUrl(url))
        self.report_result.setText("cadwiz.app/feedback is open in your browser. You can attach the picture there.")


class ConceptsView:
    """"Choosing a design" on the Creating page (ORDER-2026-10-18-02 A): the
    newest round of up to three cards, earlier rounds one click away, Pick this,
    and Make it 3D -- the only way (besides telling Claude) a concept becomes 3D."""

    CARD_WIDTH = 250

    def __init__(self, panel: Any, parent: Any) -> None:
        from ai_freecad_core.cadwiz_screen.concepts import HONEST_LINE

        self.panel = panel
        QtWidgets = panel.QtWidgets
        self.widget = QtWidgets.QWidget(parent)
        self.widget.setObjectName("CADWiz_Concepts")
        column = QtWidgets.QVBoxLayout(self.widget)
        column.setContentsMargins(6, 6, 6, 6)
        self.title = QtWidgets.QLabel(self.widget)
        self.title.setProperty("role", "heading")
        self.title.setWordWrap(True)
        honest = QtWidgets.QLabel(HONEST_LINE, self.widget)
        honest.setObjectName("CADWiz_Concepts_Honest")
        honest.setWordWrap(True)
        honest.setStyleSheet("color: #5F6368;")
        column.addWidget(self.title)
        column.addWidget(honest)
        scroll = QtWidgets.QScrollArea(self.widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        # It shares the screen's place with the picture, so its minimum is the whole
        # panel's: 340 here made CADWiz 930 px tall at the least and cut page 1 off
        # on his screen (ORDER-2026-10-19-01). The cards scroll instead.
        scroll.setMinimumHeight(CONCEPTS_MIN_HEIGHT)
        holder = QtWidgets.QWidget(scroll)
        self.cards = QtWidgets.QHBoxLayout(holder)
        self.cards.setSpacing(10)
        self.cards.setAlignment(panel.QtCore.Qt.AlignTop)
        scroll.setWidget(holder)
        column.addWidget(scroll, 1)
        history = QtWidgets.QHBoxLayout()
        history.addWidget(QtWidgets.QLabel("Rounds:", self.widget))
        self.rounds_holder = QtWidgets.QHBoxLayout()
        history.addLayout(self.rounds_holder)
        history.addStretch(1)
        self.make_3d = QtWidgets.QPushButton("Make it 3D", self.widget)
        self.make_3d.setObjectName("CADWiz_Make_It_3D")
        self.make_3d.setProperty("role", "primary")
        self.make_3d.setToolTip("Tell Claude you are happy with the picked design: it builds the 3D model on your next message")
        self.make_3d.clicked.connect(self.request_3d)
        history.addWidget(self.make_3d)
        column.addLayout(history)
        self.status = QtWidgets.QLabel(self.widget)
        self.status.setObjectName("CADWiz_Concepts_Status")
        self.status.setWordWrap(True)
        column.addWidget(self.status)
        self.seen_rounds = -1
        self.showing = 0

    def history(self) -> Any:
        return self.panel.screen().concepts

    def watch(self) -> bool:
        """True when Claude posted a new round since the last look (the panel then
        switches the screen to Choosing a design).

        Watched by the newest round's own time, not by the number of rounds: a new
        design starts its history again at round 1, so a trash can posted after a
        tennis ball left the count at 1 and the screen never switched (founder,
        2026-10-19: "I don't see the three options")."""
        rounds = self.history().rounds
        newest = (len(rounds), rounds[-1].utc, tuple(c.title for c in rounds[-1].cards)) if rounds else (0, "", ())
        if newest == self.seen_rounds:
            return False
        fresh = self.seen_rounds != -1 and bool(rounds)
        self.seen_rounds = newest
        self.showing = len(rounds)
        self.render()
        return fresh

    def render(self) -> None:
        panel = self.panel
        QtCore, QtGui, QtWidgets = panel.QtCore, panel.QtGui, panel.QtWidgets
        history = self.history()
        _clear(self.cards)
        _clear(self.rounds_holder)
        if not history.rounds:
            self.title.setText("No designs to choose from yet. Ask Claude for ideas (“show me three concepts for a shelf bracket”).")
            self.make_3d.setEnabled(False)
            self.status.setText("")
            return
        round_ = history.rounds[self.showing - 1]
        self.title.setText(f"Choosing a design -- round {round_.number} of {len(history.rounds)}" + (f": {round_.note}" if round_.note else ""))
        for number, card in enumerate(round_.cards, start=1):
            frame = QtWidgets.QFrame()
            frame.setObjectName("CADWiz_Concept_Card")
            frame.setProperty("role", "section")
            frame.setFixedWidth(self.CARD_WIDTH)
            frame.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Maximum)
            col = QtWidgets.QVBoxLayout(frame)
            picture = QtWidgets.QLabel(frame)
            picture.setAlignment(QtCore.Qt.AlignCenter)
            pixmap = _picture(QtCore, QtGui, card.picture, self.CARD_WIDTH - 24)
            if pixmap is not None:
                picture.setPixmap(pixmap)
            else:
                picture.setText("(the picture could not be shown)")
            title = QtWidgets.QLabel(f"{number}. {card.title}", frame)
            title.setStyleSheet("font-weight: 700;")
            title.setWordWrap(True)
            source = QtWidgets.QLabel("Claude's sketch" if card.kind == "sketch" else f"Found: {card.source}", frame)
            source.setWordWrap(True)
            licence = QtWidgets.QLabel(card.licence_line(), frame)
            licence.setWordWrap(True)
            three_d = QtWidgets.QLabel(card.three_d_line(), frame)
            three_d.setWordWrap(True)
            pick = QtWidgets.QPushButton("Picked" if round_.picked == number else "Pick this", frame)
            pick.setObjectName("CADWiz_Concept_Pick")
            pick.setCheckable(True)
            pick.setChecked(round_.picked == number)
            pick.clicked.connect(lambda _c=False, r=round_.number, k=number: self.pick(r, k))
            for widget in (picture, title, source, licence, three_d, pick):
                col.addWidget(widget)
            col.addStretch(1)
            self.cards.addWidget(frame)
        self.cards.addStretch(1)
        for other in history.rounds:
            button = QtWidgets.QPushButton(str(other.number))
            button.setCheckable(True)
            button.setChecked(other.number == self.showing)
            button.setToolTip(other.note or f"round {other.number}")
            button.clicked.connect(lambda _c=False, n=other.number: self.show_round(n))
            self.rounds_holder.addWidget(button)
        chosen = history.chosen()
        self.make_3d.setEnabled(chosen is not None)
        if history.make_3d:
            self.status.setText(f"You asked for “{history.make_3d['title']}” in 3D. Tell Claude “make it 3D” if you have not yet.")
        elif chosen is not None:
            self.status.setText(f"Picked: “{chosen[1].title}” (round {chosen[0].number}). Ask Claude for changes, or press Make it 3D.")
        else:
            self.status.setText("Pick the design you like, or tell Claude what to change.")

    def show_round(self, number: int) -> None:
        self.showing = number
        self.render()

    def pick(self, round_number: int, card: int) -> None:
        self.history().pick(round_number, card)
        self.panel.screen().save_concepts()
        self.render()
        self.panel.wiz_player.activity()

    def request_3d(self) -> None:
        try:
            asked = self.history().request_3d()
        except ValueError as error:
            self.status.setText(str(error)[0].upper() + str(error)[1:] + ".")
            return
        self.panel.screen().save_concepts()
        self.render()
        self.panel.flash(f"Now tell Claude “make it 3D” in the Claude app ({asked['title']}).", self.panel.FOUNDER_BLUE, seconds=5.0)


def _picture(QtCore: Any, QtGui: Any, path: str, width: int) -> Any:
    pixmap = None
    if path.lower().endswith(".svg"):
        with contextlib.suppress(Exception):
            QtSvg = import_module("PySide.QtSvg")
            renderer = QtSvg.QSvgRenderer(path)
            if renderer.isValid():
                size = renderer.defaultSize()
                height = int(width * size.height() / max(1, size.width()))
                image = QtGui.QImage(width, max(1, height), QtGui.QImage.Format_ARGB32)
                image.fill(QtCore.Qt.white)
                painter = QtGui.QPainter(image)
                renderer.render(painter)
                painter.end()
                pixmap = QtGui.QPixmap.fromImage(image)
    if pixmap is None:
        pixmap = QtGui.QPixmap(path)
    if pixmap is None or pixmap.isNull():
        return None
    return pixmap.scaledToWidth(width, QtCore.Qt.SmoothTransformation)
