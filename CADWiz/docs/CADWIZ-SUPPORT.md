# CADWiz support — 0.9.8

## Get help from the home panel

Say **“CADWiz, help me.”** in your connected assistant, then explain your goal or problem.
For a suggestion, say **“CADWiz, I've got an idea.”**, leave your message and add
**“Send this to the CADWiz team.”** These are natural-language prompts, not a new
wake-word listener. Your assistant prepares feedback for confirmation.

Press the visible **Help** button on the CADWiz home panel. Choose your
connected assistant, or email **support@cadwiz.app**. Automatic software support
covers downloads, installation, connection problems, errors and feature questions.
Describe what happened, your CADWiz and FreeCAD versions, and your operating system.
Reply in the same email thread to continue the conversation. Replies may be automated;
software fixes still require validation and owner approval before release.

The support service does not build CAD models for you. Support never uploads an
editable FreeCAD file, even if an old client option requests it. Report a problem
prepares a private preview with scrubbed text and, when safe, a native viewport
image. Desktop pixels, titles, private panels and chats are excluded by construction.
Text/image annotations, linked objects, custom renderers or mismatched documents
use text alone; old unmasked screenshots are not sent. No manual cropping is required.
The image can show your part geometry; review the preview before Send.
Email attachments are not automatically analysed; the screenshot report uses the
existing private feedback attachment route.
For the current service status and contact options, visit https://cadwiz.app/support.

## Connection recovery and ordinary-language status

After upgrading, restart FreeCAD and the connected assistant/CLI so both load the updated bridge and diagnostic tools. Save work first; do not close unsaved projects merely to diagnose a connection.

Ask "Am I connected?", "What is my AI status?" or "Is my account working?" The assistant should call CADWiz's native diagnostic_status tool, not guess from the green light or require slash syntax. connection_status lists authenticated FreeCAD instances. Codex CLI account questions reuse its native login-status probe; account plans and remaining quota are unknown when unavailable.

If the selected bridge stops answering, read-only inspection may recover only when exactly one replacement has the same known saved active document. Press Connect in the intended existing window before editing the replacement. Unknown, unsaved or ambiguous documents require explicit selection. A denied socket/process probe is not proof that FreeCAD is closed or the PID is stale. Check startup output and environment permissions without weakening system protections. Never substitute a standalone macro/new GUI for an unreachable intended edit target.

Start with read-only checks. Preserve open documents, unsaved work, preferences,
old installs and backups. Never launch an extra FreeCAD GUI for diagnosis or a
preview. Use the existing CADWiz connection for model operations.

## Installation diagnosis without a working workbench

Run the standalone Doctor with the selected FreeCAD's Python:

    python CADWiz/src/integrations/cadwiz_plugin/doctor.py

Doctor reads installation structure and dependency availability without loading
the workbench, executing its startup files, contacting a service or repairing
anything. It prints a shareable report without personal paths, file contents,
tokens, CAD geometry or prompts. Review reports before sharing.

In the existing FreeCAD Python console, obtain the active location:

    FreeCAD.getUserAppDataDir()

Then run Doctor with `--user-data` and that location. This confirms the checked
directory; it does not confirm GUI initialization. A directory named backups is
not proof of where FreeCAD loads CADWiz. Multiple FreeCAD versions may use
different user-data directories. Version-specific Mod paths take precedence
over instructions copied from another machine.

## Separate checks

1. Files present: Doctor can inspect startup syntax and panel-source presence.
2. Startup working: in the intended existing FreeCAD window, confirm the CADWiz
   panel is visible and usable. Save work before any user-requested restart.
3. Connection working: confirm the chosen assistant's connection light and ask
   it to inspect the active document. CLI availability alone proves neither MCP
   configuration nor access to the running instance.
4. Basic operation: inspect a document, create a user-approved disposable part,
   save it, reopen it in the same window and verify the result.

Do not report installation success from a file-copy message. An import or icon
problem and a workbench-registration failure can have different causes.

## Platform limits

Windows has the strongest local testing. macOS and Linux have bundled helpers
for the listed architectures, but this release has not been verified on every
real device. Older Intel Macs, Linux distributions, AppImage/Flatpak packages,
Python versions and graphics drivers need their own end-to-end test. An
untested combination is unverified, not automatically incompatible. No hardware
age diagnosis can be inferred from a missing workbench alone.

The offline connector helper targets Python 3.11 on Windows x64, macOS Intel /
Apple Silicon and Linux x64. Other Python builds use the advanced installer.
Local diagnosis and saved projects need no paid AI account or internet access;
conversational model generation depends on the user's chosen assistant.

## Files, recovery and updates

New project stores default to the configured Documents directory under CADWiz.
Existing `CADWiz Projects` folders and explicit project-root settings are kept.
The Setup page supports a chosen project location. Do not silently fall back to
another folder when a shared drive is unavailable or move historical projects.
Model versions preserve previous revisions. Installation backups and model
versions are separate; rolling back an application must not roll back documents.

Before a repair, explain the affected paths and expected result, back up the
existing installation outside Mod, obtain the user's approval, then verify the
same startup and connection checks. Never delete a competing installation to
make a diagnostic warning disappear. Do not put executable backup add-ons in
Mod: FreeCAD may load those too.

## Get help

The Setup page offers Doctor, a preview before sending a report, and Get help.
The support page is https://cadwiz.app/feedback.html. Existing discussion and
issue status should be checked before filing a duplicate. Never send a report,
screenshot or private project without the user's explicit request.

For an assistant: read this version-matched file and the shipped known limits.
Use evidence, distinguish confirmed/probable/undetermined, and say when you lack
machine or repository access. Scan is excluded from this release; do not describe
unreleased scanning as available.

## Beta 0.8.6 model recovery

Setup: Check model health tests a disposable snapshot; Reset CADWiz Layout restores right docking; Clean model view hides construction and Show construction reveals it. E1 is a fixed solid: ask for a separate native reconstruction, keeping the original. Accepted new mechanical models require verified native editability. An explicit direct-solid exception must explain the limitation. See docs/RELEASE-NOTES-0.8.6.md and docs/AUDIT-0.8.6.md in the package root.
