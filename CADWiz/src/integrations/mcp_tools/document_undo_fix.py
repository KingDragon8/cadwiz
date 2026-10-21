# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""PROVE-SWEEP batch 8 defect fix: undo/redo do not work on ANY document
CADWiz creates or opens through the ordinary product path, because nothing
ever enables it.

`create_document`/`open_document` (`vendor/robust-mcp/src/freecad_mcp/
bridge/embedded.py`, called by the identically-named MCP tools in
`vendor/robust-mcp/src/freecad_mcp/tools/documents.py`) call `FreeCAD.
newDocument(name)`/`FreeCAD.openDocument(path)` and nothing else. Real
FreeCAD's own `Document.UndoMode` property defaults to `0` (disabled) for a
document created this way -- confirmed directly 2026-09-11: `doc.
openTransaction(...)/commitTransaction()` (every mutating tool in this
program wraps its own call in exactly this pattern) leaves `doc.UndoCount
== 0` when `UndoMode == 0`, so `undo`'s own `elif doc.UndoCount > 0:
doc.undo()` branch never fires -- `undo`/`redo` silently no-op on every
document the product creates, regardless of how many operations were
performed. Setting `doc.UndoMode = 1` immediately after creation/opening is
the measured, complete fix: transactions are then recorded normally and
`undo`/`redo` work exactly as documented (confirmed against a real
multi-step chain -- two boxes and a boolean cut -- undone and redone
correctly, `tests/freecad_integration/runtime_prove_sweep_batch8.py`).

**Scope, disclosed rather than assumed.** This fixes the two entry points
that create a NEW in-memory document reference the rest of the product
actually calls (`create_document`, `open_document`) -- it does not audit
every other place in this codebase that might call `FreeCAD.newDocument`/
`FreeCAD.openDocument` directly (test harnesses in `tests/
freecad_integration/`, for instance, deliberately call `FreeCAD.
newDocument` themselves and are not covered, nor need to be for their own
qualification purposes -- see `runtime_prove_sweep_batch8.py`'s own `main()`
turning `UndoMode` on directly for its own document, the identical
one-line fix applied at the point that matters for that harness).

`vendor/` is never edited in place: this overrides both tools under their
existing names, the same technique PROVE-026's fix (`fillet_pro.py`) uses
for `fillet_edges`/`chamfer_edges` -- `mcp.remove_tool` first, since
FastMCP's own `ToolManager.add_tool` silently keeps the FIRST registration
on a name collision. Implemented via a direct generated-code string (like
every other tool in this program), not by depending on
`bridge.create_document`/`bridge.open_document`'s own typed return value,
since it differs across the vendored bridge backends (embedded/socket/
xmlrpc) and this fix only needs to run inside FreeCAD's own process.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable


def register_document_undo_fix(mcp: Any, get_bridge: Callable[[], Awaitable[Any]]) -> None:
    mcp.remove_tool("create_document")
    mcp.remove_tool("open_document")

    @mcp.tool()
    async def create_document(
        name: str = "Unnamed",
        label: str | None = None,
    ) -> dict[str, Any]:
        """Create a new FreeCAD document.

        Fixed 2026-09-11 (PROVE-SWEEP): sets `UndoMode = 1` on the new
        document -- FreeCAD's own default (`0`) means `undo`/`redo` silently
        no-op on every operation performed afterward, regardless of how many
        transactions were committed.

        Args:
            name: Internal document name (no spaces allowed, will be sanitized).
            label: Display label (can contain spaces). Defaults to name.

        Returns:
            Dictionary with created document information:
                - name: Internal document name
                - label: Display label
                - path: File path (None for new document)
        """
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.newDocument({name!r})
doc.Label = {label!r} or {name!r}
doc.UndoMode = 1

_result_ = {{
    "name": doc.Name,
    "label": doc.Label,
    "path": doc.FileName or None,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Create document failed")

    @mcp.tool()
    async def open_document(path: str) -> dict[str, Any]:
        """Open an existing FreeCAD document from file.

        Fixed 2026-09-11 (PROVE-SWEEP): sets `UndoMode = 1` on the opened
        document, for the same reason `create_document`'s own fix does.

        Args:
            path: Full path to the .FCStd file to open.

        Returns:
            Dictionary with opened document information:
                - name: Internal document name
                - label: Display label
                - path: File path
                - objects: List of object names

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the file is not a valid FreeCAD document.
        """
        bridge = await get_bridge()
        code = f"""
import os

if not os.path.exists({path!r}):
    raise FileNotFoundError(f"File not found: {path!r}")

doc = FreeCAD.openDocument({path!r})
doc.UndoMode = 1

_result_ = {{
    "name": doc.Name,
    "label": doc.Label,
    "path": doc.FileName or None,
    "objects": [obj.Name for obj in doc.Objects],
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Open document failed")
