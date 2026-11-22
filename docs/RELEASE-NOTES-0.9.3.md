# CADWiz 0.9.3 — AI connection compatibility

This update builds on released 0.9.2. It preserves the existing authenticated loopback/MCP bridge, model version store, execution sandbox, editable-geometry gates and Free AI provider manager.

## Changes

- Independent Codex CLI setup on Windows, macOS and Linux; discovery of PATH, standard npm, Homebrew and user CLI locations. Windows npm launchers resolve to Node and the actual CLI entry, without invoking a shell.
- Read-only CLI installation/login diagnostics. Discovery never launches inference, reads token files or signs users in automatically. ChatGPT Desktop is not required.
- Assistant and setup-route preferences survive restarts and temporary absence. The existing reversible Codex configuration writer now preserves CLI identity during repair.
- Credential enrollment/removal uses Windows Credential Manager, macOS Keychain through Security.framework, or Linux Secret Service via libsecret's secret-tool. There is no plaintext fallback. Missing/locked storage reports corrective guidance. API keys never appear in subprocess arguments or reports.
- Not Installed / Installed / Authenticated / Connected / CAD Ready are distinct. A heartbeat does not establish CAD readiness: an actual model inspection or validated editable-model operation must succeed through the adapter.
- Existing Free AI account enrollment, usage tracking, eligibility checks and controlled handoff are retained. No paid inference is authorized by selecting a provider. Direct unqualified provider CAD execution and automatic consumer-account switching remain disabled.
- No dedicated Orkas or DeskFox adapter is added or advertised. Existing standard MCP access remains available for future compatibility testing.

## Synthetic gearbox trial

The owner confirmed that Neil's dimensions were unavailable and authorized assumed trial values: 20/60 teeth, 3:1 ratio, 2 mm normal module, 25 degree helix angle, 20 degree normal pressure angle and 20 mm initial face width. The corresponding transverse module, pressure angle and center distance are derived rather than guessed.

The fixture uses FreeCAD's included involute profile generator, native additive lofts and fully constrained shaft-bore sketches/pockets. It is a split herringbone pair with two editable halves per gear. Three profile stations per half approximate the helical flank; this is not manufacturing-grade flank/contact validation. Saving/reopening, recomputation, wider gears, larger bores and unchanged earlier revisions are exercised in disposable files. The follow-up edits are scripted equivalents of dimensional instructions; a paid live AI conversation is not claimed.

Full automated housing, bearings, shafts, loaded contact, backlash, manufacturing clearance and strength remain a separate assembly acceptance gate. This is not Neil's actual gearbox.

## Validation and limits

Release checks include the existing cross-platform tests, installation/recovery and native FreeCAD checks, plus native vault roundtrips on Windows, Apple Silicon macOS, Intel macOS and Linux. Native macOS GUI tests exercise both APFS case modes. Evidence is attached to the release/CI runs; passing unit tests are not represented as physical-machine acceptance.

Intel macOS Monterey 12 specifically is NOT VERIFIED by newer Mac CI runners. CLI/runtime compatibility on that OS must be checked on a compatible Mac. Individual provider enrollment/account entitlements and live paid inference are not exercised by offline tests. An API key's authentication does not prove billing protection or CAD capability.

## Installation and recovery

Save work and close FreeCAD before upgrading. Windows: run CADWiz-Setup-0.9.3.exe. Mac: extract the complete ZIP and run Install-CADWiz.command (or bash scripts/install_macos.sh). Linux: use bash scripts/install.sh with the intended FreeCAD runtime. Configure assistants afterward in AI Wiz Setup. Codex CLI users install/sign in to the CLI themselves, then use Connect and ask it to inspect the open model.

Linux secure enrollment requires libsecret-tools and an unlocked Secret Service-compatible keyring. macOS requires an accessible unlocked login Keychain; Windows uses the current user's credential vault. Never enter keys in chat.

Previous installs/settings/model revisions are preserved by the existing backup and rollback paths. Public 0.9.2 artifacts remain available for rollback. No user document is deleted or automatically downgraded.
