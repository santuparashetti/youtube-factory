"""Analytics domain models for the Visual Intelligence Layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AnalyticsRecord:
    """Structured telemetry for a single image generation + review cycle."""

    video_id: str
    scene_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    provider: str = ""
    model: str = ""
    prompt_fingerprint: str = ""
    visual_metadata: dict[str, Any] = field(default_factory=dict)
    vision_score: float = 0.0
    remediation_attempts: int = 0
    latency_ms: float = 0.0
    image_size_bytes: int = 0
    estimated_cost: float = 0.0
    cache_hit: bool = False
    final_status: str = "PASS"
    era: str | None = None
    narrative_role: str | None = None
    environment: str | None = None
    mood: str | None = None
    visual_style: str | None = None
    issues: list[dict] = field(default_factory=list)
    remediation_strategy: str = ""
    prompt_growth_ratio: float = 0.0


@dataclass
class ProviderMetrics:
    """Aggregated metrics for a single provider."""

    provider_name: str
    total_requests: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    total_retries: int = 0
    total_cost: float = 0.0
    cache_hits: int = 0
    timeout_count: int = 0
    rate_429_count: int = 0
    rate_503_count: int = 0

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.success_count / self.total_requests

    @property
    def failure_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.failure_count / self.total_requests

    @property
    def avg_latency_ms(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_ms / self.total_requests

    @property
    def avg_retries(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_retries / self.total_requests

    @property
    def avg_cost(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_cost / self.total_requests

    @property
    def cache_hit_ratio(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.cache_hits / self.total_requests


@dataclass
class QualityMetrics:
    """Aggregated quality metrics."""

    total_scenes: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    total_score: float = 0.0
    scores: list[float] = field(default_factory=list)
    issues_by_category: dict[str, int] = field(default_factory=dict)
    issues_by_era: dict[str, int] = field(default_factory=dict)
    issues_by_narrative_role: dict[str, int] = field(default_factory=dict)
    issues_by_environment: dict[str, int] = field(default_factory=dict)
    issues_by_mood: dict[str, int] = field(default_factory=dict)
    issues_by_style: dict[str, int] = field(default_factory=dict)
    remediation_success_count: int = 0
    remediation_failure_count: int = 0
    regeneration_count: int = 0

    @property
    def pass_rate(self) -> float:
        if self.total_scenes == 0:
            return 0.0
        return self.passed / self.total_scenes

    @property
    def avg_score(self) -> float:
        if not self.scores:
            return 0.0
        return sum(self.scores) / len(self.scores)

    @property
    def remediation_success_rate(self) -> float:
        total = self.remediation_success_count + self.remediation_failure_count
        if total == 0:
            return 0.0
        return self.remediation_success_count / total


@dataclass
class CostSummary:
    """Cost tracking per period."""

    period: str
    total_images: int = 0
    total_scenes: int = 0
    total_videos: int = 0
    total_cost: float = 0.0
    cost_by_provider: dict[str, float] = field(default_factory=dict)
    cost_by_era: dict[str, float] = field(default_factory=dict)
    avg_cost_per_image: float = 0.0
    avg_cost_per_scene: float = 0.0
    avg_cost_per_video: float = 0.0


@dataclass
class PromptAnalytics:
    """Prompt-level analytics."""

    prompt_fingerprint: str
    prompt_length: int = 0
    estimated_tokens: int = 0
    reuse_count: int = 0
    remediation_count: int = 0
    prompt_growth_ratio: float = 0.0
    avg_score: float = 0.0
    scores: list[float] = field(default_factory=list)

    @property
    def remediation_rate(self) -> float:
        total = self.reuse_count + self.remediation_count
        if total == 0:
            return 0.0
        return self.remediation_count / total


@dataclass
class BenchmarkResult:
    """Benchmark comparison for a provider."""

    provider_name: str
    avg_score: float = 0.0
    avg_latency_ms: float = 0.0
    estimated_cost: float = 0.0
    failure_rate: float = 0.0
    remediation_rate: float = 0.0
    sample_count: int = 0


@dataclass
class DashboardModel:
    """Top-level dashboard structure."""

    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pipeline_summary: dict[str, Any] = field(default_factory=dict)
    provider_comparison: list[BenchmarkResult] = field(default_factory=list)
    quality_trends: list[dict[str, Any]] = field(default_factory=list)
    era_trends: list[dict[str, Any]] = field(default_factory=list)
    narrative_role_trends: list[dict[str, Any]] = field(default_factory=list)
    top_failure_categories: list[dict[str, Any]] = field(default_factory=list)
    cost_summary: CostSummary | None = None
    remediation_summary: dict[str, Any] = field(default_factory=dict)
    cache_statistics: dict[str, Any] = field(default_factory=dict)
