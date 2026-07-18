"""Scene assets node — parallel image + voice + caption for one scene."""

from __future__ import annotations

import threading
from pathlib import Path

from loguru import logger

from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from video_core.domain.image import ImageRequest
from video_core.providers.image.factory import get_image_provider
from video_core.providers.tts.debug import TTSDebugWriter
from video_core.providers.tts.factory import get_tts_provider
from video_core.providers.tts.optimizer import SpeechOptimizer
from video_core.providers.tts.validator import AudioValidator
from ytfactory.images.human_detector import (
    add_back_view_hand_orientation,
    add_hand_avoidance_composition,
    detect_human_presence,
    has_intentional_hands,
    is_back_or_profile_view,
)
from ytfactory.images.prompt_engine import _DEFAULT_NEGATIVE_PROMPT, _PROVIDERS_WITH_NEGATIVE_PROMPTS
from ytfactory.images.review_config import ImageReviewConfig
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.subtitles import SubtitleEngine
from ytfactory.subtitles.models import SubtitleFormat

_optimizer = SpeechOptimizer()
_validator = AudioValidator()

# Vision and TTS providers are expensive to load (GGUF weights / PyTorch model).
# Cache instances at module level so all parallel LangGraph scene nodes share one
# loaded model instead of each loading their own copy.
_vision_provider_cache: dict[str, object] = {}
_vision_provider_lock = threading.Lock()

_tts_provider_cache: dict[str, object] = {}
_tts_provider_lock = threading.Lock()


def _get_vision_provider(provider_name: str, local_model: str) -> object:
    key = f"{provider_name}:{local_model}"
    if key in _vision_provider_cache:
        return _vision_provider_cache[key]
    with _vision_provider_lock:
        if key not in _vision_provider_cache:
            from video_core.providers.vision.factory import get_vision_provider
            _vision_provider_cache[key] = get_vision_provider(
                provider_name, local_model=local_model
            )
    return _vision_provider_cache[key]


def _get_tts_provider(settings: object) -> object:
    from ytfactory.config.settings import Settings
    s = settings if isinstance(settings, Settings) else Settings()
    key = f"{s.tts_provider}:{getattr(s, 'kokoro_voice', '')}:{getattr(s, 'kokoro_speed', '')}"
    if key in _tts_provider_cache:
        return _tts_provider_cache[key]
    with _tts_provider_lock:
        if key not in _tts_provider_cache:
            _tts_provider_cache[key] = get_tts_provider(s)
    return _tts_provider_cache[key]


def _get_audio_duration(path: Path) -> float:
    from video_core.providers.tts.validator import _measure_duration

    return _measure_duration(path)


# ── Main node ─────────────────────────────────────────────────────────────────


