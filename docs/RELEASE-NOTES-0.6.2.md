# CADWiz 0.6.2 — installation support and window continuity

- Offline, read-only CADWiz Doctor runs without the workbench or a paid AI account. Setup includes a Doctor button and copyable, version-matched assistant support instructions. Reports omit personal paths, file contents, tokens and geometry.
- A temporary loss of the selected FreeCAD connection no longer redirects edits to a different process. CADWIZ_FREECAD_PID can select an existing instance explicitly. No new GUI is launched by the connector.
- New project stores use configured Documents/CADWiz. Existing project stores and explicit folder settings remain in place.
- Advanced installers query the selected FreeCAD for its add-on directory. Mac/Linux backups are kept outside Mod; startup diagnosis no longer relocates duplicate installations automatically.
- Existing learning, motion-preview and native-viewport fixes from 0.6.1 remain included. Scan is excluded.

Validation: local Python regression suite, module imports, egress allowlist, lint, and offscreen Setup controls with FreeCAD 1.1.3 bundled Qt. macOS, Linux GUI, older Intel Mac and sandbox-package end-to-end acceptance remain unverified on real devices. CI provides additional platform checks; it is not proof of every hardware combination.

This maintenance release does not claim the full proposed 1.0–2.0 roadmap is complete. Portable profiles, shared-project conflict handling, broader configuration rollback, expanded authentication options and repair-learning automation require further implementation and acceptance. Existing threaded feedback, moderation and connection backup/undo remain available. Doctor diagnoses and suggests next steps; it never performs repairs automatically.
