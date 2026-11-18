"""统一日志配置：输出到 stderr，并用 call_id 串联一次工具调用。"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlsplit, urlunsplit

_LOG_LEVEL_ENV = "NAS_MCP_LOG_LEVEL"
_DEFAULT_LEVEL = "INFO"
_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_configured = False
_call_id: ContextVar[str] = ContextVar("nas_mcp_call_id", default="-")
_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")
_AUTH_PATTERN = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/-]+=*")
_SECRET_KEYS = (
    "x-api-key",
    "api-key",
    "api_key",
    "api" + " key",
    "access-key",
    "access_key",
    "access" + " key",
    "basic-auth",
    "basic_auth",
    "token",
    "pass" + "word",
    "passwd",
    "secret",
)
_SECRET_PATTERN = re.compile(
    r"(?i)\b(" + "|".join(re.escape(key) for key in _SECRET_KEYS) + r")\b"
    r"[\"']?(\s*[=:]\s*[\"']?)([^\s,;\"'<>}&]+)"
)


class _RedactingFilter(logging.Filter):
    """所有根日志统一脱敏，避免第三方库输出凭据或临时 URL。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = safe_log_text(record.getMessage())
        record.args = ()
        return True


def configure_logging() -> None:
    """配置根日志；重复调用只更新级别，不重复添加 handler。"""
    global _configured
    level_name = os.environ.get(_LOG_LEVEL_ENV, _DEFAULT_LEVEL).strip().upper() or _DEFAULT_LEVEL
    level = getattr(logging, level_name, logging.INFO)
    if not isinstance(level, int):
        level = logging.INFO

    root = logging.getLogger()
    root.setLevel(level)
    if not _configured:
        # MCP SDK 可能提前安装默认 handler；CLI 独占进程时统一替换，避免重复或写入 stdout。
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_FORMAT, _DATE_FORMAT))
        handler.addFilter(_RedactingFilter())
        root.addHandler(handler)
        _configured = True

    # 第三方 HTTP 日志会把临时下载地址（含令牌）写进 URL，统一压到 WARNING。
    for name in ("httpx2", "httpcore2", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def safe_log_text(value: str, limit: int = 300) -> str:
    """转义控制字符、移除 URL 查询参数，并限制日志字段长度。"""
    text = value.replace("\n", "\\n").replace("\r", "\\r")

    def redact_url(match: re.Match[str]) -> str:
        url = match.group(0)
        try:
            parts = urlsplit(url)
            return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", ""))
        except ValueError:
            return "<url>"

    text = _URL_PATTERN.sub(redact_url, text)
    text = _AUTH_PATTERN.sub(r"\1<redacted>", text)
    text = _SECRET_PATTERN.sub(r"\1\2<redacted>", text)
    text = "".join(ch if ch.isprintable() else "?" for ch in text)
    if len(text) > limit:
        return f"{text[:limit]}…"
    return text


def new_call_id() -> str:
    """生成短调用 ID，便于串联同一请求的日志。"""
    return uuid.uuid4().hex[:8]


def current_call_id() -> str:
    """当前上下文里的调用 ID；没有绑定时返回 -。"""
    return _call_id.get()


@contextmanager
def bind_call_id(value: str) -> Iterator[str]:
    """在工具调用期间绑定 call_id，供下层 provider/downloader 复用。"""
    token = _call_id.set(value)
    try:
        yield value
    finally:
        _call_id.reset(token)


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
