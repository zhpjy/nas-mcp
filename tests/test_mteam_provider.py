from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from nas_mcp.config import MTeamConfig
from nas_mcp.errors import ProviderError
from nas_mcp.providers import mteam as mteam_module
from nas_mcp.providers.mteam import MTeamProvider

from .helpers import make_torrent


def make_provider(
    handler: Callable[[httpx2.Request], httpx2.Response],
    *,
    max_torrent_bytes: int = 1024 * 1024,
) -> MTeamProvider:
    return MTeamProvider(
        MTeamConfig(
            api_key="test-key",
            api_base="https://api.m-team.cc/api",
            site_url="https://kp.m-team.cc",
            timeout=5,
            max_torrent_bytes=max_torrent_bytes,
        ),
        transport=httpx2.MockTransport(handler),
    )


async def test_search_normalizes_and_sends_filters() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        body = json.loads(request.content)
        assert body["keyword"] == "沙丘"
        assert body["mode"] == "normal"
        assert "419" in body["categories"]
        assert body["sortField"] == "SEEDERS"
        return httpx2.Response(
            200,
            json={
                "code": "0",
                "message": "SUCCESS",
                "data": {
                    "pageNumber": 1,
                    "pageSize": 20,
                    "total": 1,
                    "totalPages": 1,
                    "data": [
                        {
                            "id": "1125330",
                            "name": "Dune 2024 2160p",
                            "size": "1073741824",
                            "category": "419",
                            "labelsNew": ["中字", "4k"],
                            "createdDate": "2026-01-01 12:00:00",
                            "status": {
                                "seeders": "42",
                                "leechers": "3",
                                "timesCompleted": "128",
                                "discount": "FREE",
                            },
                        }
                    ],
                },
            },
        )

    page = await make_provider(handler).search(
        keyword="沙丘",
        page=1,
        page_size=20,
        categories=["电影"],
        sort_by="seeders",
    )

    assert seen[0].headers["x-api-key"] == "test-key"
    assert seen[0].headers["origin"] == "https://kp.m-team.cc"
    assert page.total == 1
    item = page.items[0]
    assert item.id == "1125330"
    assert item.size_bytes == 1073741824
    assert item.seeders == 42
    assert item.category_name == "电影/HD"
    assert item.discount == "FREE"
    assert item.tags == ("中字", "4k")
    first_result = page.to_dict()["results"][0]
    assert first_result["index"] == 1
    assert first_result["size"] == "1 GiB"


async def test_search_accepts_traditional_chinese_category() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json={"code": "0", "data": {"data": []}})

    await make_provider(handler).search("沙丘", 1, 20, ["電影"], "seeders")

    assert "419" in seen[0]["categories"]
    assert seen[0]["mode"] == "normal"


async def test_search_surfaces_api_error() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"code": "1", "message": "API Key 错误"})

    with pytest.raises(ProviderError, match="API Key 错误"):
        await make_provider(handler).search("test", 1, 20, None, "seeders")


async def test_search_rejects_unknown_category() -> None:
    provider = make_provider(lambda _: httpx2.Response(200, json={"code": "0", "data": {}}))
    with pytest.raises(ProviderError, match="未知分类"):
        await provider.search("test", 1, 20, ["不存在的分类"], "seeders")


async def test_search_rejects_mixed_adult_and_normal_categories_when_adult_enabled() -> None:
    provider = make_provider(lambda _: httpx2.Response(200, json={"code": "0", "data": {}}))
    with pytest.raises(ProviderError, match="不能同时选择"):
        await provider.search("test", 1, 20, ["电影", "成人"], "seeders", include_adult=True)


async def test_search_removes_adult_category_when_disabled() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json={"code": "0", "data": {"data": []}})

    await make_provider(handler).search("test", 1, 20, ["电影", "成人"], "seeders")

    body = seen[0]
    assert body["mode"] == "normal"
    assert "419" in body["categories"]
    assert not set(body["categories"]) & {"410", "424", "429", "430", "425", "433", "411"}


