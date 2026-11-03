# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real MCP protocol through both packaged launch paths; no assistant/model calls."""
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("app", ["claude", "chatgpt"])
def test_desktop_launch_path_is_real_mcp_with_private_helpers(app, tmp_path):
    python = os.environ.get("CADWIZ_TEST_FREECAD_PYTHON")
    if not python:
        pytest.skip("Requires explicit FreeCAD Python path; CI's offline helper check runs separately")
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    setup = tmp_path / "private"
    setup.mkdir()
    (setup / "runtime.json").write_text(json.dumps({"version": "0.6.0", "python": python, "addon": str(ROOT / "CADWiz")}))
    env = dict(os.environ, CADWIZ_SETUP_DIR=str(setup), LOCALAPPDATA=str(tmp_path / "local"), CADWIZ_CLIENT_APP=app)
    command = shutil.which("node") if app == "claude" else python
    args = [str(ROOT / "CADWiz/Resources/claude-extension/launcher.cjs")] if app == "claude" else [str(ROOT / "CADWiz/src/integrations/cadwiz_plugin/offline_launcher.py")]
    async def run():
        async with stdio_client(StdioServerParameters(command=command, args=args, env=env)) as (read, write):
            async with ClientSession(read, write) as client:
                initialized = await client.initialize()
                tools = await client.list_tools()
                return initialized, tools
    initialized, tools = asyncio.run(asyncio.wait_for(run(), 90))
    assert initialized.serverInfo.name == "CADWiz"
    assert "inspect_document" in {t.name for t in tools.tools}
    assert list((setup / "helpers").glob("*/mcp/__init__.py"))
