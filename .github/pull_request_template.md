**What this changes, and why**

**How it was tested** (the tests you added or ran; no test may call a paid AI service)

**Checklist**
- [ ] Every commit is signed off (`git commit -s`) -- see CONTRIBUTING.md
- [ ] `python -m pytest` passes
- [ ] No new network call, or it is listed in `config/egress_allowlist.toml` with what it sends
- [ ] Nothing in this change deletes a user's files or loosens the sandbox
