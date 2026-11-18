from __future__ import annotations

from typing import Any

import pytest

from nas_mcp.access import (
    AccessKeyASGIMiddleware,
    AccessKeyRegistry,
    UnauthorizedError,
    bearer_token,
    current_adult_enabled_value,
    resolve_request_adult_enabled,
)
from nas_mcp.config import Settings


def make_settings(*, adult_enabled: bool = False, access_keys: bool = True) -> Settings:
    return Settings.from_mapping(
        {
            "adult_enabled": adult_enabled,
            "access_keys": [
                {"name": "启用", "key": "key-enabled", "adult_enabled": True},
                {"name": "未启用", "key": "key-disabled", "adult_enabled": False},
                {"name": "继承", "key": "key-inherit"},
            ]
            if access_keys
            else [],
        }
    )


def test_bearer_token() -> None:
    assert bearer_token({"Authorization": "Bearer abc"}) == "abc"
    assert bearer_token({"authorization": "bearer abc"}) == "abc"
    assert bearer_token({"Authorization": "Basic abc"}) is None
    assert bearer_token({"Authorization": "Bearer"}) is None
    assert bearer_token({"Authorization": "Bearer "}) is None
    assert bearer_token(None) is None
    assert bearer_token({}) is None


def test_registry_resolves_hashed_access_keys() -> None:
    registry = AccessKeyRegistry(make_settings())

    assert registry.enabled is True
    assert registry.resolve_token("key-enabled") is not None
    assert registry.resolve_token("key-enabled").name == "启用"  # type: ignore[union-attr]
    assert registry.resolve_token("wrong") is None
    assert registry.resolve_token(None) is None
    assert registry.resolve_headers({"Authorization": "Bearer key-disabled"}) is not None


def test_registry_disabled_without_access_keys() -> None:
    registry = AccessKeyRegistry(make_settings(access_keys=False))
    assert registry.enabled is False
    assert registry.resolve_token("anything") is None


def test_request_adult_permission_tristate() -> None:
    settings = make_settings(adult_enabled=False)
    registry = AccessKeyRegistry(settings)

    def resolve(token: str | None) -> bool:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        return resolve_request_adult_enabled(
            settings,
            registry,
            transport_kind="streamable-http",
            headers=headers,
        )

    assert resolve("key-enabled") is True
    assert resolve("key-disabled") is False
    assert resolve("key-inherit") is False
    with pytest.raises(UnauthorizedError):
        resolve(None)


def test_request_adult_permission_inherits_global() -> None:
    settings = make_settings(adult_enabled=True)
    registry = AccessKeyRegistry(settings)

    assert (
        resolve_request_adult_enabled(
            settings,
            registry,
            transport_kind="streamable-http",
            headers={"Authorization": "Bearer key-inherit"},
        )
        is True
    )
    assert (
        resolve_request_adult_enabled(
            settings,
            registry,
            transport_kind="streamable-http",
            headers={"Authorization": "Bearer key-disabled"},
        )
        is False
    )


def test_request_rejects_invalid_or_missing_key() -> None:
    settings = make_settings()
    registry = AccessKeyRegistry(settings)

    with pytest.raises(UnauthorizedError):
        resolve_request_adult_enabled(
            settings,
            registry,
            transport_kind="streamable-http",
            headers={"Authorization": "Bearer wrong"},
        )
    with pytest.raises(UnauthorizedError):
        resolve_request_adult_enabled(
            settings,
            registry,
            transport_kind="streamable-http",
            headers={},
        )


def test_request_uses_asgi_fallback_for_stateless_http() -> None:
    settings = make_settings()
    registry = AccessKeyRegistry(settings)

    assert (
        resolve_request_adult_enabled(
            settings,
            registry,
            transport_kind="streamable-http",
            headers=None,
            fallback=True,
        )
        is True
    )
    with pytest.raises(UnauthorizedError):
        resolve_request_adult_enabled(
            settings,
            registry,
            transport_kind="streamable-http",
            headers=None,
        )


def test_stdio_uses_global_setting_even_with_access_keys() -> None:
    settings = make_settings(adult_enabled=True)
    registry = AccessKeyRegistry(settings)

    assert (
        resolve_request_adult_enabled(
            settings,
            registry,
            transport_kind="stdio",
            headers=None,
        )
        is True
    )


async def test_asgi_middleware_rejects_missing_and_invalid_keys() -> None:
    registry = AccessKeyRegistry(make_settings())
    called: list[bool] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        called.append(True)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b""}

    async def call(headers: list[tuple[bytes, bytes]]) -> tuple[int, list[dict[str, Any]]]:
        sent: list[dict[str, Any]] = []
        scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": headers}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        middleware = AccessKeyASGIMiddleware(app, registry=registry)
        await middleware(scope, receive, send)  # type: ignore[arg-type]
        return next(
            (message["status"] for message in sent if message["type"] == "http.response.start"),
            0,
        ), sent

    status, sent = await call([])
    assert status == 401
    assert called == []
    assert any(
        header == (b"www-authenticate", b'Bearer realm="nas-mcp"')
        for message in sent
        if message["type"] == "http.response.start"
        for header in message["headers"]
    )

    status, _ = await call([(b"authorization", b"Bearer wrong")])
    assert status == 401
    assert called == []


async def test_asgi_middleware_allows_valid_key_and_sets_permission() -> None:
    registry = AccessKeyRegistry(make_settings())
    seen: list[bool | None] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen.append(current_adult_enabled_value())

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b""}

    sent: list[dict[str, Any]] = []
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"authorization", b"Bearer key-enabled")],
    }

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await AccessKeyASGIMiddleware(app, registry=registry)(scope, receive, send)  # type: ignore[arg-type]

    assert seen == [True]
    assert sent == []


async def test_asgi_middleware_is_transparent_without_access_keys() -> None:
    registry = AccessKeyRegistry(make_settings(access_keys=False))
    called: list[bool] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        called.append(True)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b""}

    async def send(message: dict[str, Any]) -> None:
        pass

    scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": []}
    await AccessKeyASGIMiddleware(app, registry=registry)(scope, receive, send)  # type: ignore[arg-type]

    assert called == [True]
