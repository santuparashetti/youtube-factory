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

_NEGATIVE_PROMPT = (
    "text, watermark, logo, words, letters, numbers, captions, subtitles, "
    "blurry, distorted, ugly, low quality, bad anatomy, duplicate, "
    "worst quality, overexposed, underexposed"
)


# ── SRT helpers ───────────────────────────────────────────────────────────────

def _fmt_time(seconds: float) -> str:
    """Format float seconds as SRT timestamp HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    # Clamp ms to [0, 999] to avoid rounding to 1000
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_srt_from_boundaries(
    boundaries: list[dict],
    words_per_line: int = 7,
) -> str:
    """
    Build an SRT file from Edge TTS word boundary events.
    Each block groups ~7 words and uses their real start/end timestamps —
    so captions appear and disappear in exact sync with the spoken audio.
    """
    if not boundaries:
        return ""

    blocks: list[str] = []
    i = 0
    block_num = 1

    while i < len(boundaries):
        chunk = boundaries[i : i + words_per_line]
        text = " ".join(b["word"] for b in chunk)
        start = chunk[0]["start"]
        end = chunk[-1]["end"]
        blocks.append(f"{block_num}\n{_fmt_time(start)} --> {_fmt_time(end)}\n{text}\n")
        block_num += 1
        i += words_per_line

    return "\n".join(blocks)


def _build_srt_fallback(narration: str, total_duration: float) -> str:
    """
    Proportional-timing fallback when word boundaries aren't available.
    Used by non-EdgeTTS providers.
    """
    words = narration.split()
    if not words:
        return f"1\n00:00:00,000 --> {_fmt_time(total_duration)}\n{narration}\n"

    phrase_size = 7
    phrases = [words[i : i + phrase_size] for i in range(0, len(words), phrase_size)]
    total_words = len(words)
    blocks: list[str] = []
    cursor = 0.0

    for idx, phrase_words in enumerate(phrases, start=1):
        phrase_duration = (len(phrase_words) / total_words) * total_duration
        end_time = cursor + phrase_duration
        text = " ".join(phrase_words)
        blocks.append(f"{idx}\n{_fmt_time(cursor)} --> {_fmt_time(end_time)}\n{text}\n")
        cursor = end_time

    return "\n".join(blocks)


def _get_audio_duration(path: Path) -> float:
    try:
        from mutagen.mp3 import MP3
        return MP3(str(path)).info.length
    except Exception:
        return 0.0


# ── Main node ─────────────────────────────────────────────────────────────────

def generate_scene_assets(state: VideoState) -> dict:
    """
    Process one scene (invoked in parallel via LangGraph Send API):
      1. Generate image  (idempotent — skip if PNG already exists)
      2. Generate voice  (streaming → captures word boundary events)
      3. Build SRT from real word timestamps  (frame-perfect sync)
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

    # ── 1. Generate image (idempotent) ────────────────────────────────────
    if not image_path.exists():
        try:
            provider = get_image_provider(settings)
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
                    provider.generate(request)
                    break
                except Exception as exc:
                    if attempt == 2:
                        errors.append(f"Scene {index} image failed after 3 attempts: {exc}")
                        logger.error("Scene {} image failed: {}", index, exc)
        except Exception as exc:
            errors.append(f"Scene {index} image provider error: {exc}")
    else:
        logger.info("Scene {} image already exists, skipping", index)

    # ── 2. Generate voice + capture word boundaries ───────────────────────
    boundaries: list[dict] = []

    if not audio_path.exists():
        try:
            tts = get_tts_provider(settings)
            for attempt in range(3):
                try:
                    _, boundaries = tts.generate_with_boundaries(
                        text=narration,
                        output_path=audio_path,
                        language=language,
                    )
                    break
                except Exception as exc:
                    if attempt == 2:
                        errors.append(f"Scene {index} voice failed after 3 attempts: {exc}")
                        logger.error("Scene {} voice failed: {}", index, exc)
        except Exception as exc:
            errors.append(f"Scene {index} TTS provider error: {exc}")
    else:
        logger.info("Scene {} audio already exists, skipping", index)

    # ── 3. Determine real audio duration ─────────────────────────────────
    real_duration = estimated_duration
    if boundaries:
        # Duration from the last word boundary event (most accurate)
        real_duration = boundaries[-1]["end"]
    elif audio_path.exists():
        measured = _get_audio_duration(audio_path)
        if measured > 0.5:
            real_duration = measured

    # ── 4. Build SRT ─────────────────────────────────────────────────────
    if boundaries:
        # Frame-perfect: every word appears at its exact spoken timestamp
        srt_content = _build_srt_from_boundaries(boundaries)
        method = "word-boundary"
    else:
        # Fallback: proportional estimate (non-EdgeTTS providers)
        srt_content = _build_srt_fallback(narration, real_duration)
        method = "proportional-estimate"

    srt_path.write_text(srt_content, encoding="utf-8")

    logger.info(
        "Scene {} — image:{} audio:{:.1f}s srt:{} blocks ({})",
        index,
        "✓" if image_path.exists() else "✗",
        real_duration,
        srt_content.count("\n\n") + 1,
        method,
    )

    return {
        "image_paths": {index: str(image_path)} if image_path.exists() else {},
        "audio_paths": {index: str(audio_path)} if audio_path.exists() else {},
        "audio_durations": {index: real_duration},
        "srt_paths": {index: str(srt_path)},
        "stage_errors": errors,
    }
