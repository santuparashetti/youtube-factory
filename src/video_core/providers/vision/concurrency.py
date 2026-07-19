"""
Vision review concurrency control — process-wide, provider-agnostic limiter.

Goal
----
Per-user *concurrency* limits on cloud vision providers surface as HTTP 429
("Per-user concurrency limit exceeded"). This is a *scheduling* problem, not a
model or quota problem.  We throttle only the vision review gate so the rest of
the pipeline (image generation, TTS, WhisperX, rendering, subtitles) keeps
running in full parallel.

Design
------
- A single process-wide ``threading.BoundedSemaphore`` bounds concurrent
  ``review()`` calls.  The vision providers are invoked **synchronously from
  parallel worker threads** (LangGraph ``Send`` / ``ThreadPoolExecutor``), so a
  thread-safe semaphore — not an ``asyncio.Semaphore`` — is the primitive that
  actually bounds this concurrency.  Using an asyncio semaphore here would NOT
  limit the worker threads and would let 429s through.
- The semaphore is created **lazily** from ``SharedSettings().vision_max_concurrency``
  and is **shared by every provider instance** (exactly one limiter per process).
- All orchestration (acquire/release, retry/backoff, logging, metrics) lives in
  one wrapper (``throttled.py``), so no provider contains concurrency logic and
  adding a future provider requires zero changes here.
- ``VisionReviewMetrics`` is a small in-memory accumulator that integrates the
  metrics required by the task (peak/avg concurrency, queue wait, latency, 429/503).
"""

from __future__ import annotations

import threading

from loguru import logger

from video_core.config.shared_settings import SharedSettings


# ── Process-wide limiter ──────────────────────────────────────────────────────

_lock = threading.Lock()
_semaphore: threading.BoundedSemaphore | None = None
_max_concurrency: int = 0


def get_vision_semaphore() -> threading.BoundedSemaphore:
    """Return the process-wide vision concurrency semaphore (lazy, shared).

    Created once from ``SharedSettings().vision_max_concurrency``.  All vision
    providers must pass through this single instance — there is never one
    semaphore per provider instance.
    """
    global _semaphore, _max_concurrency
    if _semaphore is None:
        with _lock:
            if _semaphore is None:  # double-checked locking
                limit = int(getattr(SharedSettings(), "vision_max_concurrency", 5))
                _max_concurrency = limit
                _semaphore = threading.BoundedSemaphore(limit)
                logger.info(
                    "Vision concurrency limiter initialised (max_concurrency={})",
                    limit,
                )
    return _semaphore


def reset_vision_semaphore() -> None:
    """Drop the cached limiter (test isolation only — not used in production)."""
    global _semaphore, _max_concurrency
    with _lock:
        _semaphore = None
        _max_concurrency = 0


def configured_max_concurrency() -> int:
    """Return the configured limit (re-reads if no limiter exists yet)."""
    if _max_concurrency:
        return _max_concurrency
    return int(getattr(SharedSettings(), "vision_max_concurrency", 5))


# ── In-memory metrics ─────────────────────────────────────────────────────────

class VisionReviewMetrics:
    """Thread-safe in-memory accumulator for vision review telemetry.

    Tracks peak/avg concurrency, queue wait time, average latency, and the
    counts of throttling-relevant HTTP statuses (429/503). Integrated with the
    existing metrics pattern (a module-level singleton, no external storage).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total_reviews = 0
        self.completed_reviews = 0
        self._peak_concurrent = 0
        self._concurrency_sum = 0  # sum of concurrent counts over all samples
        self._concurrency_samples = 0
        self._total_queue_wait_s = 0.0
        self._total_latency_s = 0.0
        self.count_429 = 0
        self.count_503 = 0
        self.current_active = 0
        self.current_waiting = 0

    # ── Recording helpers (all internally synchronised) ───────────────────────

    def record_wait_start(self) -> None:
        with self._lock:
            self.current_waiting += 1

    def record_acquired(self, waited_s: float) -> None:
        with self._lock:
            self.current_waiting -= 1
            self.current_active += 1
            self._total_queue_wait_s += waited_s
            self._peak_concurrent = max(self._peak_concurrent, self.current_active)
            self._concurrency_sum += self.current_active
            self._concurrency_samples += 1

    def record_completed(self, latency_s: float) -> None:
        with self._lock:
            self.completed_reviews += 1
            self.current_active = max(0, self.current_active - 1)
            self._total_latency_s += latency_s

    def record_review_started(self) -> None:
        with self._lock:
            self.total_reviews += 1

    def record_status(self, status_code: int | None) -> None:
        if status_code == 429:
            with self._lock:
                self.count_429 += 1
        elif status_code == 503:
            with self._lock:
                self.count_503 += 1

    # ── Derived snapshots ──────────────────────────────────────────────────────

    @property
    def peak_concurrent_reviews(self) -> int:
        with self._lock:
            return self._peak_concurrent

    @property
    def average_concurrent_reviews(self) -> float:
        with self._lock:
            return (
                self._concurrency_sum / self._concurrency_samples
                if self._concurrency_samples
                else 0.0
            )

    @property
    def average_queue_wait_s(self) -> float:
        with self._lock:
            return self._total_queue_wait_s / self.completed_reviews if self.completed_reviews else 0.0

    @property
    def average_review_latency_s(self) -> float:
        with self._lock:
            return (
                self._total_latency_s / self.completed_reviews
                if self.completed_reviews
                else 0.0
            )

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "total_reviews": self.total_reviews,
                "completed_reviews": self.completed_reviews,
                "peak_concurrent_reviews": self._peak_concurrent,
                "average_concurrent_reviews": round(
                    self._concurrency_sum / self._concurrency_samples, 3
                )
                if self._concurrency_samples
                else 0.0,
                "current_active": self.current_active,
                "current_waiting": self.current_waiting,
                "average_queue_wait_s": round(self._total_queue_wait_s / max(self.completed_reviews, 1), 4),
                "average_review_latency_s": round(self._total_latency_s / max(self.completed_reviews, 1), 4),
                "count_429": self.count_429,
                "count_503": self.count_503,
            }


# Module-level singleton — integrates with existing in-memory metrics.
_metrics = VisionReviewMetrics()


def get_vision_review_metrics() -> VisionReviewMetrics:
    """Return the process-wide vision review metrics accumulator."""
    return _metrics


def reset_vision_review_metrics() -> None:
    """Replace the metrics singleton (test isolation only)."""
    global _metrics
    _metrics = VisionReviewMetrics()
