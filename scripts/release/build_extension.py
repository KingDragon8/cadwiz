"""Rebuild the small offline extension from its reviewed source, without downloads."""
from pathlib import Path
import json
import zipfile


def main():
    root = Path(__file__).resolve().parents[2]
    source = root / "CADWiz/Resources/claude-extension"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf8"))
    assert manifest["server"]["entry_point"] == "launcher.cjs"
    output = root / "CADWiz/Resources/CADWiz.mcpb"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("launcher.cjs", "manifest.json"):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            data = (source / name).read_bytes().replace(b"\r\n", b"\n")
            archive.writestr(info, data)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
    print("Rebuilt extension version " + manifest["version"])


if __name__ == "__main__":
    main()
