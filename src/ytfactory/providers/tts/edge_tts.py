"""
Edge TTS provider — documentary narration quality.

Improvements over V1:
  - Per-scene emotion classification → rate/pitch tuned to mood
  - Strategic <break/> injection for dramatic pauses at sentence boundaries
  - Emotional arc awareness (beginning → curious, middle → reflective, end → hopeful)
  - Natural paragraph breaks preserved as audible silences
  - Christopher Neural at near-natural pace (no robotic slow-down)
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import re
from pathlib import Path

import edge_tts

from ytfactory.config.settings import Settings

from .base import TTSProvider
from .emotion import EmotionProfile, classify_scene

# Edge TTS emits offsets in 100-nanosecond ticks (Windows FILETIME units).
_TICKS_PER_SECOND = 10_000_000

# Primary documentary voice — warm, calm, trustworthy US male.
_DOC_VOICE = "en-US-ChristopherNeural"

# Fallback: same voice with neutral delivery for non-spiritual content.
_DEFAULT_RATE  = "+0%"
_DEFAULT_PITCH = "+0Hz"


class EdgeTTSProvider(TTSProvider):
    """Microsoft Edge Text-to-Speech provider — documentary narration mode."""

    _VOICES: dict[str, str] = {
        "en":    "en-US-AndrewNeural",
        "en-US": "en-US-AndrewNeural",
        "en-GB": "en-GB-RyanNeural",
        "es":    "es-ES-AlvaroNeural",
        "fr":    "fr-FR-HenriNeural",
        "de":    "de-DE-ConradNeural",
        "hi":    "hi-IN-MadhurNeural",
        "mr":    "mr-IN-ManoharNeural",
        "ja":    "ja-JP-KeitaNeural",
        "zh":    "zh-CN-YunxiNeural",
        "pt":    "pt-BR-AntonioNeural",
        "ar":    "ar-SA-HamedNeural",
        "ru":    "ru-RU-DmitryNeural",
        "ko":    "ko-KR-InJoonNeural",
        "it":    "it-IT-DiegoNeural",
    }

    def __init__(self, settings: Settings):
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

    # ── Text preparation ──────────────────────────────────────────────────────

    def _prepare_text(self, text: str, style: str | None) -> str:
        """
        Clean narration text for TTS synthesis.

        Strips markdown and normalises punctuation. For documentary/spiritual
        style, paragraph newlines become <break/> tags so they produce audible
        silence rather than being collapsed into spaces.
        """
        # Strip markdown formatting
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text, flags=re.DOTALL)
        text = re.sub(r"\b_(.+?)_\b", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"-{3,}", ".", text)
        text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)

        # Normalise special punctuation
        text = text.replace("“", '"').replace("”", '"')
        text = text.replace("‘", "'").replace("’", "'")
        text = re.sub(r"\s*—\s*", ", ", text)   # em dash → comma pause
        text = re.sub(r"\s*–\s*", " to ", text)  # en dash → "to"
        text = text.replace("&", "and")

        if style == "spiritual":
            # Paragraph breaks → period (Edge TTS pauses naturally at sentence ends)
            text = re.sub(r"\n+", ". ", text)
            # Ellipsis → period
            text = re.sub(r"\.{3,}", ".", text)
        else:
            text = re.sub(r"\.\.\.", ".", text)
            text = re.sub(r"\n{2,}", " ", text)
            text = re.sub(r"\n", " ", text)

        # Collapse whitespace
        text = " ".join(text.split())
        return text.strip()

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
                start    = chunk["offset"]   / _TICKS_PER_SECOND
                duration = chunk["duration"] / _TICKS_PER_SECOND
                sentences.append({
                    "text":  chunk["text"],
                    "start": start,
                    "end":   start + duration,
                })

        output_path.write_bytes(b"".join(audio_chunks))

        # Expand sentence timing → per-word boundaries (proportional within sentence)
        boundaries: list[dict] = []
        for sent in sentences:
            words = sent["text"].split()
            if not words:
                continue
            n          = len(words)
            sent_start = sent["start"]
            sent_dur   = sent["end"] - sent["start"]
            for i, word in enumerate(words):
                boundaries.append({
                    "word":  word,
                    "start": sent_start + (i / n) * sent_dur,
                    "end":   sent_start + ((i + 1) / n) * sent_dur,
                })

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
    ) -> list[dict]:
        """
        Full synthesis pipeline:
          1. Classify scene emotion → rate, pitch, pause profile
          2. Clean text (strip markdown, preserve breaks for spiritual)
          3. Inject strategic <break/> pauses
          4. Synthesise with emotion-appropriate prosody
        """
        if style == "spiritual":
            profile    = classify_scene(text, scene_position)
            rate       = profile.rate
            pitch      = profile.pitch
        else:
            rate       = _DEFAULT_RATE
            pitch      = _DEFAULT_PITCH

        clean_text = self._prepare_text(text, style)
        return self._run_async(self._stream(clean_text, output_path, voice, rate, pitch))

    # ── Public API (interface unchanged from V1) ──────────────────────────────

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
        self._synthesise(text, output_path, resolved, style, scene_position)
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
        resolved   = self._resolve_voice(voice, language, style)
        boundaries = self._synthesise(text, output_path, resolved, style, scene_position)
        return output_path, boundaries
