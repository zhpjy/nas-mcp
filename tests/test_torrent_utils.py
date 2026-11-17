from __future__ import annotations

import pytest

from nas_mcp.torrent_utils import BencodeError, parse_torrent_metadata, validate_torrent

from .helpers import bencode, make_torrent


def test_parse_torrent_metadata() -> None:
    content, expected_hash = make_torrent()
    metadata = parse_torrent_metadata(content)
    assert metadata.infohash == expected_hash
    assert metadata.name == "Test Torrent"


def test_validate_torrent_rejects_non_bencode() -> None:
    with pytest.raises(BencodeError):
        validate_torrent(b"not-a-torrent")


def test_validate_torrent_rejects_missing_info() -> None:
    with pytest.raises(BencodeError):
        validate_torrent(bencode({"announce": "https://tracker.example"}))


def test_validate_torrent_rejects_truncated_data() -> None:
    content, _ = make_torrent()
    with pytest.raises(BencodeError):
        parse_torrent_metadata(content[:-3])
