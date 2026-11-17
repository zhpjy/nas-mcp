"""种子的 bencode 校验、名称和 v1 infohash 解析。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

_MAX_DEPTH = 64


class BencodeError(ValueError):
    """种子文件不是合法的 bencode。"""


@dataclass(frozen=True)
class TorrentMetadata:
    infohash: str
    name: str | None


def _parse_bytes(data: bytes, index: int) -> tuple[bytes, int]:
    colon = data.find(b":", index)
    if colon < 0:
        raise BencodeError("缺少字符串长度分隔符")
    length_bytes = data[index:colon]
    if not length_bytes.isdigit():
        raise BencodeError("字符串长度不是数字")
    length = int(length_bytes)
    start = colon + 1
    end = start + length
    if end > len(data):
        raise BencodeError("字符串长度超出数据范围")
    return data[start:end], end


def _parse_int(data: bytes, index: int) -> tuple[int, int]:
    end = data.find(b"e", index)
    if end < 0:
        raise BencodeError("整数缺少结束符")
    raw = data[index + 1 : end]
    digits = raw[1:] if raw.startswith(b"-") else raw
    if not digits or not digits.isdigit():
        raise BencodeError("整数格式非法")
    if len(digits) > 1 and digits.startswith(b"0"):
        raise BencodeError("整数格式非法")
    if raw == b"-0":
        raise BencodeError("整数格式非法")
    return int(raw), end + 1


def _skip_value(data: bytes, index: int, depth: int = 0) -> int:
    if depth > _MAX_DEPTH:
        raise BencodeError("bencode 嵌套层级过深")
    token = data[index : index + 1]
    if token == b"i":
        return _parse_int(data, index)[1]
    if token == b"l":
        index += 1
        while data[index : index + 1] != b"e":
            if index >= len(data):
                raise BencodeError("列表缺少结束符")
            index = _skip_value(data, index, depth + 1)
        return index + 1
    if token == b"d":
        index += 1
        while data[index : index + 1] != b"e":
            if index >= len(data):
                raise BencodeError("字典缺少结束符")
            _, index = _parse_bytes(data, index)
            index = _skip_value(data, index, depth + 1)
        return index + 1
    if token.isdigit():
        return _parse_bytes(data, index)[1]
    raise BencodeError(f"无法识别的 bencode 类型：{token!r}")


def _decode_value(data: bytes, index: int, depth: int = 0) -> tuple[object, int]:
    if depth > _MAX_DEPTH:
        raise BencodeError("bencode 嵌套层级过深")
    token = data[index : index + 1]
    if token == b"i":
        return _parse_int(data, index)
    if token == b"l":
        index += 1
        values: list[object] = []
        while data[index : index + 1] != b"e":
            if index >= len(data):
                raise BencodeError("列表缺少结束符")
            value, index = _decode_value(data, index, depth + 1)
            values.append(value)
        return values, index + 1
    if token == b"d":
        index += 1
        values_dict: dict[bytes, object] = {}
        while data[index : index + 1] != b"e":
            if index >= len(data):
                raise BencodeError("字典缺少结束符")
            key, index = _parse_bytes(data, index)
            value, index = _decode_value(data, index, depth + 1)
            values_dict[key] = value
        return values_dict, index + 1
    if token.isdigit():
        return _parse_bytes(data, index)
    raise BencodeError(f"无法识别的 bencode 类型：{token!r}")


def parse_torrent_metadata(data: bytes) -> TorrentMetadata:
    """解析种子名称并计算 v1 infohash。"""
    if not data.startswith(b"d"):
        raise BencodeError("种子文件必须以 bencode 字典开头")

    index = 1
    info_span: tuple[int, int] | None = None
    name: str | None = None

    while data[index : index + 1] != b"e":
        if index >= len(data):
            raise BencodeError("顶层字典缺少结束符")
        key, index = _parse_bytes(data, index)
        value_start = index
        value_end = _skip_value(data, index)
        if key == b"info":
            info_span = (value_start, value_end)
            info, _ = _decode_value(data, value_start)
            if not isinstance(info, dict):
                raise BencodeError("info 字段不是字典")
            raw_name = info.get(b"name.utf-8") or info.get(b"name")
            if isinstance(raw_name, bytes):
                name = raw_name.decode("utf-8", errors="replace")
        index = value_end

    if index >= len(data):
        raise BencodeError("顶层字典缺少结束符")
    if info_span is None:
        raise BencodeError("种子缺少 info 字段")

    info_start, info_end = info_span
    digest = hashlib.sha1(data[info_start:info_end], usedforsecurity=False).hexdigest()
    return TorrentMetadata(infohash=digest, name=name)


def validate_torrent(data: bytes) -> TorrentMetadata:
    """校验种子内容并返回元数据。"""
    if not data:
        raise BencodeError("种子内容为空")
    return parse_torrent_metadata(data)
