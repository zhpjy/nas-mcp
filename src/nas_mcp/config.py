"""从 YAML 配置文件读取运行配置。"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast

import yaml

from .errors import ConfigError

_DEFAULT_MCP_PORT = 8000
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_TORRENT_MB = 32
_ENV_CONFIG_PATH = "NAS_MCP_CONFIG"


def _config_candidates() -> tuple[Path, ...]:
    """默认配置位置：当前目录优先，其次是用户配置目录。"""
    candidates = [Path("config.yaml")]
    config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base_dir = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    candidates.append(base_dir / "nas-mcp" / "config.yaml")
    return tuple(candidates)


def _env_config_path() -> Path | None:
    """读取 NAS_MCP_CONFIG；未设置时返回 None。"""
    value = os.environ.get(_ENV_CONFIG_PATH, "").strip()
    if not value:
        return None
    return Path(value).expanduser()


def _env_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("必须是 true 或 false")


def _env_int(value: str) -> int:
    try:
        return int(value.strip())
    except ValueError:
        raise ValueError("必须是整数") from None


def _env_float(value: str) -> float:
    try:
        return float(value.strip())
    except ValueError:
        raise ValueError("必须是数字") from None


def _env_tags(value: str) -> list[str]:
    """逗号分隔的标签列表。"""
    return [tag.strip() for tag in value.split(",") if tag.strip()]


def _env_access_keys(value: str) -> Any:
    """读取 access_keys 环境变量，支持 JSON 或 YAML 列表。"""
    try:
        data = yaml.safe_load(value)
    except yaml.YAMLError as exc:
        raise ValueError(f"不是有效 JSON/YAML：{exc}") from exc
    # 提前校验一次，报错信息才能带上环境变量名
    _parse_access_keys(data)
    return data


# 环境变量白名单：变量名 -> (配置路径, 解析函数)。不在此表中的 NAS_MCP_* 变量忽略。
_ENV_FIELDS: dict[str, tuple[tuple[str, ...], Callable[[str], Any]]] = {
    "NAS_MCP_ADULT_ENABLED": (("adult_enabled",), _env_bool),
    "NAS_MCP_ACCESS_KEYS": (("access_keys",), _env_access_keys),
    "NAS_MCP_TRANSPORT": (("mcp", "transport"), str),
    "NAS_MCP_HOST": (("mcp", "host"), str),
    "NAS_MCP_PORT": (("mcp", "port"), _env_int),
    "NAS_MCP_EXTRA_INSTRUCTIONS": (("mcp", "extra_instructions"), str),
    "NAS_MCP_DEFAULT_SITE": (("defaults", "site"), str),
    "NAS_MCP_DEFAULT_DOWNLOADER": (("defaults", "downloader"), str),
    "NAS_MCP_MTEAM_API_KEY": (("mteam", "api_key"), str),
    "NAS_MCP_MTEAM_API_BASE": (("mteam", "api_base"), str),
    "NAS_MCP_MTEAM_SITE_URL": (("mteam", "site_url"), str),
    "NAS_MCP_MTEAM_TIMEOUT": (("mteam", "timeout"), _env_float),
    "NAS_MCP_MTEAM_MAX_TORRENT_MB": (("mteam", "max_torrent_mb"), _env_int),
    "NAS_MCP_QBITTORRENT_URL": (("qbittorrent", "url"), str),
    "NAS_MCP_QBITTORRENT_BASIC_AUTH": (("qbittorrent", "basic_auth"), str),
    "NAS_MCP_QBITTORRENT_USERNAME": (("qbittorrent", "username"), str),
    "NAS_MCP_QBITTORRENT_PASSWORD": (("qbittorrent", "password"), str),
    "NAS_MCP_QBITTORRENT_SAVE_PATH": (("qbittorrent", "save_path"), str),
    "NAS_MCP_QBITTORRENT_CATEGORY": (("qbittorrent", "category"), str),
    "NAS_MCP_QBITTORRENT_TAGS": (("qbittorrent", "tags"), _env_tags),
    "NAS_MCP_QBITTORRENT_TIMEOUT": (("qbittorrent", "timeout"), _env_float),
}


def _env_mapping() -> tuple[dict[str, Any], tuple[str, ...]]:
    """把白名单内的环境变量组装成配置映射，并返回实际生效的变量名。"""
    overrides: dict[str, Any] = {}
    applied: list[str] = []
    for name, (path, parse) in _ENV_FIELDS.items():
        raw = os.environ.get(name)
        if raw is None:
            continue
        try:
            value = parse(raw)
        except ConfigError as exc:
            raise ConfigError(f"环境变量 {name}：{exc}") from exc
        except ValueError as exc:
            raise ConfigError(f"环境变量 {name} 格式错误：{exc}") from exc
        cursor = overrides
        for key in path[:-1]:
            child = cursor.get(key)
            if not isinstance(child, dict):
                child = {}
                cursor[key] = child
            cursor = child
        cursor[path[-1]] = value
        applied.append(name)
    return overrides, tuple(applied)


def _merge_mapping(base: Mapping[str, Any], extra: Mapping[str, Any]) -> dict[str, Any]:
    """递归合并配置映射，extra 覆盖同名字段。"""
    merged = dict(base)
    for key, value in extra.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _merge_mapping(existing, value)
        else:
            merged[key] = value
    return merged


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
    # 追加到 MCP initialize 响应的部署者自定义要求
    extra_instructions: str = ""
    # 实际读取的配置文件，仅用于诊断；不参与相等比较和 repr
    config_path: Path | None = field(default=None, compare=False, repr=False)
    # 实际生效的环境变量名，仅用于诊断，不含具体值
    env_overrides: tuple[str, ...] = field(default=(), compare=False, repr=False)

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
        _only_keys(mcp, {"transport", "host", "port", "extra_instructions"}, "mcp")
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
            extra_instructions=_string(mcp, "extra_instructions", "mcp"),
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> Settings:
        """读取配置。

        文件依次查找 ``path`` 参数、``NAS_MCP_CONFIG`` 环境变量、当前目录的
        ``config.yaml``、``~/.config/nas-mcp/config.yaml``；显式指定的文件
        不存在时报错。随后用 ``NAS_MCP_*`` 环境变量覆盖文件中的同名字段，
        其中 ``NAS_MCP_ACCESS_KEYS`` 整表替换 ``access_keys``。
        两者都没有时返回默认配置。
        """
        config_path: Path | None
        if path is not None:
            config_path = Path(path).expanduser()
        elif (env_path := _env_config_path()) is not None:
            config_path = env_path
        else:
            config_path = next(
                (candidate.resolve() for candidate in _config_candidates() if candidate.exists()),
                None,
            )

        file_data: Mapping[str, Any] = {}
        if config_path is not None:
            if not config_path.exists():
                raise ConfigError(f"配置文件不存在：{config_path}")
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
            if data is not None:
                file_data = cast(Mapping[str, Any], data)

        env_data, env_overrides = _env_mapping()
        return replace(
            cls.from_mapping(_merge_mapping(file_data, env_data)),
            config_path=config_path,
            env_overrides=env_overrides,
        )


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
