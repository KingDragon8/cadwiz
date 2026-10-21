# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Downloads a picture or a model file the founder asked for (ORDER-2026-10-18-02).

The only network use of the Claude plug-in, allowlisted in
config/egress_allowlist.toml with what it sends. Claude names the address (a
concept picture it found, or the model page link the founder gave); this fetches
that one file with a plain HTTPS GET -- no cookies, no account, nothing of his
sent -- into the plug-in's project folder:

  * https only, a size cap, and a time limit;
  * a picture must come back as a picture and a model as STL/3MF/OBJ/STEP;
  * never overwrites a file (a new name instead);
  * runs on a background thread while FreeCAD's window keeps answering (the
    founder's 2026-10-06 ruling: nothing slow on the window thread).
"""
from __future__ import annotations

import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

PICTURE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif", "image/svg+xml": ".svg"}
MODEL_SUFFIXES = (".stl", ".3mf", ".obj", ".step", ".stp")
MAX_PICTURE_BYTES = 15_000_000
MAX_MODEL_BYTES = 250_000_000
TIME_LIMIT_S = 90.0


class FetchRefused(Exception):
    """Plain reason the file was not fetched (for Claude; the founder gets one line)."""


def safe_name(text: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")[:60]
    return cleaned or fallback


def unique(path: Path) -> Path:
    candidate, n = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        n += 1
    return candidate


def _check_url(url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(str(url).strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise FetchRefused("only https addresses are fetched")
    if parsed.hostname in ("localhost", "127.0.0.1", "::1") or (parsed.hostname or "").endswith(".local"):
        raise FetchRefused("addresses on this computer or network are not fetched")
    return parsed


def _get(url: str, max_bytes: int) -> tuple[bytes, str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "CADWiz (FreeCAD plug-in; fetches one file the user asked for)"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - https only, checked above
        declared = int(response.headers.get("Content-Length") or 0)
        if declared and declared > max_bytes:
            raise FetchRefused(f"the file is {declared // 1_000_000} MB, over the {max_bytes // 1_000_000} MB limit")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise FetchRefused(f"the file is over the {max_bytes // 1_000_000} MB limit")
        return data, str(response.headers.get("Content-Type") or "").split(";")[0].strip().lower(), response.geturl()


def _pumped(work: Callable[[], tuple[bytes, str, str]], pump: Callable[[], None] | None) -> tuple[bytes, str, str]:
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = work()
        except BaseException as error:  # noqa: BLE001 - handed back to the caller's thread
            box["error"] = error

    worker = threading.Thread(target=run, name="cadwiz-fetch", daemon=True)
    worker.start()
    started = time.monotonic()
    while worker.is_alive():
        if pump is not None:
            pump()
        worker.join(0.05)
        if time.monotonic() - started > TIME_LIMIT_S:
            raise FetchRefused("the download took too long")
    if "error" in box:
        error = box["error"]
        if isinstance(error, FetchRefused):
            raise error
        raise FetchRefused(f"the download failed ({type(error).__name__}: {error})")
    return box["value"]


def fetch_picture(url: str, folder: Path, name: str, pump: Callable[[], None] | None = None,
                  getter: Callable[[str, int], tuple[bytes, str, str]] | None = None) -> Path:
    _check_url(url)
    get = getter or _get
    data, content_type, _final = _pumped(lambda: get(url, MAX_PICTURE_BYTES), pump)
    suffix = PICTURE_TYPES.get(content_type)
    if suffix is None:
        raise FetchRefused(f"that address did not return a picture (it returned {content_type or 'nothing named'})")
    folder.mkdir(parents=True, exist_ok=True)
    target = unique(folder / (safe_name(name, "concept") + suffix))
    target.write_bytes(data)
    return target


def fetch_model(url: str, folder: Path, pump: Callable[[], None] | None = None,
                getter: Callable[[str, int], tuple[bytes, str, str]] | None = None) -> Path:
    parsed = _check_url(url)
    get = getter or _get
    data, content_type, final = _pumped(lambda: get(url, MAX_MODEL_BYTES), pump)
    name = Path(urllib.parse.unquote(urllib.parse.urlparse(final or url).path or parsed.path)).name
    suffix = Path(name).suffix.lower()
    if suffix not in MODEL_SUFFIXES:
        if content_type.startswith("text/html"):
            raise FetchRefused("that link is a web page, not a model file -- use the page's download link for the STL, 3MF, OBJ or STEP")
        raise FetchRefused(f"that link is not an STL, 3MF, OBJ or STEP file ({suffix or content_type or 'no file type'})")
    if suffix == ".stl" and not (data[:5].lower() == b"solid" or len(data) > 84):
        raise FetchRefused("the file is not a readable STL")
    folder.mkdir(parents=True, exist_ok=True)
    target = unique(folder / safe_name(name, f"model{suffix}"))
    target.write_bytes(data)
    return target
