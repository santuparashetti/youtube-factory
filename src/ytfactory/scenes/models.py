from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from video_core.domain.visual_metadata import VisualMetadata


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
    scene_analysis: SceneAnalysis | None = Field(default=None, description="Structured scene analysis for story-first prompt generation")
    anchor_role: Literal["primary", "spectator", "absent"] = Field(
        default="absent",
        description="Kai anchor character role: primary (Kai is subject), spectator (Kai observes real figure), absent (symbolic, no Kai)",
    )


class ScenePlan(BaseModel):
    model_config = ConfigDict(extra='allow')
    title: str
    total_duration_seconds: float
    scenes: list[Scene]
