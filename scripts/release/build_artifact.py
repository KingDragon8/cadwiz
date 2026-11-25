# SPDX-License-Identifier: LGPL-2.1-or-later
"""Build a release ZIP and checksums from a committed public repository.

    python scripts/release/build_artifact.py --output /path/to/release

Only Git-tracked, committed files enter the ZIP. Local settings, caches and
uncommitted work cannot accidentally become part of a download.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import tomllib
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-tree", help="Immutable staged Git tree for an unpublished OASIS candidate; defaults to committed HEAD")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = args.source_tree or "HEAD"
    if args.source_tree:
        import re
        assert re.fullmatch(r"[a-f0-9]{40}", source), "A full immutable Git tree hash is required"
        assert subprocess.check_output(["git", "cat-file", "-t", source], cwd=root).strip() == b"tree"
    version = tomllib.loads(subprocess.check_output(
        ["git", "show", source + ":pyproject.toml"], cwd=root).decode("utf-8"))["project"]["version"]
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / f"cadwiz-{version}.zip"
    if archive.exists():
        raise SystemExit(f"Refusing to overwrite {archive}")
    prefix = f"cadwiz-{version}/"
    subprocess.run(["git", "archive", "--format=zip", f"--prefix={prefix}",
                    f"--output={archive.resolve()}", source], cwd=root, check=True)
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None, "Corrupt ZIP"
        names = package.namelist()
        for name in names:
            parts = Path(name).parts
            assert not any(p in {".git", ".env", ".secrets", "__pycache__"} for p in parts), name
            assert not name.lower().endswith((".fcstd", ".fcstd1")), name
        for module in ["learning.py", "motion_preview.py", "general_motion.py", "gear_quality.py", "offline_launcher.py"]:
            assert prefix + "CADWiz/src/integrations/cadwiz_plugin/" + module in names, module
        for platform in ["win32-x86_64-cp311", "darwin-arm64-cp311", "darwin-x86_64-cp311", "linux-x86_64-cp311"]:
            assert any(platform in name and name.endswith(".whl") for name in names), platform
        (args.output / "CADWiz.mcpb").write_bytes(package.read(prefix + "CADWiz/Resources/CADWiz.mcpb"))
    files = [archive, args.output / "CADWiz.mcpb"]
    sums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in files)
    (args.output / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
    print(sums, end="")


if __name__ == "__main__":
    main()
