# Bridge recovery investigation — 0.9.5

## Confirmed findings

The reported Intel Mac had a configured Codex MCP connector and prior successful document inspections. Its later inspection failed before document access. The supplied report says process/socket probes were denied by the investigation sandbox. Thus a stale PID, a closed application, a startup failure and sandbox reachability cannot be distinguished for that particular incident. PID989 being old is not proof of the root cause.

Source audit and restart reproduction confirm a software recovery gap: the selected PID/start identity is retained, and an unavailable selection immediately terminates discovery. That is an intentional edit-safety rule but also prevents useful read-only recovery and masks live alternatives behind one generic message. Separate confirmed platform defects called PowerShell, Explorer and tasklist from Mac/Linux helper paths. The Windows-shaped Mac data directory was internally consistent; this release deliberately does not migrate it.

## Correction and safety

Discovery validates authenticated PID, session nonce and start identity. FreeCAD document metadata is captured on its main thread; the HTTP thread never reads FreeCAD objects. The status tool publishes identities/documents, not tokens. A replacement is eligible only for a small read-only tool allowlist and only when exactly one authenticated active saved-file match exists. Connect remains mandatory before editing that replacement. Legacy selections without document identity need explicit reselection. Explicit PID overrides remain strict. No operation starts/closes a GUI or retries a failed edit.

Corrupt selectors cannot become implicit consent. Session nonces protect PID reuse and shutdown cleanup. Registry files are written atomically. POSIX records are restricted to the owner. Older authenticated bridge handshakes remain usable, but cannot supply the new document recovery metadata until FreeCAD is restarted with the updated add-on.

Native diagnostic_status routes connection/login/account questions without slash syntax. It reuses the existing Codex CLI login probe and never infers account access from a heartbeat. External assistants must invoke the supplied MCP tools; CADWiz cannot rewrite Codex CLI's own application command parser. Unsupported account/plan/quota information is explicitly unknown.

## Local validation checkpoint, November23,2026

- Full release-tree suite:375 collected,370 passed,5 conditional skips,0 failures/errors. The skips are not passes.
- Real Windows FreeCAD1.1.3 engine processes: authenticated inspection; shutdown/restart; same-document read-only recovery; edit refused before selection; explicit reselection; production PluginSession parameter mutation; save/reopen; second driving-dimension edit. Final width47mm, valid native Body, fully constrained sketches, retained Pad/Pocket history.
- New cases cover Windows/macOS/Linux selection semantics, multiple live bridges, ambiguous/different/unsaved documents, stale legacy selection, PID/session mismatch, malformed registry/selection, socket denial, no mutation replay, native helper command selection and natural-language status intent. Platform-parameterized local tests are simulations, not native Mac/Linux execution.
- Lint/import/egress checks passed locally. Existing parametric acceptance and rollback safeguards are unchanged.

Cross-platform hosted checks and native installation/restart checks are required on the PR. Their executed results and installer/release checksums are recorded in the release evidence assets. This document is the pre-publication local checkpoint, not a claim that pending hosted jobs passed. Intel macOS12.7.6/Monterey on the reporter's hardware remains unverified even if newer hosted Intel Mac tests pass.

## Website/shortcut findings

The owner's Website shortcut explicitly launched an old local preview at127.0.0.1:4173 instead of cadwiz.app; that preview served0.6.1. Its source and built page were backed up and repaired, and the shortcut now opens the public HTTPS site. A separate public-site defect mixed a0.9.4 installation page with a0.9.3 home-page release manifest. The website build now rejects mixed release versions/asset metadata. GitHub's generic latest release endpoint still resolves stable0.6.1 because newer releases are betas; explicit beta asset URLs are used instead of changing that stable/beta distinction.

## Remaining risks

Read-only recovery depends on a saved document path and current main-thread snapshot. Multiple matching copies require selection. Document identity is not a cross-machine project-content fingerprint. Process and socket sandbox denials still require environment-specific diagnosis. Physical camera identification and ScanWiz development are separate from this connection-maintenance release. No current owner document or unsaved scan was closed for these tests.
