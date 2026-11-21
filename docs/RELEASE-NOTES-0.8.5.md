# CADWiz 0.8.5 beta

This beta includes the audited non-Scan update. Install from tag `v0.8.5` or the attached ZIP; the protected main branch remains on its separately reviewed release line.

## Included

- Offline, read-only CADWiz Doctor, version-matched support instructions and one-click diagnostic launchers.
- Explicit selection of an existing FreeCAD window via Connect or Show. Initial connections never guess between multiple windows, and outages never redirect edits to another window. The saved selection includes process identity to reject a reused PID. No additional FreeCAD GUI is launched.
- Doctor reports loadable backup add-ons and unreadable directories while preserving files and omitting private paths and credentials.
- New projects default to Documents/CADWiz; existing projects and explicit folder settings remain in place. Setup includes CAD-folder permission controls.
- Print-file checks detect slicer projects renamed as G-code, incomplete files and temperature problems. Warnings cannot receive a ready checkmark.
- Advanced installers query the selected FreeCAD for its add-on directory. Mac/Linux backups stay outside Mod. Startup no longer relocates duplicate installations automatically.
- Existing learning, motion-preview and viewport fixes from 0.6.1 remain included. Scan is excluded.

## Audit and limits

The release is checked with Python regression tests, module imports, lint, the network allowlist, PowerShell/Bash syntax checks, offscreen Qt Setup verification and GitHub's Windows/macOS/Linux checks plus a real FreeCAD headless load. This is not real-device GUI acceptance on every older Intel Mac, Linux package or graphics driver. Preserve backups and report machine-specific failures.

Doctor diagnoses; it does not automatically repair. The broader 1.0–2.0 proposals, including portable profiles, shared-project conflict handling, expanded sign-in methods and general configuration rollback, are not claimed complete. AI service access depends on the user's chosen assistant.
