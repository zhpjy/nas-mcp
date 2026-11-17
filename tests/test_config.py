from __future__ import annotations

import pytest

from nas_mcp.config import Settings
from nas_mcp.errors import ConfigError


def test_defaults() -> None:
    settings = Settings.from_env({})
    assert settings.mteam.api_base == "https://api.m-team.cc/api"
    assert settings.mteam.site_url == "https://kp.m-team.cc"
    assert settings.mteam.enabled is False
    assert settings.qbittorrent.enabled is False
    assert settings.transport == "stdio"
    assert settings.port == 8000


def test_qbittorrent_basic_auth_and_url_normalization() -> None:
    settings = Settings.from_env(
        {
            "QBITTORRENT_URL": "qbt:8080/",
            "QBITTORRENT_BASIC_AUTH": "admin:secret:with-colon",
            "QBITTORRENT_TAGS": "pt, 4k,,",
        }
    )
    assert settings.qbittorrent.url == "http://qbt:8080"
    assert settings.qbittorrent.basic_auth == ("admin", "secret:with-colon")
    assert settings.qbittorrent.use_basic_auth is True
    assert settings.qbittorrent.tags == ("pt", "4k")


def test_qbittorrent_basic_auth_requires_username_and_password() -> None:
    for value in ("username", "username:", ":password"):
        with pytest.raises(ConfigError, match="username:password"):
            Settings.from_env({"QBITTORRENT_BASIC_AUTH": value})


def test_legacy_qbittorrent_api_key_is_ignored() -> None:
    settings = Settings.from_env(
        {
            "QBITTORRENT_URL": "http://qbt:8080",
            "QBITTORRENT_API_KEY": "legacy-token",
        }
    )
    assert settings.qbittorrent.use_basic_auth is False


def test_qbittorrent_password_mode() -> None:
    settings = Settings.from_env(
        {
            "QBITTORRENT_URL": "http://qbt:8080",
            "QBITTORRENT_USERNAME": "admin",
            "QBITTORRENT_PASSWORD": "pass",
        }
    )
    assert settings.qbittorrent.enabled is True
    assert settings.qbittorrent.use_basic_auth is False


def test_secrets_are_not_in_repr() -> None:
    settings = Settings.from_env(
        {
            "MTEAM_API_KEY": "mteam-secret",
            "QBITTORRENT_URL": "http://qbt:8080",
            "QBITTORRENT_BASIC_AUTH": "qbt-user:qbt-secret",
            "QBITTORRENT_PASSWORD": "qbt-pass",
        }
    )
    rendered = repr(settings)
    assert "mteam-secret" not in rendered
    assert "qbt-secret" not in rendered
    assert "qbt-pass" not in rendered


def test_invalid_transport() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({"MCP_TRANSPORT": "websocket"})


def test_invalid_port() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({"MCP_PORT": "70000"})


def test_invalid_mteam_base_url() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({"MTEAM_API_BASE": "api.m-team.cc/api"})
