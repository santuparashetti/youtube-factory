from __future__ import annotations

from ytfactory.config.settings import Settings
from ytfactory.providers.tts.factory import get_tts_provider

from .artifacts import audio_directory
from .models import VoiceArtifact, VoiceRequest
from .repository import VoiceRepository


class VoicePipeline:
    """Generate narration audio from scene text."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._provider = get_tts_provider(settings)
        self._repository = VoiceRepository()

    def generate(
        self,
        request: VoiceRequest,
    ) -> VoiceArtifact:

        output = (
            audio_directory(request.project)
            / f"scene-{request.scene_id:03d}.wav"
        )

        self._provider.generate(
            text=request.text,
            output_path=output,
            voice=request.voice,
            language=request.language,
        )

        artifact = VoiceArtifact(
            scene_id=request.scene_id,
            audio_path=output,
        )

        self._repository.save(artifact)

        return artifact