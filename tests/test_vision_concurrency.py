"""Tests for vision review concurrency control.

Covers: limit enforcement, shared semaphore across providers, release-on-
exception, 429/concurrency retry with backoff, no deadlock, and metrics.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from video_core.config.shared_settings import SharedSettings
from video_core.providers.vision import (
    ConcurrencyLimitedVisionProvider,
    get_vision_provider,
)
from video_core.providers.vision.concurrency import (
    get_vision_semaphore,
    reset_vision_review_metrics,
    reset_vision_semaphore,
)
from video_core.providers.vision.mock import MockVisionProvider
from video_core.providers.vision.models import VisionReviewResult as _VR


# ── Helpers ───────────────────────────────────────────────────────────────────


def _settings_factory(max_concurrency: int = 5):
    """Settings-like object for the limiter (sets only what's needed)."""
    class _S:
        vision_max_concurrency = max_concurrency
    return _S()


def _png(tmp_path: Path, name: str = "img.png") -> Path:
    p = tmp_path / name
    p.write_bytes(b"\x89PNG")
    return p


@pytest.fixture(autouse=True)
def _isolate():
    """Each test gets a fresh limiter + metrics (no cross-test leakage)."""
    reset_vision_semaphore()
    reset_vision_review_metrics()
    yield
    reset_vision_semaphore()
    reset_vision_review_metrics()


# ── Step 10: configuration validation ────────────────────────────────────────


class TestConfigValidation:
    def test_default_is_one(self):
        s = SharedSettings()
        assert s.vision_max_concurrency == 1

    @pytest.mark.parametrize("bad", [0, -1, 101, 200])
    def test_rejects_out_of_range(self, bad):
        with pytest.raises(ValueError, match="VISION_MAX_CONCURRENCY"):
            SharedSettings(vision_max_concurrency=bad)

    def test_accepts_boundary_values(self):
        assert SharedSettings(vision_max_concurrency=1).vision_max_concurrency == 1
        assert SharedSettings(vision_max_concurrency=100).vision_max_concurrency == 100


# ── Step 2: shared, lazy, process-wide limiter ───────────────────────────────


class TestSharedLimiter:
    def test_lazy_singleton(self):
        reset_vision_semaphore()
        a = get_vision_semaphore()
        b = get_vision_semaphore()
        assert a is b

    def test_semaphore_size_matches_config(self):
        reset_vision_semaphore()
        sem = get_vision_semaphore()
        assert sem._initial_value == 1

    def test_two_providers_share_one_semaphore(self):
        reset_vision_semaphore()
        p1 = ConcurrencyLimitedVisionProvider(MockVisionProvider(), "mock")
        p2 = ConcurrencyLimitedVisionProvider(MockVisionProvider(), "mock")
        assert p1._semaphore is p2._semaphore


# ── Step 3: semaphore release on exception ───────────────────────────────────


class TestReleaseOnException:
    def test_semaphore_released_after_inner_raises(self, tmp_path):
        reset_vision_semaphore()
        sem = get_vision_semaphore()
        before = sem._value

        class Boom(MockVisionProvider):
            def review(self, image_path, visual_prompt, scene_context=None):
                raise RuntimeError("boom")

        wrapped = ConcurrencyLimitedVisionProvider(Boom(), "mock")
        result = wrapped.review(_png(tmp_path), "prompt")
        assert result.status == "ERROR"
        # Semaphore fully released.
        assert sem._value == before

    def test_normal_completion_releases(self, tmp_path):
        reset_vision_semaphore()
        sem = get_vision_semaphore()
        before = sem._value
        wrapped = ConcurrencyLimitedVisionProvider(MockVisionProvider(), "mock")
        wrapped.review(_png(tmp_path), "prompt")
        assert sem._value == before


# ── Step 1/4: limit never exceeded (real thread parallelism) ─────────────────


class TestLimitEnforcement:
    def test_max_concurrent_never_exceeds_limit(self, tmp_path):
        reset_vision_semaphore()
        max_c = 3
        # Reconfigure limiter to a small value for a tight test.
        import video_core.providers.vision.concurrency as C

        C._semaphore = threading.BoundedSemaphore(max_c)
        C._max_concurrency = max_c

        hold = threading.Event()
        active = {"n": 0}
        peak = {"n": 0}
        lock = threading.Lock()

        class Slow(MockVisionProvider):
            def review(self, image_path, visual_prompt, scene_context=None, **kwargs):
                with lock:
                    active["n"] += 1
                    peak["n"] = max(peak["n"], active["n"])
                hold.wait(0.2)  # all threads must overlap
                with lock:
                    active["n"] -= 1
                return _VR(status="PASS", score=95, confidence=90)

        wrapped = ConcurrencyLimitedVisionProvider(Slow(), "mock")
        threads = [
            threading.Thread(target=lambda: wrapped.review(_png(tmp_path, f"i{i}.png"), "p"))
            for i in range(12)
        ]
        for t in threads:
            t.start()
        time.sleep(0.05)
        # While work is in flight, active must never exceed max_c.
        with lock:
            assert active["n"] <= max_c
        hold.set()
        for t in threads:
            t.join()

        assert peak["n"] <= max_c
        # No deadlock: all completed.
        assert peak["n"] > 0

    def test_queue_does_not_deadlock(self, tmp_path):
        reset_vision_semaphore()
        import video_core.providers.vision.concurrency as C

        C._semaphore = threading.BoundedSemaphore(2)
        C._max_concurrency = 2

        flag = threading.Event()

        class Blocking(MockVisionProvider):
            def review(self, image_path, visual_prompt, scene_context=None, **kwargs):
                flag.wait()
                return _VR(status="PASS", score=95, confidence=90)

        wrapped = ConcurrencyLimitedVisionProvider(Blocking(), "mock")
        threads = [
            threading.Thread(target=lambda: wrapped.review(_png(tmp_path, f"q{i}.png"), "p"))
            for i in range(6)
        ]
        for t in threads:
            t.start()
        time.sleep(0.1)
        flag.set()  # release the in-flight ones; queued ones must proceed
        for t in threads:
            t.join(timeout=5)
        assert all(not t.is_alive() for t in threads)


# ── Step 7: congestion retry (429 / concurrency_limit_exceeded) ───────────────


class TestCongestionRetry:
    def test_retries_congestion_then_succeeds(self, tmp_path):
        reset_vision_semaphore()
        calls = {"n": 0}

        class Flaky(MockVisionProvider):
            def review(self, image_path, visual_prompt, scene_context=None, **kwargs):
                calls["n"] += 1
                if calls["n"] < 3:
                    # Simulate a 429 concurrency-limit error.
                    raise RuntimeError("429 Per-user concurrency limit exceeded")
                return _VR(status="PASS", score=95, confidence=90)

        wrapped = ConcurrencyLimitedVisionProvider(Flaky(), "mock")
        import video_core.providers.vision.throttled as T

        orig_sleep = time.sleep
        T.time.sleep = lambda *_a, **_k: None  # speed up backoff
        try:
            result = wrapped.review(_png(tmp_path), "prompt")
        finally:
            T.time.sleep = orig_sleep
        assert result.status == "PASS"
        assert calls["n"] == 3

    def test_does_not_retry_auth_errors(self, tmp_path):
        reset_vision_semaphore()
        calls = {"n": 0}

        class AuthFail(MockVisionProvider):
            def review(self, image_path, visual_prompt, scene_context=None, **kwargs):
                calls["n"] += 1
                raise PermissionError("403 Forbidden — invalid api key")

        wrapped = ConcurrencyLimitedVisionProvider(AuthFail(), "mock")
        result = wrapped.review(_png(tmp_path), "prompt")
        # auth error → single attempt, surfaced as ERROR, no retries.
        assert result.status == "ERROR"
        assert calls["n"] == 1

    def test_exhausts_retries_then_returns_error(self, tmp_path):
        reset_vision_semaphore()

        class AlwaysCongested(MockVisionProvider):
            def review(self, image_path, visual_prompt, scene_context=None, **kwargs):
                raise RuntimeError("429 concurrency limit exceeded")

        wrapped = ConcurrencyLimitedVisionProvider(AlwaysCongested(), "mock")
        import video_core.providers.vision.throttled as T

        orig_sleep = time.sleep
        T.time.sleep = lambda *_a, **_k: None
        try:
            result = wrapped.review(_png(tmp_path), "prompt")
        finally:
            T.time.sleep = orig_sleep
        assert result.status == "ERROR"
        assert "congestion" in result.error.lower()


# ── Step 8: provider hint (informational) ───────────────────────────────────


class TestProviderHint:
    def test_logs_hint_from_error_message(self, tmp_path, caplog):
        from video_core.providers.vision.throttled import (
            ConcurrencyLimitedVisionProvider as _CLVP,
            _extract_reported_limit,
        )

        reset_vision_semaphore()

        # The hint parser is a module-level helper; verify it parses the limit.
        reported = _extract_reported_limit(
            RuntimeError("Current limit = 10 concurrent requests reached")
        )
        assert reported == 10

        # The wrapper logs an *informational* recommended config and never
        # mutates settings. We capture the log via a loguru sink.
        import io

        from loguru import logger as _loguru

        captured = io.StringIO()
        _loguru.add(captured, level="INFO")

        class Hinted(MockVisionProvider):
            def review(self, image_path, visual_prompt, scene_context=None, **kwargs):
                # Non-retryable error path, but still surfaces the hint.
                raise PermissionError("Current limit = 10 concurrent requests reached")

        # PermissionError is auth-like (non-retryable) so the hint is parsed via
        # the exception branch; the recommendation is limit - 1 = 9.
        wrapped = _CLVP(Hinted(), "mock")
        result = wrapped.review(_png(tmp_path), "prompt")
        assert result.status == "ERROR"
        logs = captured.getvalue()
        assert "VISION_MAX_CONCURRENCY=9" in logs


# ── Step 9: metrics integration ──────────────────────────────────────────────


class TestMetrics:
    def test_metrics_recorded(self, tmp_path):
        reset_vision_semaphore()
        metrics = __import__(
            "video_core.providers.vision.concurrency", fromlist=["get_vision_review_metrics"]
        ).get_vision_review_metrics()
        wrapped = ConcurrencyLimitedVisionProvider(MockVisionProvider(), "mock")
        for i in range(5):
            wrapped.review(_png(tmp_path, f"m{i}.png"), "p")
        assert metrics.completed_reviews == 5
        assert metrics.total_reviews == 5
        # Peak concurrency should be >= 1 (some overlap is fine; at least 1).
        assert metrics.peak_concurrent_reviews >= 1
        snap = metrics.snapshot()
        assert "average_review_latency_s" in snap
        assert "count_429" in snap

    def test_factory_returns_wrapped_provider(self):
        reset_vision_semaphore()
        provider = get_vision_provider("mock")
        assert isinstance(provider, ConcurrencyLimitedVisionProvider)
        assert isinstance(provider.inner, MockVisionProvider)
