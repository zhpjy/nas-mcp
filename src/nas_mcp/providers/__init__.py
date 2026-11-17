"""PT 站提供者注册表。"""

from __future__ import annotations

from ..config import Settings
from .base import PTProvider
from .mteam import MTeamProvider


def build_providers(settings: Settings) -> dict[str, PTProvider]:
    providers: list[PTProvider] = [MTeamProvider(settings.mteam)]
    return {provider.id: provider for provider in providers}
