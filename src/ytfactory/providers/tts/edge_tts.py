from __future__ import annotations

import asyncio
import concurrent.futures
import re
from pathlib import Path

import edge_tts

from ytfactory.config.settings import Settings

from .base import TTSProvider

# Edge TTS emits offsets in 100-nanosecond ticks (Windows FILETIME units).
_TICKS_PER_SECOND = 10_000_000

# Calm, warm US male voice — ideal for spiritual / documentary narration
_SPIRITUAL_VOICE = "en-US-ChristopherNeural"
_SPIRITUAL_RATE = "-20%"    # 20% slower — meditative pace
_SPIRITUAL_PITCH = "-3Hz"   # Slightly lower for gravitas


class EdgeTTSProvider(TTSProvider):
    """Microsoft Edge Text-to-Speech provider."""

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

    def __init__(self, settings: Settings):
        self._settings = settings

    def _resolve_voice(self, voice: str | None, language: str, style: str | None) -> str:
        if voice:
            return voice
        if style == "spiritual" and language.startswith("en"):
            return _SPIRITUAL_VOICE
        return self._VOICES.get(language, self._VOICES["en"])

    def _prepare_text(self, text: str, style: str | None) -> str:
        """
        Pre-process narration text for crystal-clear TTS rendering.

        Strips ALL markdown and special characters that can confuse Edge TTS,
        normalises punctuation for natural pausing, and applies style-specific
        pacing hints.
        """
        # ── Strip markdown formatting ─────────────────────────────────────
        # Headers (#, ##, etc.)
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Bold+italic ***word*** or **word** or *word*
        text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text, flags=re.DOTALL)
        # Italic _word_
        text = re.sub(r"\b_(.+?)_\b", r"\1", text)
        # Markdown links [text](url) → text
        text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
        # Inline code `code` → code
        text = re.sub(r"`([^`]+)`", r"\1", text)
        # Horizontal rules --- → pause (period)
        text = re.sub(r"-{3,}", ".", text)
        # Bullet points at line start
        text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)

        # ── Normalise special punctuation ─────────────────────────────────
        # Curly quotes → straight (TTS handles straight quotes better)
        text = text.replace("“", '"').replace("”", '"')
        text = text.replace("‘", "'").replace("’", "'")
        # Em dash — → comma pause; en dash – → " to "
        text = re.sub(r"\s*—\s*", ", ", text)
        text = re.sub(r"\s*–\s*", " to ", text)
        # Ampersand → and
        text = text.replace("&", "and")

        # ── Style-specific pacing ─────────────────────────────────────────
        if style == "spiritual":
            # Preserve "..." as a natural meditative pause (Edge TTS respects it)
            # But clean up any run of 4+ dots down to exactly three
            text = re.sub(r"\.{4,}", "...", text)
        else:
            # Non-spiritual: convert ellipsis to a period for cleaner flow
            text = re.sub(r"\.\.\.", ".", text)

        # ── Whitespace normalisation ──────────────────────────────────────
        # Multiple blank lines → sentence break
        text = re.sub(r"\n{2,}", " ", text)
        # Remaining single newlines → space
        text = re.sub(r"\n", " ", text)
        # Multiple spaces → single space
        text = " ".join(text.split())

        return text.strip()

    # ── Internal async helpers ────────────────────────────────────────────

    async def _stream(
        self,
        text: str,
        output_path: Path,
        voice: str,
        rate: str = "+0%",
        pitch: str = "+0Hz",
    ) -> list[dict]:
        """
        Stream Edge TTS, save audio, and derive word-level timing from
        SentenceBoundary events.

        Edge TTS emits one SentenceBoundary per sentence with real start/end
        timestamps. Words within each sentence are distributed proportionally
        across its time window — sentence timing is exact, within-sentence
        timing is proportional to word count (matches natural TTS pacing well).

        Returns a list of dicts: [{word, start, end}] in seconds.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
        sentences: list[dict] = []
        audio_chunks: list[bytes] = []

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                start = chunk["offset"] / _TICKS_PER_SECOND
                duration = chunk["duration"] / _TICKS_PER_SECOND
                sentences.append({
                    "text": chunk["text"],
                    "start": start,
                    "end": start + duration,
                })

        output_path.write_bytes(b"".join(audio_chunks))

        # Expand sentence boundaries → per-word boundaries
        boundaries: list[dict] = []
        for sent in sentences:
            words = sent["text"].split()
            if not words:
                continue
            n = len(words)
            sent_start = sent["start"]
            sent_dur = sent["end"] - sent["start"]
            for i, word in enumerate(words):
                word_start = sent_start + (i / n) * sent_dur
                word_end = sent_start + ((i + 1) / n) * sent_dur
                boundaries.append({"word": word, "start": word_start, "end": word_end})

        return boundaries

    def _run_async(self, coro):
        """Run an async coroutine safely regardless of event-loop context."""
        try:
            asyncio.get_running_loop()
            # Already inside an event loop — run in a thread
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        except RuntimeError:
            return asyncio.run(coro)

    # ── Public API ────────────────────────────────────────────────────────

    def generate(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        language: str = "en",
        style: str | None = None,
    ) -> Path:
        resolved = self._resolve_voice(voice, language, style)
        rate = _SPIRITUAL_RATE if style == "spiritual" else "+0%"
        pitch = _SPIRITUAL_PITCH if style == "spiritual" else "+0Hz"
        text = self._prepare_text(text, style)
        self._run_async(self._stream(text, output_path, resolved, rate, pitch))
        return output_path

    def generate_with_boundaries(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        language: str = "en",
        style: str | None = None,
    ) -> tuple[Path, list[dict]]:
        """
        Generate audio AND return word-level timing.

        Returns:
            (output_path, boundaries)
            boundaries: [{word: str, start: float, end: float}] in seconds
        """
        resolved = self._resolve_voice(voice, language, style)
        rate = _SPIRITUAL_RATE if style == "spiritual" else "+0%"
        pitch = _SPIRITUAL_PITCH if style == "spiritual" else "+0Hz"
        text = self._prepare_text(text, style)
        boundaries = self._run_async(self._stream(text, output_path, resolved, rate, pitch))
        return output_path, boundaries
