"""Auto Remediation Engine V1 — core orchestrator.

Orchestrates the full remediation loop:
  1. DecisionEngine builds a RemediationPlan from review artifacts
  2. Each action is executed by the RemediationExecutor (delete + re-generate)
  3. VideoQualityReviewEngine re-validates after each cycle
  4. Loop stops when quality threshold is met or max_retries reached

When RemediationConfig.dry_run=True, planning runs but no files are touched
and no re-validation is run.  This is the safe default for testing.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from ytfactory.review.remediation.config import RemediationConfig
from ytfactory.review.remediation.decision import DecisionEngine
from ytfactory.review.remediation.executor import (
    DryRunExecutor,
    RemediationExecutorBase,
)
from ytfactory.review.remediation.models import (
    RegeneratedAsset,
    RemediationCycle,
    RemediationReport,
    RetryHistoryEntry,
)
from ytfactory.review.remediation.reporter import RemediationReporter
from ytfactory.shared.constants import WORKSPACE_DIR


class AutoRemediationEngine:
    """Orchestrate selective repair of failed pipeline components.

    Usage:
        engine = AutoRemediationEngine(config=RemediationConfig(dry_run=True))
        report = engine.remediate(project_id, review_report)
    """

    def __init__(
        self,
        config: RemediationConfig | None = None,
        executor: RemediationExecutorBase | None = None,
    ) -> None:
        self._config = config or RemediationConfig()
        # Use DryRunExecutor when dry_run=True so no real pipelines are called.
        if self._config.dry_run:
            self._executor: RemediationExecutorBase = DryRunExecutor()
        else:
            self._executor = executor or _default_executor()

    # ── Public API ─────────────────────────────────────────────────────────────

    def remediate(self, project_id: str, review_report: object) -> RemediationReport:
        """Run the full remediation loop and return a RemediationReport."""
        t0 = time.perf_counter()
        timestamp = datetime.now(timezone.utc).isoformat()
        project_dir = Path(WORKSPACE_DIR) / project_id

        # Extract structured reports from the ReviewReport dict fields
        val_report, rca_report, score_report, efl_report = _extract_reports(
            review_report
        )

        # Build initial plan
        retry_history: list[dict] = []
        plan = DecisionEngine(self._config).plan(
            project_id=project_id,
            val_report=val_report,
            rca_report=rca_report,
            score_report=score_report,
            efl_report=efl_report,
            retry_history=retry_history,
        )

        # Load scenes for executor context
        scenes = _load_scenes(project_dir)

        # No actions → stop immediately
        if not plan.actions:
            report = RemediationReport(
                project_id=project_id,
                timestamp=timestamp,
                plan=plan,
                final_verdict=_extract_verdict(review_report),
                final_quality_score=plan.quality_score_before,
                stopped_reason="no_actions_needed",
                processing_time_seconds=round(time.perf_counter() - t0, 3),
                dry_run=self._config.dry_run,
            )
            RemediationReporter().write(report)
            return report

        # Dry run → plan but do not execute
        if self._config.dry_run:
            report = RemediationReport(
                project_id=project_id,
                timestamp=timestamp,
                plan=plan,
                final_verdict=_extract_verdict(review_report),
                final_quality_score=plan.quality_score_before,
                stopped_reason="dry_run",
                processing_time_seconds=round(time.perf_counter() - t0, 3),
                dry_run=True,
            )
            RemediationReporter().write(report)
            return report

        # ── Remediation loop ───────────────────────────────────────────────────
        cycles: list[RemediationCycle] = []
        all_retry_entries: list[RetryHistoryEntry] = []
        all_regenerated: list[RegeneratedAsset] = []
        stopped_reason = "max_retries_reached"
        current_score = plan.quality_score_before
        current_verdict = _extract_verdict(review_report)

        for cycle_num in range(1, self._config.max_retries + 1):
            cycle_t0 = time.perf_counter()
            cycle_ts = datetime.now(timezone.utc).isoformat()
            score_before = current_score

            # Execute all pending actions
            succeeded = failed = 0
            for action in plan.actions:
                if action.status != "pending":
                    continue
                action.status = "in_progress"
                action.attempt_count += 1
                exec_t0 = time.perf_counter()
                ok, outcome, regen_assets = self._executor.execute(
                    action=action,
                    project_dir=project_dir,
                    scenes=scenes,
                    cycle=cycle_num,
                    enable_rollback=self._config.enable_rollback,
                )
                elapsed = time.perf_counter() - exec_t0
                action.status = "completed" if ok else "failed"
                action.outcome = outcome
                if ok:
                    succeeded += 1
                else:
                    failed += 1
                all_regenerated.extend(regen_assets)
                all_retry_entries.append(
                    RetryHistoryEntry(
                        cycle=cycle_num,
                        action_id=action.action_id,
                        strategy=action.strategy,
                        engine_target=action.engine_target,
                        category=action.category,
                        scene_index=action.scene_index,
                        timestamp=cycle_ts,
                        success=ok,
                        outcome=outcome,
                        elapsed_seconds=elapsed,
                    )
                )
                retry_history.append(action.to_dict())

            # Re-validate after this cycle's actions
            new_review = _revalidate(project_id)
            _, _, new_score_report, _ = _extract_reports(new_review)
            new_score = (
                new_score_report.overall_score if new_score_report is not None else None
            )
            new_verdict = _extract_verdict(new_review)

            threshold_met = (
                new_score is not None and new_score >= self._config.quality_threshold
            )
            cycles.append(
                RemediationCycle(
                    cycle_number=cycle_num,
                    timestamp=cycle_ts,
                    actions_attempted=succeeded + failed,
                    actions_succeeded=succeeded,
                    actions_failed=failed,
                    quality_score_before=score_before,
                    quality_score_after=new_score,
                    verdict_before=current_verdict,
                    verdict_after=new_verdict,
                    elapsed_seconds=round(time.perf_counter() - cycle_t0, 3),
                    threshold_met=threshold_met,
                )
            )

            current_score = new_score
            current_verdict = new_verdict

            if threshold_met:
                stopped_reason = "quality_threshold_met"
                break

            if all(a.status != "pending" for a in plan.actions):
                # All actions exhausted
                if failed == succeeded == 0:
                    stopped_reason = "no_actions_needed"
                elif failed > 0 and succeeded == 0:
                    stopped_reason = "all_actions_failed"
                break

            # Re-plan for next cycle with updated data
            val_r2, rca_r2, sc_r2, efl_r2 = _extract_reports(new_review)
            plan = DecisionEngine(self._config).plan(
                project_id=project_id,
                val_report=val_r2,
                rca_report=rca_r2,
                score_report=sc_r2,
                efl_report=efl_r2,
                retry_history=retry_history,
            )
            if not plan.actions:
                stopped_reason = "quality_threshold_met"
                break

        total_attempted = sum(c.actions_attempted for c in cycles)
        total_succeeded = sum(c.actions_succeeded for c in cycles)
        total_failed = sum(c.actions_failed for c in cycles)

        report = RemediationReport(
            project_id=project_id,
            timestamp=timestamp,
            plan=plan,
            cycles=cycles,
            final_verdict=current_verdict,
            final_quality_score=current_score,
            stopped_reason=stopped_reason,
            total_cycles=len(cycles),
            total_actions_executed=total_attempted,
            total_actions_succeeded=total_succeeded,
            total_actions_failed=total_failed,
            retry_history=all_retry_entries,
            regenerated_assets=all_regenerated,
            processing_time_seconds=round(time.perf_counter() - t0, 3),
            dry_run=self._config.dry_run,
        )
        RemediationReporter().write(report)
        return report


# ── Helpers ───────────────────────────────────────────────────────────────────


def _default_executor() -> RemediationExecutorBase:
    from ytfactory.review.remediation.executor import ProductionExecutor

    return ProductionExecutor()


def _extract_verdict(review_report: object) -> str:
    """Pull verdict string from a ReviewReport or dict."""
    if hasattr(review_report, "verdict"):
        return review_report.verdict  # type: ignore[union-attr]
    if isinstance(review_report, dict):
        return review_report.get("verdict", "UNKNOWN")
    return "UNKNOWN"


def _extract_reports(review_report: object) -> tuple:
    """Extract structured sub-reports from a ReviewReport (or its dict form)."""
    from ytfactory.review.efl.models import EngineFeedbackReport
    from ytfactory.review.rca.models import RCAReport
    from ytfactory.review.scoring.models import QualityScoreReport
    from ytfactory.review.validation.models import ValidationReport

    # Accept either a ReviewReport dataclass or a plain dict (from to_dict())
    if isinstance(review_report, dict):
        # Already serialized — can't reconstruct full objects, use None
        return None, None, None, None

    val_report = None
    rca_report = None
    score_report = None
    efl_report = None

    try:
        # The VQRE returns a ReviewReport whose sub-reports are stored as
        # dicts (from .to_dict()). We need the original objects.
        # They're available on the engine's last result or passed directly.
        # Strategy: accept duck-typed objects via type checking.
        if hasattr(review_report, "validation_report"):
            vd = review_report.validation_report  # type: ignore[union-attr]
            if isinstance(vd, ValidationReport):
                val_report = vd
        if hasattr(review_report, "rca_report"):
            rd = review_report.rca_report  # type: ignore[union-attr]
            if isinstance(rd, RCAReport):
                rca_report = rd
        if hasattr(review_report, "quality_score_report"):
            sd = review_report.quality_score_report  # type: ignore[union-attr]
            if isinstance(sd, QualityScoreReport):
                score_report = sd
        if hasattr(review_report, "efl_report"):
            ed = review_report.efl_report  # type: ignore[union-attr]
            if isinstance(ed, EngineFeedbackReport):
                efl_report = ed
    except Exception:
        pass

    # Fallback: build lightweight proxies from dict fields if dicts are stored
    if val_report is None and hasattr(review_report, "validation_report"):
        val_report = _val_proxy(review_report.validation_report)  # type: ignore[union-attr,assignment]
    if score_report is None and hasattr(review_report, "quality_score_report"):
        score_report = _score_proxy(review_report.quality_score_report)  # type: ignore[union-attr,assignment]
    if rca_report is None and hasattr(review_report, "rca_report"):
        rca_report = _rca_proxy(review_report.rca_report)  # type: ignore[union-attr,assignment]
    if efl_report is None and hasattr(review_report, "efl_report"):
        efl_report = _efl_proxy(review_report.efl_report)  # type: ignore[union-attr,assignment]

    return val_report, rca_report, score_report, efl_report


def _val_proxy(d: object | None) -> object | None:
    """Accept dict or duck-typed objects with ValidationReport-like fields."""
    if d is None:
        return None
    if hasattr(d, "results"):
        return d  # duck-typed object (MagicMock, real ValidationReport, etc.)
    if isinstance(d, dict):

        class _Proxy:
            results: list = []
            critical_failures: list = []
            category_scores: dict = {}

        return _Proxy()
    return None


def _score_proxy(d: object | None) -> object | None:
    if d is None:
        return None
    if hasattr(d, "overall_score"):
        return d  # duck-typed
    if isinstance(d, dict):

        class _Proxy:
            overall_score: float = d.get("overall_score", 0.0)  # type: ignore[union-attr]
            letter_grade: str = d.get("letter_grade", "F")  # type: ignore[union-attr]
            verdict: str = d.get("verdict", "FAIL")  # type: ignore[union-attr]
            category_scores: dict = {}

        return _Proxy()
    return None


def _rca_proxy(d: object | None) -> object | None:
    if d is None:
        return None
    if hasattr(d, "issues"):
        return d  # duck-typed
    if isinstance(d, dict):

        class _Proxy:
            issues: list = []
            recurring_issues: list = []

        return _Proxy()
    return None


def _efl_proxy(d: object | None) -> object | None:
    if d is None:
        return None
    if hasattr(d, "feedback_items"):
        return d  # duck-typed (MagicMock works fine here)
    if isinstance(d, dict):

        class _Proxy:
            feedback_items: list = []
            recurring_patterns: list = []

        return _Proxy()
    return None


def _revalidate(project_id: str) -> object:
    """Re-run the full VQRE and return a fresh ReviewReport."""
    from ytfactory.review.engine import VideoQualityReviewEngine

    return VideoQualityReviewEngine().review(project_id)


def _load_scenes(project_dir: Path) -> list[dict]:
    import json

    scene_plan = project_dir / "scenes" / "scene-plan.json"
    if not scene_plan.exists():
        return []
    try:
        data = json.loads(scene_plan.read_text(encoding="utf-8"))
        return data.get("scenes", [])
    except (json.JSONDecodeError, OSError):
        return []
