# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The automated-spend switch (ORDER-2026-10-06-02, amended ORDER-2026-10-11-01).

Founder ruling, 2026-10-06: "I want all automated testing stopped. I'm tired of
using up credits." Nothing automated may call a paid AI service. Only the
founder's own use of CADWiz may.

HOW A RUN GETS MARKED. Two layers, in this order:

1. THE REQUEST. A request that starts from a click or a voice press in the
   CADWiz panel is the founder's own use -- whatever started FreeCAD, whatever
   is in the environment, whatever ran earlier in the process. The panel wraps
   each such turn in `founder_request()` (or `begin_founder_request()` /
   `end_founder_request()` around an asynchronous turn). While one is open,
   nothing in this process is blocked, and `CADWIZ_FOUNDER_REQUEST=1` is set in
   the environment so a helper process the panel starts for that request (the
   ElevenLabs speech child, for one) inherits the same answer. Scripts and
   tools never set either -- `tests/contract/test_founder_panel_request_not_
   blocked.py` fails if one does.

2. THE PROCESS, decided once at its first paid call when no request mark is
   open. It is automated if the environment says so (`CADWIZ_AUTOMATED_RUN`),
   if a test runner is loaded, if any ancestor process is a terminal /
   interpreter / scheduler (a script, a test, a scheduled task, a helper
   started by a terminal session), or if there is no FreeCAD window at all (the
   founder only ever uses CADWiz through the panel inside FreeCAD). A FreeCAD
   window with none of those signs is the founder's, however it was started.
   When the origin genuinely cannot be determined, it is founder use.

   Found 2026-10-11 (ORDER-2026-10-11-01): this used to ALSO demand `explorer.exe`
   somewhere above the process as "positive proof of the desktop". The
   founder's FreeCAD had been started by Microsoft Edge (opening a file from the
   browser) and had no explorer.exe above it, so his own panel was marked
   automated at its first paid call, the answer was cached for the life of the
   process, and he was refused twice. That requirement is gone.

WHERE THE BLOCK SITS. At the one place requests leave the machine: this module
replaces `urllib.request.urlopen` (what the vendored AI client and the cloud
voice code use) with a guard that refuses a request to a paid AI host from an
automated run, before anything is sent, writes one plain line to the local log
and raises `AutomatedSpendBlocked`, whose message starts "NEEDS FOUNDER TEST"
-- a label for scripts and reports; the panel never shows it (the provider
layer turns it into a plain sentence). Scripts that use another HTTP library
call `require_spend_allowed()` first.

The switch defaults to OFF. Turning spending on for automated runs is a
founder-only step recorded in `docs/FOUNDER-RULINGS.md`; see `spend_enabled()`.

No network, no FreeCAD, no vendor import in here: this module never sends
anything itself.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

BLOCK_LINE = "blocked: automated runs may not spend AI credit"
NEEDS_FOUNDER_TEST = "NEEDS FOUNDER TEST"

#: Set in this process's environment for the life of a founder request, so a
#: helper process started for that request inherits the answer. Panel-only.
FOUNDER_REQUEST_ENV = "CADWIZ_FOUNDER_REQUEST"


#: Hosts whose requests cost money (or hand a key to a paid service).
def _load_hosts() -> tuple[frozenset[str], dict[str, str]]:
    """The paid-service host list is DATA (`paid_ai_hosts.json`, next to this file),
    not code, so no provider name appears in core Python."""
    data = json.loads((Path(__file__).with_name("paid_ai_hosts.json")).read_text(encoding="utf-8"))
    return frozenset(data["hosts"]), dict(data["provider_by_host_fragment"])


PAID_AI_HOSTS, _PROVIDER_BY_FRAGMENT = _load_hosts()

#: Process names that mean "a terminal, a script runner or a scheduler started me".
AUTOMATION_PARENTS = frozenset(
    {
        "cmd.exe", "powershell.exe", "pwsh.exe", "python.exe", "pythonw.exe", "py.exe", "bash.exe", "sh.exe",
        "node.exe", "claude.exe", "wsl.exe", "git.exe", "pytest.exe", "taskeng.exe", "taskhostw.exe",
        "conhost.exe", "windowsterminal.exe", "wt.exe", "code.exe", "cursor.exe", "schtasks.exe",
    }
)

_lock = threading.Lock()
_decided: bool | None = None
_founder_requests = 0
_real_urlopen = urllib.request.urlopen
_installed = False


