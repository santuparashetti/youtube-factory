"""
Fish Audio TTS provider — cloud narration via Fish Audio REST API.

Uses the official Fish Audio REST endpoint (POST /v1/tts). Follows the exact
same patterns as the Cartesia and ElevenLabs providers:

  - Batch synthesis into ~1500–2200 char requests to minimise API calls.
  - Local content-addressed cache (shared TTSCache) — identical settings never
    re-call Fish Audio.
  - Retry only on transient failures via the shared with_retry() helper.
  - Fail-fast validation of required config at construction.
  - Structured logging before/after synthesis.
  - Analytics recording via TTSAnalyticsCollector.

The API returns raw binary MP3 data, which is written directly to the output
file.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests
from loguru import logger

from video_core.config.shared_settings import SharedSettings
from video_core.providers.tts.analytics.collector import TTSAnalyticsCollector
from video_core.providers.tts.analytics.models import TTSAnalyticsRecord
from video_core.providers.tts.analytics.text_counter import count_text

from .base import TTSProvider
from .capabilities import ProviderCapabilities
from .infra import TTSCache, batch_sentences, with_retry


class FishProvider(TTSProvider):
    """Cloud TTS via Fish Audio (s2.1-pro-free / other models)."""

    _FISH_API_URL = "https://api.fish.audio/v1/tts"

    def __init__(
        self,
        settings: SharedSettings,
        *,
        cache: TTSCache | None = None,
        analytics: TTSAnalyticsCollector | None = None,
    ) -> None:
        self._settings = settings
        self._analytics = analytics

        if not settings.fish_api_key:
            raise ValueError(
                "Fish Audio TTS requires FISH_API_KEY — set it in .env"
            )
        if not settings.fish_model:
            raise ValueError(
                "Fish Audio TTS requires FISH_MODEL — set it in .env"
            )
        if not settings.fish_reference_id:
            raise ValueError(
                "Fish Audio TTS requires FISH_REFERENCE_ID — set it in .env"
            )

        self._model = settings.fish_model
        self._reference_id = settings.fish_reference_id
        self._output_format = settings.fish_format or "mp3"
        self._timeout = settings.fish_timeout
        self._max_chars = settings.fish_max_chars
        self._speed = settings.fish_speed
        self._sample_rate = settings.fish_sample_rate
        self._temperature = settings.fish_temperature
        self._top_p = settings.fish_top_p
        self._repetition_penalty = settings.fish_repetition_penalty
        self._max_new_tokens = settings.fish_max_new_tokens
        self._normalize = settings.fish_normalize
        self._ext = "." + self._output_format.lstrip(".")

        self._cache = cache or TTSCache(
            enabled=settings.fish_cache_enabled
        )

    # ── Capabilities ──────────────────────────────────────────────────────────

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_name="fish",
            supports_ssml=False,
            supports_word_boundaries=False,
            supports_pitch=False,
            supports_rate=True,
            supports_streaming=False,
            supports_emotion=False,
            supports_voice_styles=False,
        )

    # ── Internal synthesis ─────────────────────────────────────────────────────

    def _synthesise_chunk(self, text: str, output_path: Path) -> float:
        """Synthesise one text batch to ``output_path``. Returns duration (s)."""
        ext = self._output_format
        key = TTSCache.make_key(
            text=text,
            voice_id=self._reference_id,
            model=self._model,
            speed=self._speed,
            output_format=ext,
            emotion="",
            sample_rate=self._sample_rate,
        )

        if self._cache.copy_to(key, ext, output_path):
            logger.debug(
                "TTS [fish] cache HIT — skipping API call (chars={})",
                len(text),
            )
            return self._probe_duration(output_path)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        def _call() -> bytes:
            headers = {
                "Authorization": f"Bearer {self._settings.fish_api_key}",
                "Content-Type": "application/json",
                "model": self._model,
            }
            payload: dict[str, Any] = {
                "text": text,
                "reference_id": self._settings.fish_reference_id,
                "format": self._output_format,
                "sample_rate": self._sample_rate,
                "prosody": {
                    "speed": self._speed,
                },
                "temperature": self._temperature,
                "top_p": self._top_p,
                "repetition_penalty": self._repetition_penalty,
                "max_new_tokens": self._max_new_tokens,
                "normalize": self._normalize,
            }
            response = requests.post(
                self._FISH_API_URL,
                headers=headers,
                data=json.dumps(payload),
                timeout=self._timeout,
            )
            logger.debug(
                "TTS [fish] API response status={} content_length={}",
                response.status_code,
                len(response.content),
            )
            if response.status_code == 401:
                raise ValueError(
                    "Fish Audio API returned 401 Unauthorized — check FISH_API_KEY"
                )
            if response.status_code == 403:
                raise ValueError(
                    "Fish Audio API returned 403 Forbidden — check API permissions"
                )
            if response.status_code == 404:
                raise ValueError(
                    "Fish Audio API returned 404 — check FISH_MODEL or FISH_REFERENCE_ID"
                )
            if response.status_code == 429:
                raise ValueError(
                    "Fish Audio API rate limit exceeded (429)"
                )
            if response.status_code >= 400:
                raise ValueError(
                    f"Fish Audio API error {response.status_code}: {response.text}"
                )
            return response.content

        def _action() -> None:
            audio = _call_with_timeout(_call, self._timeout)
            if self._cache.enabled:
                self._cache.put(key, ext, audio)
            output_path.write_bytes(audio)

        max_retries = (
            self._settings.tts_max_retries
            if self._settings.tts_auto_retry
            else 1
        )
        with_retry(_action, max_retries=max_retries, timeout=self._timeout)

        return self._probe_duration(output_path)

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
        batches = batch_sentences(text, max_chars=self._max_chars)

        t0 = time.perf_counter()
        if len(batches) == 1:
            duration = self._synthesise_chunk(batches[0], output_path)
        else:
            duration = self._synthesize_batched(batches, output_path)
        elapsed = time.perf_counter() - t0

        cache_key = TTSCache.make_key(
            text=text,
            voice_id=self._reference_id,
            model=self._model,
            speed=self._speed,
            output_format=self._output_format,
            emotion="",
            sample_rate=self._sample_rate,
        )
        cache_hit = self._cache.get(cache_key, self._output_format) is not None

        logger.info(
            "TTS [fish] model={} reference_id={} chars={} format={} cache_hit={}",
            self._model,
            self._reference_id,
            len(text),
            self._output_format,
            cache_hit,
        )
        logger.info(
            "TTS [fish] latency={:.1f}s duration={:.2f}s provider=fish cache_hit={}",
            elapsed,
            duration,
            cache_hit,
        )

        if self._analytics and self._settings.tts_analytics_enabled:
            counts = count_text(text)
            output_size = output_path.stat().st_size if output_path.exists() else 0
            try:
                pricing = self._analytics._pricing.get_pricing("fish")
                credits = pricing.estimate_credits(counts["characters"])
                cost = pricing.estimate_cost(credits)
            except Exception:  # noqa: BLE001 — pricing lookup may fail for unregistered providers
                credits = 0.0
                cost = 0.0
            record = TTSAnalyticsRecord(
                scene_id=output_path.stem,
                provider="fish",
                model=self._model,
                voice=self._reference_id,
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
                total += self._synthesise_chunk(batch, tmp)
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
        """Generate audio. Returns empty boundaries — use WhisperX for timing."""
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
                f"Fish Audio synthesis timed out after {timeout}s"
            ) from exc


def _concat_audio(parts: list[Path], output_path: Path) -> None:
    """Concatenate audio files into ``output_path`` via FFmpeg."""
    import subprocess

    list_file = output_path.with_suffix(".concat.txt")
    list_file.write_text("\n".join(f"file '{p.resolve()}'" for p in parts))
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(output_path),
            ],
            check=True,
            capture_output=True,
        )
    finally:
        list_file.unlink(missing_ok=True)
