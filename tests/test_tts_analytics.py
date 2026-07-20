"""Tests for TTS Analytics, Cost Tracking, Cache Verification, and Duplicate Detection."""

from __future__ import annotations

from pathlib import Path

from video_core.providers.tts.analytics.collector import TTSAnalyticsCollector
from video_core.providers.tts.analytics.models import (
    TTSAnalyticsRecord,
    TTSProviderPricing,
)
from video_core.providers.tts.analytics.pricing import ProviderPricingConfig
from video_core.providers.tts.analytics.text_counter import count_text
from video_core.providers.tts.infra import TTSCache


# ── Text Counter ───────────────────────────────────────────────────────────────


class TestTextCounter:
    def test_counts(self) -> None:
        result = count_text("Hello world. How are you?")
        assert result["characters"] == 25
        assert result["words"] == 5
        assert result["sentences"] == 2

    def test_empty(self) -> None:
        result = count_text("")
        assert result["characters"] == 0
        assert result["words"] == 0
        assert result["sentences"] == 0

    def test_no_punctuation(self) -> None:
        result = count_text("Hello world")
        assert result["sentences"] == 1


# ── Provider Pricing ──────────────────────────────────────────────────────────


class TestProviderPricing:
    def test_default_zero(self) -> None:
        pricing = TTSProviderPricing(provider_name="cartesia")
        assert pricing.estimate_credits(100) == 0.0
        assert pricing.estimate_cost(0.0) == 0.0

    def test_estimate_credits(self) -> None:
        pricing = TTSProviderPricing(
            provider_name="cartesia",
            credits_per_character=0.001,
            credits_per_request=0.1,
            usd_per_credit=0.01,
        )
        credits = pricing.estimate_credits(1000)
        assert credits == 1.1  # 1000 * 0.001 + 0.1

    def test_estimate_cost(self) -> None:
        pricing = TTSProviderPricing(
            provider_name="cartesia",
            usd_per_credit=0.01,
        )
        assert pricing.estimate_cost(100.0) == 1.0

    def test_config_loading(self) -> None:
        config = ProviderPricingConfig.from_dict({
            "providers": {
                "cartesia": {
                    "credits_per_character": 0.001,
                    "usd_per_credit": 0.01,
                }
            }
        })
        pricing = config.get_pricing("cartesia")
        assert pricing.credits_per_character == 0.001
        assert pricing.usd_per_credit == 0.01


# ── TTSAnalyticsCollector ─────────────────────────────────────────────────────


