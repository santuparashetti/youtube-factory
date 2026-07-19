"""
Throttled vision provider wrapper — the single place where vision-review
concurrency control lives.

Every concrete ``VisionProvider`` is wrapped by ``ConcurrencyLimitedVisionProvider``
at the factory boundary (see ``factory.py``).  The wrapper is fully
provider-agnostic: it contains no provider-specific logic and works for local,
gemini, huggingface, and any future provider.

Responsibilities (all centralised here, never duplicated in a provider):
  - Acquire the process-wide shared semaphore around every ``review()`` call
    and ALWAYS release it (even on exception) via ``try/finally``.
  - Adaptive logging: queue depth / active / max before, latency / active after.
  - Retry only transient congestion (429 / "concurrency_limit_exceeded") with
    exponential backoff + jitter (2s → 4s → 8s, max 3 retries).  Auth and
    configuration errors are NOT retried.
  - Provider hint: if a response/error reports the provider's own limit, log an
    informational "Recommended VISION_MAX_CONCURRENCY=…" line (never auto-edit).
  - Feed the in-memory ``VisionReviewMetrics`` accumulator.
"""

from __future__ import annotations

import random
import time
from pathlib import Path

from loguru import logger

from .base import VisionProvider
from .concurrency import (
    configured_max_concurrency,
    get_vision_review_metrics,
    get_vision_semaphore,
)
from .models import VisionReviewResult


# Errors that indicate *temporary congestion* and may be retried with backoff.
# These map to the HTTP 429 "Per-user concurrency limit exceeded" class.
_CONGESTION_MARKERS = (
    "429",
    "concurrency_limit_exceeded",
    "concurrency limit",
    "too many requests",
    "rate limit",
    "rate_limit",
    "overloaded",
    "503",
    "service unavailable",
)

# Errors that must NOT be retried (auth / configuration / permanent client errors).
# Provider quota errors are treated as congestion (retryable) per the task; only
# genuine auth/config failures are excluded here.
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


def _is_congestion(exc: Exception) -> bool:
    """True if the error is transient congestion (429-class) worth retrying."""
    msg = str(exc).lower()
    if any(token in msg for token in _NON_RETRYABLE_MARKERS):
        return False
    if any(token in msg for token in _CONGESTION_MARKERS):
        return True
    # Provider-specific quota errors (HuggingFace/Gemini) subclass Exception.
    name = type(exc).__name__.lower()
    if "quota" in name or "rate" in name:
        return True
    return False


