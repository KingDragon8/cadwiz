# 0.9.3 implementation audit

Baseline:a273283 (released0.9.2 main).

| Requirement | Existing implementation | Extension / guard |
|---|---|---|
| Bidirectional CAD communication | STDIO MCP server + authenticated loopback bridge + GUI-thread queue | Reused; separate CLI identity and actual CAD-success evidence |
| Codex setup | Shared Codex config writer, backup/undo | Independent CLI discovery/login check; persistent CLI selection |
| Persistent preference | ai_app in preferences.json | CLI enum + persisted setup route; no clearing when unavailable |
| Credentials | Windows Credential Manager only | Existing Windows identifiers retained; Keychain and Secret Service adapters |
| Provider manager | ProviderState + capability-gated SafeHandoff | Reused unchanged cost/state protections; shared secure enrollment |
| Geometry preservation | Sandbox, versions, native E3 acceptance | Existing regressions retained; synthetic split-herringbone fixture |
| Orkas / DeskFox | No verified dedicated integration | None added; research standard protocol only |
| Cross-platform evidence | Native Windows/Linux and Apple Silicon Mac installation tests | Intel Mac native install checks and four-platform vault workflow |

The owner clarified that0.9.3 is a new update and authorized assumed gearbox values. Release publication requires core connectivity/editability and packaging checks to pass. Untested OS versions/accounts remain labeled, never converted into PASS by assumption. No paid inference is performed during this work.
