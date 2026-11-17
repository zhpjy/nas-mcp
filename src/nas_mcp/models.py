"""服务层与工具层共享的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .formatting import human_bytes, human_eta, human_speed


@dataclass(frozen=True)
class Category:
    id: str
    name: str


@dataclass(frozen=True)
class TorrentItem:
    id: str
    name: str
    size_bytes: int
    seeders: int = 0
    leechers: int = 0
    completed: int = 0
    category: str = ""
    category_name: str = ""
    discount: str = "NORMAL"
    tags: tuple[str, ...] = ()
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "size": human_bytes(self.size_bytes),
            "seeders": self.seeders,
            "leechers": self.leechers,
            "completed": self.completed,
            "discount": self.discount,
            "category": self.category_name or self.category,
            "tags": list(self.tags),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class SearchPage:
    site: str
    keyword: str
    page: int
    page_size: int
    total: int
    total_pages: int
    items: tuple[TorrentItem, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "site": self.site,
            "keyword": self.keyword,
            "page": self.page,
            "page_size": self.page_size,
            "total": self.total,
            "total_pages": self.total_pages,
            "results": [
                {"index": index, **item.to_dict()} for index, item in enumerate(self.items, start=1)
            ],
        }


@dataclass(frozen=True)
class TorrentFile:
    filename: str
    content: bytes
    infohash: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class AddOutcome:
    name: str | None
    infohash: str | None
    message: str


@dataclass(frozen=True)
class DownloadTask:
    hash: str
    name: str
    state: str
    state_label: str
    progress: float
    size_bytes: int
    downloaded_bytes: int
    dlspeed: int
    upspeed: int
    eta_seconds: int | None
    ratio: float
    category: str
    added_on: int
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "hash": self.hash,
            "name": self.name,
            "state": self.state,
            "state_label": self.state_label,
            "progress": self.progress,
            "size": human_bytes(self.size_bytes),
            "downloaded": human_bytes(self.downloaded_bytes),
            "download_speed": human_speed(self.dlspeed),
            "upload_speed": human_speed(self.upspeed),
            "eta": human_eta(self.eta_seconds),
            "ratio": round(self.ratio, 3),
            "category": self.category,
        }
        if self.error:
            result["error"] = self.error
        return result
