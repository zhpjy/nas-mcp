from __future__ import annotations

import os
from pathlib import Path

import pytest

from nas_mcp.config import AccessKeyConfig, Settings
from nas_mcp.errors import ConfigError


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """清除宿主的 NAS_MCP_* 变量，避免环境影响测试结果。"""
    for name in list(os.environ):
        if name.startswith("NAS_MCP_"):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def config_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离 HOME、XDG 配置目录和 NAS_MCP_CONFIG，避免读到本机配置。"""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    return home


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
    assert settings.extra_instructions == ""


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


def test_mcp_extra_instructions() -> None:
    settings = Settings.from_mapping(
        {"mcp": {"extra_instructions": "  每次下载前先查分类。\n必须传 category。  "}}
    )
    # 仅去掉首尾空白，保留换行结构
    assert settings.extra_instructions == "每次下载前先查分类。\n必须传 category。"

    with pytest.raises(ConfigError, match="必须是字符串"):
        Settings.from_mapping({"mcp": {"extra_instructions": ["分类"]}})


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


def test_missing_default_config_uses_defaults(config_env: Path) -> None:
    settings = Settings.load()
    assert settings.config_path is None
    assert settings.adult_enabled is False
    assert settings.mteam.enabled is False


def test_local_config_is_used(config_env: Path, tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("adult_enabled: true\n", encoding="utf-8")

    settings = Settings.load()

    assert settings.adult_enabled is True
    assert settings.config_path == config.resolve()


def test_user_config_is_used_outside_project(config_env: Path) -> None:
    config = config_env / ".config" / "nas-mcp" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("adult_enabled: true\n", encoding="utf-8")

    settings = Settings.load()

    assert settings.adult_enabled is True
    assert settings.config_path == config.resolve()


def test_xdg_config_home_is_used(
    config_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xdg_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
    config = xdg_home / "nas-mcp" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("adult_enabled: true\n", encoding="utf-8")

    settings = Settings.load()

    assert settings.adult_enabled is True
    assert settings.config_path == config.resolve()


def test_local_config_wins_over_user_config(config_env: Path, tmp_path: Path) -> None:
    user_config = config_env / ".config" / "nas-mcp" / "config.yaml"
    user_config.parent.mkdir(parents=True)
    user_config.write_text("adult_enabled: false\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("adult_enabled: true\n", encoding="utf-8")

    assert Settings.load().adult_enabled is True


def test_env_config_wins_over_local_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "config.yaml").write_text("adult_enabled: false\n", encoding="utf-8")
    custom = tmp_path / "custom.yaml"
    custom.write_text("adult_enabled: true\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NAS_MCP_CONFIG", str(custom))

    settings = Settings.load()

    assert settings.adult_enabled is True
    assert settings.config_path == custom


def test_missing_env_config_is_an_error(
    config_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NAS_MCP_CONFIG", str(tmp_path / "missing.yaml"))

    with pytest.raises(ConfigError, match="不存在"):
        Settings.load()


def test_env_only_config(config_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAS_MCP_MTEAM_API_KEY", "env-key")
    monkeypatch.setenv("NAS_MCP_QBITTORRENT_URL", "qbt:8080")
    monkeypatch.setenv("NAS_MCP_QBITTORRENT_USERNAME", "admin")
    monkeypatch.setenv("NAS_MCP_QBITTORRENT_PASSWORD", "pass")

    settings = Settings.load()

    assert settings.config_path is None
    assert settings.mteam.api_key == "env-key"
    assert settings.qbittorrent.url == "http://qbt:8080"
    assert settings.qbittorrent.username == "admin"
    assert settings.qbittorrent.enabled is True
    assert set(settings.env_overrides) == {
        "NAS_MCP_MTEAM_API_KEY",
        "NAS_MCP_QBITTORRENT_URL",
        "NAS_MCP_QBITTORRENT_USERNAME",
        "NAS_MCP_QBITTORRENT_PASSWORD",
    }


def test_env_overrides_file(
    config_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config.yaml").write_text(
        "mteam:\n  api_key: file-key\n  timeout: 10\nqbittorrent:\n  category: movies\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NAS_MCP_MTEAM_API_KEY", "env-key")

    settings = Settings.load()

    assert settings.mteam.api_key == "env-key"
    assert settings.mteam.timeout == 10.0
    assert settings.qbittorrent.category == "movies"


def test_env_bool_int_and_transport(config_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAS_MCP_ADULT_ENABLED", "true")
    monkeypatch.setenv("NAS_MCP_PORT", "9100")
    monkeypatch.setenv("NAS_MCP_TRANSPORT", "stdio")

    settings = Settings.load()

    assert settings.adult_enabled is True
    assert settings.port == 9100
    assert settings.transport == "stdio"


def test_env_access_keys(config_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "NAS_MCP_ACCESS_KEYS",
        '[{"name": "日常", "key": "k1", "adult_enabled": false},'
        ' {"name": "私人", "key": "k2", "adult_enabled": true}]',
    )

    settings = Settings.load()

    assert [(item.name, item.key) for item in settings.access_keys] == [
        ("日常", "k1"),
        ("私人", "k2"),
    ]
    assert settings.adult_enabled_for(settings.access_keys[1]) is True


def test_env_access_keys_replace_file(
    config_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config.yaml").write_text(
        "access_keys:\n  - name: 文件\n    key: file-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NAS_MCP_ACCESS_KEYS", '[{"name": "环境", "key": "env-key"}]')

    settings = Settings.load()

    assert [item.name for item in settings.access_keys] == ["环境"]


def test_env_access_keys_error_mentions_variable(
    config_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "NAS_MCP_ACCESS_KEYS",
        '[{"name": "一", "key": "same"}, {"name": "二", "key": "same"}]',
    )

    with pytest.raises(ConfigError, match="NAS_MCP_ACCESS_KEYS"):
        Settings.load()


def test_invalid_env_access_keys(config_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAS_MCP_ACCESS_KEYS", "[{")

    with pytest.raises(ConfigError, match="NAS_MCP_ACCESS_KEYS"):
        Settings.load()


def test_invalid_env_values(config_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAS_MCP_MTEAM_TIMEOUT", "abc")
    with pytest.raises(ConfigError, match="NAS_MCP_MTEAM_TIMEOUT"):
        Settings.load()

    monkeypatch.setenv("NAS_MCP_ADULT_ENABLED", "maybe")
    with pytest.raises(ConfigError, match="NAS_MCP_ADULT_ENABLED"):
        Settings.load()


def test_env_tags(config_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAS_MCP_QBITTORRENT_TAGS", "pt, 4k ,")

    assert Settings.load().qbittorrent.tags == ("pt", "4k")


def test_unknown_env_is_ignored(config_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAS_MCP_UNKNOWN_FIELD", "x")

    settings = Settings.load()

    assert settings.env_overrides == ()


def test_env_secrets_are_not_in_repr(config_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAS_MCP_MTEAM_API_KEY", "env-mteam-secret")
    monkeypatch.setenv("NAS_MCP_QBITTORRENT_PASSWORD", "env-qbt-secret")

    rendered = repr(Settings.load())

    assert "env-mteam-secret" not in rendered
    assert "env-qbt-secret" not in rendered


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
