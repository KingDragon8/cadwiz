# CADWiz Beta 0.9.0 — simpler Windows setup

Windows users can download **CADWiz-Setup-0.9.0.exe** and run the setup wizard.
There is no ZIP to extract, repository address to copy, branch to choose or
PowerShell window to use in the normal Windows installation path.

1. Save your work and close FreeCAD.
2. Open **CADWiz Setup**. Confirm the detected FreeCAD application, or browse to it.
3. Click **Install CADWiz**. Setup checks the native FreeCAD API and offline helper,
   verifies the user add-on destination and keeps recovery copies when upgrading.
4. Open FreeCAD. In CADWiz **Setup**, connect your assistant and confirm it can
   inspect the model. Installation alone does not establish an AI connection.

Installation runs for the current Windows user, without administrator elevation.
It reuses the 0.8.9 transaction core, adds Windows Apps registration and a graphical
uninstall confirmation, and keeps models, preferences and assistant settings.
An existing Addon Manager installation is recognized and backed up outside Mod.
Unknown or duplicate legacy installations stop for help rather than being deleted.
The normal shortcut reuses an existing FreeCAD process instead of starting another.

## Verification and release gates

The required **Windows Setup.exe lifecycle (FreeCAD 1.1.4)** CI job downloads the
official portable FreeCAD build and pinned Inno Setup compiler, verifies their
SHA-256 digests, builds the committed source and runs the actual Setup.exe.
It checks fresh installation, upgrade with an owner-file preservation fixture,
uninstall, reinstall, invalid prerequisites and foreign-folder refusal in a profile
containing spaces and an apostrophe. A test-only registry namespace preserves
the runner's real Apps registration. Native Windows shell regressions may not skip.
Native parametric construction/edit/persistence checks run with FreeCAD's Python.
Independent Windows/macOS/Linux source checks and native Linux checks remain.

These automated checks do not prove another person's assistant-account enrollment,
their display/driver setup, physical print fit or every possible Windows machine.
Local GUI startup and communication evidence belongs to the release delivery audit.

## Limits

This beta installer is **not publisher-code-signed**. Windows may identify its
publisher as unknown. Do not mistake a checksum for an Authenticode signature.
Obtain it from the official CADWiz download/release page and use the published
checksums for integrity verification. No signing purchase or account enrollment
is performed by setup.

FreeCAD 1.1+ with the bundled Python 3.11 helper platform remains the supported
installation target. FreeCAD must remain available for the graphical uninstaller;
if its Python was removed first, reinstall FreeCAD or use Addon Manager for recovery.
macOS/Linux continue to use their existing supported installation routes; this
release does not add a Mac/Linux native installer. Existing Free AIWiz features
remain; automatic provider switching is still disabled.

## Building

Use the pinned compiler and verified FreeCAD artifacts in the CI workflow.
`python scripts/release/build_windows_installer.py --compiler <ISCC.exe> --output <folder>`
builds exclusively from a committed Git archive and emits provenance/checksums.
The Inno Setup frontend contains no account credentials or customer models.
The Python transaction/ownership checks remain available for advanced ZIP users.
