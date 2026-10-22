# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Claude as CADWiz's help desk (ORDER-2026-10-21-01, Addendum One Part B).

Two tools, run in the plug-in's server process (never on FreeCAD's window thread):

  known_issues   what the CADWiz project has said about bugs and requests -- the
                 founder's own labels, read from https://cadwiz.app/feedback/status.json
                 (kept for an hour), or the docs shipped with CADWiz when offline.
  send_feedback  files a bug, idea or question on cadwiz.app for the user.

THE CONSENT RULE IS IN THE CODE, not in Claude's instructions: a call without
confirm=true only builds a preview -- the exact title, text and every attached
item, already scrubbed -- and makes no network request of any kind. Only a second
call with confirm=true sends, and Claude may make it only after the user said yes.
Nothing is ever sent anonymously, and there is no background reporting.

The site's side of this is cadwiz-site `docs/FEEDBACK-API.md`. The only host this
module talks to is cadwiz.app, over https (config/egress_allowlist.toml).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Callable

from integrations.cadwiz_plugin import CADWIZ_VERSION
from integrations.cadwiz_plugin.error_report import (
    DEFAULT_ITEMS, ITEMS, bundle_for_sending, load_report, reports_dir, scrub,
)

SITE = "https://cadwiz.app"
STATUS_URL = f"{SITE}/feedback/status.json"
CACHE_S = 3600
SECTIONS = ("bug", "idea", "question")
MAX_FILE_BYTES = 25_000_000
LOCAL_DOCS = ("KNOWN-LIMITATIONS.md", "SCOPE.md")

#: (method, url, headers, body) -> (status, parsed JSON). Tests pass a fake; the
#: preview step must never call it.
Http = Callable[[str, str, dict[str, str], bytes | None], tuple[int, dict[str, Any]]]


def https(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, dict[str, Any]]:
    if not url.startswith(SITE + "/"):
        raise PermissionError("CADWiz's help desk only talks to https://cadwiz.app")
    request = urllib.request.Request(url, data=body, method=method,
                                     headers={"User-Agent": f"CADWiz plug-in {CADWIZ_VERSION}", **headers})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https host
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read().decode("utf-8") or "{}")
        except ValueError:
            return error.code, {}


