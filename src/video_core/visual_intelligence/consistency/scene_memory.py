"""Scene Memory — tracks identity usage across scenes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SceneMemoryEntry:
    scene_id: str
    video_id: str
    identities_used: list[str] = field(default_factory=list)
    prompt_fingerprint: str = ""
    visual_metadata: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    regeneration_count: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SceneMemory:
    """Tracks which identities appeared in which scenes."""

    def __init__(self, max_entries: int = 500) -> None:
        self._entries: list[SceneMemoryEntry] = []
        self._max_entries = max_entries

    def record(self, entry: SceneMemoryEntry) -> None:
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries :]

    def get_identity_history(self, identity_id: str) -> list[SceneMemoryEntry]:
        return [e for e in self._entries if identity_id in e.identities_used]

    def get_scene_history(self, scene_id: str) -> SceneMemoryEntry | None:
        for entry in reversed(self._entries):
            if entry.scene_id == scene_id:
                return entry
        return None

    def all_entries(self) -> list[SceneMemoryEntry]:
        return list(self._entries)
