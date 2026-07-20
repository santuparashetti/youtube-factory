"""TTS analytics domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class TTSAnalyticsRecord:
    """Structured telemetry for a single TTS synthesis request."""

    scene_id: str
    provider: str = ""
    model: str = ""
    voice: str = ""
    text: str = ""
    characters: int = 0
    words: int = 0
    sentences: int = 0
    cache_hit: bool = False
    retry_count: int = 0
    latency_ms: float = 0.0
    request_timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    output_bytes: int = 0
    audio_duration: float = 0.0
    estimated_credits: float = 0.0
    estimated_cost: float = 0.0
    provider_response_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TTSProviderPricing:
    """Configurable pricing for a TTS provider.

    Do NOT hardcode provider pricing. Load from configuration.
    """

    provider_name: str
    credits_per_character: float = 0.0
    credits_per_request: float = 0.0
    usd_per_credit: float = 0.0

    def estimate_credits(self, character_count: int) -> float:
        return (
            self.credits_per_character * character_count + self.credits_per_request
        )

    def estimate_cost(self, credits: float) -> float:
        return credits * self.usd_per_credit


@dataclass
class TTSProviderMetrics:
    """Aggregated metrics for a single TTS provider."""

    provider_name: str
    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_characters: int = 0
    total_words: int = 0
    total_sentences: int = 0
    total_latency_ms: float = 0.0
    total_retries: int = 0
    total_output_bytes: int = 0
    total_audio_duration: float = 0.0
    total_credits: float = 0.0
    total_cost: float = 0.0

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return self.cache_hits / total

    @property
    def avg_latency_ms(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_ms / self.total_requests

    @property
    def avg_credits_per_request(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_credits / self.total_requests

    @property
    def retry_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_retries / self.total_requests


@dataclass
class TTSVideoSummary:
    """Per-video TTS cost summary."""

    video_id: str
    total_scenes: int = 0
    total_requests: int = 0
    total_characters: int = 0
    total_words: int = 0
    total_sentences: int = 0
    total_audio_duration: float = 0.0
    total_credits: float = 0.0
    total_cost: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    total_retries: int = 0
    total_latency_ms: float = 0.0
    providers_used: dict[str, int] = field(default_factory=dict)
    models_used: dict[str, int] = field(default_factory=dict)
    voices_used: dict[str, int] = field(default_factory=dict)
    scene_summaries: list[dict[str, Any]] = field(default_factory=list)

    @property
    def avg_scene_duration(self) -> float:
        if self.total_scenes == 0:
            return 0.0
        return self.total_audio_duration / self.total_scenes

    @property
    def avg_characters_per_scene(self) -> float:
        if self.total_scenes == 0:
            return 0.0
        return self.total_characters / self.total_scenes

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return self.cache_hits / total

    @property
    def avg_latency_ms(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_ms / self.total_requests
