"""M-Team 官方 API 提供者。"""

from __future__ import annotations

import math
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urljoin

import httpx2

from ..config import MTeamConfig
from ..errors import ProviderError
from ..models import Category, SearchPage, TorrentFile, TorrentItem
from ..torrent_utils import BencodeError, validate_torrent
from .base import PTProvider

_USER_AGENT = "nas-mcp/0.1"
_TORRENT_ID = re.compile(r"^[0-9]{1,20}$")

# M-Team 分类 ID，来源为站点公开分类定义。
CATEGORIES: tuple[Category, ...] = (
    Category("401", "电影/SD"),
    Category("419", "电影/HD"),
    Category("420", "电影/DVDiSo"),
    Category("421", "电影/Blu-Ray"),
    Category("439", "电影/Remux"),
    Category("403", "剧集/综艺/SD"),
    Category("402", "剧集/综艺/HD"),
    Category("438", "剧集/综艺/BD"),
    Category("435", "剧集/综艺/DVDiSo"),
    Category("404", "纪录片"),
    Category("434", "音乐(无损)"),
    Category("406", "演唱会"),
    Category("423", "PC游戏"),
    Category("448", "TV游戏"),
    Category("405", "动画"),
    Category("407", "体育"),
    Category("427", "电子书"),
    Category("422", "软件"),
    Category("442", "有声书"),
    Category("451", "教育影片"),
    Category("409", "其他"),
    Category("410", "AV(有码)/HD"),
    Category("424", "AV(有码)/SD"),
    Category("437", "AV(有码)/DVDiSo"),
    Category("431", "AV(有码)/Blu-Ray"),
    Category("429", "AV(无码)/HD"),
    Category("430", "AV(无码)/SD"),
    Category("426", "AV(无码)/DVDiSo"),
    Category("432", "AV(无码)/Blu-Ray"),
    Category("436", "AV(网站)/0Day"),
    Category("440", "AV(Gay)/HD"),
    Category("425", "IV(写真影集)"),
    Category("433", "IV(写真图集)"),
    Category("411", "H-游戏"),
    Category("412", "H-动画"),
    Category("413", "H-漫画"),
)

_ADULT_CATEGORY_IDS: frozenset[str] = frozenset(
    {
        "410",
        "424",
        "437",
        "431",
        "429",
        "430",
        "426",
        "432",
        "436",
        "440",
        "425",
        "433",
        "411",
        "412",
        "413",
    }
)

_CATEGORY_NAMES: dict[str, str] = {category.id: category.name for category in CATEGORIES}

# 中文/英文别名到分类 ID 列表，避免模型必须知道数字分类。
_CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "电影": ("401", "419", "420", "421", "439"),
    "電影": ("401", "419", "420", "421", "439"),
    "movie": ("401", "419", "420", "421", "439"),
    "movies": ("401", "419", "420", "421", "439"),
    "剧集": ("402", "403", "435", "438"),
    "劇集": ("402", "403", "435", "438"),
    "电视剧": ("402", "403", "435", "438"),
    "電視劇": ("402", "403", "435", "438"),
    "tv": ("402", "403", "435", "438"),
    "综艺": ("402", "403", "435", "438"),
    "綜藝": ("402", "403", "435", "438"),
    "纪录片": ("404",),
    "紀錄片": ("404",),
    "documentary": ("404",),
    "动画": ("405",),
    "動畫": ("405",),
    "动漫": ("405",),
    "anime": ("405",),
    "音乐": ("434", "406"),
    "音樂": ("434", "406"),
    "music": ("434", "406"),
    "演唱会": ("406",),
    "演唱會": ("406",),
    "游戏": ("423", "448"),
    "遊戲": ("423", "448"),
    "game": ("423", "448"),
    "games": ("423", "448"),
    "电子书": ("427",),
    "電子書": ("427",),
    "ebook": ("427",),
    "软件": ("422",),
    "軟體": ("422",),
    "software": ("422",),
    "有声书": ("442",),
    "有聲書": ("442",),
    "audiobook": ("442",),
    "教育": ("451",),
    "education": ("451",),
    "体育": ("407",),
    "體育": ("407",),
    "sports": ("407",),
    "其他": ("409",),
    "other": ("409",),
    "成人": tuple(sorted(_ADULT_CATEGORY_IDS)),
    "adult": tuple(sorted(_ADULT_CATEGORY_IDS)),
}

