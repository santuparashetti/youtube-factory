from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from video_core.domain.visual_metadata import VisualMetadata


class VisualBible(BaseModel):
    """Visual architecture for the full video. Generated once before per-scene planning."""
    dominant_metaphor: str
    anchor_environments: list[str] = Field(min_length=2, max_length=4)
    color_arc: dict[str, str]  # keys: opening, build, climax, resolution
    visual_motifs: list[str] = Field(min_length=1, max_length=5)
    shot_arc: dict[str, str]  # keys: opening_scenes, build_scenes, climax_scene, resolution_scenes


class StructuredImagePrompt(BaseModel):
    """Per-scene structured prompt. Replaces flat visual_prompt string in generation."""

    shot_type: Literal[
        "establishing_wide",
        "medium",
        "close_up",
        "insert",
        "POV",
        "over_shoulder",
        "silhouette",
        "aerial",
    ]
    camera_angle: Literal[
        "eye_level",
        "low_angle",
        "high_angle",
        "dutch_tilt",
    ]
    environment_prompt: str
    character_staging: Optional[str] = None
    lighting_match: str = Field(default="Natural cinematic lighting matching the environment.")

    @model_validator(mode="before")
    @classmethod
    def _coerce_none_strings(cls, data: dict) -> dict:
        """LLMs sometimes return null for string fields — coerce to defaults."""
        if not isinstance(data, dict):
            return data
        _defaults = {
            "lighting_match": "Natural cinematic lighting matching the environment.",
            "focal_length": "",
            "color_palette_phase": "",
            "continuity_ref": "",
        }
        for k, default in _defaults.items():
            if k in data and data[k] is None:
                data[k] = default
        return data
    focal_length: str = ""
    color_palette_phase: str = ""
    continuity_ref: str = ""
    compiled_prompt: str


class FaithfulnessStatus(str, Enum):
    """Status of a scene's faithfulness QA pass.

    Replaces the old ad-hoc strings ("violation", "retry parse failed") which
    were implementation details, not validation outcomes — see
    docs/script/task-2.2-retry-engine-reliability.md Phase 7.
    """

    PASS = "pass"        # Validated clean (initial attempt or after retry).
    FAILED = "failed"    # Retries exhausted — violation unresolved.
    SKIPPED = "skipped"  # brand_card or other scene type exempt from validation.


@dataclass
class SceneAnalysis:
    """
    Structured analysis of a single narration scene.
    This becomes the source of truth for prompt generation.
    """
    scene_id: int
    characters: list[str] = field(default_factory=list)
    allowed_characters: list[str] = field(default_factory=list)
    primary_subject: str = ""
    secondary_subjects: list[str] = field(default_factory=list)
    environment: str = ""
    primary_action: str = ""
    emotional_beat: str = ""
    narrative_phase: str = ""  # NarrativePhase value, e.g. "HOOK", "TENSION"
    story_goal: str = ""
    human_requirement: Literal["required", "optional", "forbidden", "permitted_symbolic"] = "forbidden"
    named_person: str = ""
    camera_focus: str = ""
    scene_characters: list[str] = field(default_factory=list)
    scene_objects: list[str] = field(default_factory=list)
    forbidden_characters: list[str] = field(default_factory=list)
    forbidden_objects: list[str] = field(default_factory=list)
    visual_focus: str = ""
    continuity_reference: str = ""
    story_time: str = ""
    camera_constraints: str = ""


class Scene(BaseModel):
    model_config = ConfigDict(extra='allow')
    index: int = Field(..., description="Scene number")
    title: str = Field(..., description="Short scene title")
    narration: str = Field(..., description="Narration text")
    visual_prompt: str = Field(..., description="Prompt for image generation")
    duration_seconds: float = Field(..., gt=0)
    visual_metadata: VisualMetadata | None = Field(default=None, description="Structured visual intelligence metadata")
    scene_type: str = Field(default="generated_image", description="Scene type: generated_image, asset, brand_card")
    shot_type: str = Field(default="medium_shot", description="Cinematic shot type for this scene")
    pose: str | None = Field(default=None, description="Subject pose for this scene")
    composition: str | None = Field(default=None, description="Frame composition (e.g. center, rule_of_thirds)")
    motion_type: str | None = Field(default=None, description="Intended motion type: zoom/pan/parallax/push/fog/dust/particles/none")
    text_overlay: str | None = Field(default=None, description="On-screen text for this scene")
    text_reveal_segments: list[str] = Field(default_factory=list, description="Word/phrase groups for progressive text reveal")
    hold_required: bool = Field(default=False, description="True if scene follows a PEAK emotional segment and needs an extended hold")
    linked_segment: dict | None = Field(default=None, description="Serialized ScriptSegment linking this scene to its narration beat")
    asset_path: str | None = Field(default=None, description="Resolved path to the source image/video asset for this scene")
    asset_id: str | None = Field(default=None, description="Original asset identifier (path or ID) from brand or source config")
    faithfulness_qa: dict | None = Field(default=None, description="QA result from faithfulness validation pass")
    narrative_phase: str = Field(default="", description="Narrative pipeline phase (HOOK, STORY, TENSION, REVELATION, …). Drives SSML emotion targeting.")
    scene_analysis: SceneAnalysis | None = Field(default=None, description="Structured scene analysis for story-first prompt generation")
    character_presence: list[str] = Field(
        default_factory=list,
        description=(
            "Authoritative list of character IDs present in this scene "
            "(e.g. ['KAI', 'YOUNG_HUSBAND']). Empty list = environment-only. "
            "When non-empty this takes precedence over anchor_role for character "
            "spec injection. KAI must be explicitly listed — never auto-injected."
        ),
    )
    anchor_role: Literal["primary", "spectator", "absent"] = Field(
        default="absent",
        description=(
            "Kai anchor character role: primary (Kai is subject), spectator (Kai observes "
            "real figure), absent (symbolic, no Kai). Derived from character_presence when "
            "that field is non-empty; kept for backward compatibility with old scene plans."
        ),
    )
    scene_group_id: str | None = Field(
        default=None,
        description="Identifies scenes in the same story beat (same location, continuous action). Scenes sharing a non-None value are grouped.",
    )
    environment_anchor: str | None = Field(
        default=None,
        description="Canonical environment description for this scene group. Set by LLM on the first scene in each group; propagated to subsequent scenes by post-processing.",
    )
    structured_prompt: Optional[StructuredImagePrompt] = Field(
        default=None,
        description="V2 structured image prompt. compiled_prompt is also written to visual_prompt for backward compat.",
    )


class ScenePlan(BaseModel):
    model_config = ConfigDict(extra='allow')
    title: str
    total_duration_seconds: float
    scenes: list[Scene]
    visual_bible: Optional[VisualBible] = None
    continuity_warnings: list[str] = Field(default_factory=list)
