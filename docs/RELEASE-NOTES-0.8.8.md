# CADWiz Beta 0.8.8 — Free AIWiz setup

Free AIWiz adds a new place to discover and organize supported AI providers.
Existing Claude, ChatGPT and compatible assistant connections remain available.

- Seven provider cards with signup links, account status, connection status and
  preferred ordering: Groq, OpenRouter, Cloudflare Workers AI, Google Gemini API,
  Cerebras, Mistral and GitHub Models.
- Guided, user-initiated API-access checks with a masked key field and explicit
  consent. Windows Credential Manager stores keys; there is no plaintext fallback.
  Secure enrollment is currently Windows-only. Other platforms retain existing
  assistant connections and provider guides.
- A compact, responsive dashboard with local request-usage indicators. These
  indicate CADWiz request activity, not remaining provider credits or an
  account-wide balance. Activity begins with a supported routed request.
- Account checks use fixed HTTPS destinations and send no CAD model, screenshot,
  dimensions or generation prompt. A successful check confirms access only; it
  does not establish free billing, account eligibility or CAD generation quality.

## Beta limits

Automatic inference and automatic provider switching are not enabled in this
release. Provider accounts have their own limits, terms and regional eligibility.
A consumer ChatGPT or Claude subscription does not supply another provider's API
key. Existing assistant workflows continue to be the way to create and edit CAD.

Offline handoff tests and native FreeCAD fixture checks passed locally. These
are not live-provider benchmarks. No owner credentials were used to benchmark
inference. macOS/Linux native UI and credential enrollment have not been
qualified on real devices for this new page.

0.8.7 is the saved before-change local checkpoint, not a separate public release.
The prior public Beta 0.8.6 remains available for rollback. Scan is excluded.
