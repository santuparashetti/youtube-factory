"""Combined retention scoring — merges pre-render gate and post-render audit results."""

from __future__ import annotations

from ytfactory.retention.models import RetentionScoreResult
from ytfactory.review.validation.models import ValidationReport

CATEGORY_WEIGHTS = {
    "hook": 30,
    "story_flow": 20,
    "visuals_editing": 20,
    "audio_pacing": 15,
    "ending": 15,
}

RETENTION_RULE_IDS = {
    "STOR_006", "STOR_007", "STOR_008", "STOR_009", "STOR_010",
    "MOT_005", "MOT_006",
}

RETENTION_RULE_WEIGHTS: dict[str, float] = {
    "STOR_006": 30.0,
    "STOR_007": 15.0,
    "STOR_008": 10.0,
    "STOR_009": 10.0,
    "STOR_010": 10.0,
    "MOT_005": 25.0,
    "MOT_006": 10.0,
}


def combine_scores(
    pre_render: RetentionScoreResult,
    post_render: RetentionScoreResult | None = None,
) -> RetentionScoreResult:
    """
    Pre-render gate is the go/no-go for entering render.
    Post-render result reflects reality and is the final score.

    Upload gate: final total >= 85 AND no hard-reject violations.
    """
    if post_render is None:
        return pre_render

    hard_reject_keywords = ("[P1a]", "MOT_005", "STOR_006")
    has_hard_reject = any(
        kw in v for v in post_render.violations for kw in hard_reject_keywords
    )

    passed = post_render.total >= 85.0 and not has_hard_reject

    return RetentionScoreResult(
        total=post_render.total,
        breakdown=post_render.breakdown,
        violations=post_render.violations,
        passed=passed,
    )


def build_post_render_score(val_report: ValidationReport) -> RetentionScoreResult:
    """
    Convert retention-relevant ValidationResults into a post-render
    RetentionScoreResult. Used inside quality_review after ValidationRunner
    has executed.
    """
    breakdown = {k: 100.0 for k in CATEGORY_WEIGHTS}
    violations: list[str] = []

    for result in val_report.results:
        if result.rule_id not in RETENTION_RULE_IDS:
            continue
        weight = RETENTION_RULE_WEIGHTS.get(result.rule_id, 10.0)
        if result.status == "FAIL":
            category = _rule_category(result.rule_id)
            breakdown[category] = max(breakdown.get(category, 100.0) - weight, 0.0)
            violations.append(f"[{result.rule_id}] {result.description}")
        elif result.status == "WARNING":
            category = _rule_category(result.rule_id)
            breakdown[category] = max(breakdown.get(category, 100.0) - weight * 0.5, 0.0)
            violations.append(f"[{result.rule_id}] {result.description}")

    total = sum(breakdown.values()) / len(breakdown) if breakdown else 100.0

    return RetentionScoreResult(
        total=round(total, 2),
        breakdown=breakdown,
        violations=violations,
        passed=total >= 85.0 and not violations,
    )


def _rule_category(rule_id: str) -> str:
    if rule_id in {"STOR_006", "STOR_007", "STOR_008"}:
        return "story_flow"
    if rule_id in {"MOT_005", "MOT_006"}:
        return "visuals_editing"
    if rule_id in {"STOR_009"}:
        return "audio_pacing"
    if rule_id in {"STOR_010"}:
        return "ending"
    return "hook"

