"""HTTP access key 鉴权和成人内容权限。"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import AccessKeyConfig, Settings
from .logging_setup import new_call_id

logger = logging.getLogger(__name__)

_current_adult_enabled: ContextVar[bool | None] = ContextVar("nas_mcp_adult_enabled", default=None)


class UnauthorizedError(Exception):
    """请求缺少有效 access key。"""


class AccessKeyRegistry:
    """按 access key 查找权限，避免在内存中做明文比较。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._keys = {
            hashlib.sha256(access_key.key.encode("utf-8")).digest(): access_key
            for access_key in settings.access_keys
        }

    @property
    def enabled(self) -> bool:
        return bool(self._keys)

    def resolve_token(self, token: str | None) -> AccessKeyConfig | None:
        if not token:
            return None
        return self._keys.get(hashlib.sha256(token.encode("utf-8")).digest())

    def resolve_headers(self, headers: Mapping[str, str] | None) -> AccessKeyConfig | None:
        return self.resolve_token(bearer_token(headers))

    def adult_enabled_for(self, access_key: AccessKeyConfig | None) -> bool:
        return self._settings.adult_enabled_for(access_key)


def bearer_token(headers: Mapping[str, str] | None) -> str | None:
    if not headers:
        return None
    value = next(
        (item for name, item in headers.items() if name.lower() == "authorization"),
        None,
    )
    if not value:
        return None
    scheme, separator, token = value.strip().partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def current_adult_enabled(default: bool) -> bool:
    """读取本次请求的成人内容权限；没有请求上下文时使用全局默认值。"""
    value = _current_adult_enabled.get()
    return default if value is None else value


def current_adult_enabled_value() -> bool | None:
    return _current_adult_enabled.get()


@contextmanager
def adult_enabled_scope(value: bool) -> Iterator[None]:
    token: Token[bool | None] = _current_adult_enabled.set(value)
    try:
        yield
    finally:
        _current_adult_enabled.reset(token)


def resolve_request_adult_enabled(
    settings: Settings,
    registry: AccessKeyRegistry,
    *,
    transport_kind: str,
    headers: Mapping[str, str] | None,
    fallback: bool | None = None,
) -> bool:
    """计算单次 HTTP 请求的成人内容权限，无效 access key 时拒绝请求。"""
    if transport_kind != "streamable-http":
        return settings.adult_enabled
    if not registry.enabled:
        return settings.adult_enabled

    access_key = registry.resolve_headers(headers)
    if access_key is not None:
        return settings.adult_enabled_for(access_key)
    # 某些传输不在消息层暴露 headers，此时使用 ASGI 层已经解析出的权限。
    if headers is None and fallback is not None:
        return fallback
    raise UnauthorizedError


class AccessKeyASGIMiddleware:
    """在 HTTP 传输层校验 Bearer access key，并记录本次请求的成人内容权限。"""

    def __init__(self, app: ASGIApp, *, registry: AccessKeyRegistry) -> None:
        self.app = app
        self.registry = registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.registry.enabled or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        access_key = self.registry.resolve_headers(_scope_headers(scope))
        if access_key is None:
            logger.warning(
                "request_rejected call_id=%s reason=unauthorized transport=streamable-http",
                new_call_id(),
            )
            response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="nas-mcp"'},
            )
            await response(scope, receive, send)
            return

        token: Token[bool | None] = _current_adult_enabled.set(
            self.registry.adult_enabled_for(access_key)
        )
        try:
            await self.app(scope, receive, send)
        finally:
            _current_adult_enabled.reset(token)


def _scope_headers(scope: Scope) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in scope.get("headers", []):
        headers[name.decode("latin-1").lower()] = value.decode("latin-1")
    return headers
