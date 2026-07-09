"""Named hard-fail rules and their issue matchers.

Every named rule in the benchmark YAML must have a corresponding entry here.
To add a new rule: add one ``HardFailMatcher`` to ``RULE_MATCHERS``.
No benchmark dataset or engine code needs to change.

Detection strategy
------------------
A rule fires when *any* returned issue satisfies ALL of:
  1. issue.category is in the matcher's ``categories`` set  OR
     any keyword appears in issue.description (case-insensitive)
  2. issue.severity >= matcher's ``min_severity``
"""

from __future__ import annotations

from dataclasses import dataclass

from ytfactory.providers.vision.models import IssueSeverity, VisionIssue


@dataclass(frozen=True)
class HardFailMatcher:
    """Detects a named hard-fail rule in a list of VisionIssues."""

    categories: frozenset[str]   # issue category values that signal this rule
    keywords: frozenset[str]     # substring matches in issue.description
    min_severity: IssueSeverity = IssueSeverity.MEDIUM

    _SEVERITY_RANK: dict = None  # type: ignore[assignment]  # set below

    def matches(self, issues: list[VisionIssue]) -> bool:
        rank = _SEVERITY_RANK
        min_rank = rank[self.min_severity]
        for issue in issues:
            if rank.get(issue.severity, 0) < min_rank:
                continue
            cat_match = issue.category.lower() in self.categories
            desc = issue.description.lower()
            kw_match = any(kw in desc for kw in self.keywords)
            if cat_match or kw_match:
                return True
        return False


_SEVERITY_RANK: dict[IssueSeverity, int] = {
    IssueSeverity.LOW: 0,
    IssueSeverity.MEDIUM: 1,
    IssueSeverity.HIGH: 2,
    IssueSeverity.CRITICAL: 3,
}


def _matcher(
    categories: set[str],
    keywords: set[str],
    min_severity: IssueSeverity = IssueSeverity.MEDIUM,
) -> HardFailMatcher:
    return HardFailMatcher(
        categories=frozenset(categories),
        keywords=frozenset(keywords),
        min_severity=min_severity,
    )


# ── Rule registry ─────────────────────────────────────────────────────────────
# Add new rules here. Benchmark YAML names must match these keys.

RULE_MATCHERS: dict[str, HardFailMatcher] = {
    "hands_invalid": _matcher(
        {"anatomy"},
        {"hand", "finger", "palm", "knuckle", "wrist"},
        IssueSeverity.MEDIUM,
    ),
    "finger_count_invalid": _matcher(
        {"anatomy"},
        {"finger", "digit", "extra finger", "missing finger", "fused finger", "merged"},
        IssueSeverity.MEDIUM,
    ),
    "impossible_walk_cycle": _matcher(
        {"anatomy", "environment"},
        {"walk", "gait", "stride", "feet", "foot", "step", "limb", "impossible", "hover", "float"},
        IssueSeverity.HIGH,
    ),
    "face_distorted": _matcher(
        {"face"},
        {"face", "distort", "warp", "asym", "eye", "jaw", "deform", "disfigure", "blur"},
        IssueSeverity.HIGH,
    ),
    "pose_mismatch": _matcher(
        {"anatomy", "environment"},
        {"pose", "posture", "position", "wrong pose", "motion", "standing", "sitting", "mismatch"},
        IssueSeverity.MEDIUM,
    ),
    "content_mismatch": _matcher(
        {"environment"},
        {"content", "wrong", "mismatch", "subject", "different", "scene", "incorrect", "expected"},
        IssueSeverity.HIGH,
    ),
    "clothing_violation": _matcher(
        {"anatomy", "environment"},
        {"cloth", "dress", "attire", "costume", "wear", "bare", "naked", "exposed", "garment"},
        IssueSeverity.MEDIUM,
    ),
    "artifact_watermark": _matcher(
        {"artifact"},
        {"watermark", "text artifact", "corrupt", "glitch"},
        IssueSeverity.MEDIUM,
    ),
    "anatomy_general": _matcher(
        {"anatomy"},
        {"anatomy", "body", "limb", "proportion", "twisted", "deform", "merged"},
        IssueSeverity.HIGH,
    ),
}


# ── Public detection helper ───────────────────────────────────────────────────


def detect_hard_fails(
    issues: list[VisionIssue],
    expected_rules: list[str],
) -> tuple[list[str], list]:
    """Run every known rule against the issue list.

    Parameters
    ----------
    issues:
        Issues returned by the VisionProvider.
    expected_rules:
        Rule names from the benchmark YAML for this scene.

    Returns
    -------
    detected_rules:
        Names of rules that fired.
    hard_fail_matches:
        ``HardFailMatch`` records for TP/FP/TN/FN accounting
        (imported lazily to avoid circular import).
    """
    from ytfactory.benchmark.models import HardFailMatch

    expected_set = set(expected_rules)
    detected: list[str] = []
    matches: list[HardFailMatch] = []

    for rule, matcher in RULE_MATCHERS.items():
        fired = matcher.matches(issues)
        if fired:
            detected.append(rule)
        # Record for confusion matrix only when the rule is relevant
        if rule in expected_set or fired:
            matches.append(HardFailMatch(
                rule=rule,
                expected=rule in expected_set,
                detected=fired,
            ))

    # Any expected rule without a matcher: always FN (undetectable by design)
    for rule in expected_rules:
        if rule not in RULE_MATCHERS:
            matches.append(HardFailMatch(rule=rule, expected=True, detected=False))

    return detected, matches
