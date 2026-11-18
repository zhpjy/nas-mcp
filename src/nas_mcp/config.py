"""从 YAML 配置文件读取运行配置。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

from .errors import ConfigError

_DEFAULT_MCP_PORT = 8000
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_TORRENT_MB = 32
_DEFAULT_CONFIG_PATH = Path("config.yaml")


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"{path} 必须是映射")
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ConfigError(f"{path} 的字段名必须是字符串")
        result[key] = item
    return result


def _only_keys(data: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"{path} 包含未知字段：{', '.join(unknown)}")


def _string(
    data: Mapping[str, Any],
    key: str,
    path: str,
    default: str = "",
    *,
    required: bool = False,
) -> str:
    value = data.get(key, default)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ConfigError(f"{path}.{key} 必须是字符串；包含数字或特殊字符时请加引号")
    text = value.strip()
    if required and not text:
        raise ConfigError(f"{path}.{key} 不能为空")
    return text


def _optional_bool(data: Mapping[str, Any], key: str, path: str) -> bool | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ConfigError(f"{path}.{key} 必须是 true、false 或 null")
    return value


def _bool(data: Mapping[str, Any], key: str, path: str, default: bool) -> bool:
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError(f"{path}.{key} 必须是 true 或 false")
    return value


def _positive_float(data: Mapping[str, Any], key: str, path: str, default: float) -> float:
    value = data.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{path}.{key} 必须是数字")
    result = float(value)
    if result <= 0:
        raise ConfigError(f"{path}.{key} 必须大于 0")
    return result


def _positive_int(data: Mapping[str, Any], key: str, path: str, default: int) -> int:
    value = data.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{path}.{key} 必须是整数")
    if value <= 0:
        raise ConfigError(f"{path}.{key} 必须大于 0")
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
class AccessKeyConfig:
    """一个 HTTP access key 及其成人内容权限。"""

    name: str
    key: str = field(repr=False)
    adult_enabled: bool | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], path: str) -> AccessKeyConfig:
        _only_keys(data, {"name", "key", "adult_enabled"}, path)
        return cls(
            name=_string(data, "name", path, required=True),
            key=_string(data, "key", path, required=True),
            adult_enabled=_optional_bool(data, "adult_enabled", path),
        )


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
    def from_mapping(cls, data: Mapping[str, Any]) -> MTeamConfig:
        path = "mteam"
        _only_keys(data, {"api_key", "api_base", "site_url", "timeout", "max_torrent_mb"}, path)
        api_base = _normalize_http_url(
            _string(data, "api_base", path, "https://api.m-team.cc/api"),
            "mteam.api_base",
        )
        site_url = _normalize_http_url(
            _string(data, "site_url", path, "https://kp.m-team.cc"),
            "mteam.site_url",
        )
        max_torrent_mb = _positive_int(data, "max_torrent_mb", path, _DEFAULT_MAX_TORRENT_MB)
        return cls(
            api_key=_string(data, "api_key", path),
            api_base=api_base,
            site_url=site_url,
            timeout=_positive_float(data, "timeout", path, _DEFAULT_TIMEOUT),
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
    def from_mapping(cls, data: Mapping[str, Any]) -> QBittorrentConfig:
        path = "qbittorrent"
        _only_keys(
            data,
            {
                "url",
                "basic_auth",
                "username",
                "password",
                "save_path",
                "category",
                "tags",
                "timeout",
            },
            path,
        )
        basic_auth_value = _string(data, "basic_auth", path)
        basic_auth: tuple[str, str] | None = None
        if basic_auth_value:
            username, separator, password = basic_auth_value.partition(":")
            if not separator or not username or not password:
                raise ConfigError("qbittorrent.basic_auth 必须使用 username:password 格式")
            basic_auth = (username, password)

        return cls(
            url=_normalize_http_url(
                _string(data, "url", path),
                "qbittorrent.url",
                allow_missing_scheme=True,
            ),
            basic_auth=basic_auth,
            username=_string(data, "username", path),
            password=_string(data, "password", path),
            save_path=_string(data, "save_path", path),
            category=_string(data, "category", path),
            tags=_parse_tags(data.get("tags"), path),
            timeout=_positive_float(data, "timeout", path, _DEFAULT_TIMEOUT),
        )


def _parse_tags(value: Any, path: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw_tags = value.split(",")
    elif isinstance(value, list):
        raw_tags = value
    else:
        raise ConfigError(f"{path}.tags 必须是字符串列表")
    tags: list[str] = []
    for tag in raw_tags:
        if not isinstance(tag, str):
            raise ConfigError(f"{path}.tags 的每一项都必须是字符串")
        text = tag.strip()
        if text:
            tags.append(text)
    return tuple(tags)


@dataclass(frozen=True)
class Settings:
    """完整运行配置。"""

    adult_enabled: bool = False
    access_keys: tuple[AccessKeyConfig, ...] = ()
    mteam: MTeamConfig = field(default_factory=MTeamConfig)
    qbittorrent: QBittorrentConfig = field(default_factory=QBittorrentConfig)
    default_site: str = "mteam"
    default_downloader: str = "qbittorrent"
    transport: str = "streamable-http"
    host: str = "127.0.0.1"
    port: int = _DEFAULT_MCP_PORT

    @property
    def access_keys_enabled(self) -> bool:
        return bool(self.access_keys)

    def adult_enabled_for(self, access_key: AccessKeyConfig | None) -> bool:
        """access key 未配置 adult_enabled 时回退到全局值。"""
        if access_key is not None and access_key.adult_enabled is not None:
            return access_key.adult_enabled
        return self.adult_enabled

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> Settings:
        root = _mapping(data, "配置")
        _only_keys(
            root,
            {"adult_enabled", "access_keys", "mcp", "mteam", "qbittorrent", "defaults"},
            "配置",
        )
        mcp = _mapping(root.get("mcp"), "mcp")
        _only_keys(mcp, {"transport", "host", "port"}, "mcp")
        defaults = _mapping(root.get("defaults"), "defaults")
        _only_keys(defaults, {"site", "downloader"}, "defaults")

        transport = _string(mcp, "transport", "mcp", "streamable-http").lower()
        if transport not in {"stdio", "streamable-http"}:
            raise ConfigError("mcp.transport 只能是 stdio 或 streamable-http")
        port = _positive_int(mcp, "port", "mcp", _DEFAULT_MCP_PORT)
        if port > 65535:
            raise ConfigError(f"mcp.port 超出范围：{port}")

        return cls(
            adult_enabled=_bool(root, "adult_enabled", "配置", False),
            access_keys=_parse_access_keys(root.get("access_keys")),
            mteam=MTeamConfig.from_mapping(_mapping(root.get("mteam"), "mteam")),
            qbittorrent=QBittorrentConfig.from_mapping(
                _mapping(root.get("qbittorrent"), "qbittorrent")
            ),
            default_site=_string(defaults, "site", "defaults", "mteam"),
            default_downloader=_string(defaults, "downloader", "defaults", "qbittorrent"),
            transport=transport,
            host=_string(mcp, "host", "mcp", "127.0.0.1") or "127.0.0.1",
            port=port,
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> Settings:
        """读取 YAML 配置；未指定路径且默认文件不存在时返回默认配置。"""
        explicit = path is not None
        config_path = Path(path) if path is not None else _DEFAULT_CONFIG_PATH
        if not config_path.exists():
            if explicit:
                raise ConfigError(f"配置文件不存在：{config_path}")
            return cls()
        try:
            raw = config_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"无法读取配置文件 {config_path}：{exc}") from exc
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise ConfigError(f"配置文件 {config_path} 不是有效 YAML：{exc}") from exc
        if data is not None and not isinstance(data, Mapping):
            raise ConfigError(f"配置文件 {config_path} 的根节点必须是映射")
        return cls.from_mapping(cast(Mapping[str, Any] | None, data))


def _parse_access_keys(value: Any) -> tuple[AccessKeyConfig, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError("access_keys 必须是列表")
    access_keys: list[AccessKeyConfig] = []
    seen_keys: set[str] = set()
    seen_names: set[str] = set()
    for index, raw in enumerate(value):
        path = f"access_keys[{index}]"
        access_key = AccessKeyConfig.from_mapping(_mapping(raw, path), path)
        if access_key.key in seen_keys:
            raise ConfigError(f"{path}.key 与其他 access key 重复")
        if access_key.name in seen_names:
            raise ConfigError(f"{path}.name 与其他 access key 重复")
        seen_keys.add(access_key.key)
        seen_names.add(access_key.name)
        access_keys.append(access_key)
    return tuple(access_keys)
