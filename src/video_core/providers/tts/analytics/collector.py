"""TTS analytics collector."""

from __future__ import annotations

from typing import Any

from video_core.providers.tts.analytics.models import (
    TTSAnalyticsRecord,
    TTSProviderMetrics,
    TTSVideoSummary,
)
from video_core.providers.tts.analytics.pricing import ProviderPricingConfig


class TTSAnalyticsCollector:
    """Accumulates TTS telemetry during pipeline execution."""

    def __init__(
        self,
        enabled: bool = True,
        pricing_config: ProviderPricingConfig | None = None,
    ) -> None:
        self._enabled = enabled
        self._pricing = pricing_config or ProviderPricingConfig()
        self._records: list[TTSAnalyticsRecord] = []
        self._provider_metrics: dict[str, TTSProviderMetrics] = {}
        self._video_summaries: dict[str, TTSVideoSummary] = {}
        self._current_video_id: str | None = None
        self._scene_records: dict[str, list[TTSAnalyticsRecord]] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_current_video(self, video_id: str) -> None:
        self._current_video_id = video_id
        if video_id not in self._video_summaries:
            self._video_summaries[video_id] = TTSVideoSummary(video_id=video_id)

    def record(self, record: TTSAnalyticsRecord) -> None:
        if not self._enabled:
            return
        self._records.append(record)
        self._update_provider_metrics(record)
        self._update_video_summary(record)

    def _update_provider_metrics(self, record: TTSAnalyticsRecord) -> None:
        key = record.provider or "unknown"
        if key not in self._provider_metrics:
            self._provider_metrics[key] = TTSProviderMetrics(provider_name=key)
        m = self._provider_metrics[key]
        m.total_requests += 1
        if record.cache_hit:
            m.cache_hits += 1
        else:
            m.cache_misses += 1
        m.total_characters += record.characters
        m.total_words += record.words
        m.total_sentences += record.sentences
        m.total_latency_ms += record.latency_ms
        m.total_retries += record.retry_count
        m.total_output_bytes += record.output_bytes
        m.total_audio_duration += record.audio_duration
        pricing = self._pricing.get_pricing(key)
        credits = pricing.estimate_credits(record.characters)
        cost = pricing.estimate_cost(credits)
        m.total_credits += credits
        m.total_cost += cost

    def _update_video_summary(self, record: TTSAnalyticsRecord) -> None:
        if not self._current_video_id:
            return
        summary = self._video_summaries[self._current_video_id]
        summary.total_requests += 1
        summary.total_characters += record.characters
        summary.total_words += record.words
        summary.total_sentences += record.sentences
        summary.total_audio_duration += record.audio_duration
        summary.total_retries += record.retry_count
        summary.total_latency_ms += record.latency_ms
        if record.cache_hit:
            summary.cache_hits += 1
        else:
            summary.cache_misses += 1
        pricing = self._pricing.get_pricing(record.provider or "unknown")
        credits = pricing.estimate_credits(record.characters)
        cost = pricing.estimate_cost(credits)
        summary.total_credits += credits
        summary.total_cost += cost
        summary.providers_used[record.provider or "unknown"] = (
            summary.providers_used.get(record.provider or "unknown", 0) + 1
        )
        summary.models_used[record.model or "unknown"] = (
            summary.models_used.get(record.model or "unknown", 0) + 1
        )
        summary.voices_used[record.voice or "unknown"] = (
            summary.voices_used.get(record.voice or "unknown", 0) + 1
        )
        scene_key = str(record.scene_id)
        if scene_key not in self._scene_records:
            self._scene_records[scene_key] = []
        self._scene_records[scene_key].append(record)
        summary.scene_summaries.append({
            "scene_id": record.scene_id,
            "provider": record.provider,
            "model": record.model,
            "voice": record.voice,
            "characters": record.characters,
            "words": record.words,
            "sentences": record.sentences,
            "duration": record.audio_duration,
            "cache_hit": record.cache_hit,
            "retries": record.retry_count,
            "latency_ms": record.latency_ms,
            "estimated_credits": pricing.estimate_credits(record.characters),
            "estimated_cost": pricing.estimate_cost(pricing.estimate_credits(record.characters)),
        })

    def provider_metrics(self, provider: str) -> TTSProviderMetrics | None:
        return self._provider_metrics.get(provider)

    def video_summary(self, video_id: str) -> TTSVideoSummary | None:
        return self._video_summaries.get(video_id)

    def all_video_summaries(self) -> dict[str, TTSVideoSummary]:
        return dict(self._video_summaries)

    def all_records(self) -> list[TTSAnalyticsRecord]:
        return list(self._records)

    def cost_optimization_report(self, video_id: str) -> dict[str, Any]:
        summary = self._video_summaries.get(video_id)
        if not summary or not summary.scene_summaries:
            return {}
        scenes = summary.scene_summaries
        largest = max(scenes, key=lambda s: s.get("characters", 0))
        most_expensive = max(scenes, key=lambda s: s.get("estimated_cost", 0.0))
        total_duration = sum(s.get("duration", 0.0) for s in scenes)
        cache_savings = sum(
            s.get("estimated_cost", 0.0) for s in scenes if s.get("cache_hit")
        )
        return {
            "largest_scene": largest.get("scene_id"),
            "largest_scene_characters": largest.get("characters", 0),
            "most_expensive_scene": most_expensive.get("scene_id"),
            "most_expensive_cost": most_expensive.get("estimated_cost", 0.0),
            "longest_narration_scene": max(
                scenes, key=lambda s: s.get("duration", 0.0)
            ).get("scene_id"),
            "shortest_narration_scene": min(
                scenes, key=lambda s: s.get("duration", 0.0)
            ).get("scene_id"),
            "avg_credits_per_scene": summary.total_credits / len(scenes) if scenes else 0.0,
            "avg_credits_per_minute": (
                summary.total_credits / (total_duration / 60.0) if total_duration > 0 else 0.0
            ),
            "cache_savings": cache_savings,
            "estimated_monthly_cost": summary.total_cost * 30,
            "estimated_yearly_cost": summary.total_cost * 365,
        }

    def duplicate_detection(self, video_id: str) -> list[dict[str, Any]]:
        duplicates: list[dict[str, Any]] = []
        seen: dict[str, list[str]] = {}
        for record in self._records:
            if record.provider != "cartesia":
                continue
            key = record.text.strip().lower()
            if key not in seen:
                seen[key] = []
            seen[key].append(str(record.scene_id))
        for text, scenes in seen.items():
            if len(scenes) > 1:
                duplicates.append({
                    "text_preview": text[:100],
                    "scenes": scenes,
                    "reuse_possible": True,
                })
        return duplicates
