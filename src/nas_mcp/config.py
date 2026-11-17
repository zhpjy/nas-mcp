"""从环境变量读取运行配置。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from .errors import ConfigError

_DEFAULT_MCP_PORT = 8000
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_TORRENT_MB = 32


def _text(env: Mapping[str, str], key: str, default: str = "") -> str:
    return env.get(key, default).strip()


def _positive_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = _text(env, key)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} 必须是数字，当前值：{raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{key} 必须大于 0，当前值：{raw!r}")
    return value


def _positive_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = _text(env, key)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} 必须是整数，当前值：{raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{key} 必须大于 0，当前值：{raw!r}")
    return value


def _normalize_http_url(value: str, key: str, *, allow_missing_scheme: bool = False) -> str:
    value = value.strip()
    if not value:
        return ""
    if allow_missing_scheme and not value.startswith(("http://", "https://")):
        value = f"http://{value}"
    if not value.startswith(("http://", "https://")):
        raise ConfigError(f"{key} 必须以 http:// 或 https:// 开头，当前值：{value!r}")
    return value.rstrip("/")


@dataclass(frozen=True)
class MTeamConfig:
    """M-Team API 配置。"""

    api_key: str = field(default="", repr=False)
    api_base: str = "https://api.m-team.cc/api"
    site_url: str = "https://kp.m-team.cc"
    timeout: float = _DEFAULT_TIMEOUT
    max_torrent_bytes: int = _DEFAULT_MAX_TORRENT_MB * 1024 * 1024

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> MTeamConfig:
        api_base = _normalize_http_url(
            _text(env, "MTEAM_API_BASE", "https://api.m-team.cc/api"),
            "MTEAM_API_BASE",
        )
        site_url = _normalize_http_url(
            _text(env, "MTEAM_SITE_URL", "https://kp.m-team.cc"),
            "MTEAM_SITE_URL",
        )
        max_torrent_mb = _positive_int(env, "MTEAM_MAX_TORRENT_MB", _DEFAULT_MAX_TORRENT_MB)
        return cls(
            api_key=_text(env, "MTEAM_API_KEY"),
            api_base=api_base,
            site_url=site_url,
            timeout=_positive_float(env, "MTEAM_TIMEOUT", _DEFAULT_TIMEOUT),
            max_torrent_bytes=max_torrent_mb * 1024 * 1024,
        )


@dataclass(frozen=True)
class QBittorrentConfig:
    """qBittorrent WebUI 配置。"""

    url: str = ""
    basic_auth: tuple[str, str] | None = field(default=None, repr=False)
    username: str = ""
    password: str = field(default="", repr=False)
    save_path: str = ""
    category: str = ""
    tags: tuple[str, ...] = ()
    timeout: float = _DEFAULT_TIMEOUT

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    @property
    def use_basic_auth(self) -> bool:
        """配置 HTTP Basic 凭据时优先使用 Basic Auth，不调用登录接口。"""
        return self.basic_auth is not None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> QBittorrentConfig:
        tags = tuple(
            tag.strip() for tag in _text(env, "QBITTORRENT_TAGS").split(",") if tag.strip()
        )
        basic_auth_value = _text(env, "QBITTORRENT_BASIC_AUTH")
        basic_auth: tuple[str, str] | None = None
        if basic_auth_value:
            username, separator, password = basic_auth_value.partition(":")
            if not separator or not username or not password:
                raise ConfigError("QBITTORRENT_BASIC_AUTH 必须使用 username:password 格式")
            basic_auth = (username, password)

        return cls(
            url=_normalize_http_url(
                _text(env, "QBITTORRENT_URL"),
                "QBITTORRENT_URL",
                allow_missing_scheme=True,
            ),
            basic_auth=basic_auth,
            username=_text(env, "QBITTORRENT_USERNAME"),
            password=_text(env, "QBITTORRENT_PASSWORD"),
            save_path=_text(env, "QBITTORRENT_SAVE_PATH"),
            category=_text(env, "QBITTORRENT_CATEGORY"),
            tags=tags,
            timeout=_positive_float(env, "QBITTORRENT_TIMEOUT", _DEFAULT_TIMEOUT),
        )


@dataclass(frozen=True)
class Settings:
    """完整运行配置。"""

    mteam: MTeamConfig = field(default_factory=MTeamConfig)
    qbittorrent: QBittorrentConfig = field(default_factory=QBittorrentConfig)
    default_site: str = "mteam"
    default_downloader: str = "qbittorrent"
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = _DEFAULT_MCP_PORT

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        transport = _text(source, "MCP_TRANSPORT", "stdio").lower() or "stdio"
        if transport not in {"stdio", "streamable-http"}:
            raise ConfigError("MCP_TRANSPORT 只能是 stdio 或 streamable-http")
        port = _positive_int(source, "MCP_PORT", _DEFAULT_MCP_PORT)
        if port > 65535:
            raise ConfigError(f"MCP_PORT 超出范围：{port}")
        return cls(
            mteam=MTeamConfig.from_env(source),
            qbittorrent=QBittorrentConfig.from_env(source),
            default_site=_text(source, "PT_DEFAULT_SITE", "mteam"),
            default_downloader=_text(source, "DOWNLOADER_DEFAULT", "qbittorrent"),
            transport=transport,
            host=_text(source, "MCP_HOST", "127.0.0.1") or "127.0.0.1",
            port=port,
        )
