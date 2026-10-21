# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The connector Claude Desktop starts answers a real MCP handshake.

Starts `CADWiz/src/integrations/cadwiz_plugin/server.py` as its own process --
exactly as Claude Desktop does -- and talks to it with the MCP SDK's own client
over stdio: initialize, then list the tools. No FreeCAD, no network, no AI.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1] / "CADWiz" / "src" / "integrations" / "cadwiz_plugin" / "server.py"


def test_the_connector_answers_an_mcp_handshake_and_lists_its_tools() -> None:
    mcp = pytest.importorskip("mcp")
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def handshake() -> tuple[str, set[str]]:
        params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
        async with stdio_client(params) as (read, write):
            async with mcp.ClientSession(read, write) as session:
                started = await session.initialize()
                tools = await session.list_tools()
                return started.serverInfo.name, {tool.name for tool in tools.tools}

    name, tools = asyncio.run(asyncio.wait_for(handshake(), timeout=60))
    assert name == "CADWiz"
    assert {"inspect_document", "build_model", "render", "versions", "user_preferences",
            "cadwiz_known_issues", "cadwiz_send_feedback"} <= tools
    assert not any("delete" in tool or "remove" in tool for tool in tools)
