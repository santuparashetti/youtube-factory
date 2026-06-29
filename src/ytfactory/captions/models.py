from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class CaptionArtifact(BaseModel):
    scene_id: int
    srt_path: Path