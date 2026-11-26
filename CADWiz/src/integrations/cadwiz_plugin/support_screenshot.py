"""Capture only native CAD pixels; never desktop, chat, docks, titles or paths.

Text annotations and image objects cannot be safely masked without inspecting
their pixels. Those documents therefore use the text-only support fallback.
"""
from __future__ import annotations

from pathlib import Path

POLICY = "native-viewport-no-text-v1"


def capture(gui, app, destination: Path) -> bool:
    """Use the existing document/view without changing camera or presentation."""
    try:
        destination.unlink(missing_ok=True)
        document = app.ActiveDocument
        gui_document = gui.activeDocument()
        if document is None or gui_document is None or getattr(gui_document, "Document", None) is not document:
            return False
        for obj in document.Objects:
            kind = str(getattr(obj, "TypeId", "")).lower()
            properties = set(getattr(obj, "PropertiesList", ()) or ())
            # Linked/custom renderers can display external text or image pixels.
            # Do not resolve or mutate them: omit the image conservatively.
            if "link" in kind or "python" in kind or "LinkedObject" in properties:
                return False
            origin_primitive = kind in {"app::line", "app::plane", "app::point"}
            if not origin_primitive and not kind.startswith(("part::", "partdesign::", "sketcher::", "app::part", "app::origin")):
                return False
            provider = getattr(obj, "ViewObject", None)
            if getattr(provider, "Proxy", None) is not None:
                return False
            if any(getattr(provider, field, None) for field in ("TextureImage", "TextureImageFile")):
                return False
            if any(word in kind for word in ("annotation", "text", "image", "dimension", "drawing", "techdraw")):
                return False
            if properties.intersection({"Text", "LabelText", "TextLines", "ImageFile", "RichText"}):
                return False
        if app.ActiveDocument is not document or gui.activeDocument() is not gui_document:
            return False
        view = gui_document.activeView()
        # Native renderer excludes all application chrome and private panels.
        view.saveImage(str(destination), 960, 720, "Current")
        if destination.is_file() and destination.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
            return True
    except Exception:
        pass
    # Never leave a partial or uncertain image available to the sender.
    try:
        destination.unlink(missing_ok=True)
    except OSError:
        pass
    return False
