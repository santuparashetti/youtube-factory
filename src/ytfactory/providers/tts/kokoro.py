"""
Kokoro TTS provider — high-quality neural TTS via the kokoro Python library.

Kokoro is an open-source TTS system with studio-quality voices.
Install the library with:  pip install kokoro soundfile

Voices (American English lang_code='a'):
  am_michael  — warm male narrator (default)
  am_adam     — clear male narrator
  af_sarah    — female narrator
  af_bella    — expressive female narrator

This provider:
  - Requires the ``kokoro`` and ``soundfile`` packages (lazy imports).
  - Converts native float32/WAV output to MP3 via FFmpeg.
  - Returns empty word boundaries from generate(); use WhisperX alignment
    (whisperx_enabled=True) for accurate per-word timing.
  - Supports retry, timeouts and structured diagnostics.
  - No SSML — Kokoro is controlled via speed and voice ID only.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

from loguru import logger

from ytfactory.config.settings import Settings

from .base import TTSProvider
from .capabilities import ProviderCapabilities

# Kokoro lang_code prefix → internal language code
_LANG_MAP: dict[str, str] = {
    "en-US": "a",  # American English
    "en-GB": "b",  # British English
    "en": "a",
    "ja": "j",
    "zh": "z",
    "es": "e",
    "fr": "f",
    "hi": "h",
    "it": "i",
    "pt": "p",
}

_RETRY_DELAY_S = 2.0


class KokoroProvider(TTSProvider):
    """Kokoro TTS provider — local neural inference."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._voice = settings.kokoro_voice
        self._speed = settings.kokoro_speed
        self._sample_rate = settings.kokoro_sample_rate
        self._pipeline = None  # lazy-loaded

    # ── Capabilities ───────────────────────────────────────────────────────────

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_name="kokoro",
            supports_ssml=False,
            supports_word_boundaries=False,  # via WhisperX alignment instead
            supports_pitch=False,
            supports_rate=True,  # speed parameter
            supports_streaming=False,
            supports_emotion=False,
            supports_voice_styles=False,
        )

    # ── Lazy pipeline loader ───────────────────────────────────────────────────

    def _get_pipeline(self, lang_code: str):
        """Load (or reuse) a KPipeline for the given language code."""
        try:
            from kokoro import KPipeline  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "Kokoro TTS requires the 'kokoro' package. "
                "Install it with: pip install kokoro soundfile\n"
                f"Original error: {exc}"
            ) from exc

        if self._pipeline is None:
            logger.info("Kokoro: loading pipeline lang_code={}", lang_code)
            self._pipeline = KPipeline(lang_code=lang_code)
        return self._pipeline

    # ── Voice resolution ───────────────────────────────────────────────────────

    def _resolve_voice(self, voice: str | None) -> str:
        return voice or self._voice

    def _resolve_lang_code(self, language: str) -> str:
        return _LANG_MAP.get(language, _LANG_MAP.get(language.split("-")[0], "a"))

    # ── Core synthesis ─────────────────────────────────────────────────────────

    def _synthesise(
        self,
        text: str,
        output_path: Path,
        voice: str,
        lang_code: str,
    ) -> None:
        """Run Kokoro synthesis and write output as MP3."""
        try:
            import numpy as np  # type: ignore[import-untyped]
            import soundfile as sf  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "Kokoro TTS requires 'numpy' and 'soundfile'. "
                "Install with: pip install soundfile numpy\n"
                f"Original error: {exc}"
            ) from exc

        pipeline = self._get_pipeline(lang_code)

        # Collect all audio chunks from the generator
        chunks = []
        for _gs, _ps, audio in pipeline(
            text,
            voice=voice,
            speed=self._speed,
            split_pattern=r"\n+",
        ):
            if audio is not None and len(audio) > 0:
                chunks.append(audio)

        if not chunks:
            raise RuntimeError(f"Kokoro produced no audio for voice={voice!r}")

        audio_array = np.concatenate(chunks, axis=0) if len(chunks) > 1 else chunks[0]

        # Write to a temporary WAV file, then convert to MP3 via FFmpeg
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            sf.write(str(tmp_path), audio_array, self._sample_rate)
            self._wav_to_mp3(tmp_path, output_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _wav_to_mp3(self, wav_path: Path, mp3_path: Path) -> None:
        """Convert WAV to MP3 using FFmpeg (required in the project's environment)."""
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(wav_path),
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "2",
                str(mp3_path),
            ],
            check=True,
            capture_output=True,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        language: str = "en",
        style: str | None = None,
        scene_position: float = 0.5,
    ) -> Path:
        resolved_voice = self._resolve_voice(voice)
        lang_code = self._resolve_lang_code(language)
        t0 = time.perf_counter()

        max_retries = (
            self._settings.tts_max_retries if self._settings.tts_auto_retry else 1
        )
        last_exc: Exception | None = None

        for attempt in range(max_retries):
            if attempt > 0:
                delay = _RETRY_DELAY_S * (2 ** (attempt - 1))
                logger.info(
                    "Kokoro retry attempt {}/{} (backoff {:.1f}s)",
                    attempt + 1,
                    max_retries,
                    delay,
                )
                time.sleep(delay)

            try:
                self._synthesise(text, output_path, resolved_voice, lang_code)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Kokoro synthesis error attempt {}: {}", attempt + 1, exc
                )

        if last_exc is not None:
            raise last_exc

        elapsed = time.perf_counter() - t0
        logger.info(
            "TTS [kokoro] voice={} speed={} words={} elapsed={:.1f}s",
            resolved_voice,
            self._speed,
            len(text.split()),
            elapsed,
        )
        return output_path

    def generate_with_boundaries(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        language: str = "en",
        style: str | None = None,
        scene_position: float = 0.5,
    ) -> tuple[Path, list[dict]]:
        """Generate audio. Returns empty boundaries — use WhisperX for word timing."""
        audio_path = self.generate(
            text,
            output_path,
            voice=voice,
            language=language,
            style=style,
            scene_position=scene_position,
        )
        return audio_path, []
