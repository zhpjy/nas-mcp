"""面向模型的可读格式化和 qBittorrent 状态映射。"""

from __future__ import annotations

_UNITS = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
_QB_ETA_INFINITY = 8_640_000

# qBittorrent 原始状态 -> (内部状态, 中文描述)
_STATE_MAP: dict[str, tuple[str, str]] = {
    "downloading": ("downloading", "下载中"),
    "stalledDL": ("downloading", "等待连接"),
    "metaDL": ("downloading", "获取元数据"),
    "forcedMetaDL": ("downloading", "获取元数据"),
    "forcedDL": ("downloading", "强制下载"),
    "allocating": ("downloading", "分配空间"),
    "queuedDL": ("queued", "排队下载"),
    "checkingDL": ("checking", "校验中"),
    "checkingUP": ("checking", "校验中"),
    "checkingResumeData": ("checking", "校验中"),
    "moving": ("moving", "移动文件"),
    "uploading": ("seeding", "做种中"),
    "stalledUP": ("seeding", "做种中（无活动）"),
    "forcedUP": ("seeding", "强制做种"),
    "queuedUP": ("queued", "排队做种"),
    "stoppedDL": ("stopped", "已停止"),
    "stoppedUP": ("stopped", "已停止（完成）"),
    "pausedDL": ("stopped", "已暂停"),
    "pausedUP": ("stopped", "已暂停（完成）"),
    "error": ("error", "错误"),
    "missingFiles": ("error", "文件丢失"),
    "unknown": ("unknown", "未知"),
}

_STATUS_ALIASES: dict[str, str] = {
    "all": "all",
    "全部": "all",
    "所有": "all",
    "downloading": "downloading",
    "download": "downloading",
    "下载": "downloading",
    "下载中": "downloading",
    "seeding": "seeding",
    "seed": "seeding",
    "做种": "seeding",
    "做种中": "seeding",
    "completed": "completed",
    "complete": "completed",
    "完成": "completed",
    "已完成": "completed",
    "stopped": "stopped",
    "paused": "stopped",
    "停止": "stopped",
    "已停止": "stopped",
    "暂停": "stopped",
    "已暂停": "stopped",
    "error": "error",
    "errored": "error",
    "错误": "error",
}


def human_bytes(value: int | float | None) -> str:
    """把字节数转换成可读字符串。"""
    if value is None or value < 0:
        return "未知"
    amount = float(value)
    for unit in _UNITS:
        if amount < 1024 or unit == _UNITS[-1]:
            return f"{amount:.2f}".rstrip("0").rstrip(".") + f" {unit}"
        amount /= 1024
    return f"{amount:.2f} {_UNITS[-1]}"


def human_speed(bytes_per_second: int | float | None) -> str:
    """把字节/秒转换成可读速度。"""
    if not bytes_per_second or bytes_per_second <= 0:
        return "0 B/s"
    return f"{human_bytes(bytes_per_second)}/s"


def human_eta(seconds: int | None) -> str:
    """把秒数转换成中文 ETA。"""
    if seconds is None or seconds < 0 or seconds >= _QB_ETA_INFINITY:
        return "未知"
    if seconds == 0:
        return "完成"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    if days:
        return f"{days}天{hours}小时"
    if hours:
        return f"{hours}小时{minutes}分"
    if minutes:
        return f"{minutes}分{secs}秒"
    return f"{secs}秒"


def state_label(state: str) -> tuple[str, str]:
    """返回内部状态和中文描述。"""
    return _STATE_MAP.get(state, ("unknown", state or "未知"))


def normalize_status_filter(value: str) -> str:
    """把用户输入的状态别名标准化。"""
    key = value.strip().lower()
    return _STATUS_ALIASES.get(key, "")


def state_priority(state: str) -> int:
    """下载中的任务排在前面，便于模型优先看到进度。"""
    return {
        "downloading": 0,
        "queued": 1,
        "checking": 2,
        "moving": 2,
        "error": 3,
        "stopped": 4,
        "seeding": 5,
        "unknown": 6,
    }.get(state, 9)