def generate_scene_assets(state: VideoState) -> dict:
    """
    Process one scene (invoked in parallel via LangGraph Send API):
      1. Generate image  (idempotent — skip if PNG already exists)
      2. Generate voice  (streaming → captures word boundary events)
      3. Build SRT via SubtitleEngine (semantic, validated, typography-clean)
    Returns partial state updates merged by reducers.
    """
    scene = state["current_scene"]
    project_id = state["project_id"]
    language = state.get("language", "en")
    style = state.get("style")
    settings = Settings()

    index: int = scene["index"]
    narration: str = scene["narration"]
    visual_prompt: str = scene["visual_prompt"]
    estimated_duration: float = float(scene.get("duration_seconds", 10))

    # Apply composition-level hand avoidance when hands aren't narrative-essential.
    uses_negative = settings.image_provider.lower() in _PROVIDERS_WITH_NEGATIVE_PROMPTS
    if not has_intentional_hands(narration):
        visual_prompt = add_hand_avoidance_composition(visual_prompt)
    elif is_back_or_profile_view(visual_prompt):
        visual_prompt = add_back_view_hand_orientation(visual_prompt)

    skip_images: bool = state.get("skip_images", False)

    project_dir = Path(WORKSPACE_DIR) / project_id
    images_dir = project_dir / "images"
    audio_dir = project_dir / "audio"
    subtitles_dir = project_dir / "subtitles"

    for d in (images_dir, audio_dir, subtitles_dir):
        d.mkdir(parents=True, exist_ok=True)

    image_path = images_dir / f"scene-{index:03d}.png"
    audio_path = audio_dir / f"scene-{index:03d}.mp3"
    srt_path = subtitles_dir / f"scene-{index:03d}.srt"
    ass_path = subtitles_dir / f"scene-{index:03d}.ass"

    errors: list[str] = []
    image_was_new = False

    # ── 1. Resolve image — asset bypass or AI generation ─────────────────
    scene_type: str = scene.get("scene_type", "generated_image")

    if scene_type == "asset":
        asset_path = Path(scene.get("asset_path", ""))
        if not asset_path.is_absolute():
            asset_path = Path.cwd() / asset_path
        if asset_path.exists():
            image_path = asset_path
            logger.info("Scene {} — asset scene: {}", index, asset_path)
        else:
            errors.append(
                f"Scene {index}: asset not found: {scene.get('asset_path')} — scene will be skipped"
            )
            logger.error("Scene {} asset missing: {}", index, asset_path)
    elif skip_images:
        logger.info("Scene {} — image generation skipped (--no-images mode)", index)
    elif not image_path.exists():
        image_was_new = True
        import time

        time.sleep(index * 3)

        try:
            provider = get_image_provider(settings)
            request = ImageRequest(
                prompt=visual_prompt,
                output_path=image_path,
                width=settings.image_width,
                height=settings.image_height,
                negative_prompt=_DEFAULT_NEGATIVE_PROMPT if uses_negative else None,
                guidance_scale=7.5,
            )
            for attempt in range(5):
                try:
                    provider.generate(request)
                    break
                except Exception as exc:
                    if attempt == 4:
                        errors.append(
                            f"Scene {index} image failed after 5 attempts: {exc}"
                        )
                        logger.error("Scene {} image failed: {}", index, exc)
                    else:
                        wait = 15 * (2**attempt)
                        logger.warning(
                            "Scene {} image attempt {} failed, retrying in {}s: {}",
                            index,
                            attempt + 1,
                            wait,
                            exc,
                        )
                        time.sleep(wait)
        except Exception as exc:
            errors.append(f"Scene {index} image provider error: {exc}")
    else:
        logger.info("Scene {} image already exists, skipping", index)

    # ── 1b. Vision review + auto-remediation ─────────────────────────────
    # Mirrors the review gate in ImagePipeline.run(); only fires for newly
    # generated images that contain human subjects.
    if image_was_new and image_path.exists() and detect_human_presence(visual_prompt):
        review_config = ImageReviewConfig.from_settings(settings)
        if review_config.enabled:
            try:
                from ytfactory.workflow.image_remediation_orchestrator import ImageRemediationOrchestrator

                vision = _get_vision_provider(
                    review_config.provider, local_model=review_config.local_model
                )
                orchestrator = ImageRemediationOrchestrator(
                    review_config, vision, get_image_provider(settings)
                )
                scene_with_dims = {
                    **scene,
                    "visual_prompt": visual_prompt,
                    "narration": narration,
                    "width": settings.image_width,
                    "height": settings.image_height,
                }
                logger.info("Scene {}: vision QA — reviewing image...", index)
                artifact = orchestrator.review_scene(scene_with_dims, image_path, images_dir)
                _qa_log = logger.warning if artifact.status == "FAIL" else logger.info
                _qa_log(
                    "Scene {}: vision QA {} (score={:.0f}, attempts={})",
                    index, artifact.status, artifact.score, artifact.attempts,
                )
            except Exception as exc:
                logger.warning("Scene {}: vision review error — {}", index, exc)

    # ── 2. Generate voice + capture word boundaries ───────────────────────
    boundaries: list[dict] = []

    # Calculate scene_position for emotional arc (0.0 = first, 1.0 = last)
    all_scenes = state.get("scene_plan", [])
    total_scenes = len(all_scenes)
    scene_position = (index - 1) / max(total_scenes - 1, 1) if total_scenes > 1 else 0.5

    debug = TTSDebugWriter(
        project_id=project_id,
        scene_index=index,
        enabled=settings.tts_debug,
    )

    if not audio_path.exists():
        try:
            tts = _get_tts_provider(settings)

            optimized_narration = _optimizer.optimize(
                narration,
                style=style,
                scene_position=scene_position,
            )
            debug.write_original(narration)
            debug.write_optimized(optimized_narration)
            debug.write_provider_request(
                {
                    "text": optimized_narration,
                    "language": language,
                    "style": style,
                    "scene_position": scene_position,
                }
            )

            max_retries = settings.tts_max_retries if settings.tts_auto_retry else 1
            for attempt in range(max_retries):
                try:
                    _, boundaries = tts.generate_with_boundaries(
                        text=optimized_narration,
                        output_path=audio_path,
                        language=language,
                        style=style,
                        scene_position=scene_position,
                    )
                    debug.write_provider_response(boundaries)
                    debug.write_timing(boundaries)

                    if settings.tts_validate_audio:
                        word_count = len(narration.split())
                        vresult = _validator.validate(
                            audio_path, word_count, scene_index=index
                        )
                        debug.write_validation(vresult.to_dict())
                        if vresult.passed or attempt + 1 >= max_retries:
                            break
                        audio_path.unlink(missing_ok=True)
                    else:
                        break
                except Exception as exc:
                    if attempt + 1 >= max_retries:
                        errors.append(
                            f"Scene {index} voice failed after {max_retries} attempts: {exc}"
                        )
                        logger.error("Scene {} voice failed: {}", index, exc)
                    else:
                        import time as _time

                        _time.sleep(2**attempt)
        except Exception as exc:
            errors.append(f"Scene {index} TTS provider error: {exc}")
    else:
        logger.info("Scene {} audio already exists, skipping", index)

    # ── 3. Determine real audio duration ─────────────────────────────────
    real_duration = estimated_duration
    if boundaries:
        real_duration = boundaries[-1]["end"]
    elif audio_path.exists():
        measured = _get_audio_duration(audio_path)
        if measured > 0.5:
            real_duration = measured

    # ── 4. Build subtitles via SubtitleEngine ──────────────────────────────
    engine = SubtitleEngine.from_settings(settings)
    use_ass = engine.format == SubtitleFormat.ASS

    if use_ass:
        ass_content, srt_content, _ = engine.build_both(
            boundaries=boundaries,
            narration=narration,
            scene_index=index,
            project_id=project_id,
            total_duration=real_duration,
        )
        ass_path.write_text(ass_content, encoding="utf-8")
        srt_path.write_text(srt_content, encoding="utf-8")
        subtitle_for_state = str(ass_path)
    else:
        srt_content = engine.build(
            boundaries=boundaries,
            narration=narration,
            scene_index=index,
            project_id=project_id,
            total_duration=real_duration,
        )
        srt_path.write_text(srt_content, encoding="utf-8")
        subtitle_for_state = str(srt_path)

    cue_count = srt_content.count("\n\n") + 1 if srt_content.strip() else 0
    logger.info(
        "Scene {} — image:{} audio:{:.1f}s subtitles:{} cues [{}]",
        index,
        "✓" if image_path.exists() else "✗",
        real_duration,
        cue_count,
        "ass+srt" if use_ass else "srt",
    )

    return {
        "image_paths": {index: str(image_path)} if image_path.exists() else {},
        "audio_paths": {index: str(audio_path)} if audio_path.exists() else {},
        "srt_paths": {index: subtitle_for_state},
        "stage_errors": errors,
    }
