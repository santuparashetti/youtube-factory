from __future__ import annotations


from ytfactory.providers.tts.factory import get_tts_provider

from .artifacts import audio_directory
from .models import VoiceArtifact, VoiceRequest
from .repository import VoiceRepository


class VoicePipeline:
    def __init__(self) -> None:
        self.provider = get_tts_provider()
        self.repository = VoiceRepository()

    def generate(self, request: VoiceRequest) -> VoiceArtifact:
        output = (
            audio_directory(request.project)
            / f"scene-{request.scene_id:03d}.wav"
        )

        self.provider.generate(
            text=request.text,
            output_path=output,
            voice=request.voice,
            language=request.language,
        )

        artifact = VoiceArtifact(
            scene_id=request.scene_id,
            audio_path=output,
        )

        self.repository.save(artifact)

        return artifact