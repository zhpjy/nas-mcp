"""搜索、下载、进度和配置检查的编排层。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from .config import Settings
from .downloaders import build_downloaders
from .downloaders.base import Downloader
from .errors import ConfigError, NasMcpError
from .formatting import (
    human_speed,
    normalize_status_filter,
    state_priority,
)
from .models import DownloadTask
from .providers import build_providers
from .providers.base import PTProvider

_ALLOWED_STATUS = "all、downloading、seeding、completed、stopped、error"


class NasService:
    """把 PT 提供者和下载器组合成 MCP 工具需要的操作。"""

    def __init__(
        self,
        providers: Mapping[str, PTProvider],
        downloaders: Mapping[str, Downloader],
        default_site: str,
        default_downloader: str,
    ) -> None:
        self.providers = dict(providers)
        self.downloaders = dict(downloaders)
        self.default_site = default_site
        self.default_downloader = default_downloader

    @classmethod
    def from_settings(cls, settings: Settings) -> NasService:
        return cls(
            providers=build_providers(settings),
            downloaders=build_downloaders(settings),
            default_site=settings.default_site,
            default_downloader=settings.default_downloader,
        )

    def _provider(self) -> PTProvider:
        if self.default_site:
            provider = self.providers.get(self.default_site)
            if provider is None:
                raise ConfigError(
                    f"PT_DEFAULT_SITE={self.default_site!r} 未注册，"
                    f"可用站点：{', '.join(self.providers) or '无'}"
                )
            if not provider.enabled:
                raise ConfigError(f"PT 站 {self.default_site!r} 未配置，请先设置 MTEAM_API_KEY")
            return provider

        for provider in self.providers.values():
            if provider.enabled:
                return provider
        raise ConfigError("没有可用的 PT 站，请先设置 MTEAM_API_KEY")

    def _downloader(self) -> Downloader:
        if self.default_downloader:
            downloader = self.downloaders.get(self.default_downloader)
            if downloader is None:
                raise ConfigError(
                    f"DOWNLOADER_DEFAULT={self.default_downloader!r} 未注册，"
                    f"可用下载器：{', '.join(self.downloaders) or '无'}"
                )
            if not downloader.enabled:
                raise ConfigError(
                    f"下载器 {self.default_downloader!r} 未配置，请先设置 QBITTORRENT_URL"
                )
            return downloader

        for downloader in self.downloaders.values():
            if downloader.enabled:
                return downloader
        raise ConfigError("没有可用的下载器，请先设置 QBITTORRENT_URL")

    async def search_torrents(
        self,
        keyword: str,
        page: int,
        page_size: int,
        categories: list[str] | None,
        sort_by: str,
    ) -> dict[str, Any]:
        keyword = keyword.strip()
        if not keyword:
            raise NasMcpError("搜索关键词不能为空")
        if page < 1:
            raise NasMcpError("page 必须大于等于 1")
        if not 1 <= page_size <= 50:
            raise NasMcpError("page_size 必须在 1 到 50 之间")
        provider = self._provider()
        result = await provider.search(
            keyword=keyword,
            page=page,
            page_size=page_size,
            categories=categories,
            sort_by=sort_by,
        )
        return result.to_dict()

    async def download_torrents(
        self,
        torrent_ids: list[str],
        category: str | None = None,
    ) -> dict[str, Any]:
        if category is not None:
            category = category.strip()
            if not category:
                raise NasMcpError("category 不能为空")

        ids: list[str] = []
        seen: set[str] = set()
        for raw in torrent_ids:
            torrent_id = str(raw).strip()
            if not torrent_id or torrent_id in seen:
                continue
            seen.add(torrent_id)
            ids.append(torrent_id)
        if not ids:
            raise NasMcpError("torrent_ids 不能为空")

        provider = self._provider()
        downloader = self._downloader()

        # 先校验全部 ID，避免批量任务只执行一半才发现格式错误。
        for torrent_id in ids:
            provider.validate_torrent_id(torrent_id)

        if category is not None:
            categories = await downloader.list_categories()
            if category not in categories:
                available = ", ".join(categories) or "无"
                raise NasMcpError(f"qBittorrent 分类 {category!r} 不存在，可用分类：{available}")

        results: list[dict[str, Any]] = []
        for torrent_id in ids:
            torrent = None
            try:
                torrent = await provider.download(torrent_id)
                outcome = await downloader.add_torrent(torrent, category=category)
            except NasMcpError as exc:
                results.append(
                    {
                        "torrent_id": torrent_id,
                        "ok": False,
                        "hash": torrent.infohash if torrent else None,
                        "name": torrent.name if torrent else None,
                        "message": str(exc),
                    }
                )
            else:
                results.append(
                    {
                        "torrent_id": torrent_id,
                        "ok": True,
                        "hash": outcome.infohash,
                        "name": outcome.name,
                        "message": outcome.message,
                    }
                )

        return {
            "ok": all(result["ok"] for result in results),
            "results": results,
        }

    async def list_download_categories(self) -> dict[str, Any]:
        downloader = self._downloader()
        categories = await downloader.list_categories()
        return {"categories": categories}

    async def list_downloads(
        self,
        status: str,
        torrent_hash: str | None,
        limit: int,
    ) -> dict[str, Any]:
        status_key = normalize_status_filter(status)
        if not status_key:
            raise NasMcpError(f"不支持的状态：{status!r}，可用值：{_ALLOWED_STATUS}")
        if not 1 <= limit <= 200:
            raise NasMcpError("limit 必须在 1 到 200 之间")

        downloader = self._downloader()
        tasks = await downloader.list_torrents()
        summary = self._summary(tasks)

        if torrent_hash and torrent_hash.strip():
            target = torrent_hash.strip().lower()
            matched = [task for task in tasks if task.hash.lower() == target]
            selected = matched[:1]
            message = None if matched else f"未找到 hash 为 {torrent_hash} 的下载任务"
        else:
            selected = self._filter_tasks(tasks, status_key)
            selected.sort(key=lambda task: (state_priority(task.state), -task.added_on, task.name))
            selected = selected[:limit]
            message = None

        result: dict[str, Any] = {
            "summary": summary,
            "count": len(selected),
            "torrents": [task.to_dict() for task in selected],
        }
        if message:
            result["message"] = message
        return result

    @staticmethod
    def _filter_tasks(tasks: list[DownloadTask], status: str) -> list[DownloadTask]:
        if status == "all":
            return list(tasks)
        if status == "completed":
            return [task for task in tasks if task.progress >= 100]
        return [task for task in tasks if task.state == status]

    @staticmethod
    def _summary(tasks: list[DownloadTask]) -> dict[str, Any]:
        return {
            "total": len(tasks),
            "downloading": sum(1 for task in tasks if task.state == "downloading"),
            "queued": sum(1 for task in tasks if task.state == "queued"),
            "seeding": sum(1 for task in tasks if task.state == "seeding"),
            "stopped": sum(1 for task in tasks if task.state == "stopped"),
            "error": sum(1 for task in tasks if task.state == "error"),
            "download_speed": human_speed(sum(task.dlspeed for task in tasks)),
            "upload_speed": human_speed(sum(task.upspeed for task in tasks)),
        }

    async def get_config_status(self, check_connectivity: bool = False) -> dict[str, Any]:
        provider_checks: list[dict[str, Any] | None] = [None] * len(self.providers)
        downloader_checks: list[dict[str, Any] | None] = [None] * len(self.downloaders)

        if check_connectivity:
            provider_results = await asyncio.gather(
                *(provider.check_connectivity() for provider in self.providers.values()),
                return_exceptions=True,
            )
            downloader_results = await asyncio.gather(
                *(downloader.check_connectivity() for downloader in self.downloaders.values()),
                return_exceptions=True,
            )
            provider_checks = [self._safe_check(result) for result in provider_results]
            downloader_checks = [self._safe_check(result) for result in downloader_results]

        providers = []
        for provider, check in zip(self.providers.values(), provider_checks, strict=True):
            info = provider.status_info()
            info["is_default"] = provider.id == self.default_site
            info["connectivity"] = check
            providers.append(info)

        downloaders = []
        for downloader, check in zip(self.downloaders.values(), downloader_checks, strict=True):
            info = downloader.status_info()
            info["is_default"] = downloader.id == self.default_downloader
            info["connectivity"] = check
            downloaders.append(info)

        missing: list[str] = []
        warnings: list[str] = []
        if not any(provider.enabled for provider in self.providers.values()):
            missing.append("MTEAM_API_KEY")
        if not any(downloader.enabled for downloader in self.downloaders.values()):
            missing.append("QBITTORRENT_URL")

        if self.default_site:
            default_provider = self.providers.get(self.default_site)
            if default_provider is None:
                warnings.append(f"PT_DEFAULT_SITE={self.default_site!r} 未注册")
            elif not default_provider.enabled:
                warnings.append(f"PT_DEFAULT_SITE={self.default_site!r} 缺少必要配置")
        if self.default_downloader:
            default_downloader = self.downloaders.get(self.default_downloader)
            if default_downloader is None:
                warnings.append(f"DOWNLOADER_DEFAULT={self.default_downloader!r} 未注册")
            elif not default_downloader.enabled:
                warnings.append(f"DOWNLOADER_DEFAULT={self.default_downloader!r} 缺少必要配置")

        qbt = self.downloaders.get("qbittorrent")
        if qbt is not None:
            qbt_info = qbt.status_info()
            if (
                qbt_info["username_configured"]
                and not qbt_info["password_configured"]
                and not qbt_info["basic_auth_configured"]
            ):
                warnings.append(
                    "QBITTORRENT_USERNAME 已设置但 QBITTORRENT_PASSWORD 和 "
                    "QBITTORRENT_BASIC_AUTH 都为空"
                )

        return {
            "ready": any(provider.enabled for provider in self.providers.values())
            and any(downloader.enabled for downloader in self.downloaders.values()),
            "pt_sites": providers,
            "downloaders": downloaders,
            "defaults": {
                "site": self.default_site or None,
                "downloader": self.default_downloader or None,
            },
            "missing": missing,
            "warnings": warnings,
        }

    @staticmethod
    def _safe_check(result: object) -> dict[str, Any]:
        if isinstance(result, BaseException):
            return {"ok": False, "message": f"检查失败：{result}"}
        if isinstance(result, dict):
            return result
        return {"ok": False, "message": "检查返回格式异常"}
