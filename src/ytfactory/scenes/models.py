from __future__ import annotations

from pydantic import BaseModel, Field

from video_core.domain.visual_metadata import VisualMetadata


class Scene(BaseModel):
    index: int = Field(..., description="Scene number")
    title: str = Field(..., description="Short scene title")
    narration: str = Field(..., description="Narration text")
    visual_prompt: str = Field(..., description="Prompt for image generation")
    duration_seconds: float = Field(..., gt=0)
    visual_metadata: VisualMetadata | None = Field(default=None, description="Structured visual intelligence metadata")
    pose: str | None = Field(default=None, description="Subject pose for this scene")
    composition: str | None = Field(default=None, description="Frame composition (e.g. center, rule_of_thirds)")
    motion_type: str | None = Field(default=None, description="Intended motion type: zoom/pan/parallax/push/fog/dust/particles/none")
    text_overlay: str | None = Field(default=None, description="On-screen text for this scene")
    text_reveal_segments: list[str] = Field(default_factory=list, description="Word/phrase groups for progressive text reveal")
    hold_required: bool = Field(default=False, description="True if scene follows a PEAK emotional segment and needs an extended hold")
    linked_segment: dict | None = Field(default=None, description="Serialized ScriptSegment linking this scene to its narration beat")


class ScenePlan(BaseModel):
    title: str
    total_duration_seconds: float
    scenes: list[Scene]
