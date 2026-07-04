from __future__ import annotations

import json
from pathlib import Path

from ytfactory.config.settings import Settings
from ytfactory.providers.tts.factory import get_tts_provider
from ytfactory.providers.tts.optimizer import SpeechOptimizer

from .artifacts import audio_directory
from .models import VoiceArtifact
from .repository import VoiceRepository

_optimizer = SpeechOptimizer()


class VoicePipeline:
    """Generate narration audio for every scene."""

    def __init__(self, settings: Settings):
        self._provider = get_tts_provider(settings)
        self._repository = VoiceRepository()

    def run(
        self,
        project_id: str,
        style: str = "spiritual",
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

        total = len(scenes)

        for idx, scene in enumerate(scenes):

            output = (
                audio_directory(project_id)
                / f"scene-{scene['index']:03d}.mp3"
            )
            timing_output = output.with_suffix(".timing.json")

            if output.exists() and timing_output.exists():
                continue

            # Position in video (0.0 = first scene, 1.0 = last) for arc-aware delivery
            scene_position = idx / max(total - 1, 1)

            # Speech Optimizer: restructure written narration into spoken phrases
            optimized = _optimizer.optimize(
                scene["narration"],
                style=style,
                scene_position=scene_position,
            )

            _, boundaries = self._provider.generate_with_boundaries(
                text=optimized,
                output_path=output,
                style=style,
                scene_position=scene_position,
            )

            timing_output.write_text(
                json.dumps(boundaries, indent=2),
                encoding="utf-8",
            )

            self._repository.save(
                VoiceArtifact(
                    scene_id=scene["index"],
                    audio_path=output,
                )
            )
