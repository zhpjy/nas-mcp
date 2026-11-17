from __future__ import annotations

from typing import Any

from mcp import Client

from nas_mcp import server as server_module
from nas_mcp.server import mcp


async def test_tool_surface() -> None:
    async with Client(mcp) as client:
        result = await client.list_tools()

    names = {tool.name for tool in result.tools}
    assert names == {
        "search_torrents",
        "download_torrents",
        "list_download_categories",
        "list_downloads",
        "get_config_status",
    }


class FakeService:
    async def get_config_status(self, check_connectivity: bool = False) -> dict[str, Any]:
        return {
            "ready": False,
            "check_connectivity": check_connectivity,
            "missing": ["MTEAM_API_KEY"],
        }


async def test_get_config_status_tool(monkeypatch: Any) -> None:
    monkeypatch.setattr(server_module, "get_service", lambda: FakeService())

    async with Client(mcp) as client:
        result = await client.call_tool("get_config_status", {"check_connectivity": True})

    assert result.structured_content is not None
    assert result.structured_content["ready"] is False
    assert result.structured_content["check_connectivity"] is True
