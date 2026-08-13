"""Scene Bible Extension — optional per-scene Bible fields.

Absent bible_ext key → legacy scene (existing prompt path unchanged).
Present bible_ext key → strict parse → hard validation.
Malformed bible_ext → ValidationError — NEVER silently becomes legacy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic import StrictBool

from .character_bible import (
    AnimalPresence,
    BibleSceneCharacter,
    BibleTemporalMode,
    CharacterPresence,
)


# ── Pydantic parse model (strict) ──────────────────────────────────────────────


class BibleSceneCharacterModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str
    presence: CharacterPresence
    action: str
    emotion: Optional[str] = None
    pose_override: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _check_required(cls, data: object) -> object:
        if isinstance(data, dict):
            if not data.get("character_id"):
                raise ValueError("character_id is required in characters[] entry")
            if not data.get("action"):
                raise ValueError("action is required in characters[] entry")
        return data


class SceneBibleExtensionModel(BaseModel):
    """Strict parse model for scene-plan.json bible_ext entries.

    Unknown fields, invalid enums, and wrong primitive types all fail hard.
    """

    model_config = ConfigDict(extra="forbid")

    temporal_mode: BibleTemporalMode
    character_presence: CharacterPresence
    animal_presence: AnimalPresence

    allowed_character_ids: list[str] = Field(default_factory=list)
    forbidden_character_ids: list[str] = Field(default_factory=list)

    anonymous_humans_allowed: StrictBool = False
    anonymous_human_description: Optional[str] = None

    environment_id: str

    characters: list[BibleSceneCharacterModel] = Field(default_factory=list)


# ── Dataclass extension (runtime) ──────────────────────────────────────────────


@dataclass
class SceneBibleExtension:
    """Optional Bible fields attached to an existing scene.

    Missing bible_ext → is_legacy() returns True.
    Present bible_ext → strictly parsed; malformed data never reaches here.
    """

    allowed_character_ids: list[str] = field(default_factory=list)
    forbidden_character_ids: list[str] = field(default_factory=list)
    characters: list[BibleSceneCharacter] = field(default_factory=list)

    temporal_mode: Optional[BibleTemporalMode] = None
    character_presence: Optional[CharacterPresence] = None
    animal_presence: Optional[AnimalPresence] = None

    anonymous_humans_allowed: bool = False
    anonymous_human_description: Optional[str] = None

    environment_id: Optional[str] = None

    def is_legacy(self) -> bool:
        """True only when bible_ext was genuinely absent/empty."""
        return (
            not self.allowed_character_ids
            and not self.forbidden_character_ids
            and not self.characters
            and self.temporal_mode is None
            and self.character_presence is None
            and self.animal_presence is None
            and self.anonymous_humans_allowed is False
            and self.anonymous_human_description is None
            and self.environment_id is None
        )

    @classmethod
    def from_model(cls, model: SceneBibleExtensionModel) -> "SceneBibleExtension":
        characters = [
            BibleSceneCharacter(
                character_id=c.character_id,
                presence=c.presence,
                action=c.action,
                emotion=c.emotion,
                pose_override=c.pose_override,
            )
            for c in model.characters
        ]
        return cls(
            allowed_character_ids=list(model.allowed_character_ids),
            forbidden_character_ids=list(model.forbidden_character_ids),
            characters=characters,
            temporal_mode=model.temporal_mode,
            character_presence=model.character_presence,
            animal_presence=model.animal_presence,
            anonymous_humans_allowed=model.anonymous_humans_allowed,
            anonymous_human_description=model.anonymous_human_description,
            environment_id=model.environment_id,
        )


# ── Public parse function ───────────────────────────────────────────────────────


def parse_bible_ext(raw: dict | None) -> Optional[SceneBibleExtension]:
    """Strictly parse bible_ext from a scene dict.

    raw is None (absent key) → returns None (legacy path).
    raw is present but malformed → raises pydantic.ValidationError.

    A malformed bible_ext MUST NOT become an all-default SceneBibleExtension —
    that would silently disable enforcement. Callers must let the exception
    propagate (or convert it to PromptValidationError).
    """
    if raw is None:
        return None
    model = SceneBibleExtensionModel.model_validate(raw)
    return SceneBibleExtension.from_model(model)
