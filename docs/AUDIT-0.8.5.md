# CADWiz 0.8.5 beta audit

Scope: changes proposed as 0.6.2 against public 0.6.1; Scan excluded. This is a code and runtime audit, not an independent third-party review.

Findings corrected before release:

1. Initial bridge selection used the newest responding process when several FreeCAD windows existed. Connect and Show now explicitly persist the chosen process identity; an ambiguous initial connection refuses to guess. A saved identity mismatch also refuses to route edits. The reconnect error explains the next action without requesting another GUI.
2. Doctor skipped backup-named add-ons even though FreeCAD can still execute InitGui.py from them. It now reports loadable backup code separately and preserves it.
3. Directory enumeration permission errors could abort Doctor. It now records an incomplete check without exposing the path or exception text.
4. Print-file material and expected-temperature warnings did not clear the printable flag, allowing a green check beside warnings. Any problem now blocks the ready checkmark.
5. The Mac Doctor.command launcher lacked an executable mode in Git. The beta archive records it as executable.

Regression coverage includes no guessed multi-window routing, explicit selection, reused-PID refusal, omission of connection secrets from selection records, backup preservation and detection, unreadable-directory privacy, unsafe print-temperature rejection, renamed-project rejection and existing project-location preservation.

Release controls: build artifacts from committed files; validate ZIP members and checksums; run the Windows/macOS/Linux CI suite and FreeCAD headless load; keep the beta tag separate from protected main; point installation instructions to the exact beta tag. Seagate retains source history and working files. No running FreeCAD GUI is opened, closed or replaced.

Limits: older Intel Mac and Linux GUI/device combinations are not physically verified here. The broader 1.0–2.0 roadmap is not claimed complete. Public beta publication does not merge the protected main branch or waive its review rule.
