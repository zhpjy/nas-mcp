from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError

from nas_mcp import server as server_module
from nas_mcp.access import AccessKeyRegistry, current_adult_enabled
from nas_mcp.config import Settings
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
    schema = json.dumps([tool.model_dump() for tool in result.tools], ensure_ascii=False).lower()
    assert "adult" not in schema
    assert "access_key" not in schema


class FakeService:
    async def get_config_status(self, check_connectivity: bool = False) -> dict[str, Any]:
        return {
            "ready": False,
            "check_connectivity": check_connectivity,
            "missing": ["mteam.api_key"],
        }


async def test_get_config_status_tool(monkeypatch: Any) -> None:
    monkeypatch.setattr(server_module, "get_service", lambda: FakeService())

    async with Client(mcp) as client:
        result = await client.call_tool("get_config_status", {"check_connectivity": True})

    assert result.structured_content is not None
    assert result.structured_content["ready"] is False
    assert result.structured_content["check_connectivity"] is True


async def test_adult_access_middleware_scopes_request_permission(monkeypatch: Any) -> None:
    settings = Settings.from_mapping(
        {
            "adult_enabled": False,
            "access_keys": [
                {"name": "启用", "key": "enabled", "adult_enabled": True},
                {"name": "继承", "key": "inherit"},
            ],
        }
    )
    registry = AccessKeyRegistry(settings)
    monkeypatch.setattr(server_module, "get_settings", lambda: settings)
    monkeypatch.setattr(server_module, "get_registry", lambda: registry)

    seen: list[bool] = []

    async def call_next(ctx: Any) -> dict[str, Any]:
        seen.append(current_adult_enabled(False))
        return {"ok": True}

    middleware = server_module.AdultAccessMiddleware()
    ctx = SimpleNamespace(request=SimpleNamespace(headers={"Authorization": "Bearer enabled"}))
    result = await middleware(ctx, call_next)  # type: ignore[arg-type]
    assert result == {"ok": True}
    assert seen == [True]

    ctx = SimpleNamespace(request=SimpleNamespace(headers={"Authorization": "Bearer inherit"}))
    await middleware(ctx, call_next)  # type: ignore[arg-type]
    assert seen == [True, False]


async def test_adult_access_middleware_rejects_invalid_key(monkeypatch: Any) -> None:
    settings = Settings.from_mapping(
        {"access_keys": [{"name": "启用", "key": "enabled"}]},
    )
    registry = AccessKeyRegistry(settings)
    monkeypatch.setattr(server_module, "get_settings", lambda: settings)
    monkeypatch.setattr(server_module, "get_registry", lambda: registry)

    async def call_next(ctx: Any) -> dict[str, Any]:
        raise AssertionError("call_next should not run")

    ctx = SimpleNamespace(request=SimpleNamespace(headers={"Authorization": "Bearer wrong"}))
    with pytest.raises(MCPError):
        await server_module.AdultAccessMiddleware()(ctx, call_next)  # type: ignore[arg-type]
