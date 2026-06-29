from __future__ import annotations

import json
from pathlib import Path

from ytfactory.config.settings import Settings
from ytfactory.providers.tts.factory import get_tts_provider

from .artifacts import audio_directory
from .models import VoiceArtifact
from .repository import VoiceRepository


class VoicePipeline:
    """Generate narration audio for every scene."""

    def __init__(self, settings: Settings):
        self._provider = get_tts_provider(settings)
        self._repository = VoiceRepository()

    def run(
        self,
        project_id: str,
    ) -> None:

        scene_file = (
            Path("workspace")
            / "jobs"
            / project_id
            / "scenes"
            / "scene-plan.json"
        )

        with open(
            scene_file,
            encoding="utf-8",
        ) as f:
            scenes = json.load(f)["scenes"]

        for scene in scenes:

            output = (
                audio_directory(project_id)
                / f"scene-{scene['index']:03d}.mp3"
            )

            self._provider.generate(
                text=scene["narration"],
                output_path=output,
            )

            self._repository.save(
                VoiceArtifact(
                    scene_id=scene["index"],
                    audio_path=output,
                )
            )