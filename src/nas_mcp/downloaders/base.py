"""下载器抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models import AddOutcome, DownloadTask, TorrentFile


class Downloader(ABC):
    """新增下载器时实现此接口并在 downloaders/__init__.py 注册。"""

    id: str
    display_name: str

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """配置是否完整到可以发起请求。"""

    @abstractmethod
    async def add_torrent(self, torrent: TorrentFile, category: str | None = None) -> AddOutcome:
        """添加种子任务，可覆盖配置的默认分类。"""

    @abstractmethod
    async def list_categories(self) -> list[str]:
        """列出下载器已有分类。"""

    @abstractmethod
    async def list_torrents(self) -> list[DownloadTask]:
        """返回全部任务，由服务层负责筛选和排序。"""

    @abstractmethod
    async def check_connectivity(self) -> dict[str, Any]:
        """检查登录和接口可用性，不抛异常。"""

    @abstractmethod
    def status_info(self) -> dict[str, Any]:
        """返回可安全展示的配置信息。"""
