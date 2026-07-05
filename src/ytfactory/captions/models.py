from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel


class CaptionArtifact(BaseModel):
    scene_id: int
    srt_path: Path
    ass_path: Optional[Path] = None

    @property
    def primary_path(self) -> Path:
        """Return the best available subtitle file (ASS preferred, SRT fallback)."""
        if self.ass_path and self.ass_path.exists():
            return self.ass_path
        return self.srt_path
