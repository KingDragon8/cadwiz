# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The Drawing screen on the Creating page (ORDER-2026-10-19-06).

Founder ruling 2026-10-19: a Drawing button, "like a technical drawing. And
associated support with that button." Pressing it shows the technical drawing
sheet of the open model in the picture area. The sheet is made in FreeCAD's
windowless program (`drawings.DrawingJob`): the window only saves a copy of the
model (milliseconds) and checks for the finished sheet once a second. It is made
again when the model changes. Claude's `drawing` tool -- dimensions he asks for --
lands here too, and those dimensions are kept when the sheet is remade.
Save as PDF prints to Letter; Open folder shows the saved drawings.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
import time
from pathlib import Path
from typing import Any

#: The model must have been still this long before the sheet is made again.
SETTLE_S = 2.0
WAITING = "Making the drawing… (a few seconds; FreeCAD stays free to use)"
NO_MODEL = "Open or build a model and its technical drawing appears here."


def model_signature(document: Any) -> Any:
    """Changes whenever the model does: an edit, an undo, a reload, a script."""
    if document is None:
        return None
    from integrations.cadwiz_plugin.problems_watch import _shape_fingerprint

    with contextlib.suppress(Exception):
        return (document.Name, getattr(document, "UndoCount", 0), getattr(document, "RedoCount", 0), len(document.Objects),
                _shape_fingerprint(document.Objects))
    return (getattr(document, "Name", ""),)


class DrawingScreen:
    def __init__(self, panel: Any, parent: Any) -> None:
        self.panel = panel
        QtCore, QtWidgets = panel.QtCore, panel.QtWidgets
        self.widget = QtWidgets.QWidget(parent)
        self.widget.setObjectName("CADWiz_Drawing")
        column = QtWidgets.QVBoxLayout(self.widget)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        self.sheet = _make_sheet_widget(QtCore, panel.QtGui, QtWidgets)(self.widget)
        self.sheet.setObjectName("CADWiz_Drawing_Sheet")
        column.addWidget(self.sheet, 1)
        self.status = QtWidgets.QLabel(NO_MODEL, self.widget)
        self.status.setObjectName("CADWiz_Drawing_Status")
        self.status.setWordWrap(True)
        column.addWidget(self.status)
        row = QtWidgets.QHBoxLayout()
        self.pdf_button = QtWidgets.QPushButton("Save as PDF", self.widget)
        self.pdf_button.setObjectName("CADWiz_Drawing_Save_PDF")
        self.pdf_button.setToolTip("Save this drawing as a Letter-size PDF, ready to print or send")
        self.pdf_button.clicked.connect(self.save_pdf)
        self.folder_button = QtWidgets.QPushButton("Open folder", self.widget)
        self.folder_button.setObjectName("CADWiz_Drawing_Open_Folder")
        self.folder_button.setToolTip("Show the folder where CADWiz keeps your drawings")
        self.folder_button.clicked.connect(self.open_folder)
        self.again_button = QtWidgets.QPushButton("Make again", self.widget)
        self.again_button.setObjectName("CADWiz_Drawing_Again")
        self.again_button.clicked.connect(lambda: self.start(force=True))
        for button in (self.pdf_button, self.folder_button, self.again_button):
            row.addWidget(button)
        row.addStretch(1)
        column.addLayout(row)
        self.job: Any = None
        self.copy: Path | None = None
        self.svg = ""
        self.made_for: Any = None
        self.pending: Any = None
        self.pending_since = 0.0
        self.seen_claude = ""
        self.extra: dict[str, Any] = {}          # Claude's dimensions and section choice, kept on a remake
        self._buttons()

    # ---- where the sheets live -------------------------------------------------------------------
    def folder(self) -> Path:
        session = self.panel.session()
        project = getattr(session, "project", None)
        base = Path(project.folder) if project is not None else Path(tempfile.gettempdir()) / "CADWiz"
        folder = base / "drawings"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _version(self, document: Any) -> int:
        session = self.panel.session()
        with contextlib.suppress(Exception):
            store = session.store_for(document) if session is not None else None
            return int(store.latest()) if store is not None else 0
        return 0

    # ---- making the sheet ---------------------------------------------------------------------------
    def start(self, force: bool = False) -> None:
        from integrations.cadwiz_plugin import drawings
        from integrations.cadwiz_plugin.session import _safe_doc_name

        document = self.panel.document()
        if document is None:
            self.svg = ""
            self.sheet.show_svg("")
            self.status.setText(NO_MODEL)
            self._buttons()
            return
        if self.job is not None and not force:
            return
        if self.job is not None:
            self.job.stop()
        label = str(getattr(document, "Label", "") or document.Name)
        version = self._version(document)
        stem = f"{_safe_doc_name(label)}_v{version}" if version else _safe_doc_name(label)
        folder = self.folder()
        self.copy = folder / f".{stem}.screen.FCStd"
        try:
            document.saveCopy(str(self.copy))
        except Exception:  # noqa: BLE001
            self.status.setText("The drawing could not be started: FreeCAD would not save a copy of this model.")
            return
        extra = self.extra if self.extra.get("document") == document.Name else {}
        self.job = drawings.DrawingJob(str(self.copy), str(folder / f"{stem}.svg"), title=label.replace("_", " "), version=version,
                                       section=str(extra.get("section") or "auto"), dimensions=list(extra.get("dimensions") or []))
        self.made_for = model_signature(document)
        self.status.setText(WAITING)
        self._buttons()

    def show(self) -> None:
        """The Drawing screen was opened: make the sheet unless the one shown is current."""
        if self.job is None and (not self.svg or self.made_for != model_signature(self.panel.document())):
            self.start()

    def watch(self, showing: bool) -> bool:
        """Called every second. Returns True when Claude just made a drawing (the
        panel then switches to this screen)."""
        fresh = self._claude_made_one()
        if self.job is not None:
            result = self.job.poll()
            if result is not None:
                self._finished(result)
        if showing and self.job is None:
            current = model_signature(self.panel.document())
            if current != self.made_for:
                if current != self.pending:
                    self.pending, self.pending_since = current, time.monotonic()
                elif time.monotonic() - self.pending_since >= SETTLE_S:
                    self.start()
        return fresh

    def _finished(self, result: dict[str, Any]) -> None:
        self.job = None
        if self.copy is not None:
            with contextlib.suppress(OSError):
                self.copy.unlink()
        if not result.get("ok"):
            self.status.setText(str(result.get("say") or "The drawing could not be made from this model."))
            self._buttons()
            return
        self.svg = str(result.get("svg") or "")
        self.sheet.show_svg(self.svg)
        document = self.panel.document()
        label = str(getattr(document, "Label", "")) if document is not None else ""
        from ai_freecad_core.drawings.sheet import scale_label

        self.status.setText(f"Drawing of {label.replace('_', ' ')}, made {time.strftime('%H:%M')} at scale "
                            f"{scale_label(float(result.get('scale') or 1))}. It is made again when the model changes.")
        self._buttons()

    def _claude_made_one(self) -> bool:
        session = self.panel.session()
        made = (getattr(session, "state", None) or {}).get("drawing") if session is not None else None
        if not made or made.get("utc") == self.seen_claude:
            return False
        first = not self.seen_claude
        self.seen_claude = str(made.get("utc"))
        if first and time.time() - _epoch(self.seen_claude) > 60:
            return False                                 # one from before the panel opened
        self.extra = {"document": made.get("document"), "dimensions": made.get("dimensions") or [], "section": made.get("section") or "auto"}
        if Path(str(made.get("svg") or "")).is_file():
            if self.job is not None:
                self.job.stop()
                self.job = None
            self.svg = str(made["svg"])
            self.sheet.show_svg(self.svg)
            self.made_for = model_signature(self.panel.document())
            self.status.setText(f"Your assistant made this drawing at {time.strftime('%H:%M')}. It is made again when the model changes.")
            self._buttons()
        return True

    # ---- his buttons ------------------------------------------------------------------------------
    def save_pdf(self) -> None:
        from integrations.cadwiz_plugin import drawings

        if not self.svg:
            return
        QtWidgets = self.panel.QtWidgets
        default = str(Path(self.svg).with_suffix(".pdf"))
        path, _kind = QtWidgets.QFileDialog.getSaveFileName(self.widget, "Save the drawing as a PDF", default, "PDF (*.pdf)")
        if not path:
            return
        try:
            drawings.svg_to_pdf(self.svg, path)
        except Exception:  # noqa: BLE001
            self.status.setText("The PDF could not be saved there. Try another folder.")
            return
        self.status.setText(f"Saved: {path}")

    def open_folder(self) -> None:
        with contextlib.suppress(Exception):
            os.startfile(str(self.folder()))  # noqa: S606 - his own drawings folder, in Explorer

    def _buttons(self) -> None:
        self.pdf_button.setEnabled(bool(self.svg) and self.job is None)
        self.again_button.setEnabled(self.panel.document() is not None)


