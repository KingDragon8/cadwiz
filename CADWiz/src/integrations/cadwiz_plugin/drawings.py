# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Technical drawings for the Drawing button and Claude's `drawing` tool (ORDER-2026-10-19-06).

Founder ruling 2026-10-19 ("You can run it whenever you think it's best"): a
Drawing button, "like a technical drawing. And associated support with that
button." The sheet is made by `drawing_job.py` in FreeCAD's windowless program,
from a saved copy of the open model -- the window never waits on projection
(ORDER-2026-10-19-03) -- and laid out by `ai_freecad_core.drawings.sheet`.
Here: start that job (and wait for it, pumped, when Claude asks), and turn the
finished SVG into a PDF to print or a picture for the screen.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from importlib import import_module
from pathlib import Path
from typing import Any, Callable

#: The job is stopped after this long (a very complex model), and says so.
TIME_LIMIT_S = 180.0
JOB = Path(__file__).with_name("drawing_job.py")


class DrawingJob:
    """One drawing being made, in its own process; `poll()` never waits."""

    def __init__(self, source: str, out_svg: str, *, title: str, version: int = 0, section: str = "auto",
                 dimensions: list[dict[str, Any]] | None = None, note: str = "",
                 launch: Callable[[Path], Any] | None = None) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="cadwiz_drawing_"))
        self.out_svg = out_svg
        request = {"source": source, "out_svg": out_svg, "title": title, "version": int(version or 0), "section": section,
                   "date": time.strftime("%Y-%m-%d"), "dimensions": list(dimensions or []), "note": note}
        self.request_path = self.folder / "request.json"
        self.request_path.write_text(json.dumps(request), encoding="utf-8")
        self.started = time.monotonic()
        self.process = (launch or _launch)(self.request_path)
        self.result: dict[str, Any] | None = None

    def poll(self) -> dict[str, Any] | None:
        """The result once the job has finished (or been stopped), else None."""
        if self.result is not None:
            return self.result
        if self.process.poll() is None:
            if time.monotonic() - self.started < TIME_LIMIT_S:
                return None
            self.stop()
            self.result = {"ok": False, "say": f"The drawing took longer than {TIME_LIMIT_S:.0f} seconds and was stopped."}
            return self.result
        try:
            self.result = json.loads((self.folder / "result.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.result = {"ok": False, "say": "The drawing could not be made from this model."}
        return self.result

    def stop(self) -> None:
        if self.process.poll() is None:
            try:
                self.process.kill()
            except OSError:
                pass

    def wait(self, pump: Callable[[], None] | None = None) -> dict[str, Any]:
        """Wait for the result, keeping the window answering (and Cancel working) through `pump`."""
        while True:
            result = self.poll()
            if result is not None:
                return result
            if pump is not None:
                pump()
            time.sleep(0.05)


def _launch(request: Path) -> Any:
    from integrations.ai_master.executor import find_freecadcmd

    return subprocess.Popen(  # noqa: S603 - FreeCAD's own windowless program running our own script
        [str(find_freecadcmd()), str(JOB), str(request)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _qt() -> tuple[Any, Any, Any]:
    gui = import_module("PySide.QtGui")
    core = import_module("PySide.QtCore")
    try:
        svg = import_module("PySide.QtSvg")
    except ImportError:
        svg = import_module("PySide6.QtSvg")
    return core, gui, svg


def svg_to_pdf(svg_path: str, pdf_path: str) -> str:
    """A Letter-size PDF of the sheet, ready to print."""
    QtCore, QtGui, QtSvg = _qt()
    renderer = QtSvg.QSvgRenderer(str(svg_path))
    writer = QtGui.QPdfWriter(str(pdf_path))
    writer.setPageSize(QtGui.QPageSize(QtGui.QPageSize.Letter))
    writer.setPageOrientation(QtGui.QPageLayout.Landscape)
    writer.setPageMargins(QtCore.QMarginsF(0, 0, 0, 0))
    writer.setResolution(300)
    painter = QtGui.QPainter(writer)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    return str(pdf_path)


def svg_to_png(svg_path: str, png_path: str, width: int = 1600) -> str:
    """A picture of the sheet (for Claude to see, and for the screen)."""
    QtCore, QtGui, QtSvg = _qt()
    renderer = QtSvg.QSvgRenderer(str(svg_path))
    size = renderer.defaultSize()
    height = int(width * size.height() / max(size.width(), 1))
    image = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.white)
    painter = QtGui.QPainter(image)
    try:
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        renderer.render(painter)
    finally:
        painter.end()
    image.save(str(png_path))
    return str(png_path)
