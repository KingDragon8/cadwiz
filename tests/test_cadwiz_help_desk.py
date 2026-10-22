# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""ORDER-2026-10-21-01, Addendum One Parts B and C: Claude as the help desk, and
error reports that connect a failure to the feedback that reports it.

The founder's hard rule: "the first call never has a network side effect" --
proven here with a network stand-in that fails the test if it is called. Nothing
in this file touches the internet or a paid model.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from integrations.cadwiz_plugin import error_report
from integrations.cadwiz_plugin.feedback import STATUS_URL, HelpDesk
from integrations.cadwiz_plugin.session import PluginSession

STATUS = {
    "schema": "cadwiz-feedback-status/1", "page": "https://cadwiz.app/feedback/status",
    "items": [{"id": "t1", "title": "Remember my last hole size", "section": "idea", "label": "accepted", "votes": 7,
               "error_code": None, "fixed_in": None, "reason": None},
              {"id": "t2", "title": "Build fails on open sketch", "section": "bug", "label": "fixed", "fixed_in": "v0.5.1",
               "error_code": "CW-PLUGIN-FAIL", "reason": None, "votes": 3}],
    "scope": {"in_scope": ["Parts for 3D printing"], "out_of_scope": [{"area": "FEM", "why": "CADWiz 2.0"}]},
}


class NoNetwork:
    def __call__(self, *args, **kwargs):
        raise AssertionError(f"the network was used: {args[:2]}")


class FakeSite:
    def __init__(self, signed_in: bool = True) -> None:
        self.calls: list[tuple[str, str, dict, bytes | None]] = []
        self.signed_in = signed_in

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        if url == STATUS_URL:
            return 200, STATUS
        if url.endswith("/api/auth/plugin/start"):
            return 200, {"grant_id": "cwg_x", "sign_in_url": "https://cadwiz.app/feedback?signin=abc#sign-in"}
        if url.endswith("/api/auth/plugin/poll"):
            return (200, {"status": "signed_in", "session_token": "cws_token", "display_name": "Maker"}) if self.signed_in \
                else (202, {"status": "pending"})
        if url.endswith("/api/feedback"):
            return 201, {"ok": True, "status": "private", "url": "https://cadwiz.app/feedback#t-1"}
        return 404, {}


def _report(tmp_path: Path, username: str = "maker") -> str:
    log = tmp_path / "tool-calls.jsonl"
    log.write_text("\n".join(json.dumps({"utc": f"2026-10-21T10:00:{i:02d}Z", "tool": "build_model", "ok": i != 11,
                                         "arguments": {"note": f"C:\\Users\\{username}\\CAD\\part{i}.FCStd"},
                                         "detail": f"failed reading /home/{username}/x"}) for i in range(12)), encoding="utf-8")

    def grab(path: Path) -> bool:
        path.write_bytes(b"\x89PNG fake")
        return True

    model = tmp_path / "part.FCStd"
    model.write_bytes(b"PK fake")
    return error_report.write_report(tmp_path, error_code="CW-PLUGIN-FAIL", message=f"at C:\\Users\\{username}\\x: boom",
                                     tool="build_model", log_path=log, grab_window=grab, model_file=str(model),
                                     version_info={"cadwiz": "0.5.0-beta.2", "freecad": "1.1.3", "os": "Windows 10",
                                                   "claude_desktop": "unknown"})


def test_known_issues_come_from_the_project_labels_and_are_kept_an_hour(tmp_path: Path) -> None:
    site = FakeSite()
    desk = HelpDesk(tmp_path, http=site, clock=lambda: 1000.0)
    answer = desk.known_issues()
    assert answer["source"] == "cadwiz.app" and [i["label"] for i in answer["items"]] == ["accepted", "fixed"]
    assert answer["scope"]["out_of_scope"][0]["area"] == "FEM"
    assert desk.known_issues("CW-PLUGIN-FAIL")["items"][0]["fixed_in"] == "v0.5.1"
    assert len(site.calls) == 1                                      # the second answer came from the hour's cache


