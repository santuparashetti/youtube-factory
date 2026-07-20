"""Analytics collector — accumulates telemetry during pipeline execution."""

from __future__ import annotations

from video_core.visual_intelligence.analytics.models import (
    AnalyticsRecord,
    BenchmarkResult,
    CostSummary,
    DashboardModel,
    PromptAnalytics,
    QualityMetrics,
)


class AnalyticsCollector:
    """Thread-safe-ish in-memory analytics accumulator.

    Designed for single-process use.  For distributed setups, replace the
    internal stores with a shared backend (Redis, ClickHouse, etc.) without
    changing the pipeline interface.
    """

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._records: list[AnalyticsRecord] = []
        self._provider_metrics: dict[str, QualityMetrics] = {}
        self._prompt_analytics: dict[str, PromptAnalytics] = {}
        self._cost_by_provider: dict[str, float] = {}
        self._cost_by_era: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def record(self, record: AnalyticsRecord) -> None:
        if not self._enabled:
            return
        self._records.append(record)
        self._update_provider_metrics(record)
        self._update_prompt_analytics(record)
        self._update_cost_tracking(record)

    def _update_provider_metrics(self, record: AnalyticsRecord) -> None:
        key = record.provider or "unknown"
        if key not in self._provider_metrics:
            self._provider_metrics[key] = QualityMetrics()
        m = self._provider_metrics[key]
        m.total_scenes += 1
        if record.final_status == "PASS":
            m.passed += 1
        elif record.final_status == "FAIL":
            m.failed += 1
        elif record.final_status == "SKIP":
            m.skipped += 1
        else:
            m.errors += 1
        m.total_score += record.vision_score
        m.scores.append(record.vision_score)
        for issue in record.issues:
            cat = issue.get("category", "unknown")
            m.issues_by_category[cat] = m.issues_by_category.get(cat, 0) + 1
            if record.era:
                m.issues_by_era[record.era] = m.issues_by_era.get(record.era, 0) + 1
            if record.narrative_role:
                m.issues_by_narrative_role[record.narrative_role] = m.issues_by_narrative_role.get(record.narrative_role, 0) + 1
            if record.environment:
                m.issues_by_environment[record.environment] = m.issues_by_environment.get(record.environment, 0) + 1
            if record.mood:
                m.issues_by_mood[record.mood] = m.issues_by_mood.get(record.mood, 0) + 1
            if record.visual_style:
                m.issues_by_style[record.visual_style] = m.issues_by_style.get(record.visual_style, 0) + 1
        if record.remediation_attempts > 0:
            if record.final_status == "PASS":
                m.remediation_success_count += 1
            else:
                m.remediation_failure_count += 1
        if record.remediation_attempts > 0 and record.final_status == "PASS":
            m.regeneration_count += 1

    def _update_prompt_analytics(self, record: AnalyticsRecord) -> None:
        key = record.prompt_fingerprint
        if key not in self._prompt_analytics:
            self._prompt_analytics[key] = PromptAnalytics(prompt_fingerprint=key)
        pa = self._prompt_analytics[key]
        pa.reuse_count += 1
        pa.scores.append(record.vision_score)
        pa.avg_score = sum(pa.scores) / len(pa.scores)
        if record.remediation_attempts > 0:
            pa.remediation_count += 1
        if record.prompt_growth_ratio > pa.prompt_growth_ratio:
            pa.prompt_growth_ratio = record.prompt_growth_ratio

    def _update_cost_tracking(self, record: AnalyticsRecord) -> None:
        prov = record.provider or "unknown"
        self._cost_by_provider[prov] = self._cost_by_provider.get(prov, 0.0) + record.estimated_cost
        if record.era:
            self._cost_by_era[record.era] = self._cost_by_era.get(record.era, 0.0) + record.estimated_cost

    def quality_metrics(self, provider: str | None = None) -> QualityMetrics:
        if provider and provider in self._provider_metrics:
            return self._provider_metrics[provider]
        merged = QualityMetrics()
        for m in self._provider_metrics.values():
            merged.total_scenes += m.total_scenes
            merged.passed += m.passed
            merged.failed += m.failed
            merged.skipped += m.skipped
            merged.errors += m.errors
            merged.total_score += m.total_score
            merged.scores.extend(m.scores)
            merged.remediation_success_count += m.remediation_success_count
            merged.remediation_failure_count += m.remediation_failure_count
            merged.regeneration_count += m.regeneration_count
            for cat, count in m.issues_by_category.items():
                merged.issues_by_category[cat] = merged.issues_by_category.get(cat, 0) + count
            for era, count in m.issues_by_era.items():
                merged.issues_by_era[era] = merged.issues_by_era.get(era, 0) + count
            for role, count in m.issues_by_narrative_role.items():
                merged.issues_by_narrative_role[role] = merged.issues_by_narrative_role.get(role, 0) + count
            for env, count in m.issues_by_environment.items():
                merged.issues_by_environment[env] = merged.issues_by_environment.get(env, 0) + count
            for mood, count in m.issues_by_mood.items():
                merged.issues_by_mood[mood] = merged.issues_by_mood.get(mood, 0) + count
            for style, count in m.issues_by_style.items():
                merged.issues_by_style[style] = merged.issues_by_style.get(style, 0) + count
        return merged

    def provider_metrics(self, provider: str) -> QualityMetrics | None:
        return self._provider_metrics.get(provider)

    def prompt_analytics(self, fingerprint: str) -> PromptAnalytics | None:
        return self._prompt_analytics.get(fingerprint)

    def cost_summary(self, period: str = "session") -> CostSummary:
        total_cost = sum(self._cost_by_provider.values())
        total_images = len(self._records)
        return CostSummary(
            period=period,
            total_images=total_images,
            total_scenes=len(set(r.scene_id for r in self._records)),
            total_videos=len(set(r.video_id for r in self._records)),
            total_cost=total_cost,
            cost_by_provider=dict(self._cost_by_provider),
            cost_by_era=dict(self._cost_by_era),
            avg_cost_per_image=total_cost / total_images if total_images else 0.0,
        )

    def build_dashboard(self) -> DashboardModel:
        qm = self.quality_metrics()
        top_failures = sorted(
            qm.issues_by_category.items(), key=lambda x: x[1], reverse=True
        )[:10]
        provider_benchmarks = []
        for prov, m in self._provider_metrics.items():
            provider_benchmarks.append(
                BenchmarkResult(
                    provider_name=prov,
                    avg_score=m.avg_score,
                    failure_rate=1.0 - m.pass_rate,
                    remediation_rate=m.remediation_success_rate,
                    sample_count=m.total_scenes,
                )
            )
        return DashboardModel(
            pipeline_summary={
                "total_scenes": qm.total_scenes,
                "passed": qm.passed,
                "failed": qm.failed,
                "pass_rate": qm.pass_rate,
                "avg_score": qm.avg_score,
            },
            provider_comparison=provider_benchmarks,
            quality_trends=[{"score": s} for s in qm.scores[-50:]],
            era_trends=[{"era": k, "issues": v} for k, v in qm.issues_by_era.items()],
            narrative_role_trends=[{"role": k, "issues": v} for k, v in qm.issues_by_narrative_role.items()],
            top_failure_categories=[{"category": k, "count": v} for k, v in top_failures],
            cost_summary=self.cost_summary(),
            remediation_summary={
                "success_rate": qm.remediation_success_rate,
                "regeneration_count": qm.regeneration_count,
            },
            cache_statistics={
                "total_prompts_tracked": len(self._prompt_analytics),
            },
        )

    def records(self) -> list[AnalyticsRecord]:
        return list(self._records)
