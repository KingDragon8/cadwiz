# CADWiz Beta 0.8.9 — Windows installer repair

Retains the Free AIWiz interface and features from 0.8.8. Repairs Windows
PowerShell 5.1's loss of embedded Python quotes during user Mod discovery.
Discovery now runs a Python file using FreeCAD.getUserAppDataDir(), returning
structured results instead of passing Python source through native arguments.

## Install on Windows

1. Install supported FreeCAD 1.1 or newer from FreeCAD's official website.
2. Save your work and close FreeCAD.
3. Download the CADWiz ZIP, right-click it and choose **Extract All**.
4. Open the extracted folder and double-click **install_windows.bat**.
5. Confirm the displayed destination. No administrator account, separate Python,
   pip command or script editing is needed.
6. Open FreeCAD. Use CADWiz **Setup** to connect your assistant.

The installer verifies FreeCAD, its user add-on directory, package copies and
the bundled offline connector before replacing a recognized installation.
Previous installations are backed up beside Mod, outside FreeCAD's load path.
Account settings are not rewritten by the installer. Assistant applications
and any required Node/runtime dependencies are checked by CADWiz Setup.

## Recovery and safety

If discovery fails, open FreeCAD once, close it and retry. Interactive setup
can select FreeCAD.exe; advanced `-FreeCADBin` and `-ModDir` options require no
script changes. A manual Mod fallback must belong to a recognizable FreeCAD
profile; a conflicting automatic API result is refused.

Unknown folders, modified manager files, and duplicate legacy installations
(including AI-FreeCAD) are preserved and require support rather than silent
replacement. Installation rollback restores the previous verified add-on on
failure. Uninstall moves the installed add-on to a recovery backup and removes
only its unchanged, ownership-marked shortcuts. Models, preferences and assistant
settings are kept. Legacy records which cannot prove ownership are refused;
use FreeCAD Addon Manager for those installations.

## Validation scope

Local native validation uses available FreeCAD 1.1.3 / Python 3.11 on Windows.
FreeCAD 1.1.4 API responses and its Program Files path are covered by mocks;
these are not a native Windows 1.1.4 test. CI also exercises the native Linux
1.1.4 build. Bundled native helper wheels must match FreeCAD's Python/platform;
unsupported combinations stop with diagnostics instead of installing globally.

Windows PowerShell 5.1 and PowerShell 7 native argument boundaries are tested.
`-CheckOnly` performs read-only discovery. Legacy `-SourceOnly` no longer writes
assistant settings; use Setup. Legacy ClaudeConfig/CodexConfig/NoPip arguments
remain accepted for command compatibility but do not trigger account/pip changes.
Batch launchers preserve setup's exit code, and process checks do not depend on
Windows WMI/tasklist being healthy. Restart FreeCAD after installation.