def test_known_issues_offline_falls_back_to_the_shipped_docs_and_says_so(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "KNOWN-LIMITATIONS.md").write_text("# Known limitations\nNo FEM.", encoding="utf-8")

    def offline(*_):
        raise OSError("no network")

    answer = HelpDesk(tmp_path / "data", http=offline, docs_dir=docs).known_issues()
    assert "could not be reached" in answer["source"] and "No FEM." in answer["local_docs"]["KNOWN-LIMITATIONS.md"]


def test_a_failing_tool_writes_a_report_with_id_trail_screenshot_and_versions(tmp_path: Path) -> None:
    report_id = _report(tmp_path)
    assert error_report.REPORT_ID.match(report_id)
    folder = tmp_path / "reports" / report_id
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    assert (folder / "screenshot.png").is_file() and report["screenshot"] is True
    assert len(report["trail"]) == 10 and all(len(step["asked"]) <= 500 for step in report["trail"])
    assert report["versions"]["freecad"] == "1.1.3" and report["error_code"] == "CW-PLUGIN-FAIL"
    assert not list(folder.glob("*.FCStd"))                         # the model file is never copied into a report
    assert _report(tmp_path).endswith("0002")                         # the next one that day


def test_the_session_attaches_a_report_when_a_tool_fails(tmp_path: Path) -> None:
    class App:
        ActiveDocument = None

        @staticmethod
        def Version():
            return ["1", "1", "3"]

        @staticmethod
        def listDocuments():
            return {}

    session = PluginSession(app=App(), project_root=tmp_path / "projects", log_path=tmp_path / "tool-calls.jsonl")
    session._inspect_document = lambda **_: 1 / 0                # a tool that breaks
    result = session.call("inspect_document", {})
    assert result["ok"] is False and result["error_code"] == "CW-PLUGIN-FAIL"
    assert (tmp_path / "reports" / result["report_id"] / "report.json").is_file()
    assert "send this to Steve" in result["note_for_claude"]


def test_first_call_is_only_a_preview_and_makes_no_network_request(tmp_path: Path) -> None:
    report_id = _report(tmp_path, username="maker")
    desk = HelpDesk(tmp_path, http=NoNetwork())
    preview = desk.send_feedback("bug", "Build failed on my bracket", "It stopped at step 3 every time.", report_id=report_id)
    assert preview["sent"] is False
    shown = preview["preview"]
    assert shown["public"] is False and shown["attached"] and shown["attached"][0].startswith("screenshot.png")
    assert "model_file" in shown["left_out"]                          # off unless ticked
    text = json.dumps(shown)
    assert "maker" not in text.lower() and "C:\\\\Users" not in text and "<path>" in text   # the scrub, shown to the user


def test_confirm_sends_once_signed_in_with_the_scrubbed_bundle(tmp_path: Path) -> None:
    report_id = _report(tmp_path, username="maker")
    site = FakeSite()
    desk = HelpDesk(tmp_path, http=site, open_browser=lambda url: None)
    first = desk.send_feedback("bug", "Build failed on my bracket", "It stopped at step 3 every time.", report_id=report_id,
                               confirm=True)
    assert first["sent"] is False and first["sign_in_url"].startswith("https://cadwiz.app/")   # never anonymous
    done = desk.send_feedback("bug", "Build failed on my bracket", "It stopped at step 3 every time.", report_id=report_id,
                              confirm=True)
    assert done["sent"] is True and done["status"] == "private"
    method, url, headers, body = site.calls[-1]
    assert (method, url) == ("POST", "https://cadwiz.app/api/feedback") and headers["Authorization"] == "Bearer cws_token"
    assert b'name="report_id"' in body and report_id.encode() in body and b'filename="screenshot.png"' in body
    assert b"maker" not in body.lower() and b"Users\\\\maker" not in body
    assert b".FCStd" not in body                                      # not ticked, not sent


