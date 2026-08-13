"""
Throttled TTS provider wrapper — the single place where TTS concurrency and
rate-limit control live.

Every cloud TTS provider with strict per-user limits can be wrapped by
``ThrottledTTSProvider`` at the factory boundary. The wrapper is fully
provider-agnostic and works for Speechify, ElevenLabs, Cartesia, Fish, etc.

Responsibilities (all centralised here, never duplicated in a provider):
  - Acquire the process-wide shared semaphore around every synthesis call and
    ALWAYS release it (even on exception) via ``try/finally``.
  - Rate-limit calls to respect provider ``requests_per_second`` limits using a
    shared process-wide timer.
  - Retry only transient congestion (429 / rate limit / concurrency limit /
    quota) with exponential backoff + jitter.
  - Auth and configuration errors are NOT retried.
"""

from __future__ import annotations

import random
import threading
import time
from pathlib import Path

from loguru import logger

from .base import TTSProvider

# Congestion markers: 429 rate limit, concurrency limit, quota — transient.
_CONGESTION_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "concurrency limit",
    "concurrency_limit",
    "concurrency_limit_reached",
    "too many requests",
    "quota",
)

_NON_RETRYABLE_MARKERS = (
    "401",
    "unauthorized",
    "403",
    "forbidden",
    "404",
    "not found",
    "authentication",
    "invalid api key",
    "configuration",
    "valueerror",
)

# Retry schedule for congestion: 2s, 4s, 8s (exponential, capped at 3 retries).
_MAX_CONGESTION_RETRIES = 3

# Process-wide rate-limit state.
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_NEXT_AVAILABLE: float = 0.0


def _is_congestion(exc: Exception) -> bool:
    """True if the error is transient congestion (429-class) worth retrying."""
    msg = str(exc).lower()
    if any(token in msg for token in _NON_RETRYABLE_MARKERS):
        return False
    if any(token in msg for token in _CONGESTION_MARKERS):
        return True
    name = type(exc).__name__.lower()
    return bool("quota" in name or "rate" in name)


class ThrottledTTSProvider(TTSProvider):
    """Wrapper that throttles any inner ``TTSProvider`` through a shared limiter.

    Enforces:
      - Max 1 concurrent synthesis request (semaphore).
      - Min ``requests_per_second`` spacing between calls (rate limiter).
      - Exponential-backoff retry on 429 / concurrency-limit / quota errors.
    """

    def __init__(
        self,
        inner: TTSProvider,
        *,
        max_concurrency: int = 1,
        requests_per_second: float = 1.0,
    ) -> None:
        self._inner = inner
        self._max_concurrency = max(1, max_concurrency)
        self._requests_per_second = max(0.1, requests_per_second)
        self._semaphore = threading.BoundedSemaphore(self._max_concurrency)

    # ── TTSProvider interface ────────────────────────────────────────────────

    @property
    def capabilities(self):
        return self._inner.capabilities

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
        self._semaphore.acquire()
        try:
            self._rate_limit_wait()
            return self._generate_with_congestion_retry(
                text, output_path, voice=voice, language=language,
                style=style, scene_position=scene_position,
            )
        finally:
            self._semaphore.release()

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
        audio_path = self.generate(
            text,
            output_path,
            voice=voice,
            language=language,
            style=style,
            scene_position=scene_position,
        )
        return audio_path, []

    # ── Internal: congestion-aware retry ────────────────────────────────────

    def _generate_with_congestion_retry(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None,
        language: str,
        style: str | None,
        scene_position: float,
    ) -> Path:
        last_exc: Exception | None = None

        for attempt in range(_MAX_CONGESTION_RETRIES + 1):
            try:
                result = self._inner.generate(
                    text,
                    output_path,
                    voice=voice,
                    language=language,
                    style=style,
                    scene_position=scene_position,
                )
                return result
            except Exception as exc:
                last_exc = exc

                if _is_congestion(exc):
                    if attempt < _MAX_CONGESTION_RETRIES:
                        self._backoff(attempt, output_path.stem, str(exc))
                        continue
                    logger.error(
                        "TTS {} failed after {} congestion retries: {}",
                        output_path.stem,
                        _MAX_CONGESTION_RETRIES,
                        exc,
                    )
                    raise
                else:
                    logger.warning(
                        "TTS {} non-retryable error: {}",
                        output_path.stem,
                        exc,
                    )
                    raise

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("TTS synthesis failed: unknown error")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _rate_limit_wait(self) -> None:
        """Block until enough time has passed since the last request."""
        min_interval = 1.0 / self._requests_per_second
        now = time.monotonic()
        with _RATE_LIMIT_LOCK:
            global _RATE_LIMIT_NEXT_AVAILABLE
            wait = _RATE_LIMIT_NEXT_AVAILABLE - now
            if wait > 0:
                logger.debug(
                    "TTS rate limit: waiting {:.2f}s ({} req/s)",
                    wait,
                    self._requests_per_second,
                )
                time.sleep(wait)
            _RATE_LIMIT_NEXT_AVAILABLE = time.monotonic() + min_interval

    @staticmethod
    def _backoff(attempt: int, scene_idx: str, reason: str) -> None:
        """Exponential backoff with full jitter: 2s → 4s → 8s."""
        base = 2.0 * (2 ** attempt)
        delay = base * random.uniform(0.5, 1.0)
        logger.warning(
            "TTS {} congestion (retry {}/{}): {} — backing off {:.1f}s",
            scene_idx,
            attempt + 1,
            _MAX_CONGESTION_RETRIES,
            reason,
            delay,
        )
        time.sleep(delay)
