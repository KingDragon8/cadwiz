# Beta 0.8.8 release audit

Scope: Free AIWiz provider discovery, account enrollment and local status UI.
The preceding public release is 0.8.6; 0.8.7 is a local before-change snapshot.

## Checks

- Python regression suite: 251 passed, 3 skipped on Windows.
- Ruff, all 180 shipped-module imports and egress allowlist: passed.
- Native FreeCAD 1.1 Qt witness: seven cards, 420px layout, masked key field,
  explicit consent, worker completion, key removal and closed-dialog cancellation.
  That witness substitutes network and vault responses; it is not a live account test.
- Separate Windows Credential Manager ephemeral-key round trip: passed during
  development without reading or changing owner provider credentials.
- Offline deterministic handoff exercise: 1,000/1,000 cases passed. This is a
  software routing check, not measured AI service latency or quality.
- Native public-fixture dimension edits, valid solids and persistence: 20/20
  during development. These are native CAD checks, not provider-generated plans.

Remote CI additionally runs lint/imports/tests on Windows, macOS and Linux,
secret scanning, and headless FreeCAD loading and native session checks. The
release is published only after the required run for its exact source commit
passes. CI is not a substitute for real-device UI or live provider qualification.

## Data and billing boundaries

No CAD geometry, prompt or screenshot is transmitted by an enrollment check.
Requests are user-initiated, fixed-host HTTPS metadata/authentication checks with
redirects disabled and bounded responses. Keys are masked and stored only after
explicit consent in Windows Credential Manager. No plaintext fallback is used.
Automatic inference and fallback are disabled. No live generation benchmark or
zero-billing entitlement is claimed. Request activity is not remaining credit.

The release ZIP is built from committed public source and excludes settings,
credentials, FreeCAD model files and private demo evidence. Before-change
archives, previous downloads and existing owner accounts are preserved.
