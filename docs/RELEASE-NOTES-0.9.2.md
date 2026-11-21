# CADWiz 0.9.2 — installation recovery candidate

Status: review candidate. Production publication is gated on acceptance evidence.
Actual Neil-device testing is **NOT VERIFIED**. Do not treat simulated tests as
a real Mac installation or promise that this resolves his full incident.

## Findings and root-cause limits

Neil's supplied evidence reports a Git clone timeout, GitFailed, a retained
backup and nested release directories. A failed clone/repair is confirmed by
those reports; the exact exception that prevented workbench discovery on his
machine has not been reproduced from a complete log or a filesystem snapshot.
Folder layout alone is not an established complete root cause.

Source inspection confirmed these independent defects:

- The default `main` branch remains at 0.6.1 while the shipped beta is on
  `release/0.9.1`. Package metadata in that default branch therefore disagrees
  with the release downloaded from the website. This candidate declares its
  intended `release/0.9.2` branch; that branch must exist before publication.
  Main is not silently overwritten as part of this review.
- Startup discovery guessed `Mod/CADWiz` and one repository depth. It did not
  reliably select the startup file actually executed or Neil's deeper layout.
- Workbench registration ran setup initialization before scheduling the panel.
  An exception there could leave the workbench registered but no startup panel.
  This is distinct from an absent workbench in the dropdown.
- The old Unix installer copied files before pip/assistant configuration. A
  failure in a later stage could leave an ambiguous partial-success result.
- PR #7 correctly separated installation from AI setup and staged files, but
  guessed the active directory, handled only one case variant, kept backups in
  `Mod`, and did not roll back post-activation validation failures. It explicitly
  lacked real Mac validation. Its staging/separation approach was retained;
  those gaps are addressed here rather than blindly merging the draft.

No FreeCAD Addon Manager code or Git timeout setting was changed. The direct
ZIP installer bypasses Git. CADWiz cannot prevent an external Addon Manager
from initiating its own repair; preserved backups are moved outside its Mod
scan, and valid one-level repository layouts are distinguished from nesting.

## Changes

- Workbench-only macOS/Linux installer discovers FreeCAD's bundled runtime and
  asks it for its actual application-data directory. Multiple Mac installations
  require a selection; custom bundles use `FREECAD_APP`, or `FREECAD_PY`.
- A staged copy is parsed and hash-verified before replacement. Existing case
  variants, incomplete clones and CADWiz backups are preserved outside `Mod`.
  Transactions have an exclusive lock, verified backups and a rollback manifest.
  Models in old add-on folders remain in the backup, never silently deleted.
- Optional setup/assistant initialization failures no longer interrupt panel
  scheduling after registration. Registration is cached only after FreeCAD
  accepts the workbench.
- Setup has Check Installation and Repair CADWiz controls. Diagnostics separate
  local files, actual runtime observations, optional dependencies and connection
  status. Repair explains the closed-FreeCAD installer route; it never replaces
  a live workbench or launches a second owner GUI.
- Creating's empty screen has a bold centered heading and guidance for the
  controls above and marking tools below. The top Get help button is removed;
  Setup support remains available.

## Neil: install and verify

After this candidate passes review and real Mac acceptance:

1. Save your work and quit FreeCAD completely. Download the complete installable
   release ZIP, not an extra source ZIP nested inside an existing add-on.
2. Extract it in Downloads. Run `Install-CADWiz.command`. If macOS does not permit
   launching it, run `bash scripts/install_macos.sh` from the extracted folder
   in Terminal; do not disable security protections. The installer prints any
   runtime selection problem and makes no guessed installation.
3. Start FreeCAD 1.1. Select CADWiz in the workbench dropdown and verify its
   communication panel. Close and restart FreeCAD twice and check it persists.
4. Use AI Wiz Setup only after the interface works. A connection failure should
   leave the workbench available. Check Installation shows separate evidence.

For a custom app: `FREECAD_APP='/path/to/FreeCAD.app' bash scripts/install_macos.sh`.
For a custom bundled Python: `FREECAD_PY='/path/to/its/python' bash scripts/install.sh`.
Do not manually move folders or edit Python code.

## Rollback

Save work and close FreeCAD. Use the same extracted release and selected runtime:

    bash scripts/install_macos.sh --rollback '/printed/path/to/rollback.json'

Rollback validates the manifest, backup hashes and current installation before
moving anything. It refuses to overwrite changed installed files. It preserves
the replaced candidate outside Mod too. A first-install rollback removes the
active copy from Mod by moving it into that transaction, without deleting it.
Then reopen FreeCAD and verify the restored version. Assistant settings and
models outside the add-on are untouched by these operations.

## Acceptance gates

Automated filesystem simulations cover staging failure, post-activation failure,
preservation/rollback, interrupted clones, nested layouts, both installation
name casings, valid Addon Manager layout, repeated discovery, optional setup
failure, concurrent-install refusal and changed-file rollback refusal.

The Mac CI job downloads a checksum-verified official FreeCAD and attempts real
workbench/panel startup and restarts in disposable CI profiles. Its actual
results must be reviewed; adding a workflow is not a passing test. It does not
prove Neil's physical Mac, customer assistant enrollment, disconnected-network
behavior or both APFS case modes. Unavailable acceptance remains NOT VERIFIED.

Windows installer lifecycle, Linux native load checks, cross-platform connector
handshake and the new recovery suite remain required regression gates. The
website and public 0.9.1 assets remain unchanged until release acceptance passes.
