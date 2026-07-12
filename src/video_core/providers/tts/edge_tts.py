"""
Edge TTS provider — documentary narration quality.

Improvements over V1:
  - SpeechFormatter replaces inline _prepare_text() — fixes double-period
    clipping bug at paragraph boundaries (first word after \\n\\n was
    occasionally clipped because "word.\\n\\nnext" → "word.. next")
  - Per-scene emotion classification → rate/pitch tuned to mood
  - Strategic <break/> injection for dramatic pauses at sentence boundaries
  - Emotional arc awareness (beginning → curious, middle → reflective, end → hopeful)
  - Natural paragraph breaks preserved as audible silences
  - Christopher Neural at near-natural pace (no robotic slow-down)
  - ProviderCapabilities declared for feature detection
  - Structured logging: voice, rate, pitch, timing, duration
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from pathlib import Path

import edge_tts
from loguru import logger

from video_core.config.shared_settings import SharedSettings

from .base import TTSProvider
from .capabilities import ProviderCapabilities
from .emotion import EmotionProfile, classify_scene
from .formatter import SpeechFormatter

# Edge TTS emits offsets in 100-nanosecond ticks (Windows FILETIME units).
_TICKS_PER_SECOND = 10_000_000

# Primary documentary voice — warm, calm, trustworthy US male.
_DOC_VOICE = "en-US-ChristopherNeural"

# Default prosody when emotion classification is not applied.
_DEFAULT_RATE = "+0%"
_DEFAULT_PITCH = "+0Hz"

# Singleton formatter — stateless, safe to share across calls.
_formatter = SpeechFormatter()


class EdgeTTSProvider(TTSProvider):
    """Microsoft Edge Text-to-Speech provider — documentary narration mode."""

    # ── Capabilities ──────────────────────────────────────────────────────────

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_name="edge_tts",
            supports_ssml=False,  # edge-tts library strips SSML tags
            supports_word_boundaries=True,
            supports_pitch=True,
            supports_rate=True,
            supports_streaming=True,
            supports_emotion=True,  # rate/pitch driven by emotion classifier
            supports_voice_styles=False,
        )

    # ── Voice map ─────────────────────────────────────────────────────────────

    _VOICES: dict[str, str] = {
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

    def __init__(self, settings: SharedSettings):
        self._settings = settings

    # ── Voice selection ───────────────────────────────────────────────────────

    def _resolve_voice(
        self,
        voice: str | None,
        language: str,
        style: str | None,
    ) -> str:
        if voice:
            return voice
        if style == "spiritual" and language.startswith("en"):
            return _DOC_VOICE
        return self._VOICES.get(language, self._VOICES["en"])

    # ── Async streaming core ──────────────────────────────────────────────────

    async def _stream(
        self,
        text: str,
        output_path: Path,
        voice: str,
        rate: str = "+0%",
        pitch: str = "+0Hz",
    ) -> list[dict]:
        """
        Stream Edge TTS to disk and return sentence-level word timing.

        Uses SentenceBoundary events (exact sentence timestamps) with
        proportional word distribution within each sentence.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            pitch=pitch,
        )

        sentences: list[dict] = []
        audio_chunks: list[bytes] = []

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                start = chunk["offset"] / _TICKS_PER_SECOND
                duration = chunk["duration"] / _TICKS_PER_SECOND
                sentences.append(
                    {
                        "text": chunk["text"],
                        "start": start,
                        "end": start + duration,
                    }
                )

        output_path.write_bytes(b"".join(audio_chunks))

        # Expand sentence timing → per-word boundaries (proportional within sentence)
        boundaries: list[dict] = []
        for sent in sentences:
            words = sent["text"].split()
            if not words:
                continue
            n = len(words)
            sent_start = sent["start"]
            sent_dur = sent["end"] - sent["start"]
            for i, word in enumerate(words):
                boundaries.append(
                    {
                        "word": word,
                        "start": round(sent_start + (i / n) * sent_dur, 4),
                        "end": round(sent_start + ((i + 1) / n) * sent_dur, 4),
                    }
                )

        return boundaries

    # ── Event-loop helper ─────────────────────────────────────────────────────

    def _run_async(self, coro):
        """Run an async coroutine safely regardless of event-loop context."""
        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        except RuntimeError:
            return asyncio.run(coro)

    # ── Internal synthesis entry point ────────────────────────────────────────

    def _synthesise(
        self,
        text: str,
        output_path: Path,
        voice: str,
        style: str | None,
        scene_position: float,
    ) -> tuple[list[dict], EmotionProfile | None, str, str]:
        """
        Full synthesis pipeline:
          1. Classify scene emotion → rate, pitch
          2. Format text via SpeechFormatter (fixes double-period bug)
          3. Synthesise with emotion-appropriate prosody

        Returns:
            (boundaries, emotion_profile, rate, pitch)
        """
        profile: EmotionProfile | None = None
        if style == "spiritual":
            profile = classify_scene(text, scene_position)
            rate = profile.rate
            pitch = profile.pitch
        else:
            rate = _DEFAULT_RATE
            pitch = _DEFAULT_PITCH

        # SpeechFormatter normalizes text and prevents double-period clipping.
        # This replaces the former inline _prepare_text() method.
        clean_text = _formatter.format(text, style)

        boundaries = self._run_async(
            self._stream(clean_text, output_path, voice, rate, pitch)
        )
        return boundaries, profile, rate, pitch

    # ── Public API ────────────────────────────────────────────────────────────

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
        resolved = self._resolve_voice(voice, language, style)
        t0 = time.perf_counter()
        boundaries, profile, rate, pitch = self._synthesise(
            text, output_path, resolved, style, scene_position
        )
        elapsed = time.perf_counter() - t0
        duration = boundaries[-1]["end"] if boundaries else 0.0
        logger.info(
            "TTS [edge] voice={} rate={} pitch={} emotion={} "
            "words={} duration={:.2f}s request={:.1f}s",
            resolved,
            rate,
            pitch,
            profile.emotion.value if profile else "default",
            len(text.split()),
            duration,
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
        """
        Generate audio AND return word-level timing boundaries.

        Returns:
            (output_path, boundaries)
            boundaries: [{word: str, start: float, end: float}] in seconds
        """
        resolved = self._resolve_voice(voice, language, style)
        t0 = time.perf_counter()
        boundaries, profile, rate, pitch = self._synthesise(
            text, output_path, resolved, style, scene_position
        )
        elapsed = time.perf_counter() - t0
        duration = boundaries[-1]["end"] if boundaries else 0.0
        logger.info(
            "TTS [edge] voice={} rate={} pitch={} emotion={} "
            "words={} duration={:.2f}s request={:.1f}s boundaries={}",
            resolved,
            rate,
            pitch,
            profile.emotion.value if profile else "default",
            len(text.split()),
            duration,
            elapsed,
            len(boundaries),
        )
        return output_path, boundaries