_SORT_FIELDS: dict[str, str] = {
    "time": "CREATED_DATE",
    "created": "CREATED_DATE",
    "newest": "CREATED_DATE",
    "时间": "CREATED_DATE",
    "最新": "CREATED_DATE",
    "seeders": "SEEDERS",
    "seeder": "SEEDERS",
    "做种": "SEEDERS",
    "做种数": "SEEDERS",
    "leechers": "LEECHERS",
    "leecher": "LEECHERS",
    "下载": "LEECHERS",
    "下载数": "LEECHERS",
    "size": "SIZE",
    "大小": "SIZE",
    "completed": "TIMES_COMPLETED",
    "完成": "TIMES_COMPLETED",
    "完成数": "TIMES_COMPLETED",
    "title": "NAME",
    "name": "NAME",
    "标题": "NAME",
    "名称": "NAME",
}


def _normalize_key(value: str) -> str:
    return (
        value.strip()
        .casefold()
        .replace(" ", "")
        .replace("（", "(")
        .replace("）", ")")
        .replace("／", "/")
    )


def _category_alias_map() -> dict[str, tuple[str, ...]]:
    aliases: dict[str, tuple[str, ...]] = {}
    for category in CATEGORIES:
        aliases[_normalize_key(category.name)] = (category.id,)
    for key, ids in _CATEGORY_ALIASES.items():
        aliases[_normalize_key(key)] = ids
    return aliases


_CATEGORY_LOOKUP = _category_alias_map()


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


