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


class ScenePlan(BaseModel):
    title: str
    total_duration_seconds: float
    scenes: list[Scene]
