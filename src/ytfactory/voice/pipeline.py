from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from loguru import logger

from ytfactory.config.settings import Settings
from ytfactory.validators.kai_firewall import check_artifact
from video_core.providers.tts.debug import TTSDebugWriter
from video_core.providers.tts.factory import get_tts_provider
from video_core.providers.tts.formatter import SpeechFormatter
from video_core.providers.tts.optimizer import SpeechOptimizer
from ytfactory.providers.tts.pacing.injector import PauseInjector
from video_core.providers.tts.validator import AudioValidator, ValidationResult
from video_core.providers.tts.analytics.collector import TTSAnalyticsCollector
from video_core.providers.tts.analytics.models import TTSAnalyticsRecord, TTSVideoSummary
from video_core.providers.tts.analytics.pricing import ProviderPricingConfig

from .aligner import align as whisperx_align
from .aligner import save_alignment
from .artifacts import audio_directory
from .models import VoiceArtifact
from .repository import VoiceRepository
from ytfactory.shared.pipeline_status import get_writer
from ytfactory.shared.script_utils import strip_tts_directives
from ytfactory.ssml_enhancer import SsmlEnhancer, strip_ssml

_optimizer = SpeechOptimizer()
_formatter = SpeechFormatter()
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
                "dynaudnorm=p=0.95:m=500",
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


