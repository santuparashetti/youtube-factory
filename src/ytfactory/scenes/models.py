from pydantic import BaseModel, Field


class Scene(BaseModel):
    """A single scene in the video."""

    index: int = Field(..., description="Scene number")
    title: str = Field(..., description="Short scene title")
    narration: str = Field(..., description="Narration text")
    visual_prompt: str = Field(..., description="Prompt for image generation")
    duration_seconds: float = Field(..., gt=0)


class ScenePlan(BaseModel):
    """Complete scene plan."""

    title: str
    total_duration_seconds: float
    scenes: list[Scene]
