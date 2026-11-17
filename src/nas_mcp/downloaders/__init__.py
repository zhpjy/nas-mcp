"""下载器注册表。"""

from __future__ import annotations

from ..config import Settings
from .base import Downloader
from .qbittorrent import QBittorrentDownloader


def build_downloaders(settings: Settings) -> dict[str, Downloader]:
    downloaders: list[Downloader] = [QBittorrentDownloader(settings.qbittorrent)]
    return {downloader.id: downloader for downloader in downloaders}
