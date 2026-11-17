from __future__ import annotations

import hashlib
from typing import Any


def bencode(value: Any) -> bytes:
    if isinstance(value, int):
        return b"i" + str(value).encode() + b"e"
    if isinstance(value, str):
        value = value.encode()
    if isinstance(value, bytes):
        return str(len(value)).encode() + b":" + value
    if isinstance(value, list):
        return b"l" + b"".join(bencode(item) for item in value) + b"e"
    if isinstance(value, dict):
        items = sorted(value.items())
        return b"d" + b"".join(bencode(key) + bencode(item) for key, item in items) + b"e"
    raise TypeError(type(value))


def make_torrent() -> tuple[bytes, str]:
    info = {
        "name": "Test Torrent",
        "piece length": 16384,
        "pieces": b"0" * 20,
        "length": 12345,
    }
    torrent = {
        "announce": "https://tracker.example/announce",
        "info": info,
    }
    return bencode(torrent), hashlib.sha1(bencode(info), usedforsecurity=False).hexdigest()
