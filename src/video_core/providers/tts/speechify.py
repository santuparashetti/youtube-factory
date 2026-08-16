"""
Speechify TTS provider — cloud narration via the Speechify API.

Uses the official Speechify Python SDK. Follows the same patterns as
Cartesia, ElevenLabs, and Fish providers:

  - Batch synthesis into ~1500–2200 char requests to minimise API calls.
  - Local content-addressed cache — identical settings never re-call Speechify.
  - Retry only on transient failures via the shared with_retry() helper.
  - Fail-fast validation of required config at construction.
  - Structured logging before/after synthesis.
  - Analytics recording via TTSAnalyticsCollector.

The API returns Base64-encoded MP3 audio via response.audio_data.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

from loguru import logger

from video_core.config.shared_settings import SharedSettings
from video_core.providers.tts.analytics.collector import TTSAnalyticsCollector
from video_core.providers.tts.analytics.models import TTSAnalyticsRecord
from video_core.providers.tts.analytics.text_counter import count_text

from .base import TTSProvider
from .capabilities import ProviderCapabilities
from .infra import TTSCache, batch_sentences, with_retry


class SpeechifyProvider(TTSProvider):
    """Cloud TTS via Speechify (simba-3.2 / other models)."""

    def __init__(
        self,
        settings: SharedSettings,
        *,
        cache: TTSCache | None = None,
        analytics: TTSAnalyticsCollector | None = None,
    ) -> None:
        self._settings = settings
        self._analytics = analytics

        if not settings.speechify_api_key:
            raise ValueError(
                "Speechify TTS requires SPEECHIFY_API_KEY — set it in .env"
            )
        if not settings.speechify_model:
            raise ValueError(
                "Speechify TTS requires SPEECHIFY_MODEL — set it in .env"
            )
        if not settings.speechify_voice_id:
            raise ValueError(
                "Speechify TTS requires SPEECHIFY_VOICE_ID — set it in .env"
            )

        self._model = settings.speechify_model
        self._voice_id = settings.speechify_voice_id
        self._output_format = settings.speechify_output_format or "mp3"
        self._timeout = settings.speechify_timeout
        self._max_chars = settings.speechify_max_chars
        self._text_normalization = settings.speechify_text_normalization
        self._language = settings.speechify_language or "en-US"
        self._ext = "." + self._output_format.lstrip(".")

        self._cache = cache or TTSCache(enabled=settings.speechify_cache_enabled)
        self._client: Any = None  # lazy-loaded

    # ── Capabilities ──────────────────────────────────────────────────────────

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_name="speechify",
            supports_ssml=False,
            supports_word_boundaries=False,
            supports_pitch=False,
            supports_rate=False,
            supports_streaming=False,
            supports_emotion=False,
            supports_voice_styles=False,
        )

    # ── Lazy client ────────────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        """Lazily construct the Speechify client."""
        if self._client is None:
            try:
                from speechify import Speechify  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError(
                    "Speechify TTS requires the 'speechify' package. "
                    "Install it with: pip install speechify\n"
                    f"Original error: {exc}"
                ) from exc
            self._client = Speechify(token=self._settings.speechify_api_key)
        return self._client

    # ── Internal synthesis ─────────────────────────────────────────────────────

    def _synthesise_chunk(
        self, text: str, output_path: Path
    ) -> tuple[float, list[dict]]:
        """Synthesise one text batch to ``output_path``.

        Returns (duration_seconds, word_boundaries).
        word_boundaries is a list of dicts with keys: word, start, end (seconds).
        Uses Speechify speech marks when available so WhisperX is not needed.
        """
        ext = self._output_format
        key = TTSCache.make_key(
            text=text,
            voice_id=self._voice_id,
            model=self._model,
            speed=1.0,
            output_format=ext,
            emotion="",
            sample_rate=0,
        )

        if self._cache.copy_to(key, ext, output_path):
            logger.debug(
                "TTS [speechify] cache HIT — skipping API call (chars={})",
                len(text),
            )
            return self._probe_duration(output_path), []

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # SSML inputs must start with <speak> — prepending a warm-up cue would
        # break the XML root element and cause Speechify to read tags as plain
        # text.  Plain text gets the warm-up prefix; SSML already encodes pauses
        # via <break> tags so no prefix is needed.
        is_ssml = text.lstrip().startswith("<speak>")
        warmed_text = text if is_ssml else ". " + text.lstrip()

        speech_marks: list[dict] = []

        def _call() -> bytes:
            nonlocal speech_marks
            client = self._get_client()
            response = client.audio.speech(
                input=warmed_text,
                voice_id=self._voice_id,
                model=self._model,
                audio_format=self._output_format,
                options={"text_normalization": self._text_normalization},
            )
            logger.debug(
                "TTS [speechify] API response audio_data length={}",
                len(response.audio_data) if response.audio_data else 0,
            )
            if not response.audio_data:
                raise ValueError("Speechify API returned empty audio_data")
            # Extract word-level speech marks when the API returns them.
            # response.speech_marks is a SpeechMarks object with a chunks list.
            raw_marks = getattr(response, "speech_marks", None)
            if raw_marks is not None:
                chunks = getattr(raw_marks, "chunks", None) or []
                for chunk in chunks:
                    word = getattr(chunk, "value", None) or ""
                    start_ms = getattr(chunk, "start_time", None)
                    end_ms = getattr(chunk, "end_time", None)
                    if word and start_ms is not None and end_ms is not None:
                        speech_marks.append({
                            "word": word,
                            "start": round(start_ms / 1000, 3),
                            "end": round(end_ms / 1000, 3),
                        })
            return base64.b64decode(response.audio_data)

        def _action() -> None:
            audio = _call_with_timeout(_call, self._timeout)
            if self._cache.enabled:
                self._cache.put(key, ext, audio)
            output_path.write_bytes(audio)

        max_retries = (
            self._settings.tts_max_retries if self._settings.tts_auto_retry else 1
        )
        with_retry(_action, max_retries=max_retries, timeout=self._timeout)

        if not is_ssml:
            # Strip the warm-up pause, then add a clean 100ms lead-in.
            # SSML inputs skip this — <break> tags handle all timing.
            _strip_leading_silence(output_path)
            _prepend_silence(output_path, ms=100)
        return self._probe_duration(output_path), speech_marks

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
        resolved_voice = voice or self._voice_id
        batches = batch_sentences(text, max_chars=self._max_chars)

        t0 = time.perf_counter()
        if len(batches) == 1:
            duration, _ = self._synthesise_chunk(batches[0], output_path)
        else:
            duration = self._synthesize_batched(batches, output_path)
        elapsed = time.perf_counter() - t0

        cache_key = TTSCache.make_key(
            text=text,
            voice_id=resolved_voice,
            model=self._model,
            speed=1.0,
            output_format=self._output_format,
            emotion="",
            sample_rate=0,
        )
        cache_hit = self._cache.get(cache_key, self._output_format) is not None

        logger.info(
            "TTS [speechify] model={} voice={} chars={} format={} cache_hit={}",
            self._model,
            resolved_voice,
            len(text),
            self._output_format,
            cache_hit,
        )
        logger.info(
            "TTS [speechify] latency={:.1f}s duration={:.2f}s provider=speechify cache_hit={}",
            elapsed,
            duration,
            cache_hit,
        )

        if self._analytics and self._settings.tts_analytics_enabled:
            counts = count_text(text)
            output_size = output_path.stat().st_size if output_path.exists() else 0
            try:
                pricing = self._analytics._pricing.get_pricing("speechify")
                credits = pricing.estimate_credits(counts["characters"])
                cost = pricing.estimate_cost(credits)
            except Exception:  # noqa: BLE001
                credits = 0.0
                cost = 0.0
            record = TTSAnalyticsRecord(
                scene_id=output_path.stem,
                provider="speechify",
                model=self._model,
                voice=resolved_voice,
                text=text,
                characters=counts["characters"],
                words=counts["words"],
                sentences=counts["sentences"],
                cache_hit=cache_hit,
                retry_count=0,
                latency_ms=elapsed * 1000.0,
                output_bytes=output_size,
                audio_duration=duration,
                estimated_credits=credits,
                estimated_cost=cost,
            )
            self._analytics.record(record)

        return output_path

    def _synthesize_batched(
        self, batches: list[str], output_path: Path
    ) -> float:
        """Synthesise multiple batches and concatenate into one file."""
        from .validator import _ffprobe_duration

        tmp_paths: list[Path] = []
        total = 0.0
        try:
            for i, batch in enumerate(batches):
                tmp = output_path.with_suffix(f".part{i}{output_path.suffix}")
                tmp_paths.append(tmp)
                dur, _ = self._synthesise_chunk(batch, tmp)
                total += dur
            _concat_audio(tmp_paths, output_path)
        finally:
            for p in tmp_paths:
                p.unlink(missing_ok=True)
        return _ffprobe_duration(output_path) or total

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
        """Generate audio with word-level timing from Speechify speech marks.

        Returns (audio_path, word_boundaries) where word_boundaries is a list
        of {"word": str, "start": float, "end": float} dicts (seconds).
        Falls back to [] when speech marks are not returned by the API (e.g.
        cache hit or multi-batch synthesis) — caller should use WhisperX in
        that case.
        """
        batches = batch_sentences(text, max_chars=self._max_chars)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if len(batches) == 1:
            # Single batch — synthesise directly and capture speech marks from
            # the API response. _synthesise_chunk writes the audio file.
            _, speech_marks = self._synthesise_chunk(batches[0], output_path)
            if speech_marks:
                logger.info(
                    "TTS [speechify] speech marks: {} word boundaries captured",
                    len(speech_marks),
                )
            else:
                logger.debug(
                    "TTS [speechify] no speech marks returned (cache hit or "
                    "API did not include them) — WhisperX alignment will be used"
                )
            return output_path, speech_marks

        # Multi-batch: concatenated audio; speech marks would need per-batch
        # offset adjustment — not implemented yet, fall back to WhisperX.
        audio_path = self.generate(
            text,
            output_path,
            voice=voice,
            language=language,
            style=style,
            scene_position=scene_position,
        )
        return audio_path, []

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _probe_duration(path: Path) -> float:
        from .validator import _ffprobe_duration

        return _ffprobe_duration(path)


def _call_with_timeout(func: Any, timeout: float) -> bytes:
    """Run ``func`` in a thread with a hard timeout (raises TimeoutError)."""
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(func)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            raise TimeoutError(
                f"Speechify synthesis timed out after {timeout}s"
            ) from exc


def _strip_leading_silence(path: Path, threshold_db: float = -35.0) -> None:
    """Remove the leading pause produced by the warm-up prefix cue."""
    import subprocess

    tmp = path.with_suffix(".stripped" + path.suffix)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(path),
                "-af",
                f"silenceremove=start_periods=1:start_duration=0.01:start_threshold={threshold_db}dB",
                "-c:a", "libmp3lame", "-q:a", "2",
                str(tmp),
            ],
            check=True,
            capture_output=True,
        )
        tmp.replace(path)
    except Exception:  # noqa: BLE001
        tmp.unlink(missing_ok=True)


def _prepend_silence(path: Path, ms: int = 250) -> None:
    """Prepend ``ms`` milliseconds of silence to an audio file in-place.

    Neural TTS models often mispronounce or rush the very first phoneme
    because they start generating without prior context.  A short leading
    silence gives the decoder a clean start and lets the first word land
    with full prosodic clarity.
    """
    import subprocess

    tmp = path.with_suffix(".silpad" + path.suffix)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(path),
                "-af", f"adelay={ms}:all=1",
                "-c:a", "libmp3lame", "-q:a", "2",
                str(tmp),
            ],
            check=True,
            capture_output=True,
        )
        tmp.replace(path)
    except Exception:  # noqa: BLE001
        tmp.unlink(missing_ok=True)


def _concat_audio(parts: list[Path], output_path: Path) -> None:
    """Concatenate audio files into ``output_path`` via FFmpeg."""
    import subprocess

    list_file = output_path.with_suffix(".concat.txt")
    list_file.write_text("\n".join(f"file '{p.resolve()}'" for p in parts))
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(list_file), "-c", "copy", str(output_path),
            ],
            check=True,
            capture_output=True,
        )
    finally:
        list_file.unlink(missing_ok=True)
