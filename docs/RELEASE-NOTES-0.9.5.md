# CADWiz 0.9.5 beta — connection recovery and native status

- Authenticated instance discovery now reports reachable FreeCAD windows and their GUI-thread document snapshots without exposing bridge secrets.
- A uniquely matching saved active document can be inspected after a restart. Editing is still refused until Connect explicitly selects the replacement window. Unsaved, unknown, different and ambiguous documents never become automatic edit targets. A failed edit is never replayed.
- Session identities distinguish reused PIDs. Corrupt selection files fail closed. Bridge records are written atomically; obsolete bridge shutdown cannot delete a replacement record.
- Mac/Linux Connect and shortcut helpers use platform-native discovery and launch commands. Denied process queries do not justify launching another FreeCAD instance.
- Ordinary-language status questions route to native diagnostic tools. Account authentication, FreeCAD bridge heartbeat and successful CAD operations remain separate facts. Codex CLI login status uses its existing fixed native probe; plan/quota remain unknown where unavailable.
- All 0.9.3/0.9.4 connection, credential-storage, geometry, motion and installation improvements are retained.

No claim is made that the original Intel/macOS Monterey incident has been conclusively diagnosed or retested on its owner's machine. See BRIDGE-RECOVERY-0.9.5.md for evidence and limits.