def test_the_model_file_goes_only_when_the_user_ticks_it(tmp_path: Path) -> None:
    report_id = _report(tmp_path)
    desk = HelpDesk(tmp_path, http=NoNetwork())
    ticked = desk.send_feedback("bug", "Build failed on my bracket", "It stopped at step 3 every time.", report_id=report_id,
                                include=["error", "model_file"])["preview"]
    assert any(item.startswith("part.FCStd") for item in ticked["attached"]) and "screenshot" in ticked["left_out"]


def test_ideas_default_to_public_and_bad_input_is_refused_before_anything_else(tmp_path: Path) -> None:
    desk = HelpDesk(tmp_path, http=NoNetwork())
    assert desk.send_feedback("idea", "Remember my hole size", "Please keep the last hole size I used.")["preview"]["public"]
    with pytest.raises(TypeError):
        desk.send_feedback("rant", "Hello there", "This is not a section at all.")


def test_the_help_desk_talks_to_no_host_but_cadwiz_app() -> None:
    from integrations.cadwiz_plugin.feedback import https

    with pytest.raises(PermissionError):
        https("GET", "https://example.com/feedback/status.json", {}, None)


def test_get_help_opens_the_feedback_page_filled_in_with_versions_and_the_report() -> None:
    from integrations.cadwiz_plugin.feedback import get_help_url

    url = get_help_url(freecad_version="1.1.3", os_name="Windows-10", error_code="CW-PLUGIN-FAIL", report_id="CWR-20261021-0007")
    assert url.startswith("https://cadwiz.app/feedback?section=bug&cadwiz_version=0.5.0-beta.2")
    assert "report_id=CWR-20261021-0007" in url and "error_code=CW-PLUGIN-FAIL" in url and "freecad_version=1.1.3" in url


def test_the_panel_one_click_send_previews_offline_then_posts_picture_and_errors_privately(tmp_path: Path) -> None:
    """ORDER-2026-10-22-04: Report a problem shows the preview (no network), and the
    Send button posts it -- a private bug with the picture, errors, steps and versions,
    never the model file -- without the user finding or attaching a file."""
    from ai_freecad_core.cadwiz_screen.problems import Problem
    from integrations.cadwiz_plugin.feedback import panel_feedback, panel_report_message

    message = panel_report_message("the fillet vanished", [Problem("rebuild", "Pad failed to rebuild.", ["Pad"],
                                                                   detail_for_claude="BRep_API: command not done")])
    assert message.startswith("the fillet vanished") and "Pad failed to rebuild." in message and "BRep_API" in message
    report_id = _report(tmp_path, username="maker")
    args = panel_feedback("the fillet vanished", report_id)
    assert args["section"] == "bug" and args["public"] is False and "model_file" not in args["include"]
    shown = HelpDesk(tmp_path, http=NoNetwork()).send_feedback(**args)["preview"]
    assert shown["attached"][0].startswith("screenshot.png") and shown["bundle"]["trail"]
    site = FakeSite()
    done = HelpDesk(tmp_path, http=site, open_browser=lambda url: None).send_feedback(**args, confirm=True)
    if not done["sent"]:                                              # the first send signs in, the press after it sends
        done = HelpDesk(tmp_path, http=site, open_browser=lambda url: None).send_feedback(**args, confirm=True)
    assert done["sent"] is True
    body = site.calls[-1][3]
    assert b'filename="screenshot.png"' in body and b"failed" in body and b".FCStd" not in body


def test_panel_feedback_always_meets_the_sites_length_rules() -> None:
    from integrations.cadwiz_plugin.feedback import panel_feedback

    for note in ("", "x", "a" * 400):
        args = panel_feedback(note, "CWR-20261022-0001")
        assert 5 <= len(args["title"]) <= 120 and 10 <= len(args["description"]) <= 5000
