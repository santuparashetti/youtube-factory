from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class VoiceRequest(BaseModel):
    project: str
    scene_id: int
    text: str
    voice: str = "default"
    language: str = "en"


class VoiceArtifact(BaseModel):
    scene_id: int
    audio_path: Path