# CADWiz -- notes for an AI coding assistant working in this repository

Read this before changing code.

## What this is

A FreeCAD 1.1 addon (`CADWiz/`) plus an MCP server that Claude Desktop starts
(`CADWiz/src/integrations/cadwiz_plugin/server.py`). The server forwards Claude's
tool calls to a small local bridge inside FreeCAD (127.0.0.1 only, secret token),
which runs them on FreeCAD's window thread (`session.py`).

## Rules that must not be broken

- **The sandbox.** FreeCAD code written by a model runs in a separate FreeCAD
  without a window, on a copy, with no network, no programs and files only in the
  project folder (`mcp_tools/cadwiz_sandbox.py`, `exec_worker.py`). Never loosen it.
- **Never delete the user's files.** Every change is a version; the user's file is
  backed up beside itself before the first change; restoring adds a new version.
- **The window must keep answering.** Nothing slow on FreeCAD's window thread
  (about 2 seconds at most). Slow work runs in another process or thread, and
  Cancel must work.
- **No hidden network calls.** Every outbound call in `CADWiz/src` must be in
  `config/egress_allowlist.toml` with what it sends
  (`scripts/ci/check_egress_allowlist.py`). The help desk sends nothing without the
  user's yes; this is enforced in code (`feedback.py`: no confirm, no request).
- **No test may call a paid AI service.** Use stand-ins.
- **Layering:** `CADWiz/src/ai_freecad_core` has no FreeCAD, vendor or network
  imports; FreeCAD-aware code lives in `CADWiz/src/integrations`. Vendored code in
  `CADWiz/vendor` is never edited in place.

## Definition of done for a change

1. `python -m pytest` passes (in a clean environment: `pip install pytest
   "mcp==1.27.0" pillow`).
2. `python scripts/ci/import_every_module.py` and
   `python scripts/ci/check_egress_allowlist.py` pass.
3. If the change touches FreeCAD behaviour: `freecadcmd
   scripts/ci/freecad_load_check.py` passes, and the change was tried in FreeCAD
   itself.
4. Commits are signed off (`git commit -s`, DCO).

## Name and logo

The code is LGPL-2.1-or-later; the CADWiz name, the logo (hat and gear, no eyes)
and the Wiz character (with eyes) are not (TRADEMARK.md). Never put eyes on the
logo.