def _get_audio_duration(path: Path) -> float:
    """Return audio duration in seconds via ffprobe. Returns 0.0 on error."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _estimate_word_boundaries(narration: str, duration: float) -> list[dict]:
    """Estimate per-word timestamps by distributing duration proportionally."""
    words = narration.split()
    if not words or duration <= 0:
        return []
    total_chars = sum(len(w) for w in words)
    boundaries: list[dict] = []
    cursor = 0.0
    for word in words:
        weight = len(word) / max(total_chars, 1)
        end = cursor + weight * duration
        boundaries.append({"word": word, "start": cursor, "end": end})
        cursor = end
    return boundaries


class VoicePipeline:
    """Generate narration audio for every scene."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._ssml_enhancer: SsmlEnhancer | None = None
        self._pricing_config = ProviderPricingConfig.from_dict({
            "providers": {
                "cartesia": {
                    "credits_per_character": settings.cartesia_credits_per_character,
                    "credits_per_request": settings.cartesia_credits_per_request,
                    "usd_per_credit": settings.cartesia_usd_per_credit,
                }
            }
        })
        if (
            settings.tts_analytics_enabled
            and settings.cartesia_credits_per_character == 0.0
            and settings.cartesia_credits_per_request == 0.0
        ):
            logger.warning(
                "Cartesia pricing is not configured (CARTESIA_CREDITS_PER_CHARACTER / "
                "CARTESIA_CREDITS_PER_REQUEST are both 0.0 in .env) — Estimated Credits "
                "and Estimated Cost will report 0.0 regardless of actual usage. Set these "
                "from your Cartesia plan's rate to get real estimates."
            )
        self._analytics = TTSAnalyticsCollector(
            enabled=settings.tts_analytics_enabled,
            pricing_config=self._pricing_config,
        )
        self._provider = None
        self._repository = VoiceRepository()

    def _ensure_provider(self):
        if self._provider is None:
            self._provider = get_tts_provider(self._settings, analytics=self._analytics)
        return self._provider

    def _ensure_ssml_enhancer(self) -> SsmlEnhancer:
        if self._ssml_enhancer is None:
            from video_core.providers.llm.factory import get_llm_for_role
            self._ssml_enhancer = SsmlEnhancer(get_llm_for_role(self._settings, "ssml"))
        return self._ssml_enhancer

    def _regenerate_subtitles(
        self,
        scene: dict,
        audio_path: Path,
        timing_output: Path,
        language: str,
    ) -> None:
        """Regenerate subtitle timing when missing (e.g. TTS was cached)."""
        alignment_output = audio_path.with_suffix(".alignment.json")

        if (
            self._settings.whisperx_enabled
            and audio_path.exists()
            and not alignment_output.exists()
        ):
            try:
                alignment = whisperx_align(
                    scene["narration"],
                    audio_path,
                    device=self._settings.whisperx_device,
                    language=language,
                )
                save_alignment(alignment, alignment_output)
            except Exception as exc:
                logger.warning(
                    "WhisperX alignment failed for scene {} — "
                    "subtitle timing will use estimated boundaries instead. Error: {}",
                    scene["index"],
                    exc,
                )

        if not timing_output.exists():
            duration = _get_audio_duration(audio_path)
            if duration > 0:
                boundaries = _estimate_word_boundaries(scene["narration"], duration)
            else:
                boundaries = []
            timing_output.write_text(
                json.dumps(boundaries, indent=2),
                encoding="utf-8",
            )

    def run(
        self,
        project_id: str,
        style: str = "spiritual",
        language: str = "en",
    ) -> None:
        if not self._settings.voice_enabled:
            logger.info("VOICE_ENABLED=false — skipping narration generation")
            return

        self._ensure_provider()
        scene_file = (
            Path("workspace") / "jobs" / project_id / "scenes" / "scene-plan.json"
        )

        with open(scene_file, encoding="utf-8") as f:
            scenes = json.load(f)["scenes"]

        total = len(scenes)
        scenes_metadata: list[dict] = []
        self._analytics.set_current_video(project_id)

        _w = get_writer()
        if _w:
            _w.stage_start("tts", total=total)

        for idx, scene in enumerate(scenes):
            output = audio_directory(project_id) / f"scene-{scene['index']:03d}.mp3"
            timing_output = output.with_suffix(".timing.json")

            if output.exists() and timing_output.exists():
                logger.debug("TTS skip scene {} (already generated)", scene["index"])
                if _w:
                    _w.stage_progress(idx + 1)
                continue

            # File-level cache: audio exists (e.g. timing.json missing from an
            # interrupted prior run) — skip the paid TTS call entirely rather
            # than re-spending credits. Distinct from TTSCache's API-level
            # key-based cache, which only helps when text/voice/model match
            # exactly; this is a coarser, cheaper check that runs first.
            tts_skipped = False
            if (
                self._settings.tts_skip_existing
                and output.exists()
                and output.stat().st_size > 1000
            ):
                logger.info(
                    "TTS skip scene {} — cache_hit=True (file exists, {} bytes)",
                    scene["index"],
                    output.stat().st_size,
                )
                tts_skipped = True
                self._repository.save(
                    VoiceArtifact(scene_id=scene["index"], audio_path=output)
                )
                if self._analytics.enabled:
                    narration = scene["narration"]
                    self._analytics.record(
                        TTSAnalyticsRecord(
                            scene_id=str(scene["index"]),
                            provider=self._provider.capabilities.provider_name,
                            characters=len(narration),
                            words=len(narration.split()),
                            cache_hit=True,
                            output_bytes=output.stat().st_size,
                        )
                    )
                scenes_metadata.append({
                    "scene_index": scene["index"],
                    "provider": self._provider.capabilities.provider_name,
                    "voice": None,
                    "style": style,
                    "language": language,
                    "duration_seconds": _get_audio_duration(output),
                    "word_count": len(scene["narration"].split()),
                    "retry_count": 0,
                    "validation_passed": True,
                    "validation_issues": [],
                    "pacing_enabled": False,
                    "pacing_profile": None,
                })

            if not tts_skipped:
                scene_position = idx / max(total - 1, 1)
                original_text = strip_tts_directives(scene["narration"])
                check_artifact(original_text, "tts_input")
                word_count = len(original_text.split())
                scene_title = scene.get("title", "")
                scene_type = scene.get("scene_type", "generated_image")

                debug = TTSDebugWriter(
                    project_id=project_id,
                    scene_index=scene["index"],
                    enabled=self._settings.tts_debug,
                )
                debug.write_original(original_text)

                # SSML enhancement — Speechify-compatible SSML injected before TTS.
                # When active: ssml_script goes to TTS; clean_script goes to subtitles.
                # Pacing is bypassed because SSML already encodes all pauses via <break>.
                use_ssml = self._settings.ssml_enhancement_enabled
                if use_ssml:
                    narrative_phase = scene.get("narrative_phase", "")
                    # Normalise line breaks → natural pauses before SSML enhancement
                    # so the enhancer receives clean sentence boundaries, not raw \n.
                    formatted_for_ssml = _formatter.format(original_text, style=style)
                    ssml_script = self._ensure_ssml_enhancer().enhance(
                        formatted_for_ssml, narrative_phase=narrative_phase
                    )
                    clean_script = strip_ssml(ssml_script)
                    debug.write_ssml(ssml_script)
                else:
                    ssml_script = original_text
                    clean_script = original_text

                # Contemplative pacing is skipped for asset/brand scenes (short by design)
                # and also skipped when SSML is active (SSML encodes pauses itself).
                use_pacing = (
                    self._settings.tts_pacing_enabled
                    and scene_type not in ("asset", "brand_card")
                    and not use_ssml
                )

                if not use_pacing:
                    if use_ssml:
                        tts_input = ssml_script
                        logger.debug(
                            "TTS [ssml] scene {} — enhanced SSML ({} chars):\n{}",
                            scene["index"],
                            len(ssml_script),
                            ssml_script,
                        )
                    else:
                        # Standard path: optimizer runs on the full narration.
                        tts_input = _optimizer.optimize(
                            original_text,
                            style=style,
                            scene_position=scene_position,
                            keywords=[scene_title] if scene_title else None,
                        )
                        debug.write_optimized(tts_input)

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
                                    "text": tts_input,
                                    "language": language,
                                    "style": style,
                                    "scene_position": scene_position,
                                }
                            )
                            _, boundaries = self._provider.generate_with_boundaries(
                                text=tts_input,
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

                # dynaudnorm soft-attack fix is Edge TTS specific — other providers
                # (Speechify, Cartesia, etc.) handle their own audio shaping.
                if output.exists() and self._provider.capabilities.provider_name == "edge_tts":
                    _normalize_audio_attack(output)

                # Write timing even on partial success
                timing_output.write_text(
                    json.dumps(boundaries, indent=2),
                    encoding="utf-8",
                )

                # WhisperX forced alignment (optional — gives accurate word timestamps).
                # Always aligns against clean_script (SSML tags stripped) so the
                # transcript matches the spoken words, never the markup.
                if self._settings.whisperx_enabled and output.exists():
                    alignment_output = output.with_suffix(".alignment.json")
                    if not alignment_output.exists():
                        try:
                            alignment = whisperx_align(
                                clean_script,
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
                    if validation and validation.duration_seconds > 0
                    else (boundaries[-1]["end"] if boundaries else _get_audio_duration(output))
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

                # Per-scene TTS analytics log
                if self._settings.tts_log_per_scene and self._analytics.enabled:
                    scene_records = [
                        r for r in self._analytics.all_records()
                        if r.scene_id == str(scene["index"])
                    ]
                    if scene_records:
                        r = scene_records[-1]
                        logger.info(
                            "Scene {:03d} | Provider: {} | Model: {} | Voice: {} | "
                            "Characters: {} | Words: {} | Duration: {:.1f}s | "
                            "Cache Hit: {} | Retries: {} | Latency: {:.2f}s | "
                            "Estimated Credits: {:.1f} | Estimated Cost: ${:.4f}",
                            scene["index"],
                            r.provider,
                            r.model,
                            r.voice,
                            r.characters,
                            r.words,
                            r.audio_duration,
                            r.cache_hit,
                            r.retry_count,
                            r.latency_ms / 1000.0,
                            r.estimated_credits,
                            r.estimated_cost,
                        )

            # ── Subtitles — always regenerate if missing ─────────────────
            if not timing_output.exists():
                logger.debug("Subtitle regenerating scene {}", scene["index"])
                self._regenerate_subtitles(scene, output, timing_output, language)
            else:
                logger.debug("Subtitle skip scene {} (already exists)", scene["index"])

            if _w:
                _w.stage_progress(idx + 1)
        # Write project-level diagnostics report
        TTSDebugWriter.write_project_summary(
            project_id=project_id,
            scenes_metadata=scenes_metadata,
            enabled=self._settings.tts_debug,
        )

        # Per-video TTS summary
        if self._settings.tts_summary_enabled and self._analytics.enabled:
            self._log_video_summary(project_id)

        if _w:
            _w.stage_complete()

    def _log_video_summary(self, video_id: str) -> None:
        if not self._analytics or not self._analytics.enabled:
            return
        summary = self._analytics.video_summary(video_id)
        if not summary or not isinstance(summary, TTSVideoSummary):
            return
        if summary.total_requests == 0:
            return
        logger.info("=" * 60)
        logger.info("TTS SUMMARY")
        logger.info("=" * 60)
        logger.info("Scenes: {}", summary.total_scenes)
        logger.info("Requests: {}", summary.total_requests)
        logger.info("Characters: {}", summary.total_characters)
        logger.info("Words: {}", summary.total_words)
        logger.info("Total Audio Duration: {:.1f}s", summary.total_audio_duration)
        logger.info("Average Scene Duration: {:.1f}s", summary.avg_scene_duration)
        logger.info("Average Characters: {:.0f}", summary.avg_characters_per_scene)
        logger.info("Cache Hits: {}", summary.cache_hits)
        logger.info("Cache Misses: {}", summary.cache_misses)
        logger.info("Cache Hit %: {:.1f}%", summary.cache_hit_rate * 100)
        logger.info("Retries: {}", summary.total_retries)
        logger.info("Average Latency: {:.2f}s", summary.avg_latency_ms / 1000.0)
        logger.info("Estimated Credits: {:.1f}", summary.total_credits)
        logger.info("Estimated Cost: ${:.4f}", summary.total_cost)
        logger.info("Providers: {}", dict(summary.providers_used))
        logger.info("Models: {}", dict(summary.models_used))
        logger.info("Voices: {}", dict(summary.voices_used))
        logger.info("=" * 60)
