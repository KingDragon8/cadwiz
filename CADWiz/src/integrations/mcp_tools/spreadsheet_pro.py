# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""PROVE-SWEEP batch 10 defect fix: `spreadsheet_get_cell`'s own alias
detection and `spreadsheet_get_aliases`' own alias enumeration
(`vendor/robust-mcp/src/freecad_mcp/tools/spreadsheet.py`) never find a
real alias in FreeCAD 1.1.3, for any cell, on any sheet.

Both use the same wrong approach: iterate `sheet.PropertiesList` (or
`dir(sheet)`) and call `sheet.getCellFromAlias(candidate)`, hoping one of
those names happens to BE an alias. Confirmed directly 2026-09-11: a real
alias ("Len" on cell A1, set via the already-correct `spreadsheet_set_
alias`) is never found this way -- `sheet.PropertiesList` for a
`Spreadsheet::Sheet` lists the CELL's own address ("A1") as a dynamic
property, not the alias name ("Len"), so `getCellFromAlias("A1")` (a cell
address, not an alias) returns nothing, and `getCellFromAlias("Len")`
(the one call that WOULD work) is never made because "Len" never appears
in `PropertiesList` or `dir(sheet)` at all. `sheet.getCellFromAlias
("Len")` called directly DOES correctly return `"A1"` -- the underlying
alias mechanism works; only these two tools' own way of finding it does
not.

**The fix.** FreeCAD's own `Sheet.getUsedCells()` returns every cell
address with content; `Sheet.getAlias(cell_address)` returns that cell's
own alias (or `None`) directly -- the reverse of `getCellFromAlias`, and
the correct primitive for "what alias does this cell have", confirmed
directly 2026-09-11 for both an aliased and a non-aliased cell.

`vendor/` is never edited in place: both tools are re-registered under
their existing names, the same technique PROVE-026's fix (`fillet_pro.py`)
uses -- `mcp.remove_tool` first, since FastMCP's own `ToolManager.add_tool`
silently keeps the FIRST registration on a name collision.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable


def register_spreadsheet_pro_tools(mcp: Any, get_bridge: Callable[[], Awaitable[Any]]) -> None:
    mcp.remove_tool("spreadsheet_get_cell")
    mcp.remove_tool("spreadsheet_get_aliases")

    @mcp.tool()
    async def spreadsheet_get_cell(
        spreadsheet_name: str,
        cell: str,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Get the value of a cell in a spreadsheet.

        Fixed 2026-09-11 (PROVE-SWEEP): resolves the cell's own alias via
        `Sheet.getAlias(cell)` directly, not the vendored tool's own
        `PropertiesList`/`dir()` scan through `getCellFromAlias`, which
        never actually matched a real alias in FreeCAD 1.1.3.

        Args:
            spreadsheet_name: Name of the spreadsheet object.
            cell: Cell address (e.g., "A1", "B2").
            doc_name: Document containing the spreadsheet. Uses active if None.

        Returns:
            Dictionary with cell information:
                - cell: Cell address
                - value: Raw value (formula if it's a formula)
                - computed: Computed/displayed value
                - alias: Cell alias if set, None otherwise
        """
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

sheet = doc.getObject({spreadsheet_name!r})
if sheet is None:
    raise ValueError(f"Spreadsheet not found: {spreadsheet_name!r}")

cell = {cell!r}

try:
    computed = sheet.get(cell)
except Exception:
    computed = None

try:
    content = sheet.getContents(cell)
except Exception:
    content = None

try:
    alias = sheet.getAlias(cell) or None
except Exception:
    alias = None

_result_ = {{
    "cell": cell,
    "value": content,
    "computed": computed,
    "alias": alias,
}}
"""
        result = await bridge.execute_python(code)
        if result.success and result.result:
            return result.result
        raise ValueError(result.error_traceback or "Failed to get cell")

    @mcp.tool()
    async def spreadsheet_get_aliases(
        spreadsheet_name: str,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Get all aliases defined in a spreadsheet.

        Fixed 2026-09-11 (PROVE-SWEEP): enumerates aliases via `Sheet.
        getUsedCells()` + `Sheet.getAlias(cell)` per cell, not the vendored
        tool's own `PropertiesList` scan through `getCellFromAlias`, which
        never actually found a real alias in FreeCAD 1.1.3 (confirmed:
        `PropertiesList` lists a cell's own address as a dynamic property,
        never the alias name itself).

        Args:
            spreadsheet_name: Name of the spreadsheet object.
            doc_name: Document containing the spreadsheet. Uses active if None.

        Returns:
            Dictionary with aliases:
                - spreadsheet: Spreadsheet name
                - aliases: Dictionary mapping alias names to cell addresses
                - count: Number of aliases
        """
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

sheet = doc.getObject({spreadsheet_name!r})
if sheet is None:
    raise ValueError(f"Spreadsheet not found: {spreadsheet_name!r}")

aliases = {{}}
try:
    for used_cell in sheet.getUsedCells():
        try:
            alias_name = sheet.getAlias(used_cell)
            if alias_name:
                aliases[alias_name] = used_cell
        except Exception:
            pass
except Exception:
    pass

_result_ = {{
    "spreadsheet": sheet.Name,
    "aliases": aliases,
    "count": len(aliases),
}}
"""
        result = await bridge.execute_python(code)
        if result.success and result.result:
            return result.result
        raise ValueError(result.error_traceback or "Failed to get aliases")
