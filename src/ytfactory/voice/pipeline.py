from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from loguru import logger

from ytfactory.config.settings import Settings
from ytfactory.providers.tts.debug import TTSDebugWriter
from ytfactory.providers.tts.factory import get_tts_provider
from ytfactory.providers.tts.optimizer import SpeechOptimizer
from ytfactory.providers.tts.pacing.injector import PauseInjector
from ytfactory.providers.tts.validator import AudioValidator, ValidationResult

from .aligner import align as whisperx_align
from .aligner import save_alignment
from .artifacts import audio_directory
from .models import VoiceArtifact
from .repository import VoiceRepository

_optimizer = SpeechOptimizer()
_validator = AudioValidator()
_pacer = PauseInjector()

# Exponential backoff base delay (doubles on each retry)
_RETRY_BASE_DELAY_S = 2.0


def _normalize_audio_attack(audio_path: Path) -> None:
    """Apply dynamic normalization to fix Edge TTS soft attack at the start of speech.

    Edge TTS neural synthesis applies a natural soft-attack envelope to the first
    ~200–300 ms of each utterance. dynaudnorm corrects this by normalising
    per-frame gain so the opening word starts at full volume.
    """
    tmp = audio_path.with_suffix(".norm.mp3")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(audio_path),
                "-af",
                "dynaudnorm=p=0.95:m=100",
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "2",
                str(tmp),
            ],
            check=True,
            capture_output=True,
        )
        tmp.replace(audio_path)
    except Exception as exc:
        logger.warning("Audio normalization failed for {}: {}", audio_path.name, exc)
        if tmp.exists():
            tmp.unlink(missing_ok=True)


class VoicePipeline:
    """Generate narration audio for every scene."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._provider = get_tts_provider(settings)
        self._repository = VoiceRepository()

    def run(
        self,
        project_id: str,
        style: str = "spiritual",
        language: str = "en",
    ) -> None:
        scene_file = (
            Path("workspace") / "jobs" / project_id / "scenes" / "scene-plan.json"
        )

        with open(scene_file, encoding="utf-8") as f:
            scenes = json.load(f)["scenes"]

        total = len(scenes)
        scenes_metadata: list[dict] = []

        for idx, scene in enumerate(scenes):
            output = audio_directory(project_id) / f"scene-{scene['index']:03d}.mp3"
            timing_output = output.with_suffix(".timing.json")

            if output.exists() and timing_output.exists():
                logger.debug("TTS skip scene {} (already generated)", scene["index"])
                continue

            scene_position = idx / max(total - 1, 1)
            original_text = scene["narration"]
            word_count = len(original_text.split())
            scene_title = scene.get("title", "")
            scene_type = scene.get("scene_type", "generated_image")

            debug = TTSDebugWriter(
                project_id=project_id,
                scene_index=scene["index"],
                enabled=self._settings.tts_debug,
            )
            debug.write_original(original_text)

            # Contemplative pacing is skipped for asset/brand scenes (short by design).
            use_pacing = self._settings.tts_pacing_enabled and scene_type != "asset"

            if not use_pacing:
                # Standard path: optimizer runs on the full narration.
                optimized = _optimizer.optimize(
                    original_text,
                    style=style,
                    scene_position=scene_position,
                    keywords=[scene_title] if scene_title else None,
                )
                debug.write_optimized(optimized)

            # Retry loop with exponential backoff
            boundaries: list[dict] = []
            validation: ValidationResult | None = None
            retry_count = 0
            max_retries = (
                self._settings.tts_max_retries if self._settings.tts_auto_retry else 1
            )

            for attempt in range(max_retries):
                if attempt > 0:
                    delay = _RETRY_BASE_DELAY_S * (2 ** (attempt - 1))
                    logger.info(
                        "TTS retry scene {} attempt {}/{} (backoff {:.1f}s)",
                        scene["index"],
                        attempt + 1,
                        max_retries,
                        delay,
                    )
                    time.sleep(delay)
                    if output.exists():
                        output.unlink()

                try:
                    if use_pacing:
                        # Pacing path: PauseInjector calls optimizer per-sentence
                        # and injects silence between sentences via FFmpeg concat.
                        _, boundaries = _pacer.generate(
                            narration=original_text,
                            output_path=output,
                            optimizer=_optimizer,
                            provider=self._provider,
                            profile=self._settings.tts_pacing_profile,
                            style=style,
                            language=language,
                            scene_position=scene_position,
                            keywords=[scene_title] if scene_title else None,
                        )
                    else:
                        debug.write_provider_request(
                            {
                                "text": optimized,
                                "language": language,
                                "style": style,
                                "scene_position": scene_position,
                            }
                        )
                        _, boundaries = self._provider.generate_with_boundaries(
                            text=optimized,
                            output_path=output,
                            language=language,
                            style=style,
                            scene_position=scene_position,
                        )
                except Exception as exc:
                    logger.error("TTS error scene {}: {}", scene["index"], exc)
                    retry_count = attempt + 1
                    continue

                debug.write_provider_response(boundaries)
                debug.write_timing(boundaries)

                # Audio validation
                if self._settings.tts_validate_audio:
                    validation = _validator.validate(
                        audio_path=output,
                        word_count=word_count,
                        scene_index=scene["index"],
                    )
                    debug.write_validation(validation.to_dict())

                    if validation.passed:
                        retry_count = attempt
                        break

                    retry_count = attempt + 1
                    if attempt + 1 >= max_retries:
                        logger.warning(
                            "TTS scene {} failed validation after {} attempts — keeping last output",
                            scene["index"],
                            max_retries,
                        )
                else:
                    retry_count = attempt
                    break

            # Normalise TTS audio to fix soft attack at start of speech
            if output.exists():
                _normalize_audio_attack(output)

            # Write timing even on partial success
            timing_output.write_text(
                json.dumps(boundaries, indent=2),
                encoding="utf-8",
            )

            # WhisperX forced alignment (optional — gives accurate word timestamps)
            if self._settings.whisperx_enabled and output.exists():
                alignment_output = output.with_suffix(".alignment.json")
                if not alignment_output.exists():
                    try:
                        alignment = whisperx_align(
                            original_text,
                            output,
                            device=self._settings.whisperx_device,
                            language=language,
                        )
                        save_alignment(alignment, alignment_output)
                    except Exception as exc:
                        logger.warning(
                            "WhisperX alignment failed for scene {} — "
                            "subtitle timing will use TTS boundaries instead. Error: {}",
                            scene["index"],
                            exc,
                        )

            # Collect debug metadata for project summary
            duration = (
                validation.duration_seconds
                if validation
                else (boundaries[-1]["end"] if boundaries else 0.0)
            )
            scene_meta = {
                "scene_index": scene["index"],
                "provider": self._provider.capabilities.provider_name,
                "voice": None,
                "style": style,
                "language": language,
                "duration_seconds": duration,
                "word_count": word_count,
                "retry_count": retry_count,
                "validation_passed": validation.passed if validation else True,
                "validation_issues": validation.issues if validation else [],
                "pacing_enabled": use_pacing,
                "pacing_profile": self._settings.tts_pacing_profile
                if use_pacing
                else None,
            }
            debug.write_metadata(scene_meta)
            scenes_metadata.append(scene_meta)

            self._repository.save(
                VoiceArtifact(
                    scene_id=scene["index"],
                    audio_path=output,
                )
            )

        # Write project-level diagnostics report
        TTSDebugWriter.write_project_summary(
            project_id=project_id,
            scenes_metadata=scenes_metadata,
            enabled=self._settings.tts_debug,
        )