class MTeamProvider(PTProvider):
    """通过 api.m-team.cc 搜索和获取种子。"""

    id = "mteam"
    display_name = "M-Team"

    def __init__(
        self,
        config: MTeamConfig,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def _headers(self) -> dict[str, str]:
        # M-Team 从 2025-10-28 起要求 Origin 与站点域名一致。
        return {
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
            "x-api-key": self.config.api_key,
            "Origin": self.config.site_url,
            "Referer": f"{self.config.site_url}/",
        }

    @asynccontextmanager
    async def _api_client(self) -> AsyncIterator[httpx2.AsyncClient]:
        async with httpx2.AsyncClient(
            base_url=self.config.api_base,
            headers=self._headers(),
            timeout=self.config.timeout,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            yield client

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise ProviderError("未配置 MTEAM_API_KEY，请先在 .env 中设置 M-Team API Key")

    async def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        self._require_enabled()
        try:
            async with self._api_client() as client:
                response = await client.post(path, json=payload)
        except httpx2.HTTPError as exc:
            raise ProviderError(f"M-Team 请求失败：{exc}") from exc
        return self._parse_response(response, "M-Team API 请求失败")

    async def _post_form(self, path: str, data: dict[str, Any]) -> Any:
        self._require_enabled()
        try:
            async with self._api_client() as client:
                response = await client.post(path, data=data)
        except httpx2.HTTPError as exc:
            raise ProviderError(f"M-Team 请求失败：{exc}") from exc
        return self._parse_response(response, "M-Team API 请求失败")

    async def _post_query(self, path: str, params: dict[str, Any]) -> Any:
        self._require_enabled()
        try:
            async with self._api_client() as client:
                response = await client.post(path, params=params)
        except httpx2.HTTPError as exc:
            raise ProviderError(f"M-Team 请求失败：{exc}") from exc
        return self._parse_response(response, "M-Team API 请求失败")

    @staticmethod
    def _parse_response(response: httpx2.Response, context: str) -> Any:
        if response.status_code in {401, 403}:
            raise ProviderError(f"{context}：API Key 无效或无权限（HTTP {response.status_code}）")
        if response.status_code >= 400:
            detail = response.text[:300].strip()
            raise ProviderError(f"{context}：HTTP {response.status_code} {detail}".strip())
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(f"{context}：返回内容不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderError(f"{context}：返回格式不符合预期")

        code = str(payload.get("code", "")).strip()
        message = str(payload.get("message", "")).strip()
        if code and code not in {"0", "200"} and message.upper() != "SUCCESS":
            raise ProviderError(f"{context}：{message or f'错误码 {code}'}")
        return payload.get("data")

    def validate_torrent_id(self, torrent_id: str) -> None:
        if not _TORRENT_ID.fullmatch(torrent_id.strip()):
            raise ProviderError(f"种子 ID 必须是 1 到 20 位数字，当前值：{torrent_id!r}")

    def categories(self) -> list[Category]:
        return list(CATEGORIES)

    async def search(
        self,
        keyword: str,
        page: int,
        page_size: int,
        categories: list[str] | None,
        sort_by: str,
    ) -> SearchPage:
        category_ids, mode = self._resolve_categories(categories)
        sort_key = _normalize_key(sort_by)
        sort_field = _SORT_FIELDS.get(sort_key)
        if sort_field is None:
            raise ProviderError(
                "不支持的排序方式，可用值：time、seeders、leechers、size、completed"
            )

        body: dict[str, Any] = {
            "keyword": keyword,
            "mode": mode,
            "pageNumber": page,
            "pageSize": page_size,
            "sortField": sort_field,
            "sortDirection": "DESC",
            "visible": 1,
        }
        if category_ids:
            body["categories"] = category_ids

        data = await self._post_json("torrent/search", body)
        raw_items, total, total_pages = self._extract_search_data(data, page_size)
        items = tuple(
            item
            for raw in raw_items
            if isinstance(raw, dict)
            if (item := self._normalize_item(raw)) is not None
        )
        return SearchPage(
            site=self.id,
            keyword=keyword,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            items=items,
        )

    def _resolve_categories(self, categories: list[str] | None) -> tuple[list[str], str]:
        if not categories:
            return [], "normal"

        selected: list[str] = []
        seen: set[str] = set()
        for raw in categories:
            key = _normalize_key(raw)
            if not key:
                continue
            ids = _CATEGORY_LOOKUP.get(key)
            if ids is None and key.isdigit() and key in _CATEGORY_NAMES:
                ids = (key,)
            if ids is None:
                raise ProviderError(
                    f"未知分类：{raw!r}。可使用电影、剧集、动画、纪录片、音乐、游戏、软件、"
                    "电子书、体育、成人等名称，或直接传 M-Team 分类 ID"
                )
            for category_id in ids:
                if category_id not in seen:
                    seen.add(category_id)
                    selected.append(category_id)

        has_adult = any(category_id in _ADULT_CATEGORY_IDS for category_id in selected)
        has_normal = any(category_id not in _ADULT_CATEGORY_IDS for category_id in selected)
        if has_adult and has_normal:
            raise ProviderError("不能同时选择普通分类和成人分类")
        return selected, "adult" if has_adult else "normal"

    @staticmethod
    def _extract_search_data(data: Any, page_size: int) -> tuple[list[Any], int, int]:
        if isinstance(data, list):
            return data, len(data), 1 if data else 0
        if not isinstance(data, dict):
            return [], 0, 0

        raw_items: Any = data.get("data")
        if raw_items is None:
            for key in ("list", "results", "records", "torrents"):
                if isinstance(data.get(key), list):
                    raw_items = data[key]
                    break
        if not isinstance(raw_items, list):
            raw_items = []

        total = _as_int(data.get("total") or data.get("totalCount"), len(raw_items))
        total_pages = _as_int(data.get("totalPages"), 0)
        if total_pages <= 0 and total > 0:
            total_pages = math.ceil(total / page_size)
        return raw_items, total, total_pages

    @staticmethod
    def _normalize_item(raw: dict[str, Any]) -> TorrentItem | None:
        torrent_id = str(raw.get("id") or raw.get("torrentId") or "").strip()
        name = str(raw.get("name") or raw.get("title") or "").strip()
        if not torrent_id or not name:
            return None

        status_raw = raw.get("status")
        status: dict[str, Any] = status_raw if isinstance(status_raw, dict) else {}
        promotion = status.get("promotionRule")
        promotion_discount = promotion.get("discount") if isinstance(promotion, dict) else None
        tags_raw = raw.get("labelsNew")
        if isinstance(tags_raw, list):
            tags = tuple(str(tag).strip() for tag in tags_raw if str(tag).strip())
        elif isinstance(tags_raw, str):
            tags = tuple(tag.strip() for tag in tags_raw.split(",") if tag.strip())
        else:
            tags = ()

        category_id = str(raw.get("category") or "").strip()
        return TorrentItem(
            id=torrent_id,
            name=name,
            size_bytes=_as_int(raw.get("size")),
            seeders=_as_int(status.get("seeders")),
            leechers=_as_int(status.get("leechers")),
            completed=_as_int(status.get("timesCompleted")),
            category=category_id,
            category_name=_CATEGORY_NAMES.get(category_id, category_id),
            discount=str(promotion_discount or status.get("discount") or "NORMAL"),
            tags=tags,
            created_at=str(raw.get("createdDate") or ""),
        )

    @staticmethod
    def _extract_download_url(data: Any) -> str:
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            for key in ("url", "downloadUrl", "download_url", "data"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value
        return ""

    async def download(self, torrent_id: str) -> TorrentFile:
        self._require_enabled()
        self.validate_torrent_id(torrent_id)
        # 站点同时接受 query/form，多客户端实现中 query 方式最稳定。
        token_data = await self._post_query("torrent/genDlToken", {"id": torrent_id})
        download_url = self._extract_download_url(token_data)
        if not download_url:
            raise ProviderError("M-Team 未返回种子下载地址")
        download_url = urljoin(f"{self.config.api_base}/", download_url)

        # 临时下载地址本身包含令牌，不携带 x-api-key，避免重定向到其他域名时泄露密钥。
        try:
            async with (
                httpx2.AsyncClient(
                    timeout=self.config.timeout,
                    follow_redirects=True,
                    transport=self._transport,
                ) as client,
                client.stream(
                    "GET",
                    download_url,
                    headers={
                        "Accept": "application/x-bittorrent",
                        "User-Agent": _USER_AGENT,
                    },
                ) as response,
            ):
                if response.status_code in {401, 403}:
                    raise ProviderError(
                        f"下载 M-Team 种子失败：HTTP {response.status_code}，临时链接可能已过期"
                    )
                if response.status_code >= 400:
                    raise ProviderError(f"下载 M-Team 种子失败：HTTP {response.status_code}")

                content_length = _as_int(response.headers.get("content-length"), 0)
                if content_length > self.config.max_torrent_bytes:
                    raise ProviderError(
                        f"M-Team 返回的种子文件超过大小限制 ({self.config.max_torrent_bytes} 字节)"
                    )

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > self.config.max_torrent_bytes:
                        raise ProviderError(
                            "M-Team 返回的种子文件超过大小限制 "
                            f"({self.config.max_torrent_bytes} 字节)"
                        )
                    chunks.append(chunk)
                content = b"".join(chunks)
        except httpx2.HTTPError as exc:
            raise ProviderError(f"下载 M-Team 种子失败：{exc}") from exc

        if content.lstrip().startswith(b"{"):
            raise ProviderError("M-Team 返回的是错误信息而不是种子文件，请稍后重试")
        try:
            metadata = validate_torrent(content)
        except BencodeError as exc:
            raise ProviderError(f"M-Team 返回的不是有效种子文件：{exc}") from exc

        return TorrentFile(
            filename=f"{torrent_id}.torrent",
            content=content,
            infohash=metadata.infohash,
            name=metadata.name,
        )

    async def check_connectivity(self) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "message": "未配置 MTEAM_API_KEY"}
        try:
            await self._post_form("member/profile", {})
        except ProviderError as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "message": "API Key 有效"}

    def status_info(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.display_name,
            "enabled": self.enabled,
            "api_base": self.config.api_base,
            "site_url": self.config.site_url,
            "api_key_configured": bool(self.config.api_key),
        }
