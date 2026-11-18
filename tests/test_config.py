from __future__ import annotations

from pathlib import Path

import pytest

from nas_mcp.config import AccessKeyConfig, Settings
from nas_mcp.errors import ConfigError


def test_defaults() -> None:
    settings = Settings.from_mapping()
    assert settings.adult_enabled is False
    assert settings.access_keys == ()
    assert settings.mteam.api_base == "https://api.m-team.cc/api"
    assert settings.mteam.site_url == "https://kp.m-team.cc"
    assert settings.mteam.enabled is False
    assert settings.qbittorrent.enabled is False
    assert settings.transport == "streamable-http"
    assert settings.port == 8000


def test_qbittorrent_basic_auth_and_url_normalization() -> None:
    settings = Settings.from_mapping(
        {
            "qbittorrent": {
                "url": "qbt:8080/",
                "basic_auth": "admin:secret:with-colon",
                "tags": ["pt", " 4k ", ""],
            }
        }
    )
    assert settings.qbittorrent.url == "http://qbt:8080"
    assert settings.qbittorrent.basic_auth == ("admin", "secret:with-colon")
    assert settings.qbittorrent.use_basic_auth is True
    assert settings.qbittorrent.tags == ("pt", "4k")


def test_qbittorrent_basic_auth_requires_username_and_password() -> None:
    for value in ("username", "username:", ":password"):
        with pytest.raises(ConfigError, match="username:password"):
            Settings.from_mapping({"qbittorrent": {"basic_auth": value}})


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ConfigError, match="未知字段"):
        Settings.from_mapping({"qbittorrent": {"api_key": "legacy"}})


def test_qbittorrent_password_mode() -> None:
    settings = Settings.from_mapping(
        {
            "qbittorrent": {
                "url": "http://qbt:8080",
                "username": "admin",
                "password": "pass",
            }
        }
    )
    assert settings.qbittorrent.enabled is True
    assert settings.qbittorrent.use_basic_auth is False


def test_secrets_are_not_in_repr() -> None:
    settings = Settings.from_mapping(
        {
            "access_keys": [{"name": "私人助手", "key": "access-secret"}],
            "mteam": {"api_key": "mteam-secret"},
            "qbittorrent": {
                "url": "http://qbt:8080",
                "basic_auth": "qbt-user:qbt-secret",
                "password": "qbt-pass",
            },
        }
    )
    rendered = repr(settings)
    assert "access-secret" not in rendered
    assert "mteam-secret" not in rendered
    assert "qbt-secret" not in rendered
    assert "qbt-pass" not in rendered


def test_invalid_transport() -> None:
    with pytest.raises(ConfigError):
        Settings.from_mapping({"mcp": {"transport": "websocket"}})


def test_invalid_port() -> None:
    with pytest.raises(ConfigError):
        Settings.from_mapping({"mcp": {"port": 70000}})


def test_invalid_mteam_base_url() -> None:
    with pytest.raises(ConfigError):
        Settings.from_mapping({"mteam": {"api_base": "api.m-team.cc/api"}})


def test_access_key_adult_tristate() -> None:
    settings = Settings.from_mapping(
        {
            "adult_enabled": False,
            "access_keys": [
                {"name": "启用", "key": "key-enabled", "adult_enabled": True},
                {"name": "未启用", "key": "key-disabled", "adult_enabled": False},
                {"name": "继承", "key": "key-inherit", "adult_enabled": None},
                {"name": "省略", "key": "key-omitted"},
            ],
        }
    )
    enabled, disabled, inherited, omitted = settings.access_keys

    assert settings.adult_enabled_for(enabled) is True
    assert settings.adult_enabled_for(disabled) is False
    assert settings.adult_enabled_for(inherited) is False
    assert settings.adult_enabled_for(omitted) is False
    assert settings.adult_enabled_for(None) is False


def test_access_key_inherits_global_true() -> None:
    settings = Settings.from_mapping(
        {
            "adult_enabled": True,
            "access_keys": [
                {"name": "继承", "key": "key-inherit"},
                {"name": "未启用", "key": "key-disabled", "adult_enabled": False},
            ],
        }
    )
    inherited, disabled = settings.access_keys

    assert settings.adult_enabled_for(inherited) is True
    assert settings.adult_enabled_for(disabled) is False


def test_access_key_requires_name_and_key() -> None:
    for item in ({"key": "key"}, {"name": "名称"}, {"name": " ", "key": "key"}):
        with pytest.raises(ConfigError):
            Settings.from_mapping({"access_keys": [item]})


def test_access_key_rejects_duplicates() -> None:
    with pytest.raises(ConfigError, match="key 与其他 access key 重复"):
        Settings.from_mapping(
            {
                "access_keys": [
                    {"name": "一", "key": "same"},
                    {"name": "二", "key": "same"},
                ]
            }
        )
    with pytest.raises(ConfigError, match="name 与其他 access key 重复"):
        Settings.from_mapping(
            {
                "access_keys": [
                    {"name": "同名", "key": "one"},
                    {"name": "同名", "key": "two"},
                ]
            }
        )


def test_access_key_adult_must_be_bool_or_null() -> None:
    with pytest.raises(ConfigError, match="true、false 或 null"):
        Settings.from_mapping(
            {"access_keys": [{"name": "名称", "key": "key", "adult_enabled": "yes"}]}
        )


def test_load_yaml(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """
adult_enabled: true
access_keys:
  - name: 私人助手
    key: secret-key
    adult_enabled: null
mcp:
  transport: stdio
  port: 9000
mteam:
  api_key: mteam-key
qbittorrent:
  url: qbt:8080
""",
        encoding="utf-8",
    )

    settings = Settings.load(config)

    assert settings.adult_enabled is True
    assert settings.access_keys == (AccessKeyConfig("私人助手", "secret-key", None),)
    assert settings.transport == "stdio"
    assert settings.port == 9000
    assert settings.mteam.api_key == "mteam-key"
    assert settings.qbittorrent.url == "http://qbt:8080"


def test_missing_explicit_config_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="不存在"):
        Settings.load(tmp_path / "missing.yaml")


def test_missing_default_config_uses_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings.load()
    assert settings.adult_enabled is False
    assert settings.mteam.enabled is False


def test_invalid_yaml(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("adult_enabled: [", encoding="utf-8")
    with pytest.raises(ConfigError, match="不是有效 YAML"):
        Settings.load(config)


def test_yaml_root_must_be_mapping(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("- adult_enabled: true\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="根节点必须是映射"):
        Settings.load(config)


def test_example_config_is_valid() -> None:
    example = Path(__file__).resolve().parents[1] / "config.example.yaml"
    settings = Settings.load(example)
    assert settings.adult_enabled is False