class TestTTSAnalyticsCollector:
    def test_record_updates_metrics(self) -> None:
        collector = TTSAnalyticsCollector(enabled=True)
        collector.set_current_video("video-1")
        record = TTSAnalyticsRecord(
            scene_id="scene-001",
            provider="cartesia",
            model="sonic-3.5",
            voice="Nolan",
            characters=184,
            words=31,
            sentences=3,
            cache_hit=True,
            latency_ms=1840.0,
            audio_duration=11.2,
        )
        collector.record(record)
        metrics = collector.provider_metrics("cartesia")
        assert metrics is not None
        assert metrics.total_requests == 1
        assert metrics.cache_hits == 1
        assert metrics.cache_misses == 0
        assert metrics.total_characters == 184

    def test_disabled_collector_ignores_records(self) -> None:
        collector = TTSAnalyticsCollector(enabled=False)
        collector.set_current_video("video-1")
        record = TTSAnalyticsRecord(scene_id="scene-001", provider="cartesia")
        collector.record(record)
        assert len(collector.all_records()) == 0

    def test_video_summary(self) -> None:
        collector = TTSAnalyticsCollector(enabled=True)
        collector.set_current_video("video-1")
        for i in range(3):
            collector.record(TTSAnalyticsRecord(
                scene_id=f"scene-{i:03d}",
                provider="cartesia",
                model="sonic-3.5",
                voice="Nolan",
                characters=100 + i * 10,
                words=20,
                sentences=2,
                cache_hit=(i % 2 == 0),
                latency_ms=1000.0 + i * 100,
                audio_duration=5.0 + i,
            ))
        summary = collector.video_summary("video-1")
        assert summary is not None
        assert summary.total_requests == 3
        assert summary.total_characters == 330
        assert summary.cache_hits == 2
        assert summary.cache_misses == 1

    def test_cache_hit_rate(self) -> None:
        collector = TTSAnalyticsCollector(enabled=True)
        collector.set_current_video("video-1")
        collector.record(TTSAnalyticsRecord(scene_id="s1", provider="cartesia", cache_hit=True))
        collector.record(TTSAnalyticsRecord(scene_id="s2", provider="cartesia", cache_hit=False))
        summary = collector.video_summary("video-1")
        assert summary is not None
        assert summary.cache_hit_rate == 0.5

    def test_cost_optimization_report(self) -> None:
        pricing = ProviderPricingConfig.from_dict({
            "providers": {
                "cartesia": {
                    "credits_per_character": 0.001,
                    "credits_per_request": 0.1,
                    "usd_per_credit": 0.01,
                }
            }
        })
        collector = TTSAnalyticsCollector(enabled=True, pricing_config=pricing)
        collector.set_current_video("video-1")
        collector.record(TTSAnalyticsRecord(
            scene_id="scene-001",
            provider="cartesia",
            model="sonic-3.5",
            voice="Nolan",
            characters=200,
            words=40,
            sentences=4,
            cache_hit=False,
            latency_ms=2000.0,
            audio_duration=12.0,
        ))
        collector.record(TTSAnalyticsRecord(
            scene_id="scene-002",
            provider="cartesia",
            model="sonic-3.5",
            voice="Nolan",
            characters=100,
            words=20,
            sentences=2,
            cache_hit=True,
            latency_ms=100.0,
            audio_duration=5.0,
        ))
        report = collector.cost_optimization_report("video-1")
        assert report["largest_scene"] == "scene-001"
        assert report["cache_savings"] > 0

    def test_duplicate_detection(self) -> None:
        collector = TTSAnalyticsCollector(enabled=True)
        text = "This is a duplicate narration."
        for scene_id in ["scene-001", "scene-002", "scene-003"]:
            collector.record(TTSAnalyticsRecord(
                scene_id=scene_id,
                provider="cartesia",
                model="sonic-3.5",
                voice="Nolan",
                text=text,
            ))
        duplicates = collector.duplicate_detection("video-1")
        assert len(duplicates) == 1
        assert duplicates[0]["reuse_possible"] is True
        assert set(duplicates[0]["scenes"]) == {"scene-001", "scene-002", "scene-003"}

    def test_duplicate_detection_empty(self) -> None:
        collector = TTSAnalyticsCollector(enabled=True)
        assert collector.duplicate_detection("video-1") == []


# ── Cache Verification ────────────────────────────────────────────────────────


class TestCacheVerification:
    def test_identical_text_hits_cache(self, tmp_path: Path) -> None:
        cache = TTSCache(cache_dir=tmp_path, enabled=True)
        key = TTSCache.make_key(
            text="Hello world",
            voice_id="voice-1",
            model="model-1",
            speed=1.0,
            output_format="wav",
            emotion="calm",
            sample_rate=44100,
        )
        cache.put(key, "wav", b"fake audio data")
        assert cache.get(key, "wav") is not None

    def test_cache_key_changes_with_emotion(self) -> None:
        key1 = TTSCache.make_key(
            text="Hello",
            voice_id="v1",
            model="m1",
            speed=1.0,
            output_format="wav",
            emotion="calm",
            sample_rate=44100,
        )
        key2 = TTSCache.make_key(
            text="Hello",
            voice_id="v1",
            model="m1",
            speed=1.0,
            output_format="wav",
            emotion="happy",
            sample_rate=44100,
        )
        assert key1 != key2

    def test_cache_key_changes_with_sample_rate(self) -> None:
        key1 = TTSCache.make_key(
            text="Hello",
            voice_id="v1",
            model="m1",
            speed=1.0,
            output_format="wav",
            emotion="calm",
            sample_rate=44100,
        )
        key2 = TTSCache.make_key(
            text="Hello",
            voice_id="v1",
            model="m1",
            speed=1.0,
            output_format="wav",
            emotion="calm",
            sample_rate=48000,
        )
        assert key1 != key2

    def test_disabled_cache_returns_none(self, tmp_path: Path) -> None:
        cache = TTSCache(cache_dir=tmp_path, enabled=False)
        key = TTSCache.make_key(
            text="Hello",
            voice_id="v1",
            model="m1",
            speed=1.0,
            output_format="wav",
        )
        assert cache.get(key, "wav") is None
