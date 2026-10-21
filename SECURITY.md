# Reporting a security problem

CADWiz runs code on your computer: the FreeCAD code Claude writes runs in a
sandbox (no network, no programs, no files outside the project folder), and
CADWiz talks to Claude Desktop through a local connection protected by a secret
token. If you find a way around any of that, or anything else that could harm a
user, **please report it privately first**.

- **Email:** security@cadwiz.app *(address to be confirmed before the public
  release)*.
- **Or** file a **private** Bug at [cadwiz.app/feedback](https://cadwiz.app/feedback)
  (Bug posts are private by default and only the maintainer can read them).

Please include what you did, what happened, and the CADWiz and FreeCAD versions.

**Please don't post it publicly** (GitHub issues, forums, social media) until a fix
is released. You'll get a reply, and credit in the release notes if you'd like it.

## Supported versions

Only the newest release gets security fixes during the beta.
