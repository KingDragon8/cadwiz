# Changelog

## v0.5.0-beta.2 (not yet released): the first open-source release

CADWiz is now open source under LGPL-2.1-or-later.

This release is the **Claude plug-in**: you talk to Claude in Claude Desktop, and
CADWiz is Claude's hands and eyes in FreeCAD. The earlier closed-beta assistant,
which had a chat and voice panel inside FreeCAD and needed your own API key, is
not part of this release.

- **Tools Claude can use:** inspect, measure, render, build, edit, versions, print
  check, export, open and save; pictures before 3D (choose a design); guided
  design questions; marks on the model shared between you and Claude; mesh import,
  repair and part swap; technical drawings; problems and fixes.
- **The CADWiz panel:** in every FreeCAD workbench, with a connection light and a
  Connect button, the shared picture with marks, the time machine (every version
  is a complete saved copy), and the Creating, Printing and Setup pages.
- **Help desk:** Claude can check the project's known issues and, only with your
  yes, send a bug, idea or question to cadwiz.app, with an error report
  (screenshot, what happened, versions; file paths and your user name removed).
  **Get help** on the panel opens the feedback page filled in.
- **Your buttons:** every main button is in one table; add your own in one line
  (docs/CUSTOMIZING.md).
- **Installer** for Windows (asks before opening FreeCAD's download page); a
  script for macOS and Linux.
- **Safety:** the code Claude writes runs sandboxed in a separate FreeCAD without
  a window; your file is backed up before the first change; nothing of yours is
  ever deleted; every network call is listed with what it sends.
