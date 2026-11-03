# SPDX-License-Identifier: LGPL-2.1-or-later
"""Release-time downloads only. Runtime installation uses these files offline."""
from __future__ import annotations
import hashlib
import importlib.metadata as metadata
import json
import subprocess
import sys
from pathlib import Path
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import parse_wheel_filename, canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "win32-x86_64-cp311": ("win32", "Windows", "AMD64", ["win_amd64"]),
    "darwin-arm64-cp311": ("darwin", "Darwin", "arm64", ["macosx_11_0_arm64", "macosx_12_0_arm64", "macosx_11_0_universal2"]),
    "darwin-x86_64-cp311": ("darwin", "Darwin", "x86_64", ["macosx_10_13_x86_64", "macosx_10_15_x86_64", "macosx_11_0_x86_64", "macosx_11_0_universal2", "macosx_12_0_x86_64", "macosx_13_0_x86_64", "macosx_14_0_x86_64", "macosx_15_0_x86_64"]),
    "linux-x86_64-cp311": ("linux", "Linux", "x86_64", ["manylinux_2_34_x86_64", "manylinux_2_28_x86_64", "manylinux2014_x86_64"]),
}

def build(key):
    platform, system, machine, tags = TARGETS[key]
    env = default_environment()
    env.update(sys_platform=platform, platform_system=system, platform_machine=machine,
               python_version="3.11", python_full_version="3.11.14", extra="")
    pinned = {}
    pending = [Requirement("mcp==1.27.0")]
    seen = set()
    while pending:
        req = pending.pop()
        if req.marker and not req.marker.evaluate(env):
            continue
        identity = (req.name.lower().replace('_', '-'), tuple(sorted(req.extras)))
        if identity in seen:
            continue
        seen.add(identity)
        dist = metadata.distribution(req.name)
        if req.specifier and dist.version not in req.specifier:
            raise RuntimeError(f"Installed {req.name} does not satisfy {req}")
        pinned[dist.metadata["Name"]] = dist.version
        for child in dist.requires or []:
            requirement = Requirement(child)
            if not requirement.marker or any(requirement.marker.evaluate(dict(env, extra=extra)) for extra in ["", *req.extras]):
                # Marker was evaluated for the target/extras; do not reevaluate as a root requirement.
                requirement.marker = None
                pending.append(requirement)
    folder = ROOT / "CADWiz/vendor/connector-wheels" / key
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "manifest.json").exists():
        # Existing manifests are the release lock: rebuilding must not silently
        # select newer dependencies from a developer's Python environment.
        pinned = json.loads((folder / "manifest.json").read_text())["packages"]
    cmd = [sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--no-deps", "--python-version", "311", "--dest", str(folder)]
    for tag in tags:
        cmd += ["--platform", tag]
    subprocess.run(cmd + [f"{name}=={version}" for name, version in sorted(pinned.items())], check=True)
    normalized = {canonicalize_name(n): v for n, v in pinned.items()}
    wheels = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob("*.whl"))
              if str(parse_wheel_filename(p.name)[1]) == normalized.get(canonicalize_name(parse_wheel_filename(p.name)[0]))}
    (folder / "manifest.json").write_text(json.dumps({"target": key, "packages": pinned, "wheels": wheels}, indent=2))
    print(key, len(wheels), "verified wheel hashes recorded", flush=True)

if __name__ == "__main__":
    for key in sys.argv[1:] or TARGETS:
        build(key)