async def test_search_adult_only_falls_back_to_normal_categories_when_disabled() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json={"code": "0", "data": {"data": []}})

    await make_provider(handler).search("test", 1, 20, ["成人"], "seeders")

    body = seen[0]
    assert body["mode"] == "normal"
    assert "410" not in body["categories"]
    assert "419" in body["categories"]


async def test_search_without_categories_uses_normal_categories_when_disabled() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json={"code": "0", "data": {"data": []}})

    await make_provider(handler).search("test", 1, 20, None, "seeders")

    body = seen[0]
    assert body["mode"] == "normal"
    assert "410" not in body["categories"]
    assert "419" in body["categories"]


async def test_search_adult_category_when_enabled() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json={"code": "0", "data": {"data": []}})

    await make_provider(handler).search("test", 1, 20, ["成人"], "seeders", include_adult=True)

    body = seen[0]
    assert body["mode"] == "adult"
    assert "410" in body["categories"]


async def test_search_drops_adult_items_when_disabled() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "code": "0",
                "data": {
                    "total": 2,
                    "totalPages": 1,
                    "data": [
                        {
                            "id": "1",
                            "name": "Normal",
                            "category": "419",
                            "status": {"seeders": "1"},
                        },
                        {
                            "id": "2",
                            "name": "Adult",
                            "category": "410",
                            "status": {"seeders": "1"},
                        },
                    ],
                },
            },
        )

    page = await make_provider(handler).search("test", 1, 20, ["电影"], "seeders")

    assert [item.id for item in page.items] == ["1"]
    assert page.total == 1
    assert page.total_pages == 1


async def test_search_keeps_adult_items_when_enabled() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "code": "0",
                "data": {
                    "total": 1,
                    "data": [
                        {
                            "id": "2",
                            "name": "Adult",
                            "category": "410",
                            "status": {"seeders": "1"},
                        }
                    ],
                },
            },
        )

    page = await make_provider(handler).search(
        "test", 1, 20, ["成人"], "seeders", include_adult=True
    )

    assert [item.id for item in page.items] == ["2"]


async def test_search_returns_empty_when_all_items_are_adult_and_disabled() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "code": "0",
                "data": {
                    "total": 1,
                    "totalPages": 1,
                    "data": [
                        {
                            "id": "2",
                            "name": "Adult",
                            "category": "410",
                            "status": {"seeders": "1"},
                        }
                    ],
                },
            },
        )

    page = await make_provider(handler).search("test", 1, 20, ["成人"], "seeders")

    assert page.items == ()
    assert page.total == 0
    assert page.total_pages == 0


async def test_download_fetches_token_and_torrent_without_api_key() -> None:
    content, expected_hash = make_torrent()
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        if request.url.path == "/api/torrent/genDlToken":
            assert request.url.params["id"] == "123"
            return httpx2.Response(
                200,
                json={"code": "0", "data": "https://download.example/t.torrent"},
            )
        if request.url.host == "download.example":
            assert "x-api-key" not in request.headers
            return httpx2.Response(
                200,
                content=content,
                headers={"content-type": "application/x-bittorrent"},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    torrent = await make_provider(handler).download("123")

    assert torrent.content == content
    assert torrent.infohash == expected_hash
    assert torrent.name == "Test Torrent"
    assert torrent.filename == "123.torrent"
    assert calls[1].url.host == "download.example"


async def test_download_rejects_oversized_torrent() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/torrent/genDlToken":
            return httpx2.Response(200, json={"code": "0", "data": "https://download.example/t"})
        return httpx2.Response(200, content=b"x" * 100)

    with pytest.raises(ProviderError, match="超过大小限制"):
        await make_provider(handler, max_torrent_bytes=10).download("123")


async def test_download_rejects_non_torrent_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mteam_module, "_DOWNLOAD_RETRY_DELAY", 0)

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/torrent/genDlToken":
            return httpx2.Response(200, json={"code": "0", "data": "https://download.example/t"})
        return httpx2.Response(200, content=b'{"code":"1","message":"expired"}')

    with pytest.raises(ProviderError, match="错误信息"):
        await make_provider(handler).download("123")


