# Changelog

## v0.6.1 — Center, Learn and mechanism motion previews

- Center restores a fitted side view, replacing Front, Top, Side and Iso buttons.
- Learn offers Show me, Guide me and Explain this through the selected assistant.
- Animate previews supported toothpaste crank/slider and phone-holder mechanisms without changing saved placements. Toothpaste previews include both drive strings. This is a visual motion preview, not a force or collision simulation.
- Cutaway opens the recognized toothpaste housing while keeping its mechanism whole; other models use visible world-space bounds.
- Model presentation activates the native 3D view in the existing FreeCAD window. Dock sizing reserves usable space for the native viewport. Opening files updates Recent Files while preserving documents already open.
- Windows, Macintosh (macOS) and Linux are clearly listed on the download page. Linux uses a supported local MCP client. Mac real-device installation remains unverified.
- Existing 0.6.0 offline helpers, connector migration, backup/undo and export provenance are retained.

## v0.6.0 — desktop setup and faster communication screen

- Bundled offline Python 3.11 helpers for Windows x64, Mac Apple Silicon/Intel and Linux x64.
- Claude desktop extension with a small Node launcher; existing Python connector retained.
- Explicit OpenAI setup preview, scoped backup/undo, copyable settings and owned-entry repair.
- Offline background startup check and preserved duplicate add-on copies.
- Immediate mark preview and cancellable picking on geometry copies; nearest-hit face lookup optimized.
- Render provenance and explicit already-open file behavior.
- Workshop preferences can be saved through the assistant.
- Mac physical installation remains unverified; no claim of material or manufacturing certification.


## v0.5.0-beta.4: reconnect the selected assistant

- Connect asks the running CADWiz connector to re-establish its authenticated local FreeCAD connection.
- The button waits for the selected assistant's heartbeat; Claude's connection cannot satisfy ChatGPT's status.
- Reconnect progress remains visible instead of being overwritten by the red status label.
- The installer explicitly identifies the ChatGPT connector, including upgrades with existing settings. Existing settings are backed up.
- Reconnection uses a token-protected loopback endpoint. It never closes the assistant or invents a successful heartbeat.
- Existing open applications need one restart after installing this update.

## v0.5.0-beta.3: fixes from the first tester install

- **Readable under FreeCAD's dark theme.** With "FreeCAD Dark" chosen, the panel
  drew white text on its white buttons; it now keeps its own colours.
- **The connection light turns green with Claude Desktop from claude.ai/download.**
  That Claude Desktop is a Microsoft Store app and reads its settings from its own
  folder; the installer now writes CADWiz's entry there.
- **A CADWiz shortcut:** the Start menu (and, if you say yes, the desktop) gets
  CADWiz, which opens FreeCAD and your assistant app together, and Uninstall CADWiz.
- An earlier CADWiz is moved out of FreeCAD's Mod folder, so only one starts.
- FreeCAD installed "just for me" is found too.
- Report a problem sends in one press, with the picture and the errors.
- On macOS and Linux, CADWiz finds FreeCAD's windowless helper (reading a model failed there).

## v0.5.0-beta.2: the first open-source release, an early beta

CADWiz is now open source under LGPL-2.1-or-later, and this is an **early
release**. Please use it on real projects and tell us what happens: in CADWiz
(Setup > Help > Report a problem / Get help) or at cadwiz.app/feedback.

CADWiz is now a panel in FreeCAD that works with the assistant app **you**
choose: Claude Desktop, or the ChatGPT desktop app. Pick one at the
top of the panel. The closed beta's built-in chat and voice panel, and the need
for your own API key, are gone.

- **The CADWiz panel:** in every FreeCAD workbench, with a connection light and a
  Connect button, the picture of your model with marks, the time machine (every
  version is a complete saved copy), and the Creating, Printing and Setup pages.
- **What CADWiz can do in FreeCAD:** inspect, measure, render, build, edit,
  versions, print check, export, open and save; pictures to choose from before
  3D; guided design questions; shared marks on the model; mesh import, repair and
  part swap; technical drawings; problems and fixes.
- **Feedback built in:** Report a problem and Get help on the Setup page; your
  assistant can also check the known issues and, only with your yes, send a
  report (screenshot, what happened, versions; file paths and your user name
  removed).
- **Your buttons:** every main button is in one table; add your own in one line
  (docs/CUSTOMIZING.md).
- **Installer** for Windows that connects Claude Desktop and, if present, the ChatGPT app,
  and asks before opening FreeCAD's download page; a script for macOS and Linux.
- **Safety:** code written by the assistant runs sandboxed in a separate FreeCAD
  without a window; your file is backed up before the first change; nothing of
  yours is ever deleted; every network call is listed with what it sends.
