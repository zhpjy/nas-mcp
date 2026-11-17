from __future__ import annotations

import httpx2

from nas_mcp.config import MTeamConfig, QBittorrentConfig
from nas_mcp.downloaders.qbittorrent import QBittorrentDownloader
from nas_mcp.providers.mteam import MTeamProvider
from nas_mcp.service import NasService

from .helpers import make_torrent


async def test_mteam_download_flows_into_qbittorrent() -> None:
    content, infohash = make_torrent()

    def mteam_handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/torrent/genDlToken":
            assert request.url.params["id"] == "123"
            return httpx2.Response(
                200,
                json={"code": "0", "data": "https://download.example/t.torrent"},
            )
        if request.url.host == "download.example":
            return httpx2.Response(
                200,
                content=content,
                headers={"content-type": "application/x-bittorrent"},
            )
        raise AssertionError(f"unexpected M-Team request: {request.url}")

    def qbt_handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/v2/torrents/categories":
            return httpx2.Response(200, json={"PT": {"name": "PT"}})
        if request.url.path == "/api/v2/torrents/add":
            assert request.headers["authorization"] == "Basic dXNlcjpwYXNz"
            assert content in request.content
            return httpx2.Response(200, text="Ok.")
        raise AssertionError(f"unexpected qBittorrent request: {request.url}")

    provider = MTeamProvider(
        MTeamConfig(
            api_key="mteam-key",
            api_base="https://api.m-team.cc/api",
            site_url="https://kp.m-team.cc",
            timeout=5,
            max_torrent_bytes=1024 * 1024,
        ),
        transport=httpx2.MockTransport(mteam_handler),
    )
    downloader = QBittorrentDownloader(
        QBittorrentConfig(
            url="http://qbt:8080",
            basic_auth=("user", "pass"),
            category="PT",
            timeout=5,
        ),
        transport=httpx2.MockTransport(qbt_handler),
    )
    service = NasService(
        providers={"mteam": provider},
        downloaders={"qbittorrent": downloader},
        default_site="mteam",
        default_downloader="qbittorrent",
    )

    result = await service.download_torrents(["123"], category="PT")

    assert result["ok"] is True
    assert result["results"][0]["hash"] == infohash
    assert result["results"][0]["name"] == "Test Torrent"