async def test_download_retries_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mteam_module, "_DOWNLOAD_RETRY_DELAY", 0)
    content, expected_hash = make_torrent()
    download_calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal download_calls
        if request.url.path == "/api/torrent/genDlToken":
            return httpx2.Response(200, json={"code": "0", "data": "https://download.example/t"})
        download_calls += 1
        if download_calls == 1:
            raise httpx2.ConnectError("")
        return httpx2.Response(200, content=content)

    torrent = await make_provider(handler).download("123")

    assert torrent.infohash == expected_hash
    assert download_calls == 2


async def test_download_retries_expired_link(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mteam_module, "_DOWNLOAD_RETRY_DELAY", 0)
    content, _ = make_torrent()
    token_calls = 0
    download_calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal token_calls, download_calls
        if request.url.path == "/api/torrent/genDlToken":
            token_calls += 1
            return httpx2.Response(200, json={"code": "0", "data": "https://download.example/t"})
        download_calls += 1
        if download_calls == 1:
            return httpx2.Response(403, content=b"expired")
        return httpx2.Response(200, content=content)

    torrent = await make_provider(handler).download("123")

    assert torrent.content == content
    assert token_calls == 2


async def test_download_retries_then_reports_readable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mteam_module, "_DOWNLOAD_RETRY_DELAY", 0)
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        raise httpx2.ConnectError("")

    with pytest.raises(ProviderError, match="连接失败") as excinfo:
        await make_provider(handler).download("123")

    assert "已自动重试 5 次" in str(excinfo.value)
    assert calls == 6


async def test_download_uses_full_retry_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mteam_module, "_DOWNLOAD_RETRY_DELAY", 0)
    content, _ = make_torrent()
    download_calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal download_calls
        if request.url.path == "/api/torrent/genDlToken":
            return httpx2.Response(200, json={"code": "0", "data": "https://download.example/t"})
        download_calls += 1
        if download_calls <= 5:
            raise httpx2.ReadTimeout("")
        return httpx2.Response(200, content=content)

    torrent = await make_provider(handler).download("123")

    assert torrent.content == content
    assert download_calls == 6


def test_download_retry_delay_is_capped() -> None:
    delays = [mteam_module._retry_delay(attempt) for attempt in range(5)]

    assert delays == [0.5, 1.0, 2.0, 3.0, 3.0]


async def test_download_does_not_retry_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mteam_module, "_DOWNLOAD_RETRY_DELAY", 0)
    download_calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal download_calls
        if request.url.path == "/api/torrent/genDlToken":
            return httpx2.Response(200, json={"code": "0", "data": "https://download.example/t"})
        download_calls += 1
        return httpx2.Response(404)

    with pytest.raises(ProviderError, match="HTTP 404"):
        await make_provider(handler).download("123")

    assert download_calls == 1


async def test_check_connectivity() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/member/profile"
        return httpx2.Response(200, json={"code": "0", "data": {"id": "1"}})

    result = await make_provider(handler).check_connectivity()
    assert result["ok"] is True


def test_validate_torrent_id() -> None:
    provider = make_provider(lambda _: httpx2.Response(200, json={}))
    provider.validate_torrent_id("123")
    with pytest.raises(ProviderError):
        provider.validate_torrent_id("abc")


def test_status_info_has_no_secret() -> None:
    info: dict[str, Any] = make_provider(lambda _: httpx2.Response(200, json={})).status_info()
    assert info["api_key_configured"] is True
    assert "test-key" not in json.dumps(info)
