from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class Era(str, Enum):
    ANCIENT = "ANCIENT"
    HISTORICAL = "HISTORICAL"
    MODERN = "MODERN"
    SYMBOLIC = "SYMBOLIC"
    TRANSITIONAL = "TRANSITIONAL"


class NarrativeRole(str, Enum):
    STORY = "STORY"
    ANALOGY = "ANALOGY"
    METAPHOR = "METAPHOR"
    EXPLANATION = "EXPLANATION"
    ESTABLISHING = "ESTABLISHING"
    CTA = "CTA"


class Environment(str, Enum):
    FOREST = "FOREST"
    TEMPLE = "TEMPLE"
    ASHRAM = "ASHRAM"
    KINGDOM = "KINGDOM"
    BATTLEFIELD = "BATTLEFIELD"
    CITY = "CITY"
    OFFICE = "OFFICE"
    HOME = "HOME"
    MOUNTAIN = "MOUNTAIN"
    RIVER = "RIVER"
    ABSTRACT = "ABSTRACT"
    COSMIC = "COSMIC"


class Mood(str, Enum):
    PEACEFUL = "PEACEFUL"
    MYSTERIOUS = "MYSTERIOUS"
    REVERENT = "REVERENT"
    REFLECTIVE = "REFLECTIVE"
    HOPEFUL = "HOPEFUL"
    FEARFUL = "FEARFUL"
    CURIOUS = "CURIOUS"
    LONELY = "LONELY"
    DETERMINED = "DETERMINED"


class VisualStyle(str, Enum):
    DOCUMENTARY = "DOCUMENTARY"
    CINEMATIC = "CINEMATIC"
    REALISTIC = "REALISTIC"
    DREAMLIKE = "DREAMLIKE"
    PAINTING = "PAINTING"
    ANIME = "ANIME"
    WATERCOLOR = "WATERCOLOR"


class VisualMetadata(BaseModel):
    version: int = Field(default=1, description="Schema version")
    era: Era | None = Field(default=None, description="Historical/visual era of the scene")
    narrative_role: NarrativeRole | None = Field(default=None, description="Why this image exists in the story")
    environment: Environment | None = Field(default=None, description="Physical setting of the scene")
    mood: Mood | None = Field(default=None, description="Dominant emotional tone")
    visual_style: VisualStyle | None = Field(default=None, description="Visual appearance style")
    allow_modern_objects: bool = Field(default=False, description="Whether modern objects are permitted")
    reason: str = Field(default="", description="Debug rationale for metadata choices")

    @property
    def is_populated(self) -> bool:
        return any(
            [
                self.era,
                self.narrative_role,
                self.environment,
                self.mood,
                self.visual_style,
            ]
        )

    def to_prompt_snapshot(self) -> dict:
        return self.model_dump()
