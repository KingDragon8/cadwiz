<p align="center"><img src="CADWiz/Resources/icons/cadwiz-256.png" width="128" alt="CADWiz logo"></p>

# CADWiz

**A smart CAD buddy for 3D-printer owners.** CADWiz is a FreeCAD addon that lets
Claude Desktop see, measure, build and edit your FreeCAD models. You talk to
Claude in plain words ("make the lip 18 mm tall", "what's the wall thickness
here?"), and CADWiz is Claude's hands and eyes inside FreeCAD. It shows you
pictures before anything is built, keeps every change as a version you can go
back to, and checks the part against your printer.

> **Status: v0.5.0-beta.2, beta.**
> **Works:** inspecting and measuring models; building and editing parts as
> editable FreeCAD models; pictures to choose from before 3D; marks on the model
> shared with Claude; versions and backups; print checks; STL/3MF/STEP export;
> technical drawings; bringing in and repairing meshes.
> **Not yet:** ChatGPT (its app can't reach programs on your computer yet); FEM,
> CAM, architecture, surfaces and assemblies (planned for "CADWiz 2.0"); daily use
> on macOS and Linux (they should work, but are less tested).
> See [known limitations](CADWiz/docs/KNOWN-LIMITATIONS.md).

## What you need

- **FreeCAD 1.1.3** (1.1 or newer): [freecad.org/downloads](https://www.freecad.org/downloads.php)
- **Claude Desktop** with a **Claude subscription**: [claude.ai/download](https://claude.ai/download).
  CADWiz itself makes no paid AI calls; Claude does the thinking.
- **Windows 10 or 11** is the most tested. **macOS and Linux:** help wanted. They
  should work, but nobody uses them day to day yet.

## Install

**Windows (recommended):**
1. Download the latest `cadwiz-<version>.zip` from
   [cadwiz.app/download](https://cadwiz.app/download) and unzip it.
2. Close FreeCAD and Claude Desktop.
3. Double-click **`install_windows.bat`**. If FreeCAD 1.1 isn't installed, it asks
   whether to open FreeCAD's download page. It never downloads anything by itself.
   It then copies CADWiz into FreeCAD, adds the one package the Claude connection
   needs, and adds CADWiz to Claude Desktop's settings, after saving a copy of
   them. It lists everything it changed.

**macOS / Linux (less tested):** unzip, then run `bash scripts/install.sh`.

**FreeCAD Addon Manager:** once CADWiz is listed, open **Tools > Addon manager**,
search for **CADWiz**, press **Install**, and restart FreeCAD. Then run the
installer once (or the two steps below by hand) to connect Claude Desktop.

**By hand:** copy the `CADWiz` folder into FreeCAD's `Mod` folder, run
`"C:\Program Files\FreeCAD 1.1\bin\python.exe" -m pip install --user "mcp==1.27.0"`,
and add this to Claude Desktop's settings file
(`%APPDATA%\Claude\claude_desktop_config.json`) under `"mcpServers"`:

```json
"cadwiz": {
  "command": "C:\\Program Files\\FreeCAD 1.1\\bin\\python.exe",
  "args": ["C:\\Users\\<you>\\AppData\\Roaming\\FreeCAD\\v1-1\\Mod\\CADWiz\\src\\integrations\\cadwiz_plugin\\server.py"]
}
```

## First use

1. **Open FreeCAD.** The **CADWiz panel** appears on the right side of the window
   and stays there in every workbench.
2. **Open Claude Desktop.** Within a minute the light at the top of the CADWiz
   panel turns **green: "Connected to Claude"**. If it stays red, press
   **Connect** on the panel; it opens Claude Desktop for you and says what to
   check.
3. In Claude Desktop, check that CADWiz is switched on: **Settings > Connectors**
   (or the tools button under the message box) shows **CADWiz**.
4. **Talk to Claude.** Try: *"What's open in FreeCAD?"*, *"Make me a phone stand
   for my desk"*, or open a model and say *"Make this 10 mm taller"*.
5. To point at something, draw on the model on the CADWiz panel (point, circle,
   arrow...) and press **Show Claude**. Then say *"this"* in your message.

The panel's **Setup** page holds your printer, your material and how much you
want Claude to explain or ask first. Claude reads those settings.

## Known gaps

See [CADWiz/docs/KNOWN-LIMITATIONS.md](CADWiz/docs/KNOWN-LIMITATIONS.md) and the
live list of what's planned at
[cadwiz.app/feedback/status](https://cadwiz.app/feedback/status).

## Help, bugs and ideas

- **Just ask Claude.** It can check the known issues for you and, if you say yes,
  send a bug report, with a screenshot and what happened, so you don't have to
  write it up.
- **[cadwiz.app/feedback](https://cadwiz.app/feedback)**: report a bug, suggest an
  idea or ask a question. No GitHub account needed.
- **Discord:** *link to be added.*
- **GitHub Issues**, if you use GitHub: there are templates for bugs and ideas.
- **Security problems:** please report privately; see [SECURITY.md](SECURITY.md).

## Changing it

You have the code: [docs/CUSTOMIZING.md](docs/CUSTOMIZING.md) shows how to rename
a button or add your own in one line.
[CONTRIBUTING.md](CONTRIBUTING.md) says how to send changes back.

## Licence and name

The code is free software under the **GNU LGPL, version 2.1 or later**
([LICENSE](LICENSE)), the same licence family as FreeCAD. The **CADWiz name and
logo are not** covered by that licence: forks must use a different name and
logo ([TRADEMARK.md](TRADEMARK.md)). Third-party parts and their licences are in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Credits

Built on [FreeCAD](https://www.freecad.org), the free and open-source parametric
3D modeller, and its community. The design conversation is with Anthropic's
[Claude](https://claude.ai). CADWiz includes the MIT-licensed
freecad-robust-mcp tools and the LGPL freecad-ai code; see the notices.
