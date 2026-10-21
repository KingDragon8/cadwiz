# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""What the founder and Claude look at together (ORDER-2026-10-18-01).

One `ScreenState` per FreeCAD session, held by the plug-in session so the panel
and Claude's tools share it (both run on FreeCAD's window thread):

  * the marks on the Visual Communications Screen -- his (blue) and Claude's
    (orange) -- anchored to the model;
  * the frame he froze with Show Claude: the picture with his marks, the marks
    themselves, what he had selected, the view, the document and its version.
    It stays exactly as frozen until he presses Show Claude again, so he can keep
    working without changing what Claude is talking about;
  * whether Claude has read that frame, which makes the panel flash
    "Claude has it".

No Qt and no FreeCAD here: the panel draws and captures, `view_link` reads the
view, and this keeps the record.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from ai_freecad_core.visual_communications.anchored import (
    AnchoredMark,
    Camera,
    MarkBook,
    describe_marks,
)
from ai_freecad_core.visual_communications.contracts import VisualMarkAuthor

NOTHING_SHOWN = ("The user has not pressed Show Claude yet, so there is no frozen frame. "
                 "Use get_selection for what the user has selected and render(current_view=true) for what is on their screen.")
HOW_TO_READ = ("The first picture is exactly what the user froze: their marks are blue and numbered, yours are orange. "
               "The second is the same view without marks. Every mark is anchored on the model in mm (document coordinates), "
               "with the object and face it sits on when it was drawn on a surface. 'This' and 'here' mean their marks and "
               "their selection, most recent first.")


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ScreenState:
    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder) / "shown"
        #: Marks belong to one document each: a circle on the helmet never lands
        #: on the bracket he switches to. `active_document` is set by the panel.
        self.books: dict[str, MarkBook] = {}
        self.active_document = ""
        #: The concept stage (ORDER-2026-10-18-02 A): rounds of up-to-three cards,
        #: his pick, and whether he pressed Make it 3D. Kept on disk for the session's
        #: design so a restart of FreeCAD does not lose his choice.
        from ai_freecad_core.cadwiz_screen.concepts import ConceptHistory

        self.concepts_file = Path(folder) / "concepts" / "history.json"
        self.concepts = ConceptHistory()
        try:
            self.concepts = ConceptHistory.from_dict(json.loads(self.concepts_file.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.shown: dict[str, Any] | None = None
        self.frames = 0
        #: Set by the panel: draw the screen as it is now (picture + every mark) to
        #: a file and return its path, so Claude can see the marks it just made.
        self.compose: Callable[[], str] | None = None
        #: Set by the panel: the camera and picture shape the screen shows now.
        self.current_view: Callable[[], tuple[Camera | None, float]] | None = None

    def book_for(self, document: str) -> MarkBook:
        return self.books.setdefault(str(document or ""), MarkBook())

    @property
    def book(self) -> MarkBook:
        """The marks of the document on screen now."""
        return self.book_for(self.active_document)

    # ---- Show Claude ----------------------------------------------------------------
    def freeze(self, *, picture: str, clean_picture: str, camera: Camera | None, aspect: float, selection: list[dict[str, Any]],
               view: str, cut_away: bool, document: str, file: str, version: int, latest_version: int,
               broken: list[str] | None = None, request: dict[str, Any] | None = None) -> dict[str, Any]:
        """Freeze what is on the screen now as 'what I'm showing Claude'."""
        self.frames += 1
        marks = list(self.book.marks)
        founder = [m for m in marks if m.author is VisualMarkAuthor.USER]
        self.shown = {
            "frame": self.frames,
            "frozen_at_utc": _utc(),
            "read_by_claude_utc": None,
            "document": document,
            "file": file,
            "version": version,
            "latest_version": latest_version,
            "version_line": (f"version {version} of {latest_version}" if version else "no saved versions yet"),
            "model_in_error": list(broken or []),
            "view": view,
            "cut_away": bool(cut_away),
            "camera": camera.to_dict() if camera is not None else None,
            "picture_aspect": round(float(aspect), 6),
            "marks": [m.to_dict() for m in marks],
            "marks_in_words": describe_marks(marks),
            "founder_mark_count": len(founder),
            "selection": selection,
            "pictures": [p for p in (picture, clean_picture) if p],
            "how_to_read": HOW_TO_READ,
        }
        if self.concepts.rounds:
            self.shown["concepts"] = self.concepts.summary()
        if request:
            # A button on his screen asked for something (ORDER-2026-10-18-03: "Ask Claude to fix").
            self.shown["the_founder_asks"] = request
        self._write()
        return dict(self.shown)

    def read(self) -> dict[str, Any] | None:
        """Claude reads the frozen frame; the panel sees the read and flashes."""
        if self.shown is None:
            return None
        self.shown["read_by_claude_utc"] = _utc()
        self.shown["read_count"] = int(self.shown.get("read_count") or 0) + 1
        self._write()
        return dict(self.shown)

    def frozen_camera(self) -> tuple[Camera | None, float]:
        if not self.shown or not self.shown.get("camera"):
            return None, 1.0
        return Camera.from_dict(self.shown["camera"]), float(self.shown.get("picture_aspect") or 1.0)

    def _write(self) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            (self.folder / "shown.json").write_text(json.dumps(self.shown, indent=1, default=str), encoding="utf-8")
        except OSError:
            pass

    def picture_path(self, kind: str) -> Path:
        """Where a frozen picture goes: one pair of files per frame, kept for the
        session so an earlier frame Claude is talking about is never overwritten."""
        self.folder.mkdir(parents=True, exist_ok=True)
        return self.folder / f"frame-{self.frames + 1:03d}-{kind}.png"

    # ---- the concept stage ---------------------------------------------------------
    def save_concepts(self) -> None:
        try:
            self.concepts_file.parent.mkdir(parents=True, exist_ok=True)
            self.concepts_file.write_text(json.dumps(self.concepts.to_dict(), indent=1), encoding="utf-8")
        except OSError:
            pass

    def new_design(self) -> None:
        """Start a fresh concept history; the old one stays on disk under a dated name."""
        from ai_freecad_core.cadwiz_screen.concepts import ConceptHistory

        if self.concepts.rounds and self.concepts_file.is_file():
            stamp = time.strftime("%Y%m%d-%H%M%S")
            try:
                self.concepts_file.replace(self.concepts_file.with_name(f"history-{stamp}.json"))
            except OSError:
                pass
        self.concepts = ConceptHistory()
        self.save_concepts()

    # ---- Claude's marks ------------------------------------------------------------
    def claude_marks(self, document: str | None = None) -> list[AnchoredMark]:
        book = self.book if document is None else self.book_for(document)
        return book.by(VisualMarkAuthor.ASSISTANT)
