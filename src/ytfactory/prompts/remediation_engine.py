"""Intelligent Prompt Remediation Engine (Phase 4).

Consumes Vision QA results, VisualMetadata, and PromptPackage to produce
targeted prompt refinements that fix only the detected issues while preserving
the original scene intent.

Extension guide
---------------
To handle a new remediation strategy → add one entry to ``STRATEGY_LIBRARY``.
To handle a new issue category → add one entry to ``ERA_REMEDIATION_LIBRARY``
or ``CATEGORY_REMEDIATION_LIBRARY``.
No orchestrator or pipeline code needs to change.

Invariants
----------
* The output always begins with the original prompt verbatim.
* Only corrective instruction blocks are appended — the original scene content
  is never rewritten, expanded, or hallucinated.
* Each instruction is a single, self-contained corrective sentence.
* Strategies are selected based on issue category, era, severity, and attempt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from video_core.domain.visual_metadata import VisualMetadata
from video_core.providers.vision.models import IssueSeverity, VisionIssue, VisionReviewResult
from video_core.visual_intelligence.prompt_package import PromptPackage


# ── RemediationPackage ─────────────────────────────────────────────────────────


@dataclass
class RemediationPackage:
    """Structured output from the Remediation Engine."""

    original_prompt: str
    remediated_prompt: str
    remediation_reason: str
    issues_fixed: list[str] = field(default_factory=list)
    preserved_constraints: list[str] = field(default_factory=list)
    added_constraints: list[str] = field(default_factory=list)
    removed_constraints: list[str] = field(default_factory=list)
    prompt_diff: str = ""
    remediation_strategy: str = ""
    attempt_number: int = 1
    era: str | None = None
    confidence: float = 0.0
    highest_severity: str | None = None


# ── Strategy Selection ─────────────────────────────────────────────────────────

_STRATEGY_ORDER: dict[str, str] = {
    "anachronism": "era_constraint",
    "historical_accuracy": "era_constraint",
    "anatomy": "anatomy_fix",
    "face": "anatomy_fix",
    "artifact": "artifact_removal",
    "lighting": "lighting_fix",
    "environment": "environment_fix",
    "mood": "mood_fix",
    "composition": "composition_fix",
    "cinematic": "composition_fix",
    "camera": "composition_fix",
    "text": "artifact_removal",
    "style": "style_fix",
}


class RemediationStrategyEngine:
    """Select remediation strategies based on issue metadata."""

    @staticmethod
    def select_strategy(
        issues: list[VisionIssue],
        visual_metadata: VisualMetadata | None = None,
        attempt: int = 1,
    ) -> str:
        if not issues:
            return "fallback"

        primary_category = issues[0].category.lower()

        if primary_category in ("anachronism", "historical_accuracy"):
            return "era_constraint"
        if primary_category in ("anatomy", "face"):
            return "anatomy_fix"
        if primary_category in ("artifact", "text"):
            return "artifact_removal"
        if primary_category == "lighting":
            return "lighting_fix"
        if primary_category == "environment":
            return "environment_fix"
        if primary_category in ("mood",):
            return "mood_fix"
        if primary_category in ("composition", "cinematic", "camera"):
            return "composition_fix"
        if primary_category == "style":
            return "style_fix"

        return "generic_fix"

    @staticmethod
    def _highest_severity(issues: list[VisionIssue]) -> str:
        rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
        best = "LOW"
        for issue in issues:
            val = (
                issue.severity.value
                if isinstance(issue.severity, IssueSeverity)
                else str(issue.severity)
            )
            if rank.get(val, 0) > rank.get(best, 0):
                best = val
        return best


# ── Era-Aware Remediation Library ──────────────────────────────────────────────

_ERA_REMEDIATION_LIBRARY: dict[str, dict[str, list[str]]] = {
    "ANCIENT": {
        "increase": [
            "historical authenticity",
            "traditional architecture",
            "natural materials",
            "ancient setting details",
        ],
        "remove": [
            "drones", "aircraft", "smartphones", "cameras", "roads",
            "modern vehicles", "glass buildings", "concrete highways",
            "power lines", "LED lighting", "plastic", "modern clothing",
            "laptops", "televisions",
        ],
    },
    "HISTORICAL": {
        "increase": [
            "historical authenticity",
            "period-accurate details",
            "traditional materials",
        ],
        "remove": [
            "anachronistic technology",
            "modern infrastructure",
            "inaccurate period details",
        ],
    },
    "MODERN": {
        "increase": [],
        "remove": [],
    },
    "SYMBOLIC": {
        "increase": [
            "metaphorical imagery",
            "abstract representation",
            "conceptual visual elements",
        ],
        "remove": [],
    },
    "TRANSITIONAL": {
        "increase": [
            "intentional coexistence of ancient and modern elements",
        ],
        "remove": [],
    },
}


# ── Category Remediation Library ──────────────────────────────────────────────

_CATEGORY_REMEDIATION_LIBRARY: dict[str, str] = {
    "anatomy": (
        "Correct anatomical proportions, realistic limb structure, and natural "
        "body posture without deformation or merging."
    ),
    "face": (
        "Natural symmetrical facial features with realistic skin tone and "
        "coherent expression."
    ),
    "lighting": (
        "Correct lighting direction, consistent light source, natural cast "
        "shadows, and realistic highlights."
    ),
    "environment": (
        "Scene background and setting match the described location — "
        "no unrelated elements or incorrect environmental details."
    ),
    "cinematic": (
        "Stronger cinematic composition with intentional framing, visual depth, "
        "and a clear primary subject."
    ),
    "artifact": (
        "No compression artifacts, digital noise, unintended text, "
        "or visual distortions."
    ),
    "anachronism": (
        "Remove all anachronistic objects and technology that contradict the era."
    ),
    "historical_accuracy": (
        "Ensure all objects, clothing, and architecture are historically accurate."
    ),
    "mood": (
        "Reinforce the intended atmosphere and emotional tone throughout the scene."
    ),
    "composition": (
        "Improve framing, focal point, and visual hierarchy for stronger storytelling."
    ),
    "camera": (
        "Use intentional camera angle and perspective to serve the narrative."
    ),
    "text": (
        "Remove all text artifacts, watermarks, and unintended lettering."
    ),
    "style": (
        "Maintain consistent visual style throughout the scene."
    ),
}


# ── Confidence-Based Escalation ──────────────────────────────────────────────

_ESCALATION_LEVELS: dict[str, dict[str, str]] = {
    "LOW": {
        "strategy": "minimal_edit",
        "description": "Adjust prompt only — no structural changes.",
    },
    "MEDIUM": {
        "strategy": "strengthen_constraints",
        "description": "Strengthen existing constraints with explicit instructions.",
    },
    "HIGH": {
        "strategy": "significant_remediation",
        "description": "Significant remediation while preserving narrative intent.",
    },
    "CRITICAL": {
        "strategy": "full_regeneration_hint",
        "description": "Recommend full regeneration while preserving story intent.",
    },
}


def _escalation_for_severity(severity: str, attempt: int) -> dict[str, str]:
    base = _ESCALATION_LEVELS.get(severity, _ESCALATION_LEVELS["MEDIUM"])
    if attempt >= 3 and severity in ("HIGH", "CRITICAL"):
        return _ESCALATION_LEVELS["CRITICAL"]
    if attempt >= 2 and severity == "HIGH":
        return _ESCALATION_LEVELS["CRITICAL"]
    return base


# ── Prompt Diff ──────────────────────────────────────────────────────────────


def _compute_diff(old: str, new: str) -> str:
    """Return a simple word-level diff summary."""
    old_words = set(old.lower().replace(",", " ").split())
    new_words = set(new.lower().replace(",", " ").split())
    added = sorted(new_words - old_words)
    removed = sorted(old_words - new_words)
    parts = []
    if added:
        parts.append("Added: " + ", ".join(added[:10]))
    if removed:
        parts.append("Removed: " + ", ".join(removed[:10]))
    return "; ".join(parts) if parts else "No semantic diff"


# ── Main Remediation Engine ───────────────────────────────────────────────────


class RemediationEngine:
    """Produce RemediationPackage from vision review results."""

    def __init__(
        self,
        strategy_engine: RemediationStrategyEngine | None = None,
    ) -> None:
        self._strategy = strategy_engine or RemediationStrategyEngine()

    def build(
        self,
        original_prompt: str,
        result: VisionReviewResult,
        visual_metadata: VisualMetadata | None = None,
        prompt_package: PromptPackage | None = None,
        attempt: int = 1,
    ) -> RemediationPackage:
        issues = result.issues or []
        strategy = self._strategy.select_strategy(issues, visual_metadata, attempt)
        highest = RemediationStrategyEngine._highest_severity(issues)

        instructions: list[str] = []
        added_constraints: list[str] = []
        removed_constraints: list[str] = []
        preserved_constraints: list[str] = [
            "subject",
            "composition",
            "environment",
            "mood",
            "narrative role",
        ]
        issues_fixed: list[str] = []

        if visual_metadata and visual_metadata.is_populated:
            era_key = visual_metadata.era.value if visual_metadata.era else None
            if era_key and era_key in _ERA_REMEDIATION_LIBRARY:
                era_data = _ERA_REMEDIATION_LIBRARY[era_key]
                for item in era_data.get("increase", []):
                    instructions.append(f"Increase: {item}")
                    added_constraints.append(item)
                for item in era_data.get("remove", []):
                    instructions.append(f"Remove: {item}")
                    removed_constraints.append(item)

        covered_categories: set[str] = set()
        for issue in issues:
            cat = issue.category.lower()
            covered_categories.add(cat)
            instr = _CATEGORY_REMEDIATION_LIBRARY.get(cat)
            if instr and instr not in instructions:
                instructions.append(instr)
                issues_fixed.append(f"{cat}: {issue.description}")

        if not instructions:
            instructions.append(
                "High photographic quality, sharp focus, correct proportions, "
                "no artifacts — preserve all original scene elements."
            )

        seen: set[str] = set()
        unique_instructions: list[str] = []
        for instr in instructions:
            if instr not in seen:
                seen.add(instr)
                unique_instructions.append(instr)

        remediated_prompt = self._format(original_prompt, unique_instructions)
        prompt_diff = _compute_diff(original_prompt, remediated_prompt)

        return RemediationPackage(
            original_prompt=original_prompt,
            remediated_prompt=remediated_prompt,
            remediation_reason=(
                f"Vision QA FAIL (score={result.score:.0f}, confidence={result.confidence:.0f}): "
                f"highest_severity={highest}, strategy={strategy}, attempt={attempt}"
            ),
            issues_fixed=issues_fixed,
            preserved_constraints=preserved_constraints,
            added_constraints=added_constraints,
            removed_constraints=removed_constraints,
            prompt_diff=prompt_diff,
            remediation_strategy=strategy,
            attempt_number=attempt,
            era=visual_metadata.era.value if visual_metadata and visual_metadata.era else None,
            confidence=result.confidence,
            highest_severity=highest,
        )

    @staticmethod
    def _format(original_prompt: str, instructions: list[str]) -> str:
        lines = [
            original_prompt,
            "",
            "Improve only the following while preserving the original scene:",
        ]
        for instr in instructions:
            lines.append(f"- {instr}")
        return "\n".join(lines)
