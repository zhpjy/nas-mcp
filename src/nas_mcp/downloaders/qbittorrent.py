"""qBittorrent WebUI API 下载器。"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2

from ..config import QBittorrentConfig
from ..errors import DownloaderError
from ..formatting import state_label
from ..models import AddOutcome, DownloadTask, TorrentFile
from .base import Downloader

_QB_ETA_INFINITY = 8_640_000


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class QBittorrentDownloader(Downloader):
    """通过 qBittorrent WebUI API 管理任务。"""

    id = "qbittorrent"
    display_name = "qBittorrent"

    def __init__(
        self,
        config: QBittorrentConfig,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Referer": f"{self.config.url}/",
            "Origin": self.config.url,
        }
        if self.config.basic_auth is not None:
            credentials = ":".join(self.config.basic_auth).encode("utf-8")
            encoded_credentials = base64.b64encode(credentials).decode("ascii")
            headers["Authorization"] = f"Basic {encoded_credentials}"
        return headers

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx2.AsyncClient]:
        if not self.enabled:
            raise DownloaderError(
                "未配置 QBITTORRENT_URL，请先在 .env 中设置 qBittorrent WebUI 地址"
            )
        async with httpx2.AsyncClient(
            base_url=self.config.url,
            headers=self._headers(),
            timeout=self.config.timeout,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            # Basic Auth 模式直接发送认证头；否则使用 qBittorrent 登录接口。
            if not self.config.use_basic_auth and (self.config.username or self.config.password):
                await self._login(client)
            yield client

    async def _login(self, client: httpx2.AsyncClient) -> None:
        try:
            response = await client.post(
                "api/v2/auth/login",
                data={
                    "username": self.config.username,
                    "password": self.config.password,
                },
            )
        except httpx2.HTTPError as exc:
            raise DownloaderError(f"无法连接 qBittorrent：{exc}") from exc

        if response.status_code in {401, 403}:
            raise DownloaderError("qBittorrent 拒绝登录：凭据无效或 IP 可能已被封禁")
        if response.status_code >= 400:
            raise DownloaderError(
                f"qBittorrent 登录失败：HTTP {response.status_code} {response.text[:200]}"
            )
        body = response.text.strip()
        if body and body.lower() not in {"ok.", "ok"}:
            raise DownloaderError("qBittorrent 登录失败，请检查用户名和密码")

    async def _request(
        self,
        client: httpx2.AsyncClient,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx2.Response:
        try:
            response = await client.request(method, path, **kwargs)
        except httpx2.HTTPError as exc:
            raise DownloaderError(f"无法连接 qBittorrent：{exc}") from exc

        # 用户名密码会话过期时重新登录；Basic Auth 不使用登录会话。
        if (
            response.status_code == 403
            and not self.config.use_basic_auth
            and (self.config.username or self.config.password)
        ):
            await self._login(client)
            try:
                response = await client.request(method, path, **kwargs)
            except httpx2.HTTPError as exc:
                raise DownloaderError(f"无法连接 qBittorrent：{exc}") from exc
        return response

    def _check(self, response: httpx2.Response, context: str) -> None:
        if response.status_code in {401, 403}:
            if self.config.use_basic_auth:
                raise DownloaderError(f"{context}：qBittorrent Basic Auth 凭据无效或无权限")
            if self.config.username or self.config.password:
                raise DownloaderError(
                    f"{context}：qBittorrent 拒绝访问，登录可能已失效或 IP 被封禁"
                )
            raise DownloaderError(
                f"{context}：qBittorrent 需要认证，请配置 QBITTORRENT_BASIC_AUTH "
                "或 QBITTORRENT_USERNAME/QBITTORRENT_PASSWORD"
            )
        if response.status_code == 404:
            raise DownloaderError(f"{context}：qBittorrent 接口不存在，请确认 WebUI API 版本")
        if response.status_code >= 400:
            detail = response.text[:300].strip()
            raise DownloaderError(f"{context}：HTTP {response.status_code} {detail}".strip())

    async def _get_categories(self, client: httpx2.AsyncClient) -> dict[str, Any]:
        response = await self._request(client, "GET", "api/v2/torrents/categories")
        self._check(response, "读取 qBittorrent 分类失败")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DownloaderError("qBittorrent 返回的分类不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise DownloaderError("qBittorrent 返回的分类格式不符合预期")
        return payload

    async def _ensure_category(self, client: httpx2.AsyncClient, category: str) -> None:
        if not category:
            return
        categories = await self._get_categories(client)
        if category in categories:
            return
        response = await self._request(
            client,
            "POST",
            "api/v2/torrents/createCategory",
            data={"category": category},
        )
        if response.status_code == 409:
            return
        self._check(response, f"创建 qBittorrent 分类 {category!r} 失败")

    async def list_categories(self) -> list[str]:
        async with self._client() as client:
            categories = await self._get_categories(client)
        return sorted(categories, key=str.casefold)

    async def add_torrent(
        self,
        torrent: TorrentFile,
        category: str | None = None,
    ) -> AddOutcome:
        if category is not None:
            category = category.strip()
            if not category:
                raise DownloaderError("分类名不能为空")
        selected_category = self.config.category if category is None else category
        async with self._client() as client:
            if category is None:
                await self._ensure_category(client, selected_category)

            data: dict[str, str] = {
                "paused": "false",
                "stopped": "false",
            }
            if selected_category:
                data["category"] = selected_category
            if self.config.tags:
                data["tags"] = ",".join(self.config.tags)
            if self.config.save_path:
                data["savepath"] = self.config.save_path
                # 指定保存路径时关闭自动 Torrent 管理，避免被分类路径覆盖。
                data["autoTMM"] = "false"

            response = await self._request(
                client,
                "POST",
                "api/v2/torrents/add",
                data=data,
                files={
                    "torrents": (
                        torrent.filename,
                        torrent.content,
                        "application/x-bittorrent",
                    )
                },
            )
            self._check(response, "添加 qBittorrent 任务失败")
            body = response.text.strip()
            if body.lower().startswith("fail"):
                raise DownloaderError(f"qBittorrent 拒绝添加任务：{body}")

        return AddOutcome(
            name=torrent.name,
            infohash=torrent.infohash,
            message="已添加到 qBittorrent",
        )

    async def list_torrents(self) -> list[DownloadTask]:
        async with self._client() as client:
            response = await self._request(client, "GET", "api/v2/torrents/info")
            self._check(response, "读取 qBittorrent 任务失败")
            try:
                payload = response.json()
            except ValueError as exc:
                raise DownloaderError("qBittorrent 返回的任务列表不是有效 JSON") from exc

        if not isinstance(payload, list):
            raise DownloaderError("qBittorrent 返回的任务列表格式不符合预期")
        return [self._to_task(raw) for raw in payload if isinstance(raw, dict)]

    @staticmethod
    def _to_task(raw: dict[str, Any]) -> DownloadTask:
        raw_state = str(raw.get("state") or "unknown")
        normalized_state, label = state_label(raw_state)
        progress = round(_as_float(raw.get("progress")) * 100, 1)
        size_bytes = _as_int(raw.get("size"))
        downloaded = _as_int(raw.get("downloaded"))
        if downloaded <= 0 and size_bytes > 0:
            downloaded = int(size_bytes * progress / 100)
        eta = _as_int(raw.get("eta"), -1)
        if eta < 0 or eta >= _QB_ETA_INFINITY:
            eta_value: int | None = None
        else:
            eta_value = eta
        return DownloadTask(
            hash=str(raw.get("hash") or ""),
            name=str(raw.get("name") or ""),
            state=normalized_state,
            state_label=label,
            progress=progress,
            size_bytes=size_bytes,
            downloaded_bytes=downloaded,
            dlspeed=_as_int(raw.get("dlspeed")),
            upspeed=_as_int(raw.get("upspeed")),
            eta_seconds=eta_value,
            ratio=_as_float(raw.get("ratio")),
            category=str(raw.get("category") or ""),
            added_on=_as_int(raw.get("added_on")),
            error=str(raw.get("error") or ""),
        )

    async def check_connectivity(self) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "message": "未配置 QBITTORRENT_URL"}
        try:
            async with self._client() as client:
                version_response = await self._request(client, "GET", "api/v2/app/version")
                self._check(version_response, "读取 qBittorrent 版本失败")
                categories = await self._get_categories(client)
        except DownloaderError as exc:
            return {"ok": False, "message": str(exc)}

        category_exists = not self.config.category or self.config.category in categories
        return {
            "ok": True,
            "message": "已连接",
            "version": version_response.text.strip(),
            "category_exists": category_exists,
        }

    def status_info(self) -> dict[str, Any]:
        if self.config.use_basic_auth:
            auth_mode = "basic"
        elif self.config.username or self.config.password:
            auth_mode = "password"
        else:
            auth_mode = "none"
        return {
            "id": self.id,
            "name": self.display_name,
            "enabled": self.enabled,
            "url": self.config.url,
            "auth_mode": auth_mode,
            "basic_auth_configured": self.config.use_basic_auth,
            "username_configured": bool(self.config.username),
            "password_configured": bool(self.config.password),
            "save_path": self.config.save_path,
            "category": self.config.category,
            "tags": list(self.config.tags),
        }