def _extract_reported_limit(exc_or_result) -> int | None:
    """Best-effort parse of a provider-reported concurrency limit (Step 8)."""
    text = ""
    if isinstance(exc_or_result, Exception):
        text = str(exc_or_result)
    elif isinstance(exc_or_result, VisionReviewResult):
        text = f"{exc_or_result.error} {exc_or_result.raw_response}"
    import re

    m = re.search(r"(?:current|max|limit)[^0-9]{0,20}(\d{1,3})", text, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 100:
            return val
    return None


class ConcurrencyLimitedVisionProvider(VisionProvider):
    """Wrapper that throttles any inner ``VisionProvider`` through a shared limiter."""

    def __init__(self, inner: VisionProvider, provider_name: str = "vision") -> None:
        self._inner = inner
        self._provider_name = provider_name
        self._semaphore = get_vision_semaphore()
        self._metrics = get_vision_review_metrics()

    @property
    def inner(self) -> VisionProvider:
        return self._inner

    # ── VisionProvider interface ───────────────────────────────────────────

    def review(
        self,
        image_path: Path,
        visual_prompt: str,
        scene_context: dict | None = None,
    ) -> VisionReviewResult:
        scene_idx = (scene_context or {}).get("index", "?")
        max_c = configured_max_concurrency()

        self._metrics.record_review_started()

        # ── Adaptive pre-log (Step 6) ───────────────────────────────────────
        logger.info(
            "Vision Queue | Provider: {} | Active: {} | Waiting: {} | Max: {} | Scene: {}",
            self._provider_name,
            self._metrics.current_active,
            self._metrics.current_waiting,
            max_c,
            scene_idx,
        )

        wait_start = time.perf_counter()
        self._metrics.record_wait_start()

        # Acquire the SHARED limiter. try/finally guarantees release even on
        # exception, retry, or re-raise (Step 3).
        self._semaphore.acquire()
        try:
            waited = time.perf_counter() - wait_start
            self._metrics.record_acquired(waited)

            result = self._review_with_congestion_retry(
                image_path, visual_prompt, scene_context, scene_idx
            )
            return result
        finally:
            self._semaphore.release()

    # ── Internal: congestion-aware retry (Step 7) ───────────────────────────

    def _review_with_congestion_retry(
        self,
        image_path: Path,
        visual_prompt: str,
        scene_context: dict | None,
        scene_idx: object,
    ) -> VisionReviewResult:
        last_exc: Exception | None = None

        for attempt in range(_MAX_CONGESTION_RETRIES + 1):
            start = time.perf_counter()
            try:
                result = self._inner.review(
                    image_path, visual_prompt, scene_context
                )
                latency = time.perf_counter() - start
                self._metrics.record_completed(latency)

                # Provider may surface a limit hint even on a PASS/FAIL.
                reported = _extract_reported_limit(result)
                if reported is not None:
                    self._log_provider_hint(reported)

                # A provider that returned an ERROR containing congestion text
                # is still treated as a transient failure worth one retry cycle.
                if result.status == "ERROR" and _is_congestion(
                    ValueError(result.error)
                ):
                    self._metrics.record_status(429)
                    if attempt < _MAX_CONGESTION_RETRIES:
                        self._backoff(attempt, scene_idx, result.error)
                        continue
                return result

            except Exception as exc:  # noqa: BLE001 — centralised decision
                latency = time.perf_counter() - start
                self._metrics.record_completed(latency)
                last_exc = exc
                reported = _extract_reported_limit(exc)
                if reported is not None:
                    self._log_provider_hint(reported)

                if _is_congestion(exc):
                    self._metrics.record_status(
                        self._status_from_exc(exc)
                    )
                    if attempt < _MAX_CONGESTION_RETRIES:
                        self._backoff(attempt, scene_idx, str(exc))
                        continue
                    logger.error(
                        "Vision review scene {} failed after {} congestion retries: {}",
                        scene_idx,
                        _MAX_CONGESTION_RETRIES,
                        exc,
                    )
                    return VisionReviewResult.error_result(
                        f"Vision review congestion: {exc}"
                    )
                else:
                    # Auth / configuration / non-retryable — re-raise semantics
                    # as an ERROR result (providers never raise to the pipeline).
                    logger.warning(
                        "Vision review scene {} non-retryable error: {}",
                        scene_idx,
                        exc,
                    )
                    return VisionReviewResult.error_result(
                        f"Vision review failed: {exc}"
                    )

        # Should be unreachable, but guarantees a result either way.
        if last_exc is not None:
            return VisionReviewResult.error_result(
                f"Vision review failed: {last_exc}"
            )
        return VisionReviewResult.error_result("Vision review failed")

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _status_from_exc(exc: Exception) -> int | None:
        msg = str(exc).lower()
        if "429" in msg or "concurrency" in msg:
            return 429
        if "503" in msg:
            return 503
        return None

    def _backoff(self, attempt: int, scene_idx: object, reason: str) -> None:
        """Exponential backoff with full jitter: 2s → 4s → 8s (Step 7)."""
        base = 2.0 * (2 ** attempt)  # attempt 0→2s, 1→4s, 2→8s
        delay = base * random.uniform(0.5, 1.0)  # jitter
        logger.warning(
            "Vision review scene {} congestion (retry {}/{}): {} — backing off {:.1f}s",
            scene_idx,
            attempt + 1,
            _MAX_CONGESTION_RETRIES,
            reason,
            delay,
        )
        time.sleep(delay)

    def _log_provider_hint(self, reported_limit: int) -> None:
        """Informational only — never modify settings automatically (Step 8)."""
        recommended = max(1, reported_limit - 1)
        logger.info(
            "Vision provider hint: provider reports limit={}. "
            "Recommended configuration: VISION_MAX_CONCURRENCY={}",
            reported_limit,
            recommended,
        )
