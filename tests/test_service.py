from __future__ import annotations

from typing import Any

import pytest

from nas_mcp.downloaders.base import Downloader
from nas_mcp.errors import ConfigError, NasMcpError, ProviderError
from nas_mcp.models import (
    AddOutcome,
    Category,
    DownloadTask,
    SearchPage,
    TorrentFile,
    TorrentItem,
)
from nas_mcp.providers.base import PTProvider
from nas_mcp.service import NasService


class FakeProvider(PTProvider):
    id = "fake"
    display_name = "Fake PT"

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled
        self.download_calls: list[str] = []
        self.search_calls: list[dict[str, Any]] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def search(
        self,
        keyword: str,
        page: int,
        page_size: int,
        categories: list[str] | None,
        sort_by: str,
    ) -> SearchPage:
        self.search_calls.append(
            {
                "keyword": keyword,
                "page": page,
                "page_size": page_size,
                "categories": categories,
                "sort_by": sort_by,
            }
        )
        item = TorrentItem(
            id="1",
            name="Example",
            size_bytes=1024,
            seeders=10,
            leechers=2,
            completed=3,
            category="419",
            category_name="电影/HD",
        )
        return SearchPage(
            site=self.id,
            keyword=keyword,
            page=page,
            page_size=page_size,
            total=1,
            total_pages=1,
            items=(item,),
        )

    async def download(self, torrent_id: str) -> TorrentFile:
        self.download_calls.append(torrent_id)
        if torrent_id == "2":
            raise ProviderError("模拟下载失败")
        return TorrentFile(
            filename=f"{torrent_id}.torrent",
            content=b"d4:infod4:name5:testee",
            infohash=f"hash-{torrent_id}",
            name=f"Torrent {torrent_id}",
        )

    def validate_torrent_id(self, torrent_id: str) -> None:
        if not torrent_id.isdigit():
            raise ProviderError(f"种子 ID 必须是数字：{torrent_id}")

    def categories(self) -> list[Category]:
        return [Category("419", "电影/HD")]

    async def check_connectivity(self) -> dict[str, Any]:
        return {"ok": self.enabled, "message": "ok"}

    def status_info(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.display_name,
            "enabled": self.enabled,
            "api_key_configured": self.enabled,
        }


class FakeDownloader(Downloader):
    id = "fakeqbt"
    display_name = "Fake qBittorrent"

    def __init__(
        self,
        *,
        enabled: bool = True,
        tasks: list[DownloadTask] | None = None,
    ) -> None:
        self._enabled = enabled
        self.tasks = tasks or []
        self.added: list[str] = []
        self.selected_categories: list[str | None] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def add_torrent(
        self,
        torrent: TorrentFile,
        category: str | None = None,
    ) -> AddOutcome:
        self.added.append(torrent.filename)
        self.selected_categories.append(category)
        return AddOutcome(
            name=torrent.name,
            infohash=torrent.infohash,
            message="已添加",
        )

    async def list_categories(self) -> list[str]:
        return ["Movies", "TV"]

    async def list_torrents(self) -> list[DownloadTask]:
        return list(self.tasks)

    async def check_connectivity(self) -> dict[str, Any]:
        return {"ok": self.enabled, "message": "ok", "version": "5.1.2"}

    def status_info(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.display_name,
            "enabled": self.enabled,
            "url": "http://qbt:8080",
            "auth_mode": "basic",
            "basic_auth_configured": self.enabled,
            "username_configured": False,
            "password_configured": False,
            "save_path": "",
            "category": "",
            "tags": [],
        }


def make_service(
    provider: FakeProvider | None = None,
    downloader: FakeDownloader | None = None,
) -> NasService:
    return NasService(
        providers={"fake": provider or FakeProvider()},
        downloaders={"fakeqbt": downloader or FakeDownloader()},
        default_site="fake",
        default_downloader="fakeqbt",
    )


def make_task(
    task_hash: str,
    *,
    state: str = "downloading",
    progress: float = 50.0,
    added_on: int = 1,
) -> DownloadTask:
    return DownloadTask(
        hash=task_hash,
        name=f"Task {task_hash}",
        state=state,
        state_label=state,
        progress=progress,
        size_bytes=1000,
        downloaded_bytes=int(progress * 10),
        dlspeed=100,
        upspeed=10,
        eta_seconds=60,
        ratio=0.5,
        category="PT",
        added_on=added_on,
    )


