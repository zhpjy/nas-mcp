"""PT 站提供者的抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models import Category, SearchPage, TorrentFile


class PTProvider(ABC):
    """新增 PT 站时实现此接口并在 providers/__init__.py 注册。"""

    id: str
    display_name: str

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """配置是否完整到可以发起请求。"""

    @abstractmethod
    async def search(
        self,
        keyword: str,
        page: int,
        page_size: int,
        categories: list[str] | None,
        sort_by: str,
        include_adult: bool = False,
    ) -> SearchPage:
        """搜索种子；include_adult=false 时不得返回成人内容。"""

    @abstractmethod
    async def download(self, torrent_id: str) -> TorrentFile:
        """获取种子文件内容和元数据，不落盘。"""

    @abstractmethod
    def validate_torrent_id(self, torrent_id: str) -> None:
        """校验种子 ID，非法时抛出业务异常。"""

    @abstractmethod
    def categories(self) -> list[Category]:
        """返回站点分类，供文档或内部映射使用。"""

    @abstractmethod
    async def check_connectivity(self) -> dict[str, Any]:
        """检查认证和接口可用性，不抛异常。"""

    @abstractmethod
    def status_info(self) -> dict[str, Any]:
        """返回可安全展示的配置信息。"""
