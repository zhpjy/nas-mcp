"""可以在工具结果中安全展示给模型的业务异常。"""

from __future__ import annotations


class NasMcpError(Exception):
    """业务错误基类。"""


class ConfigError(NasMcpError):
    """配置缺失或格式错误。"""


class ProviderError(NasMcpError):
    """PT 站接口或响应错误。"""


class DownloaderError(NasMcpError):
    """下载器接口或响应错误。"""