def _epoch(utc: str) -> float:
    with contextlib.suppress(Exception):
        import calendar

        return float(calendar.timegm(time.strptime(utc, "%Y-%m-%dT%H:%M:%SZ")))
    return 0.0


def _make_sheet_widget(QtCore: Any, QtGui: Any, QtWidgets: Any) -> Any:
    class SheetWidget(QtWidgets.QWidget):  # type: ignore[misc]
        """The sheet, drawn sharp at any size, keeping its shape."""

        def __init__(self, parent: Any) -> None:
            super().__init__(parent)
            self.renderer: Any = None
            self.setMinimumHeight(120)
            self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        def show_svg(self, path: str) -> None:
            self.renderer = None
            if path and Path(path).is_file():
                from integrations.cadwiz_plugin.drawings import _qt

                _core, _gui, QtSvg = _qt()
                renderer = QtSvg.QSvgRenderer(str(path))
                if renderer.isValid():
                    self.renderer = renderer
            self.update()

        def paintEvent(self, _event: Any) -> None:  # noqa: N802
            painter = QtGui.QPainter(self)
            painter.fillRect(self.rect(), QtGui.QColor("#E8EAF6"))
            if self.renderer is not None:
                size = self.renderer.defaultSize()
                aspect = size.width() / float(max(size.height(), 1))
                w, h = self.width(), self.height()
                if w / float(max(h, 1)) > aspect:
                    w = int(h * aspect)
                else:
                    h = int(w / aspect)
                target = QtCore.QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
                painter.fillRect(target, QtGui.QColor("white"))
                painter.setRenderHint(QtGui.QPainter.Antialiasing)
                self.renderer.render(painter, target)
            painter.end()

    return SheetWidget
