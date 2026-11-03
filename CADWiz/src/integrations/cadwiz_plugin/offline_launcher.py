# SPDX-License-Identifier: LGPL-2.1-or-later
"""Start the unchanged connector with private, verified offline dependencies."""
from __future__ import annotations

import hashlib
import contextlib
import json
import os
import platform
import runpy
import site
import sys
import tempfile
import time
import zipfile
from pathlib import Path


@contextlib.contextmanager
def helper_lock(path):
    # OS locks are released even if a process crashes; no stale lock directory.
    with path.open("a+b") as stream:
        deadline = time.monotonic() + 60
        while True:
            try:
                stream.seek(0)
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, PermissionError, OSError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("CW-SETUP-BUSY: Another CADWiz process is preparing the helper. Try again shortly.")
                time.sleep(.1)
        try:
            yield
        finally:
            stream.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def prepare(addon: Path) -> Path:
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    key = f"{sys.platform}-{machine}-cp{sys.version_info.major}{sys.version_info.minor}"
    source = addon / "vendor/connector-wheels" / key
    if not (source / "manifest.json").is_file():
        raise RuntimeError(f"CW-SETUP-PYTHON: No offline helper for {key}. Use FreeCAD with Python 3.11 on a supported platform, or the advanced installer.")
    manifest_bytes = (source / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    digest = hashlib.sha256(manifest_bytes).hexdigest()[:16]
    sys.path.insert(0, str(addon / "src"))
    from integrations.cadwiz_plugin.install_setup import data_dir
    parent = data_dir() / "helpers"
    target = parent / (key + "-" + digest)
    marker = target / ".verified.json"
    def intact():
        if not marker.is_file():
            return False
        try:
            files = json.loads(marker.read_text())
            return all((target / name).is_file() and hashlib.sha256((target / name).read_bytes()).hexdigest() == sha
                       for name, sha in files.items())
        except (OSError, ValueError):
            return False
    parent.mkdir(parents=True, exist_ok=True)
    with helper_lock(parent / (key + ".lock")):
        if not intact():
            parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=key + "-stage-", dir=parent))
            files = {}
            try:
                for name, sha in manifest["wheels"].items():
                    wheel = source / name
                    if hashlib.sha256(wheel.read_bytes()).hexdigest() != sha:
                        raise RuntimeError("CW-SETUP-HASH: The bundled helper is damaged. Reinstall CADWiz through Addon Manager.")
                    with zipfile.ZipFile(wheel) as archive:
                        for item in archive.infolist():
                            if item.is_dir():
                                continue
                            relative = Path(item.filename)
                            if relative.is_absolute() or ".." in relative.parts:
                                raise RuntimeError("CW-SETUP-ARCHIVE: Unsafe helper archive; nothing installed.")
                            parts = relative.parts
                            if parts[0].endswith(".data"):
                                if len(parts) < 3 or parts[1] not in {"purelib", "platlib"}:
                                    continue
                                relative = Path(*parts[2:])
                            content = archive.read(item)
                            output = stage / relative
                            output.parent.mkdir(parents=True, exist_ok=True)
                            output.write_bytes(content)
                            files[relative.as_posix()] = hashlib.sha256(content).hexdigest()
                (stage / ".verified.json").write_text(json.dumps(files))
                if target.exists():
                    # Preserve damaged data for inspection; never delete a user's directory.
                    target.rename(parent / (target.name + "-backup-" + stage.name.rsplit("-", 1)[-1]))
                stage.rename(target)
            except Exception:
                # Staged files are retained for diagnosis; the active helper is untouched.
                raise
    site.addsitedir(str(target))
    # Private packages take precedence over unrelated user-installed packages.
    sys.path.remove(str(target))
    sys.path.insert(0, str(target))
    return target


def main() -> None:
    addon = Path(__file__).resolve().parents[3]
    prepare(addon)
    if "--check" in sys.argv:
        import mcp
        import pydantic_core
        print(json.dumps({"ok": True, "mcp": str(mcp.__file__), "native": str(pydantic_core.__file__)}))
        return
    runpy.run_path(str(Path(__file__).with_name("server.py")), run_name="__main__")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
