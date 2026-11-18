"""MCP 工具入口。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import replace
from functools import lru_cache
from typing import Any

from mcp.server import MCPServer
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from starlette.applications import Starlette

from .access import (
    AccessKeyASGIMiddleware,
    AccessKeyRegistry,
    UnauthorizedError,
    adult_enabled_scope,
    current_adult_enabled_value,
    resolve_request_adult_enabled,
)
from .config import Settings
from .errors import ConfigError, NasMcpError
from .service import NasService

_INSTRUCTIONS = (
    "NAS 下载助手：搜索 PT 种子并推送到 qBittorrent。"
    "固定流程：search_torrents → 用户确认 → download_torrents → list_downloads。"
    "用户指定 qBittorrent 分类时，先用 list_download_categories 查询，再传给 download_torrents。"
    "配置或连接问题使用 get_config_status。"
    "不要编造种子 ID，不要向用户展示 API Key、密码、access key 或临时下载地址。"
    "download_torrents 只在服务端内部获取种子并上传，不会返回种子文件。"
)

_settings: Settings | None = None
_registry: AccessKeyRegistry | None = None


def get_settings() -> Settings:
    """首次使用时读取 config.yaml。"""
    global _settings
    if _settings is None:
        _settings = Settings.load()
    return _settings


def _apply_instructions(settings: Settings) -> None:
    """把部署者自定义要求追加到 initialize 响应的 instructions。"""
    extra = settings.extra_instructions.strip()
    text = _INSTRUCTIONS
    if extra:
        # 自定义要求放在内置规则之后，避免被固定流程淹没
        text = f"{_INSTRUCTIONS}\n\n以下为部署者配置的自定义要求，请优先遵循：\n{extra}"
    # MCPServer 的 instructions 是只读属性，实际字段在底层 Server 上
    mcp._lowlevel_server.instructions = text


def configure_settings(settings: Settings) -> None:
    """启动时固定配置，供工具和 HTTP 中间件共用。"""
    global _settings, _registry
    _settings = settings
    _registry = AccessKeyRegistry(settings)
    _apply_instructions(settings)
    get_service.cache_clear()


def get_registry() -> AccessKeyRegistry:
    global _registry
    if _registry is None:
        _registry = AccessKeyRegistry(get_settings())
    return _registry


class AdultAccessMiddleware:
    """按每次 HTTP 请求的 access key 设置成人内容权限。"""

    async def __call__(
        self,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        # stdio 和进程内客户端没有 HTTP 请求，直接使用全局配置。
        request = ctx.request
        if request is None:
            return await call_next(ctx)
        try:
            adult_enabled = resolve_request_adult_enabled(
                get_settings(),
                get_registry(),
                transport_kind="streamable-http",
                headers=request.headers,
                fallback=current_adult_enabled_value(),
            )
        except UnauthorizedError as exc:
            raise MCPError(code=-32001, message="Unauthorized") from exc
        with adult_enabled_scope(adult_enabled):
            return await call_next(ctx)


mcp = MCPServer(
    "nas-mcp",
    instructions=_INSTRUCTIONS,
    middleware=[AdultAccessMiddleware()],
)


@lru_cache(maxsize=1)
def get_service() -> NasService:
    """首次调用工具时读取配置并构建服务，便于测试时清空缓存。"""
    try:
        return NasService.from_settings(get_settings())
    except ConfigError as exc:
        raise NasMcpError(str(exc)) from exc


@mcp.tool()
async def search_torrents(
    keyword: str,
    page: int = 1,
    page_size: int = 20,
    categories: list[str] | None = None,
    sort_by: str = "seeders",
) -> dict[str, Any]:
    """搜索 PT 站种子。

    用户要查找电影、剧集、动画等资源时使用。返回结果中的 id 是后续
    download_torrents 的输入。

    Args:
        keyword: 搜索关键词，也可以是 IMDb/豆瓣链接。
        page: 页码，从 1 开始。
        page_size: 每页数量，1 到 50。
        categories: 可选分类，可传中文名（电影、剧集、动画等）或分类 ID。
        sort_by: 排序方式：time、seeders、leechers、size、completed。
    """
    try:
        return await get_service().search_torrents(
            keyword=keyword,
            page=page,
            page_size=page_size,
            categories=categories,
            sort_by=sort_by,
        )
    except NasMcpError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def download_torrents(
    torrent_ids: list[str],
    category: str | None = None,
) -> dict[str, Any]:
    """把 PT 种子添加到 qBittorrent 下载。

    torrent_ids 来自 search_torrents 返回的 id，可一次传多个。
    可选 category 应来自 list_download_categories；未指定时使用配置的默认分类。
    服务端会获取 .torrent 并直接上传到 qBittorrent，不保存、不返回种子文件。
    """
    try:
        return await get_service().download_torrents(torrent_ids, category=category)
    except NasMcpError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def list_download_categories() -> dict[str, Any]:
    """列出 qBittorrent 中已有的分类，供 download_torrents 的 category 参数选择。"""
    try:
        return await get_service().list_download_categories()
    except NasMcpError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def list_downloads(
    status: str = "all",
    hash: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """查看 qBittorrent 下载和做种进度。

    不传 hash 时返回任务列表和汇总；传 hash 时查看单个任务。
    status 可选 all、downloading、seeding、completed、stopped、error，也接受中文。
    limit 控制返回任务数量，1 到 200。
    """
    try:
        return await get_service().list_downloads(
            status=status,
            torrent_hash=hash,
            limit=limit,
        )
    except NasMcpError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def get_config_status(check_connectivity: bool = False) -> dict[str, Any]:
    """检查 M-Team 和 qBittorrent 的配置状态。

    默认只检查环境变量是否完整，不发起网络请求。
    check_connectivity=true 时会验证 M-Team API Key、qBittorrent 登录和分类，
    可能稍慢。用户首次配置、询问配置或排查连接问题时使用。
    """
    try:
        return await get_service().get_config_status(check_connectivity=check_connectivity)
    except NasMcpError as exc:
        raise ToolError(str(exc)) from exc


def _print_check(status: dict[str, Any], settings: Settings) -> int:
    source = str(settings.config_path) if settings.config_path is not None else "未找到，使用默认值"
    print(f"配置文件：{source}")
    if settings.env_overrides:
        print(f"环境变量：{', '.join(settings.env_overrides)}")
    healthy = bool(status.get("ready"))
    print(f"NAS MCP: {'就绪' if healthy else '未就绪'}")

    for site in status.get("pt_sites", []):
        connectivity = site.get("connectivity")
        if not site.get("enabled"):
            healthy = False
            print(f"[FAIL] {site.get('name', site.get('id'))}: 未配置 mteam.api_key")
            continue
        if isinstance(connectivity, dict):
            ok = bool(connectivity.get("ok"))
            healthy = healthy and ok
            mark = "OK" if ok else "FAIL"
            print(f"[{mark}] {site.get('name', site.get('id'))}: {connectivity.get('message', '')}")
        else:
            print(f"[OK] {site.get('name', site.get('id'))}: 已配置")

    for downloader in status.get("downloaders", []):
        connectivity = downloader.get("connectivity")
        if not downloader.get("enabled"):
            healthy = False
            print(f"[FAIL] {downloader.get('name', downloader.get('id'))}: 未配置 qbittorrent.url")
            continue
        if isinstance(connectivity, dict):
            ok = bool(connectivity.get("ok"))
            healthy = healthy and ok
            mark = "OK" if ok else "FAIL"
            details = [str(connectivity.get("message", ""))]
            if connectivity.get("version"):
                details.append(f"版本 {connectivity['version']}")
            if connectivity.get("category_exists") is False:
                details.append("配置的分类不存在，添加任务时会尝试创建")
            print(
                f"[{mark}] {downloader.get('name', downloader.get('id'))}: "
                + "，".join(part for part in details if part)
            )
        else:
            print(f"[OK] {downloader.get('name', downloader.get('id'))}: 已配置")

    for item in status.get("missing", []):
        print(f"缺失配置: {item}")
    for warning in status.get("warnings", []):
        print(f"警告: {warning}")

    return 0 if healthy else 1


def create_http_app(settings: Settings) -> Starlette:
    """构建带 access key 鉴权的 Streamable HTTP 应用。"""
    configure_settings(settings)
    app = mcp.streamable_http_app(host=settings.host)
    app.add_middleware(
        AccessKeyASGIMiddleware,
        registry=AccessKeyRegistry(settings),
    )
    return app


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nas-mcp", description="PT 搜索与 qBittorrent 下载 MCP")
    parser.add_argument("--config", help="配置文件路径，默认 config.yaml")
    parser.add_argument("--check", action="store_true", help="检查配置和连接后退出")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        help="覆盖 mcp.transport",
    )
    parser.add_argument("--host", help="覆盖 mcp.host")
    parser.add_argument("--port", type=int, help="覆盖 mcp.port")
    args = parser.parse_args(argv)

    try:
        settings = Settings.load(args.config)
        if args.transport:
            settings = replace(settings, transport=args.transport)
        if args.host:
            settings = replace(settings, host=args.host)
        if args.port is not None:
            if not 1 <= args.port <= 65535:
                raise ConfigError(f"mcp.port 超出范围：{args.port}")
            settings = replace(settings, port=args.port)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    configure_settings(settings)

    if args.check:
        service = NasService.from_settings(settings)
        status = asyncio.run(service.get_config_status(check_connectivity=True))
        return _print_check(status, settings)

    if settings.transport == "streamable-http":
        import uvicorn

        uvicorn.run(create_http_app(settings), host=settings.host, port=settings.port)
    else:
        mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
