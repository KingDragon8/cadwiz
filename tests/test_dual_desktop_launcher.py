# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real MCP protocol through packaged launch paths; no assistant/model calls.

This proves native launcher/SDK interoperability, not Codex-client integration.
The native Windows release gate supplies FreeCAD Python and forbids skips.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("app", ["claude", "chatgpt", "codex_cli"])
def test_desktop_launch_path_is_real_mcp_with_private_helpers(app, tmp_path):
    python = os.environ.get("CADWIZ_TEST_FREECAD_PYTHON")
    if not python:
        pytest.skip("Requires explicit FreeCAD Python path; CI's offline helper check runs separately")
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    setup = tmp_path / "private"
    setup.mkdir()
    (setup / "runtime.json").write_text(json.dumps({"version": json.loads((ROOT / "CADWiz/Resources/claude-extension/manifest.json").read_text())["version"], "python": python, "addon": str(ROOT / "CADWiz")}))
    env = dict(os.environ, CADWIZ_SETUP_DIR=str(setup), LOCALAPPDATA=str(tmp_path / "local"), CADWIZ_CLIENT_APP=app)
    # Codex sanitizes these variables; runtime selection must not depend on them.
    # Explicit empty values override the SDK client's inherited defaults.
    env["PROCESSOR_ARCHITECTURE"] = ""
    env["PROCESSOR_ARCHITEW6432"] = ""
    command = shutil.which("node") if app == "claude" else python
    if app == "claude":
        extracted = tmp_path / "packaged-extension"
        with zipfile.ZipFile(ROOT / "CADWiz/Resources/CADWiz.mcpb") as archive:
            assert set(archive.namelist()) == {"launcher.cjs", "manifest.json"}
            for name in archive.namelist():
                source = (ROOT / "CADWiz/Resources/claude-extension" / name).read_bytes().replace(b"\r\n", b"\n")
                assert archive.read(name).replace(b"\r\n", b"\n") == source
            archive.extractall(extracted)
        args = [str(extracted / "launcher.cjs")]
    else:
        args = [str(ROOT / "CADWiz/src/integrations/cadwiz_plugin/offline_launcher.py")]
    async def run():
        async with stdio_client(StdioServerParameters(command=command, args=args, env=env)) as (read, write):
            async with ClientSession(read, write) as client:
                initialized = await client.initialize()
                tools = await client.list_tools()
                status = await client.call_tool("connection_status", {})
                assert not status.isError
                assert isinstance(json.loads(next(c.text for c in status.content if c.type == "text")), dict)
                return initialized, tools
    initialized, tools = asyncio.run(asyncio.wait_for(run(), 90))
    assert initialized.serverInfo.name == "CADWiz"
    assert "inspect_document" in {t.name for t in tools.tools}
    assert list((setup / "helpers").glob("*/mcp/__init__.py"))
    # A clean subprocess restart must reinitialize and expose the same tools.
    restarted, restarted_tools = asyncio.run(asyncio.wait_for(run(), 90))
    assert restarted.serverInfo.name == initialized.serverInfo.name
    assert {t.name for t in restarted_tools.tools} == {t.name for t in tools.tools}
