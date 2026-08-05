"""Data models for the Story Bible system."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterEntry(BaseModel):
    """Locked visual description for one character across all scenes."""

    name: str = Field(..., description="Character name from narration")
    slug: str = Field(..., description="Kebab-case slug for filenames")
    appearance: str = Field(..., description="Locked physical description: age, build, features")
    clothing: str = Field(..., description="Locked clothing description")
    role: str = Field(default="", description="Narrative role in the story")
    scenes: list[int] = Field(default_factory=list, description="Scene indexes where this character appears")


class LocationEntry(BaseModel):
    """Locked visual description for one location across all scenes."""

    name: str = Field(..., description="Location name from narration")
    slug: str = Field(..., description="Kebab-case slug for filenames")
    description: str = Field(..., description="Locked visual description — architecture, materials, colors")
    lighting_default: str = Field(default="", description="Default lighting for this location")
    key_details: list[str] = Field(default_factory=list, description="Specific physical details that must appear every time")
    scenes: list[int] = Field(default_factory=list, description="Scene indexes set in this location")


class WorldRules(BaseModel):
    """Global world-building rules for visual consistency."""

    era: str = Field(default="", description="ANCIENT|HISTORICAL|MODERN|SYMBOLIC")
    cultural_context: str = Field(default="", description="Which culture/geography this story inhabits")
    key_objects: dict[str, str] = Field(default_factory=dict, description="Object name -> locked visual description")
    recurring_symbols: list[str] = Field(default_factory=list, description="Objects that recur across scenes and must appear consistently")
    architectural_style: str = Field(default="", description="Architecture/structures description")
    time_period_note: str = Field(default="", description="Important time-period constraints")


class GlobalStyle(BaseModel):
    """Single-source style config inherited by all scenes."""

    rendering_prefix: str = Field(
        default="HYBRID CINEMATIC STYLE: 100% photorealistic environment, "
        "hand-painted storybook illustrated characters with clean ink outlines "
        "and soft cel shading, composited with matching lighting and shadows.",
        description="First line of every compiled_prompt",
    )
    negative_prompt: str = Field(
        default="No text, no watermark, no subtitle, no logo.",
        description="Appended to every compiled_prompt",
    )
    aspect_ratio: str = Field(default="16:9", description="Target aspect ratio")
    camera_defaults: str = Field(
        default="Cinematic framing. Vary shot size and angle intentionally across scenes.",
        description="Default camera direction",
    )
    grain_and_dof: str = Field(
        default="Subtle film grain, shallow depth of field on subject, "
        "naturalistic color grading.",
        description="Global rendering quality directives",
    )
    color_progression: dict[str, str] = Field(
        default_factory=lambda: {
            "opening": "cool desaturated tones",
            "build": "warming amber tones",
            "climax": "deep gold, high contrast",
            "resolution": "cool blue with one warm accent",
        },
        description="Arc phase -> palette",
    )


class StoryBible(BaseModel):
    """Complete story bible for a video project.  Generated once, referenced by every scene."""

    world: WorldRules = Field(default_factory=WorldRules)
    characters: list[CharacterEntry] = Field(default_factory=list)
    locations: list[LocationEntry] = Field(default_factory=list)
    style: GlobalStyle = Field(default_factory=GlobalStyle)
    do_not_change: list[str] = Field(
        default_factory=list,
        description="Locked visual elements that must not be altered across scenes",
    )
