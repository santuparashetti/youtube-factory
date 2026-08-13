"""Environment Bible — canonical environment descriptions and temporal compatibility.

Loaded once from environment_bible.yaml. Project overrides are merged on top.
Temporal compatibility is data-driven: no environment names are hardcoded in validators.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from .character_bible import BibleTemporalMode


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class EnvironmentEntry:
    environment_id: str
    era_family: str
    period: str
    description: str
    allowed_temporal_modes: set[BibleTemporalMode] = field(default_factory=set)

    def is_compatible_with(self, temporal_mode: BibleTemporalMode) -> bool:
        return temporal_mode in self.allowed_temporal_modes


# ── Registry ───────────────────────────────────────────────────────────────────


class EnvironmentBible:
    """Loads global environment_bible.yaml and optional project override.

    Singleton pattern mirrors CharacterBible.
    """

    _instance: Optional["EnvironmentBible"] = None

    def __init__(self, config_path: Path, project_config_path: Optional[Path] = None):
        self._entries: dict[str, EnvironmentEntry] = {}
        self._load(config_path)
        if project_config_path and project_config_path.exists():
            self._merge_project(project_config_path)

    @classmethod
    def get_instance(
        cls,
        config_path: Optional[Path] = None,
        project_config_path: Optional[Path] = None,
    ) -> "EnvironmentBible":
        """Return the singleton. First call must pass config_path."""
        if cls._instance is None:
            if config_path is None:
                config_path = _default_config_path()
            cls._instance = cls(config_path, project_config_path)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton — used in tests."""
        cls._instance = None

    def get(self, environment_id: str) -> EnvironmentEntry:
        """Return EnvironmentEntry. Raises KeyError if not found."""
        if environment_id not in self._entries:
            raise KeyError(f"Environment '{environment_id}' not found in EnvironmentBible")
        return self._entries[environment_id]

    def has(self, environment_id: str) -> bool:
        return environment_id in self._entries

    def all_ids(self) -> list[str]:
        return list(self._entries.keys())

    def _load(self, path: Path) -> None:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        envs = (data or {}).get("environments", {}) or {}
        for env_id, attrs in envs.items():
            entry = _build_entry(env_id, attrs)
            self._entries[env_id] = entry

    def _merge_project(self, path: Path) -> None:
        """Merge project overrides. Matching IDs are overridden; new IDs are added."""
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        envs = (data or {}).get("environments", {}) or {}
        for env_id, attrs in envs.items():
            if not isinstance(attrs, dict):
                continue
            if env_id in self._entries:
                existing = self._entries[env_id]
                self._entries[env_id] = _merge_entry(existing, attrs)
            else:
                self._entries[env_id] = _build_entry(env_id, attrs)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _default_config_path() -> Path:
    return Path(__file__).parent.parent / "config" / "environment_bible.yaml"


def _parse_temporal_modes(raw: list[str] | None) -> set[BibleTemporalMode]:
    modes: set[BibleTemporalMode] = set()
    for item in (raw or []):
        try:
            modes.add(BibleTemporalMode(item))
        except ValueError:
            pass  # unknown mode — skip; load-time validation should catch this
    return modes


def _build_entry(env_id: str, attrs: dict) -> EnvironmentEntry:
    return EnvironmentEntry(
        environment_id=env_id,
        era_family=attrs.get("era_family", ""),
        period=attrs.get("period", ""),
        description=(attrs.get("description") or "").strip(),
        allowed_temporal_modes=_parse_temporal_modes(attrs.get("allowed_temporal_modes")),
    )


def _merge_entry(existing: EnvironmentEntry, overrides: dict) -> EnvironmentEntry:
    modes = (
        _parse_temporal_modes(overrides["allowed_temporal_modes"])
        if "allowed_temporal_modes" in overrides
        else existing.allowed_temporal_modes
    )
    return EnvironmentEntry(
        environment_id=existing.environment_id,
        era_family=overrides.get("era_family", existing.era_family),
        period=overrides.get("period", existing.period),
        description=(overrides.get("description") or existing.description).strip(),
        allowed_temporal_modes=modes,
    )
