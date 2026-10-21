# Contributing to CADWiz

Thanks for wanting to help. Most people help most by **telling us what broke or
what they wish CADWiz did**: [cadwiz.app/feedback](https://cadwiz.app/feedback)
is the main door (no GitHub account needed), and you can also just ask Claude to
"send this to Steve" while you work. GitHub Issues is the second door, for people
who already use GitHub.

## Running it from source

1. Install **FreeCAD 1.1.3** and **Claude Desktop**.
2. Clone this repository and copy (or link) the `CADWiz` folder into FreeCAD's
   `Mod` folder (`%APPDATA%\FreeCAD\v1-1\Mod` on Windows).
3. Install the one extra package into FreeCAD's own Python:
   `"C:\Program Files\FreeCAD 1.1\bin\python.exe" -m pip install --user "mcp==1.27.0"`
4. Run `scripts/install_windows.ps1 -SourceOnly` (or `scripts/install.sh` on Mac or
   Linux) to add CADWiz to Claude Desktop's settings, then restart both apps.

## Tests

```
python -m pip install pytest "mcp==1.27.0"
python -m pytest
```

The tests use stand-ins for FreeCAD, the network and the AI: **no test needs a
paid AI account, and none may call one.** Please keep it that way.

## Making a change

1. Fork the repository and make a branch.
2. Keep the change small and about one thing. Add or update a test.
3. **Sign off every commit**: `git commit -s`. This adds
   `Signed-off-by: Your Name <you@example.com>`, your statement under the
   [Developer Certificate of Origin](https://developercertificate.org/) that you
   have the right to contribute the change under this project's licence. Pull
   requests with unsigned commits can't be merged. There is no other agreement to
   sign.
4. Open a pull request saying what it changes and why.

## What gets accepted

- **In scope:** CADWiz as FreeCAD's "hands and eyes" for Claude Desktop: seeing,
  measuring, building and editing models; pictures and marks on the CADWiz panel;
  versions and backups; print checks; making things for 3D printing.
- **Out of scope for now:** FEM, CAM, architecture (BIM), surface modelling and
  full assembly tools (planned for "CADWiz 2.0"), and anything that sends a user's
  model or files anywhere without them asking.
- **Never accepted:** loosening the sandbox around the FreeCAD code Claude writes,
  anything that deletes a user's files, or hidden network calls. Every network
  call must be listed in `config/egress_allowlist.toml` with what it sends.

See [GOVERNANCE.md](GOVERNANCE.md) for how decisions are made, and
[docs/CUSTOMIZING.md](docs/CUSTOMIZING.md) if you only want to change a button for
yourself.

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).
