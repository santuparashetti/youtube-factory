"""Decision Engine for Auto Remediation Engine V1.

Pure business logic — no I/O.  Given all available review reports, produces
a RemediationPlan with the minimal set of actions needed to meet the quality
threshold.

Priority of action selection:
1. Critical EFL feedback items with confidence >= min_confidence
2. High EFL feedback items with confidence >= min_confidence
3. RCA issues not already covered by EFL feedback

Deduplication key: (strategy, category, scene_index) — avoids scheduling
the same artifact for regeneration twice.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ytfactory.review.remediation.config import (
    CATEGORY_STRATEGY_MAP,
    ENGINE_STRATEGY_MAP,
    STRATEGY_COST,
    RemediationConfig,
)
from ytfactory.review.remediation.models import RemediationAction, RemediationPlan

if TYPE_CHECKING:
    from ytfactory.review.efl.models import EngineFeedbackReport
    from ytfactory.review.rca.models import RCAReport
    from ytfactory.review.scoring.models import QualityScoreReport
    from ytfactory.review.validation.models import ValidationReport


class DecisionEngine:
    """Map review reports to a RemediationPlan with the minimum required actions."""

    def __init__(self, config: RemediationConfig) -> None:
        self._config = config

    def plan(
        self,
        project_id: str,
        val_report: ValidationReport | None,
        rca_report: RCAReport | None,
        score_report: QualityScoreReport | None,
        efl_report: EngineFeedbackReport | None,
        retry_history: list[dict] | None = None,
    ) -> RemediationPlan:
        """Produce a RemediationPlan from all available review artifacts."""
        timestamp = datetime.now(timezone.utc).isoformat()
        current_score = score_report.overall_score if score_report is not None else None

        # Already passing — nothing to do
        if (
            current_score is not None
            and current_score >= self._config.quality_threshold
        ):
            return RemediationPlan(
                project_id=project_id,
                timestamp=timestamp,
                actions=[],
                quality_score_before=current_score,
                quality_threshold=self._config.quality_threshold,
                max_retries=self._config.max_retries,
                estimated_total_cost=0.0,
                decision_summary=(
                    f"Quality score {current_score:.1f} already meets threshold "
                    f"{self._config.quality_threshold:.1f} — no remediation required."
                ),
            )

        actions: list[RemediationAction] = []
        # Deduplication: (strategy, category, scene_index)
        seen: set[tuple[str, str, int | None]] = set()

        # Count how many times each (engine, rule_id) has been retried already
        retry_counts = _build_retry_counts(retry_history or [])

        # ── Phase 1: Build actions from EFL feedback ──────────────────────────
        if efl_report is not None:
            for item in efl_report.feedback_items:
                if item.priority not in self._config.remediate_severities:
                    continue
                if item.confidence < self._config.min_confidence:
                    continue

                # Skip if already retried too many times
                retry_key = (item.engine_owner, item.rule_id)
                if retry_counts.get(retry_key, 0) >= self._config.max_retries:
                    continue

                strategy = _select_strategy(item.engine_owner, item.category)

                # Skip full_regeneration unless explicitly allowed
                if (
                    strategy == "full_regeneration"
                    and not self._config.allow_full_regeneration
                ):
                    strategy = "retry_validation"

                cost = STRATEGY_COST.get(strategy, 0.0)
                scene_index = _extract_scene_index(item)
                dedup_key = (strategy, item.category, scene_index)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                actions.append(
                    RemediationAction(
                        action_id="",  # assigned after collection
                        strategy=strategy,
                        engine_target=item.engine_owner,
                        category=item.category,
                        severity=item.severity,
                        confidence=item.confidence,
                        rationale=(
                            f"EFL feedback {item.feedback_id}: {item.root_cause}. "
                            f"Fix: {item.recommended_fix}"
                        ),
                        estimated_cost=cost,
                        scene_index=scene_index,
                        rule_id=item.rule_id,
                        source_feedback=item.feedback_id,
                    )
                )

        # ── Phase 2: Fill gaps from RCA issues not covered above ──────────────
        if rca_report is not None:
            covered_rules = {a.rule_id for a in actions}
            for issue in rca_report.issues:
                if issue.severity not in self._config.remediate_severities:
                    continue
                if issue.confidence < self._config.min_confidence:
                    continue
                if issue.rule_id in covered_rules:
                    continue

                strategy = _select_strategy(issue.primary_engine, issue.category)
                if (
                    strategy == "full_regeneration"
                    and not self._config.allow_full_regeneration
                ):
                    strategy = "retry_validation"

                cost = STRATEGY_COST.get(strategy, 0.0)
                dedup_key = (strategy, issue.category, issue.scene_index)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                actions.append(
                    RemediationAction(
                        action_id="",
                        strategy=strategy,
                        engine_target=issue.primary_engine,
                        category=issue.category,
                        severity=issue.severity,
                        confidence=issue.confidence,
                        rationale=(
                            f"RCA issue {issue.issue_id}: {issue.root_cause_description}. "
                            f"Fix: {issue.suggested_fix}"
                        ),
                        estimated_cost=cost,
                        scene_index=issue.scene_index,
                        rule_id=issue.rule_id,
                        source_issue=issue.issue_id,
                    )
                )

        # ── Assign sequential IDs and compute total cost ──────────────────────
        # Sort: highest severity first, then by cost (cheapest first within same severity)
        actions.sort(key=lambda a: (_severity_rank(a.severity), a.estimated_cost))
        for i, action in enumerate(actions, start=1):
            action.action_id = f"ARE-{i:04d}"

        total_cost = sum(a.estimated_cost for a in actions)

        summary = _build_summary(actions, current_score, self._config.quality_threshold)

        return RemediationPlan(
            project_id=project_id,
            timestamp=timestamp,
            actions=actions,
            quality_score_before=current_score,
            quality_threshold=self._config.quality_threshold,
            max_retries=self._config.max_retries,
            estimated_total_cost=total_cost,
            decision_summary=summary,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _select_strategy(engine: str, category: str) -> str:
    """Choose the cheapest adequate strategy given engine and category."""
    return ENGINE_STRATEGY_MAP.get(engine) or CATEGORY_STRATEGY_MAP.get(
        category, "retry_validation"
    )


def _extract_scene_index(item: object) -> int | None:
    """Extract scene_index from a FeedbackItem if available."""
    # FeedbackItem has no scene_index directly, but the rule_id or evidence may hint.
    # For V1, we return None (action applies to all affected scenes).
    return None


def _severity_rank(severity: str) -> int:
    """Lower = higher priority."""
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(severity, 4)


def _build_retry_counts(history: list[dict]) -> dict[tuple[str, str], int]:
    """Count past executions per (engine_target, rule_id) from retry history."""
    counts: dict[tuple[str, str], int] = {}
    for entry in history:
        key = (entry.get("engine_target", ""), entry.get("rule_id", ""))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _build_summary(
    actions: list[RemediationAction],
    current_score: float | None,
    threshold: float,
) -> str:
    if not actions:
        score_str = f"{current_score:.1f}" if current_score is not None else "N/A"
        return (
            f"No remediable actions found (score={score_str}, threshold={threshold:.1f}). "
            "All failures are below confidence threshold or outside remediable severities."
        )
    strategies: dict[str, int] = {}
    for a in actions:
        strategies[a.strategy] = strategies.get(a.strategy, 0) + 1
    strategy_str = ", ".join(f"{s}×{c}" for s, c in sorted(strategies.items()))
    score_str = f"{current_score:.1f}" if current_score is not None else "N/A"
    return (
        f"{len(actions)} action(s) planned to improve score from {score_str} "
        f"to ≥{threshold:.1f}: {strategy_str}."
    )
