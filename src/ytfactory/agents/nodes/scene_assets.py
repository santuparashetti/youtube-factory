"""Scene assets node — parallel image + voice + caption for one scene."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.domain.image import ImageRequest
from ytfactory.providers.image.factory import get_image_provider
from ytfactory.providers.tts.factory import get_tts_provider
from ytfactory.shared.constants import WORKSPACE_DIR

# Default negative prompt for image quality
_NEGATIVE_PROMPT = (
    "text, watermark, logo, words, letters, numbers, captions, subtitles, "
    "blurry, distorted, ugly, low quality, bad anatomy, duplicate, "
    "worst quality, overexposed, underexposed"
)

# Language → Edge TTS voice mapping
_LANGUAGE_VOICES: dict[str, str] = {
    "en": "en-US-AndrewNeural",
    "en-US": "en-US-AndrewNeural",
    "en-GB": "en-GB-RyanNeural",
    "es": "es-ES-AlvaroNeural",
    "fr": "fr-FR-HenriNeural",
    "de": "de-DE-ConradNeural",
    "hi": "hi-IN-MadhurNeural",
    "mr": "mr-IN-ManoharNeural",
    "ja": "ja-JP-KeitaNeural",
    "zh": "zh-CN-YunxiNeural",
    "pt": "pt-BR-AntonioNeural",
    "ar": "ar-SA-HamedNeural",
    "ru": "ru-RU-DmitryNeural",
    "ko": "ko-KR-InJoonNeural",
    "it": "it-IT-DiegoNeural",
}


def _get_voice(language: str) -> str:
    return _LANGUAGE_VOICES.get(language, _LANGUAGE_VOICES["en"])


def _get_audio_duration(path: Path) -> float:
    """Return MP3 duration in seconds using mutagen."""
    try:
        from mutagen.mp3 import MP3
        return MP3(str(path)).info.length
    except Exception:
        return 0.0


def _fmt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_srt(narration: str, total_duration: float) -> str:
    """
    Generate phrase-level SRT: one caption block every 6-8 words,
    timed proportionally to word count so captions follow speech pace.
    """
    words = narration.split()
    if not words:
        return f"1\n00:00:00,000 --> {_fmt_time(total_duration)}\n{narration}\n"

    phrase_size = 7
    phrases = [words[i : i + phrase_size] for i in range(0, len(words), phrase_size)]
    total_words = len(words)

    blocks = []
    cursor = 0.0

    for i, phrase_words in enumerate(phrases, start=1):
        phrase_text = " ".join(phrase_words)
        phrase_duration = (len(phrase_words) / total_words) * total_duration
        end_time = cursor + phrase_duration
        blocks.append(f"{i}\n{_fmt_time(cursor)} --> {_fmt_time(end_time)}\n{phrase_text}\n")
        cursor = end_time

    return "\n".join(blocks)


def generate_scene_assets(state: VideoState) -> dict:
    """
    Process one scene (invoked in parallel via LangGraph Send API):
      1. Generate image (idempotent — skip if PNG already exists)
      2. Generate voice audio (idempotent)
      3. Measure real audio duration
      4. Generate phrase-level SRT caption
    Returns partial state updates merged by reducers.
    """
    scene = state["current_scene"]
    project_id = state["project_id"]
    language = state.get("language", "en")
    settings = Settings()

    index: int = scene["index"]
    narration: str = scene["narration"]
    visual_prompt: str = scene["visual_prompt"]
    estimated_duration: float = float(scene.get("duration_seconds", 10))

    project_dir = Path(WORKSPACE_DIR) / project_id
    images_dir = project_dir / "images"
    audio_dir = project_dir / "audio"
    subtitles_dir = project_dir / "subtitles"

    for d in (images_dir, audio_dir, subtitles_dir):
        d.mkdir(parents=True, exist_ok=True)

    image_path = images_dir / f"scene-{index:03d}.png"
    audio_path = audio_dir / f"scene-{index:03d}.mp3"
    srt_path = subtitles_dir / f"scene-{index:03d}.srt"

    errors: list[str] = []

    # ── Generate image (idempotent) ───────────────────────────────────────
    if not image_path.exists():
        try:
            image_provider = get_image_provider(settings)
            request = ImageRequest(
                prompt=visual_prompt,
                output_path=image_path,
                width=settings.image_width,
                height=settings.image_height,
                negative_prompt=_NEGATIVE_PROMPT,
                guidance_scale=7.5,
            )
            for attempt in range(3):
                try:
                    image_provider.generate(request)
                    break
                except Exception as exc:
                    if attempt == 2:
                        errors.append(f"Scene {index} image failed after 3 attempts: {exc}")
                        logger.error("Scene {} image generation failed: {}", index, exc)
        except Exception as exc:
            errors.append(f"Scene {index} image provider error: {exc}")
    else:
        logger.info("Scene {} image already exists, skipping", index)

    # ── Generate voice (idempotent) ───────────────────────────────────────
    if not audio_path.exists():
        try:
            tts_provider = get_tts_provider(settings)
            voice = _get_voice(language)
            for attempt in range(3):
                try:
                    tts_provider.generate(
                        text=narration,
                        output_path=audio_path,
                        voice=voice,
                        language=language,
                    )
                    break
                except Exception as exc:
                    if attempt == 2:
                        errors.append(f"Scene {index} voice failed after 3 attempts: {exc}")
                        logger.error("Scene {} voice generation failed: {}", index, exc)
        except Exception as exc:
            errors.append(f"Scene {index} TTS provider error: {exc}")
    else:
        logger.info("Scene {} audio already exists, skipping", index)

    # ── Measure real audio duration ───────────────────────────────────────
    real_duration = estimated_duration
    if audio_path.exists():
        measured = _get_audio_duration(audio_path)
        if measured > 0.5:
            real_duration = measured

    # ── Generate phrase-level SRT (always regenerate with real duration) ──
    srt_content = _build_srt(narration, real_duration)
    srt_path.write_text(srt_content, encoding="utf-8")

    logger.info(
        "Scene {} — image: {}, audio: {}s, srt: {} blocks",
        index,
        "✓" if image_path.exists() else "✗",
        f"{real_duration:.1f}",
        srt_content.count("\n\n") + 1,
    )

    return {
        "image_paths": {index: str(image_path)} if image_path.exists() else {},
        "audio_paths": {index: str(audio_path)} if audio_path.exists() else {},
        "audio_durations": {index: real_duration},
        "srt_paths": {index: str(srt_path)},
        "stage_errors": errors,
    }
