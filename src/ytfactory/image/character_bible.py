"""Character Bible — canonical intended identity for all named characters.

Loaded once at startup from character_bible.yaml. Never written to at runtime.
Project-level overrides merge on top without mutating the global config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml


# ── Enums ──────────────────────────────────────────────────────────────────────


class CharacterSystem(str, Enum):
    DOCUMENTARY = "documentary"
    THUMBNAIL = "thumbnail"


class CharacterPresence(str, Enum):
    NONE = "NONE"
    PRIMARY = "PRIMARY"
    BACKGROUND = "BACKGROUND"
    SYMBOLIC = "SYMBOLIC"


class AnimalPresence(str, Enum):
    NONE = "NONE"
    INCIDENTAL = "INCIDENTAL"
    PRIMARY = "PRIMARY"
    THREATENING = "THREATENING"


class BibleTemporalMode(str, Enum):
    """Temporal mode for the Character Bible image prompt system.

    Distinct from scene_continuity.models.TemporalMode which governs story
    continuity. These two enums serve different layers and must not be merged.
    """

    HISTORICAL_LITERAL = "HISTORICAL_LITERAL"
    HISTORICAL_SYMBOLIC = "HISTORICAL_SYMBOLIC"
    CONTEMPORARY_LITERAL = "CONTEMPORARY_LITERAL"
    CONTEMPORARY_SYMBOLIC = "CONTEMPORARY_SYMBOLIC"
    TIMELESS_SYMBOLIC = "TIMELESS_SYMBOLIC"


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class CharacterEntry:
    character_id: str
    role: str
    system: CharacterSystem
    identity_lock: str

    age: Optional[int] = None
    sex: Optional[str] = None
    build: Optional[str] = None
    hair: Optional[str] = None
    facial_hair: Optional[str] = None
    face: Optional[str] = None
    eyes: Optional[str] = None
    skin: Optional[str] = None
    clothing: dict[str, str] = field(default_factory=dict)
    accessories: Optional[str] = None
    jewelry: Optional[str] = None
    tattoos: Optional[str] = None
    pose_rule: Optional[str] = None
    expression_default: Optional[str] = None
    style_note: Optional[str] = None
    # Thumbnail-only fields
    age_range: Optional[str] = None
    body: Optional[str] = None
    glasses: Optional[str] = None

    def render_identity_block(self) -> str:
        """Format the character identity block for injection into an image prompt.

        This is the ONLY place character appearance prose is generated —
        never inside scene prompts directly.
        """
        lines = [f"CHARACTER — {self.character_id}:"]
        lines.append(
            f"Use the established {self.character_id} identity "
            "(age, build, clothing, etc)."
        )
        if self.age:
            lines.append(f"Age: {self.age}.")
        if self.sex:
            lines.append(f"Sex: {self.sex}.")
        if self.build:
            lines.append(f"Build: {self.build}.")
        if self.hair:
            lines.append(f"Hair: {self.hair}.")
        if self.facial_hair:
            lines.append(f"Facial hair: {self.facial_hair}.")
        if self.face:
            lines.append(f"Face: {self.face}.")
        if self.eyes:
            lines.append(f"Eyes: {self.eyes}.")
        if self.skin:
            lines.append(f"Skin: {self.skin}.")
        if self.clothing:
            clothing_parts = [f"{k}: {v}" for k, v in self.clothing.items()]
            lines.append(f"Clothing — {'; '.join(clothing_parts)}.")
        if self.accessories and self.accessories.lower() != "none":
            lines.append(f"Accessories: {self.accessories}.")
        if self.pose_rule:
            lines.append(f"Pose rule: {self.pose_rule.strip()}")
        if self.style_note:
            lines.append(f"Style: {self.style_note.strip()}")
        lines.append(self.identity_lock.strip())
        return "\n".join(lines)

    def render_forbidden_block(self) -> str:
        """One-line negative constraint for NEGATIVE prompt sections."""
        return f"No {self.character_id}."


@dataclass
class BibleSceneCharacter:
    """One character's role within a specific scene.

    Replaces free-form character prose in scene definitions.
    """

    character_id: str
    presence: CharacterPresence
    action: str
    emotion: Optional[str] = None
    pose_override: Optional[str] = None


# ── Registry ───────────────────────────────────────────────────────────────────


class CharacterBible:
    """Loads and serves character_bible.yaml.

    Singleton — one instance shared across a pipeline run.
    """

    _instance: Optional["CharacterBible"] = None

    def __init__(self, config_path: Path, project_config_path: Optional[Path] = None):
        self._entries: dict[str, CharacterEntry] = {}
        self._load(config_path)
        if project_config_path and project_config_path.exists():
            self._merge_project(project_config_path)

    @classmethod
    def get_instance(
        cls,
        config_path: Optional[Path] = None,
        project_config_path: Optional[Path] = None,
    ) -> "CharacterBible":
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

    def get(
        self,
        character_id: str,
        system: CharacterSystem = CharacterSystem.DOCUMENTARY,
    ) -> CharacterEntry:
        """Return CharacterEntry for character_id. Raises KeyError if not found."""
        key = _entry_key(character_id, system)
        if key not in self._entries:
            raise KeyError(
                f"Character '{character_id}' not found in system '{system.value}'"
            )
        return self._entries[key]

    def all_ids(
        self, system: CharacterSystem = CharacterSystem.DOCUMENTARY
    ) -> list[str]:
        """Return all character IDs in the given system namespace."""
        return [
            entry.character_id
            for entry in self._entries.values()
            if entry.system == system
        ]

    def render_global_identity_lock(self) -> str:
        """Return the full IDENTITY IMMUTABILITY block for injection into prompts."""
        lines = [
            "IDENTITY IMMUTABILITY:",
            "Character appearance is fixed globally, not per-scene.",
            "Do NOT reinterpret adult→child, man→woman, or redesign any named character.",
        ]
        for entry in self._entries.values():
            if entry.system == CharacterSystem.DOCUMENTARY:
                lines.append(f"{entry.character_id}: {entry.identity_lock.strip()}")
        return "\n".join(lines)

    def _load(self, path: Path) -> None:
        """Parse YAML and populate self._entries."""
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        self._load_system(data, CharacterSystem.DOCUMENTARY, "documentary")
        self._load_system(data, CharacterSystem.THUMBNAIL, "thumbnail")

    def _load_system(
        self, data: dict, system: CharacterSystem, key: str
    ) -> None:
        system_data = data.get(key, {}) or {}
        for char_id, attrs in system_data.items():
            if not isinstance(attrs, dict):
                continue
            entry = _build_entry(char_id, attrs, system)
            self._entries[_entry_key(char_id, system)] = entry

    def _merge_project(self, path: Path) -> None:
        """Merge project-level overrides. Never mutates global config files."""
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for sys_key, system in [
            ("documentary", CharacterSystem.DOCUMENTARY),
            ("thumbnail", CharacterSystem.THUMBNAIL),
        ]:
            system_data = (data or {}).get(sys_key, {}) or {}
            for char_id, attrs in system_data.items():
                if not isinstance(attrs, dict):
                    continue
                key = _entry_key(char_id, system)
                if key in self._entries:
                    # Merge: project attrs override matching fields
                    existing = self._entries[key]
                    merged = _merge_entry(existing, attrs)
                    self._entries[key] = merged
                else:
                    # Project-only character
                    self._entries[key] = _build_entry(char_id, attrs, system)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _default_config_path() -> Path:
    return Path(__file__).parent.parent / "config" / "character_bible.yaml"


def _entry_key(character_id: str, system: CharacterSystem) -> str:
    return f"{system.value}:{character_id}"


def _build_entry(char_id: str, attrs: dict, system: CharacterSystem) -> CharacterEntry:
    clothing_raw = attrs.get("clothing") or {}
    if isinstance(clothing_raw, dict):
        clothing = {k: v for k, v in clothing_raw.items() if isinstance(v, str)}
    elif isinstance(clothing_raw, str):
        clothing = {"description": clothing_raw}
    else:
        clothing = {}
    return CharacterEntry(
        character_id=char_id,
        role=attrs.get("role", ""),
        system=system,
        identity_lock=attrs.get("identity_lock", "").strip(),
        age=attrs.get("age"),
        sex=attrs.get("sex"),
        build=attrs.get("build"),
        hair=attrs.get("hair"),
        facial_hair=attrs.get("facial_hair"),
        face=attrs.get("face"),
        eyes=attrs.get("eyes"),
        skin=attrs.get("skin"),
        clothing=clothing,
        accessories=attrs.get("accessories"),
        jewelry=attrs.get("jewelry"),
        tattoos=attrs.get("tattoos"),
        pose_rule=attrs.get("pose_rule"),
        expression_default=attrs.get("expression_default"),
        style_note=attrs.get("style_note"),
        age_range=attrs.get("age_range"),
        body=attrs.get("body"),
        glasses=attrs.get("glasses"),
    )


def _merge_entry(existing: CharacterEntry, overrides: dict) -> CharacterEntry:
    """Return a new CharacterEntry with project overrides applied."""
    clothing = dict(existing.clothing)
    if "clothing" in overrides and isinstance(overrides["clothing"], dict):
        clothing.update(overrides["clothing"])

    return CharacterEntry(
        character_id=existing.character_id,
        role=overrides.get("role", existing.role),
        system=existing.system,
        identity_lock=overrides.get("identity_lock", existing.identity_lock),
        age=overrides.get("age", existing.age),
        sex=overrides.get("sex", existing.sex),
        build=overrides.get("build", existing.build),
        hair=overrides.get("hair", existing.hair),
        facial_hair=overrides.get("facial_hair", existing.facial_hair),
        face=overrides.get("face", existing.face),
        eyes=overrides.get("eyes", existing.eyes),
        skin=overrides.get("skin", existing.skin),
        clothing=clothing,
        accessories=overrides.get("accessories", existing.accessories),
        jewelry=overrides.get("jewelry", existing.jewelry),
        tattoos=overrides.get("tattoos", existing.tattoos),
        pose_rule=overrides.get("pose_rule", existing.pose_rule),
        expression_default=overrides.get("expression_default", existing.expression_default),
        style_note=overrides.get("style_note", existing.style_note),
        age_range=overrides.get("age_range", existing.age_range),
        body=overrides.get("body", existing.body),
        glasses=overrides.get("glasses", existing.glasses),
    )
