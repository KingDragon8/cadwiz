# CADWiz -- known limitations (v0.5.0-beta.2)

CADWiz is a beta. This is the honest list of what it does not do yet, or does
only in part. The live list, with what is planned, is at
https://cadwiz.app/feedback/status.

## Where it runs

- **Windows** is the most tested: CADWiz is used daily there with FreeCAD 1.1.3
  and Claude Desktop.
- **macOS and Linux**: the code is written to work, and the automatic checks load
  it in FreeCAD on Linux without a window, but nobody has used it day to day on
  either yet. Reports are very welcome.
- **FreeCAD 1.1.3** is the version it is tested with. Older versions are not
  supported.

## What you need

- **One assistant app, your choice:** Claude Desktop (with a Claude subscription),
  or the ChatGPT desktop app (signed in with a ChatGPT account). Choose
  at the top of the CADWiz panel. CADWiz itself makes no paid calls.
- One package in FreeCAD's own Python: `mcp` version 1.27 (the installer adds it;
  newer 2.x versions do not work yet).
- **Optional:** Blender and PyMeshLab, for some mesh jobs (repairing a downloaded
  model, swapping a piece of a figurine). Without them those tools say so.

## What it does not do yet

- **In the ChatGPT desktop app**, CADWiz's tools are proven in its Codex (agent)
  conversations. Whether its plain chats can use local tools like CADWiz depends
  on the app's version; if a chat says it can't see CADWiz, start a Codex
  conversation in the same app.
- **FEM (stress analysis), CAM (tool paths), architecture, surface modelling and
  full assembly tools** are out of scope until "CADWiz 2.0". Technical drawings
  are in (the Drawing button).
- **Organic shapes** (figurines, sculpted bodies) are handled as meshes, with
  fewer ways to edit them than engineered parts.
- **Pictures of designs** are real examples your assistant finds on the web, or rough
  sketches; CADWiz does not make photo-real pictures.
- **Big models** can take a while to rebuild; FreeCAD's window stays usable and
  Cancel works, but a very large model may take minutes.

## Safety, in one paragraph

The FreeCAD code Claude writes runs in a sandbox: a separate FreeCAD without a
window, no network, no programs, files only in the project folder, with time and
memory limits. Your file is backed up beside itself before the first change, every
change is a complete saved version you can go back to, and CADWiz never deletes
your files. Nothing is sent anywhere unless you ask: the only network calls are
listed in `config/egress_allowlist.toml`.
