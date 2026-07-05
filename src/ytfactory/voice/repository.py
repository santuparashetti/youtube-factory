from __future__ import annotations

import json
from pathlib import Path

from .models import VoiceArtifact


class VoiceRepository:
    """Repository for generated voice artifacts."""

    def save(
        self,
        artifact: VoiceArtifact,
    ) -> Path:

        artifact.audio_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        manifest = artifact.audio_path.parent / "audio.json"

        data = []

        if manifest.exists():
            data = json.loads(
                manifest.read_text(
                    encoding="utf-8",
                )
            )

        data.append(
            {
                "scene_id": artifact.scene_id,
                "audio_path": str(artifact.audio_path),
            }
        )

        manifest.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )

        return artifact.audio_path
