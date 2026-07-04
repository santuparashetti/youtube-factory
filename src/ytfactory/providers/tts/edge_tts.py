from __future__ import annotations

import asyncio
import concurrent.futures
from pathlib import Path

import edge_tts

from ytfactory.config.settings import Settings

from .base import TTSProvider

# Edge TTS emits offsets in 100-nanosecond ticks (Windows FILETIME units).
_TICKS_PER_SECOND = 10_000_000


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

    def _resolve_voice(self, voice: str | None, language: str) -> str:
        if voice:
            return voice
        return self._VOICES.get(language, self._VOICES["en"])

    # ── Internal async helpers ────────────────────────────────────────────

    async def _stream(
        self,
        text: str,
        output_path: Path,
        voice: str,
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

        communicate = edge_tts.Communicate(text=text, voice=voice)
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
    ) -> Path:
        resolved = self._resolve_voice(voice, language)
        self._run_async(self._stream(text, output_path, resolved))
        return output_path

    def generate_with_boundaries(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        language: str = "en",
    ) -> tuple[Path, list[dict]]:
        """
        Generate audio AND return word-level timing.

        Returns:
            (output_path, boundaries)
            boundaries: [{word: str, start: float, end: float}] in seconds
        """
        resolved = self._resolve_voice(voice, language)
        boundaries = self._run_async(self._stream(text, output_path, resolved))
        return output_path, boundaries
