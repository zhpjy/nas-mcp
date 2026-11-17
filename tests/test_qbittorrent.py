from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from nas_mcp.config import QBittorrentConfig
from nas_mcp.downloaders.qbittorrent import QBittorrentDownloader
from nas_mcp.errors import DownloaderError
from nas_mcp.models import TorrentFile

from .helpers import make_torrent


def make_downloader(
    handler: Callable[[httpx2.Request], httpx2.Response],
    **overrides: Any,
) -> QBittorrentDownloader:
    options: dict[str, Any] = {
        "url": "http://qbt:8080",
        "basic_auth": ("admin", "api-token"),
        "timeout": 5,
    }
    options.update(overrides)
    return QBittorrentDownloader(
        QBittorrentConfig(**options),
        transport=httpx2.MockTransport(handler),
    )


def sample_torrent() -> TorrentFile:
    content, infohash = make_torrent()
    return TorrentFile(
        filename="123.torrent",
        content=content,
        infohash=infohash,
        name="Test Torrent",
    )


async def test_basic_auth_add_torrent() -> None:
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        if request.url.path == "/api/v2/torrents/categories":
            return httpx2.Response(200, json={"PT": {"name": "PT"}})
        if request.url.path == "/api/v2/torrents/add":
            assert request.headers["authorization"] == "Basic YWRtaW46YXBpLXRva2Vu"
            assert request.headers["content-type"].startswith("multipart/form-data")
            body = request.content
            assert b'name="category"' in body
            assert b"PT" in body
            assert b'name="savepath"' in body
            assert b"/downloads" in body
            assert b'name="autoTMM"' in body
            assert b"false" in body
            return httpx2.Response(200, text="Ok.")
        raise AssertionError(f"unexpected request: {request.url}")

    downloader = make_downloader(
        handler,
        category="PT",
        save_path="/downloads",
        tags=("pt", "4k"),
    )
    outcome = await downloader.add_torrent(sample_torrent())

    assert outcome.infohash
    assert outcome.name == "Test Torrent"
    assert all(request.url.path != "/api/v2/auth/login" for request in calls)


async def test_password_login_fallback() -> None:
    calls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v2/auth/login":
            return httpx2.Response(
                200,
                text="Ok.",
                headers={"set-cookie": "SID=abc; path=/"},
            )
        if request.url.path == "/api/v2/torrents/add":
            assert "authorization" not in request.headers
            return httpx2.Response(200, text="Ok.")
        raise AssertionError(f"unexpected request: {request.url}")

    downloader = make_downloader(
        handler,
        basic_auth=None,
        username="admin",
        password="pass",
        category="",
        save_path="",
    )
    await downloader.add_torrent(sample_torrent())

    assert calls[0] == "/api/v2/auth/login"
    assert "/api/v2/torrents/add" in calls


async def test_login_failure() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/v2/auth/login"
        return httpx2.Response(200, text="Fails.")

    downloader = make_downloader(
        handler,
        basic_auth=None,
        username="admin",
        password="wrong",
        category="",
    )
    with pytest.raises(DownloaderError, match="登录失败"):
        await downloader.add_torrent(sample_torrent())


async def test_no_auth_does_not_send_authorization() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/v2/torrents/info"
        assert "authorization" not in request.headers
        return httpx2.Response(200, json=[])

    downloader = make_downloader(handler, basic_auth=None, username="", password="")
    assert await downloader.list_torrents() == []
    assert downloader.status_info()["auth_mode"] == "none"


async def test_list_categories() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/v2/torrents/categories"
        return httpx2.Response(200, json={"TV": {}, "Movies": {}})

    assert await make_downloader(handler).list_categories() == ["Movies", "TV"]


async def test_add_torrent_uses_selected_category() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/v2/torrents/add":
            assert b'name="category"' in request.content
            assert b"TV" in request.content
            return httpx2.Response(200, text="Ok.")
        raise AssertionError(f"unexpected request: {request.url}")

    downloader = make_downloader(handler, category="Movies")
    await downloader.add_torrent(sample_torrent(), category="TV")


async def test_list_torrents_maps_states() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/v2/torrents/info"
        return httpx2.Response(
            200,
            json=[
                {
                    "hash": "H1",
                    "name": "Downloading",
                    "state": "downloading",
                    "progress": 0.452,
                    "size": 1000,
                    "downloaded": 452,
                    "dlspeed": 1024,
                    "upspeed": 0,
                    "eta": 3600,
                    "ratio": 0.1,
                    "category": "PT",
                    "added_on": 2,
                },
                {
                    "hash": "H2",
                    "name": "Paused",
                    "state": "pausedDL",
                    "progress": 0,
                    "size": 2000,
                    "downloaded": 0,
                    "dlspeed": 0,
                    "upspeed": 0,
                    "eta": 8640000,
                    "ratio": 0,
                    "category": "",
                    "added_on": 1,
                },
            ],
        )

    tasks = await make_downloader(handler).list_torrents()

    assert tasks[0].state == "downloading"
    assert tasks[0].state_label == "下载中"
    assert tasks[0].progress == 45.2
    assert tasks[1].state == "stopped"
    assert tasks[1].eta_seconds is None
    assert tasks[1].to_dict()["eta"] == "未知"


async def test_category_is_created_when_missing() -> None:
    calls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v2/torrents/categories":
            return httpx2.Response(200, json={})
        if request.url.path == "/api/v2/torrents/createCategory":
            assert b"NewPT" in request.content
            return httpx2.Response(200, text="")
        if request.url.path == "/api/v2/torrents/add":
            return httpx2.Response(200, text="Ok.")
        raise AssertionError(f"unexpected request: {request.url}")

    downloader = make_downloader(handler, category="NewPT")
    await downloader.add_torrent(sample_torrent())

    assert calls == [
        "/api/v2/torrents/categories",
        "/api/v2/torrents/createCategory",
        "/api/v2/torrents/add",
    ]


async def test_check_connectivity() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/v2/app/version":
            return httpx2.Response(200, text="5.1.2")
        if request.url.path == "/api/v2/torrents/categories":
            return httpx2.Response(200, json={"PT": {"name": "PT"}})
        raise AssertionError(f"unexpected request: {request.url}")

    result = await make_downloader(handler, category="PT").check_connectivity()

    assert result["ok"] is True
    assert result["version"] == "5.1.2"
    assert result["category_exists"] is True


async def test_basic_auth_forbidden_has_clear_error() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(403, text="Forbidden")

    with pytest.raises(DownloaderError, match="Basic Auth"):
        await make_downloader(handler).list_torrents()
