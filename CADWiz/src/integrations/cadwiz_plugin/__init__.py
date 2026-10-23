# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""CADWiz as a plug-in for Claude Desktop (ORDER-2026-10-12-05).

The founder talks to Claude in the Claude Desktop app; CADWiz is Claude's hands
and eyes in FreeCAD. Three pieces:

  session.py  the tools themselves, run inside the founder's FreeCAD (inspect,
              measure, render, build, edit, versions, print check, export, open,
              save, design record) on top of CADWiz's sandboxed worker, versions
              and backups beside his file, and measurement.
  bridge.py   a small local server inside FreeCAD (127.0.0.1 only, a secret
              token) that runs session calls on FreeCAD's window thread.
  server.py   the MCP server Claude Desktop starts: it forwards Claude's tool
              calls to the bridge and returns plain text and images.

The hard safety envelope is enforced here and in the worker, not in Claude's
instructions: model code runs sandboxed (no network, no shell, no subprocesses,
files only inside the project folder); the founder's file is backed up beside
itself before the first change; nothing of his is ever deleted; every tool call
is logged.
"""

#: The release this code belongs to (shown in error reports and the Get help form).
CADWIZ_VERSION = "0.5.0-beta.3"