class AutomatedSpendBlocked(RuntimeError):
    """An automated run tried to make a paid AI call. Nothing was sent."""

    needs_founder_test = True

    def __init__(self, host: str) -> None:
        super().__init__(f"{NEEDS_FOUNDER_TEST}: {BLOCK_LINE} ({host})")
        self.host = host


def log_path() -> Path:
    return Path(os.environ.get("CADWIZ_AI_CALL_LOG") or Path.home() / ".cadwiz" / "ai-call-log.jsonl")


def _process_names_of_ancestors(limit: int = 12) -> list[str]:
    """Names of this process's ancestors, nearest first. Windows only; elsewhere
    (or on any failure) returns [] and the other signals decide."""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessEntry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)
        table: dict[int, tuple[int, str]] = {}
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(ProcessEntry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            table[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile.lower())
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        kernel32.CloseHandle(snapshot)
        names: list[str] = []
        pid = os.getpid()
        seen: set[int] = set()
        for _ in range(limit):
            parent = table.get(pid, (0, ""))[0]
            if not parent or parent in seen or parent not in table:
                break
            seen.add(parent)
            names.append(table[parent][1])
            pid = parent
        return names
    except Exception:  # noqa: BLE001 - a failed lookup must not decide anything by itself
        return []


def reasons_from(environ: dict[str, str], modules: dict[str, Any], ancestors: list[str]) -> list[str]:
    """The decision itself, as a pure function (so it can be tested without a
    real process tree). Empty list = the founder's own use.

    A founder request mark in the environment (set by the panel for a click or
    a voice press, inherited by its helpers) wins over everything else. After
    that, only POSITIVE signs of automation count; the absence of a desktop
    shell above the process is not one of them."""
    if environ.get(FOUNDER_REQUEST_ENV):
        return []
    reasons: list[str] = []
    if environ.get("CADWIZ_AUTOMATED_RUN"):
        reasons.append("CADWIZ_AUTOMATED_RUN is set")
    if "pytest" in modules or environ.get("PYTEST_CURRENT_TEST"):
        reasons.append("a test runner is loaded")
    freecad = modules.get("FreeCAD")
    if "FreeCADGui" not in modules or not getattr(freecad, "GuiUp", False):
        reasons.append("no FreeCAD window (the founder only uses CADWiz through the panel)")
    started_by = sorted({name for name in ancestors if name in AUTOMATION_PARENTS})
    if started_by:
        reasons.append("started by " + ", ".join(started_by))
    return reasons


def automated_reasons() -> list[str]:
    """Why this process counts as an automated run (empty = the founder's own use)."""
    return reasons_from(dict(os.environ), dict(sys.modules), _process_names_of_ancestors())


def is_automated_run() -> bool:
    """False for the whole of a founder request, whatever the process looks like;
    otherwise the process's own decision, made once."""
    global _decided
    if _founder_requests > 0 or os.environ.get(FOUNDER_REQUEST_ENV):
        return False
    if _decided is None:
        _decided = bool(automated_reasons())
    return _decided


def begin_founder_request() -> None:
    """A click or a voice press in the panel started a request. Panel-only.
    Pair with `end_founder_request()` in a `finally`; nesting is fine."""
    global _founder_requests
    with _lock:
        _founder_requests += 1
        os.environ[FOUNDER_REQUEST_ENV] = "1"


def end_founder_request() -> None:
    global _founder_requests
    with _lock:
        _founder_requests = max(0, _founder_requests - 1)
        if _founder_requests == 0:
            os.environ.pop(FOUNDER_REQUEST_ENV, None)


@contextlib.contextmanager
def founder_request() -> Iterator[None]:
    """`with spend_guard.founder_request():` around a synchronous founder action."""
    begin_founder_request()
    try:
        yield
    finally:
        end_founder_request()


def rulings_file() -> Path:
    return Path(__file__).resolve().parents[3] / "docs" / "beta" / "FOUNDER-RULINGS.md"


def spend_enabled() -> bool:
    """The founder-only switch. OFF unless `~/.cadwiz/automated-spend-allowed.json`
    exists, says `"allowed": true`, and names a ruling that is really written in
    docs/FOUNDER-RULINGS.md (a heading `AUTOMATED-SPEND-ENABLED <date>`). Nobody
    but the founder writes that ruling; see docs/FOUNDER-RULINGS.md."""
    path = Path(os.environ.get("CADWIZ_SPEND_SWITCH") or Path.home() / ".cadwiz" / "automated-spend-allowed.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("allowed") is not True:
            return False
        reference = str(data.get("ruling", ""))
        return bool(reference) and reference.startswith("AUTOMATED-SPEND-ENABLED") and reference in rulings_file().read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 - anything unreadable means OFF
        return False


def _provider_of(host: str) -> str:
    for needle, name in _PROVIDER_BY_FRAGMENT.items():
        if needle in host:
            return name
    return host


def record_call(event: str, *, host: str = "", provider: str = "", model: str = "", usage: dict[str, Any] | None = None,
                purpose: str = "", note: str = "") -> None:
    """One line in the one local log of paid AI calls. Never raises."""
    try:
        line = {
            "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,  # sent | blocked | usage
            "provider": provider or _provider_of(host),
            "model": model,
            "host": host,
            "made_by": "automated run" if is_automated_run() else "founder",
            "input_tokens": (usage or {}).get("input_tokens", (usage or {}).get("prompt_tokens", (usage or {}).get("promptTokenCount"))),
            "output_tokens": (usage or {}).get("output_tokens", (usage or {}).get("completion_tokens", (usage or {}).get("candidatesTokenCount"))),
            "process": Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "",
            "purpose": purpose,
            "note": note,
        }
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")
    except Exception:  # noqa: BLE001
        pass


def is_paid_host(host: str) -> bool:
    host = (host or "").lower()
    return host in PAID_AI_HOSTS or any(host.endswith("." + known) for known in PAID_AI_HOSTS)


def require_spend_allowed(host: str, *, model: str = "", purpose: str = "") -> None:
    """Call before any paid request made by a path that does not go through
    `urllib.request.urlopen`. Raises `AutomatedSpendBlocked` for an automated
    run while the switch is off; otherwise returns."""
    if is_automated_run() and not spend_enabled():
        record_call("blocked", host=host, model=model, purpose=purpose, note=BLOCK_LINE)
        raise AutomatedSpendBlocked(host)


def _model_of(request: Any) -> str:
    try:
        data = getattr(request, "data", None)
        if data:
            return str(json.loads(data).get("model", ""))
    except Exception:  # noqa: BLE001
        pass
    return ""


def guarded_urlopen(url: Any, *args: Any, **kwargs: Any) -> Any:
    target = url.full_url if hasattr(url, "full_url") else str(url)
    host = (urllib.parse.urlparse(target).hostname or "").lower()
    if is_paid_host(host):
        model = _model_of(url)
        require_spend_allowed(host, model=model)
        record_call("sent", host=host, model=model)
    return _real_urlopen(url, *args, **kwargs)


def install_egress_guard() -> None:
    """Make `urllib.request.urlopen` the guarded one. Idempotent; called when the
    AI seam and the provider client are imported."""
    global _installed
    if _installed:
        return
    urllib.request.urlopen = guarded_urlopen  # type: ignore[assignment]
    _installed = True


def _log_rows(since_utc: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for raw in log_path().read_text(encoding="utf-8").splitlines():
            entry = json.loads(raw)
            if since_utc and entry.get("utc", "") < since_utc:
                continue
            rows.append(entry)
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001
        pass
    return rows


def paid_calls_by_automated_runs(since_utc: str = "") -> dict[str, int]:
    """From the one local log: how many paid calls were SENT by automated runs
    (should always be 0 under the ruling) and how many were blocked, since the
    given UTC time (ISO, e.g. "2026-10-06T20:00:00Z"; empty = whole log)."""
    sent = blocked = 0
    for entry in _log_rows(since_utc):
        if entry.get("made_by") != "automated run":
            continue
        if entry.get("event") == "sent":
            sent += 1
        elif entry.get("event") == "blocked":
            blocked += 1
    return {"sent": sent, "blocked": blocked}


def founder_panel_requests_refused(since_utc: str = "") -> list[dict[str, Any]]:
    """From the one local log: the blocked rows that came from the FreeCAD
    window itself -- the founder's own panel refused as if it were a script
    (the 2026-10-11 defect). A blocked row from any other process (a `python -c`,
    a test) was a real automated run and is not counted."""
    return [
        entry for entry in _log_rows(since_utc)
        if entry.get("event") == "blocked" and str(entry.get("process", "")).lower() == "freecad.exe"
    ]