async def test_search_passes_parameters() -> None:
    provider = FakeProvider()
    result = await make_service(provider).search_torrents(
        "  沙丘  ", page=2, page_size=10, categories=["电影"], sort_by="seeders"
    )

    assert provider.search_calls[0]["keyword"] == "沙丘"
    assert provider.search_calls[0]["page"] == 2
    assert result["results"][0]["id"] == "1"


async def test_search_rejects_empty_keyword() -> None:
    with pytest.raises(NasMcpError, match="关键词不能为空"):
        await make_service().search_torrents(" ", 1, 20, None, "seeders")


async def test_download_partial_failure() -> None:
    provider = FakeProvider()
    downloader = FakeDownloader()
    result = await make_service(provider, downloader).download_torrents(["1", "2", "1"])

    assert result["ok"] is False
    assert result["results"][0]["ok"] is True
    assert result["results"][1]["ok"] is False
    assert "模拟下载失败" in result["results"][1]["message"]
    assert downloader.added == ["1.torrent"]


async def test_download_passes_selected_category() -> None:
    downloader = FakeDownloader()
    result = await make_service(downloader=downloader).download_torrents(["1"], " Movies ")

    assert result["ok"] is True
    assert downloader.selected_categories == ["Movies"]


async def test_list_download_categories() -> None:
    result = await make_service().list_download_categories()

    assert result == {"categories": ["Movies", "TV"]}


async def test_download_rejects_unknown_category_before_downloading() -> None:
    provider = FakeProvider()
    downloader = FakeDownloader()
    with pytest.raises(NasMcpError, match=r"分类.*不存在"):
        await make_service(provider, downloader).download_torrents(["1"], "Unknown")

    assert provider.download_calls == []
    assert downloader.added == []


async def test_download_validates_all_ids_before_side_effects() -> None:
    provider = FakeProvider()
    downloader = FakeDownloader()
    with pytest.raises(ProviderError, match="必须是数字"):
        await make_service(provider, downloader).download_torrents(["1", "abc"])
    assert provider.download_calls == []
    assert downloader.added == []


async def test_list_downloads_filters_and_sorts() -> None:
    downloader = FakeDownloader(
        tasks=[
            make_task("seeding", state="seeding", progress=100, added_on=1),
            make_task("downloading", state="downloading", progress=20, added_on=2),
            make_task("stopped", state="stopped", progress=10, added_on=3),
        ]
    )
    result = await make_service(downloader=downloader).list_downloads(
        status="all", torrent_hash=None, limit=2
    )

    assert result["summary"]["total"] == 3
    assert result["summary"]["downloading"] == 1
    assert result["count"] == 2
    assert result["torrents"][0]["hash"] == "downloading"
    assert result["torrents"][1]["hash"] == "stopped"


async def test_list_downloads_by_hash() -> None:
    downloader = FakeDownloader(tasks=[make_task("abc")])
    result = await make_service(downloader=downloader).list_downloads(
        status="all", torrent_hash="ABC", limit=20
    )
    assert result["count"] == 1
    assert result["torrents"][0]["hash"] == "abc"


async def test_list_downloads_hash_not_found() -> None:
    downloader = FakeDownloader(tasks=[make_task("abc")])
    result = await make_service(downloader=downloader).list_downloads(
        status="all", torrent_hash="missing", limit=20
    )
    assert result["count"] == 0
    assert "未找到" in result["message"]


async def test_config_status_reports_missing() -> None:
    service = make_service(FakeProvider(enabled=False), FakeDownloader(enabled=False))
    status = await service.get_config_status()

    assert status["ready"] is False
    assert "MTEAM_API_KEY" in status["missing"]
    assert "QBITTORRENT_URL" in status["missing"]
    assert status["pt_sites"][0]["connectivity"] is None


async def test_config_status_active_checks() -> None:
    status = await make_service().get_config_status(check_connectivity=True)

    assert status["ready"] is True
    assert status["pt_sites"][0]["connectivity"]["ok"] is True
    assert status["downloaders"][0]["connectivity"]["version"] == "5.1.2"


async def test_invalid_default_site() -> None:
    service = NasService(
        providers={"fake": FakeProvider()},
        downloaders={"fakeqbt": FakeDownloader()},
        default_site="missing",
        default_downloader="fakeqbt",
    )
    with pytest.raises(ConfigError, match="未注册"):
        await service.search_torrents("test", 1, 20, None, "seeders")
