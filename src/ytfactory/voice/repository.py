from __future__ import annotations

from pathlib import Path

from .models import VoiceArtifact


class VoiceRepository:
    """Repository for generated voice artifacts."""

    def save(
        self,
        artifact: VoiceArtifact,
    ) -> Path:
        return artifact.audio_path