"""Data models for the vision review benchmark."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


# ── Dataset ───────────────────────────────────────────────────────────────────


@dataclass
class BenchmarkScene:
    """One entry from benchmark.yaml."""

    id: str
    image: Path
    expected_failures: list[str]   # named hard-fail rules expected to fire
    visual_prompt: str = ""        # prompt used during image generation
    notes: str = ""

    @property
    def is_bad(self) -> bool:
        return bool(self.expected_failures)


# ── Per-rule detection result ─────────────────────────────────────────────────


@dataclass
class HardFailMatch:
    """TP/FP/TN/FN result for one rule on one scene."""

    rule: str
    expected: bool   # this rule was listed in expected_failures
    detected: bool   # the model's issues matched this rule

    @property
    def is_tp(self) -> bool:
        return self.expected and self.detected

    @property
    def is_fp(self) -> bool:
        return not self.expected and self.detected

    @property
    def is_tn(self) -> bool:
        return not self.expected and not self.detected

    @property
    def is_fn(self) -> bool:
        return self.expected and not self.detected


# ── Per-scene result ──────────────────────────────────────────────────────────


@dataclass
class SceneResult:
    """Benchmark result for one scene under one model."""

    scene: str                         # scene id, e.g. "scene-002"
    model: str                         # registry key, e.g. "qwen2_5_vl_3b"
    narrative_score: float             # 100 - environment-issue deductions
    technical_score: float             # 100 - anatomy/face/artifact deductions
    cinematic_score: float             # 100 - lighting/cinematic deductions
    overall_score: float               # raw provider score
    recommendation: str                # PASS | REGENERATE | MANUAL_REVIEW | SKIP | ERROR
    hard_fail: bool                    # model issued REGENERATE
    detected_failures: list[str]       # rule names matched by issues
    expected_failures: list[str]       # rule names from benchmark.yaml
    hard_fail_matches: list[HardFailMatch]
    latency_ms: float
    confidence: float = 0.0
    raw_issues: list[dict] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "scene": self.scene,
            "model": self.model,
            "narrative_score": round(self.narrative_score, 1),
            "technical_score": round(self.technical_score, 1),
            "cinematic_score": round(self.cinematic_score, 1),
            "overall_score": round(self.overall_score, 1),
            "recommendation": self.recommendation,
            "hard_fail": self.hard_fail,
            "detected_failures": self.detected_failures,
            "expected_failures": self.expected_failures,
            "latency_ms": round(self.latency_ms),
            "confidence": round(self.confidence, 1),
            "issues": self.raw_issues,
            "error": self.error,
        }


# ── Per-model aggregate metrics ───────────────────────────────────────────────


@dataclass
class ModelMetrics:
    """Aggregate metrics for one model over the full dataset."""

    model: str
    tp: int = 0    # expected bad  + predicted REGENERATE
    fp: int = 0    # expected good + predicted REGENERATE
    tn: int = 0    # expected good + predicted PASS / MANUAL_REVIEW
    fn: int = 0    # expected bad  + predicted PASS / MANUAL_REVIEW
    total_latency_ms: float = 0.0
    total_narrative: float = 0.0
    total_technical: float = 0.0
    total_cinematic: float = 0.0
    scene_count: int = 0

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d > 0 else 0.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def accuracy(self) -> float:
        total = self.tp + self.fp + self.tn + self.fn
        return (self.tp + self.tn) / total if total > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.scene_count if self.scene_count else 0.0

    @property
    def avg_narrative(self) -> float:
        return self.total_narrative / self.scene_count if self.scene_count else 0.0

    @property
    def avg_technical(self) -> float:
        return self.total_technical / self.scene_count if self.scene_count else 0.0

    @property
    def avg_cinematic(self) -> float:
        return self.total_cinematic / self.scene_count if self.scene_count else 0.0

    @property
    def benchmark_score(self) -> float:
        """Composite score (max 100): 60% F1 + 20% technical + 10% narrative + 10% cinematic."""
        return round(
            self.f1 * 60.0
            + self.avg_technical * 0.20
            + self.avg_narrative * 0.10
            + self.avg_cinematic * 0.10,
            1,
        )


# ── Full benchmark report ─────────────────────────────────────────────────────


@dataclass
class BenchmarkReport:
    """Full output: all scenes, all models, all metrics."""

    dataset_path: str
    total_scenes: int
    bad_scenes: int            # scenes with expected_failures
    good_scenes: int           # scenes without expected_failures
    models: list[str]
    scene_results: dict[str, list[SceneResult]]   # model_key → results
    metrics: dict[str, ModelMetrics]              # model_key → metrics
    winner: str | None = None  # model with highest F1 (None when tied or single model)