class HelpDesk:
    def __init__(self, data_dir: Path, *, http: Http = https, docs_dir: Path | None = None,
                 open_browser: Callable[[str], Any] = webbrowser.open, clock: Callable[[], float] = time.time) -> None:
        self.data_dir = Path(data_dir)
        self.http = http
        self.docs_dir = docs_dir
        self.open_browser = open_browser
        self.clock = clock

    # ---- known issues ------------------------------------------------------------------
    def known_issues(self, about: str = "") -> dict[str, Any]:
        cache = self.data_dir / "known-issues.json"
        status, source = None, ""
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if self.clock() - float(cached.get("fetched", 0)) < CACHE_S:
                status, source = cached["status"], "cadwiz.app (checked within the hour)"
        except (OSError, ValueError, KeyError):
            pass
        if status is None:
            try:
                code, body = self.http("GET", STATUS_URL, {"Accept": "application/json"}, None)
                if code == 200 and body.get("schema", "").startswith("cadwiz-feedback-status/"):
                    status, source = body, "cadwiz.app"
                    self.data_dir.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps({"fetched": self.clock(), "status": body}), encoding="utf-8")
            except Exception:  # noqa: BLE001 - offline: fall back to the shipped docs below
                status = None
        if status is None:
            return {"ok": True, "source": "the documents shipped with CADWiz (cadwiz.app could not be reached; say so)",
                    "local_docs": self._local_docs(), "items": []}
        items = status.get("items", [])
        if about:
            words = about.casefold()
            items = [i for i in items if words in json.dumps(i).casefold()] or items
        return {"ok": True, "source": source, "page": status.get("page", f"{SITE}/feedback/status"),
                "items": items[:40], "scope": status.get("scope", {}),
                "note_for_claude": "These are the project's own labels: accepted = planned, later, fixed (fixed_in), "
                                   "declined (with the reason). Answer from them; do not guess."}

    def _local_docs(self) -> dict[str, str]:
        found = {}
        for name in LOCAL_DOCS:
            path = (self.docs_dir or Path()) / name
            if self.docs_dir and path.is_file():
                found[name] = path.read_text(encoding="utf-8")[:6000]
        return found

    # ---- send feedback -----------------------------------------------------------------
    def send_feedback(self, section: str, title: str, description: str, public: bool | None = None,
                      report_id: str = "", include: list[str] | None = None, confirm: bool = False) -> dict[str, Any]:
        section = str(section).strip().lower()
        if section not in SECTIONS:
            raise TypeError("section is bug, idea or question")
        title, description = str(title).strip(), str(description).strip()
        if not 5 <= len(title) <= 120 or not 10 <= len(description) <= 5000:
            raise TypeError("title is 5-120 characters and description 10-5000")
        is_public = (section != "bug") if public is None else bool(public)
        package = self._package(section, title, description, is_public, report_id, include)
        if not confirm:
            # The preview: built from local files only. NO network request here.
            return {"ok": True, "sent": False, "preview": package["shown"],
                    "note_for_claude": "Show the user this preview exactly -- the title, the text, public or private, and "
                                       "every item that would be attached. Send ONLY if they say yes, by calling again "
                                       "with the same arguments and confirm=true. If they want an item left out, change "
                                       "`include`."}
        token = self._session_token()
        if token is None:
            return self._sign_in_first()
        return self._post(package, token)

    def _package(self, section: str, title: str, description: str, is_public: bool, report_id: str,
                 include: list[str] | None) -> dict[str, Any]:
        fields = {"section": section, "title": scrub(title), "description": scrub(description),
                  "public": "true" if is_public else "false", "cadwiz_version": CADWIZ_VERSION}
        files: list[tuple[str, Path]] = []
        shown: dict[str, Any] = {"section": section, "title": fields["title"], "description": fields["description"],
                                 "public": is_public, "attached": []}
        if report_id:
            report = load_report(self.data_dir, report_id)
            if report is None:
                raise TypeError(f"no error report {report_id!r} on this computer")
            chosen = [i for i in (include if include is not None else DEFAULT_ITEMS) if i in ITEMS]
            bundle = bundle_for_sending(report, chosen)
            fields.update(report_id=report_id, error_code=str(report.get("error_code", "")),
                          bundle=json.dumps(bundle))
            versions = report.get("versions", {})
            fields.update({k: str(v)[:60] for k, v in (("freecad_version", versions.get("freecad")), ("os", versions.get("os")),
                                                        ("claude_desktop_version", versions.get("claude_desktop"))) if v})
            shot = reports_dir(self.data_dir) / report_id / "screenshot.png"
            if "screenshot" in chosen and shot.is_file():
                files.append(("screenshot.png", shot))
            model = Path(str(report.get("model_file") or ""))
            if "model_file" in chosen and model.suffix.lower() == ".fcstd" and model.is_file():
                if model.stat().st_size <= MAX_FILE_BYTES:
                    files.append((model.name, model))
            shown["report_id"] = report_id
            shown["bundle"] = bundle
            shown["attached"] = [f"{name} ({path.stat().st_size // 1024} KB)" for name, path in files]
            shown["left_out"] = [i for i in ITEMS if i not in chosen]
        return {"fields": fields, "files": files, "shown": shown}

    # ---- sign-in (device style, docs/FEEDBACK-API.md section 1) -------------------------
    def _session_path(self) -> Path:
        return self.data_dir / "feedback-session.json"

    def _session_token(self) -> str | None:
        try:
            saved = json.loads(self._session_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        if saved.get("session_token"):
            return str(saved["session_token"])
        grant = saved.get("grant_id")
        if not grant:
            return None
        code, body = self.http("POST", f"{SITE}/api/auth/plugin/poll", {"Content-Type": "application/json"},
                               json.dumps({"grant_id": grant}).encode("utf-8"))
        if code == 200 and body.get("session_token"):
            self._save({"session_token": body["session_token"], "display_name": body.get("display_name", "")})
            return str(body["session_token"])
        if code in (404, 410):
            self._save({})
        return None

    def _sign_in_first(self) -> dict[str, Any]:
        code, body = self.http("POST", f"{SITE}/api/auth/plugin/start", {"Content-Type": "application/json"},
                               json.dumps({"client_name": f"CADWiz plug-in {CADWIZ_VERSION}"}).encode("utf-8"))
        if code != 200 or not body.get("sign_in_url"):
            return {"ok": False, "sent": False, "say_to_founder": "cadwiz.app could not be reached to sign in; nothing was sent."}
        self._save({"grant_id": body["grant_id"]})
        try:
            self.open_browser(body["sign_in_url"])
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "sent": False, "sign_in_url": body["sign_in_url"],
                "say_to_founder": "Nothing has been sent yet. A sign-in page for cadwiz.app has opened in your browser: "
                                  "enter your email and a display name, then press the link in the email. Tell me when "
                                  "you're done and I'll send it.",
                "note_for_claude": "After the user says they signed in, call again with confirm=true."}

    def _save(self, data: dict[str, Any]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._session_path().write_text(json.dumps(data), encoding="utf-8")

    # ---- the post ------------------------------------------------------------------------
    def _post(self, package: dict[str, Any], token: str) -> dict[str, Any]:
        body, content_type = multipart(package["fields"], package["files"])
        code, answer = self.http("POST", f"{SITE}/api/feedback", {"Content-Type": content_type,
                                                                  "Authorization": f"Bearer {token}"}, body)
        if code == 201 and answer.get("ok"):
            status = answer.get("status")
            where = {"public": "It's on the public forum now.",
                     "held": "It's waiting for approval (a first post is checked before it appears).",
                     "private": "It's private: only the CADWiz maintainer can see it."}.get(status, "")
            return {"ok": True, "sent": True, "status": status, "url": answer.get("url"),
                    "say_to_founder": f"Sent. {where}".strip()}
        if code == 401:
            self._save({})
            return self._sign_in_first()
        return {"ok": False, "sent": False, "say_to_founder": answer.get("message") or "cadwiz.app did not accept it; nothing was posted.",
                "detail_for_claude": f"HTTP {code}: {answer.get('error', '')} {answer.get('field', '')}".strip()}


def panel_report_message(note: str, problems: list[Any]) -> str:
    """What the panel's Report a problem button puts in the error report: his note,
    then every problem his screen shows, with the technical detail behind it."""
    lines = [note.strip() or "(no note)"]
    if problems:
        lines.append("")
        lines.append("Problems on screen:")
        for problem in problems:
            detail = str(getattr(problem, "detail_for_claude", "") or "")
            lines.append(f"- {getattr(problem, 'what', problem)}" + (f" [{detail[:400]}]" if detail else ""))
    return "\n".join(lines)


def panel_feedback(note: str, report_id: str) -> dict[str, Any]:
    """The send_feedback arguments for the panel's one-click send (ORDER-2026-10-22-04):
    a private bug carrying the report's default items -- the picture, the error, the
    last steps and the versions; the model file only through the assistant, on request."""
    note = " ".join(note.split())
    title = f"Problem: {note}"[:120] if len(note) >= 3 else "Problem reported from the CADWiz panel"
    return {"section": "bug", "title": title, "public": False, "report_id": report_id,
            "include": list(DEFAULT_ITEMS),
            "description": f"{note or '(no note)'}\n\nSent with the Report a problem button in the CADWiz panel."}


def get_help_url(*, cadwiz_version: str = CADWIZ_VERSION, freecad_version: str = "", os_name: str = "",
                 claude_desktop_version: str = "", error_code: str = "", report_id: str = "", section: str = "bug") -> str:
    """The panel's Get help button: cadwiz.app/feedback with the form pre-filled
    (docs/FEEDBACK-API.md section 5). Only versions and ids -- nothing of the model."""
    from urllib.parse import urlencode

    params = {"section": section, "cadwiz_version": cadwiz_version, "freecad_version": freecad_version, "os": os_name,
              "claude_desktop_version": claude_desktop_version, "error_code": error_code, "report_id": report_id}
    return f"{SITE}/feedback?" + urlencode({k: v for k, v in params.items() if v})


def multipart(fields: dict[str, str], files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = "cadwiz-" + uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode() + str(value).encode("utf-8") + b"\r\n")
    for filename, path in files:
        kind = "image/png" if filename.endswith(".png") else "application/octet-stream"
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="attachments"; filename="{filename}"\r\n'
                     f"Content-Type: {kind}\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
