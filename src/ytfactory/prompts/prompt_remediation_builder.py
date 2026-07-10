"""Prompt Remediation Builder.

Converts structured review results into targeted prompt refinements that fix
only the detected issues while preserving the original scene, artistic intent,
and script context.

Extension guide
---------------
To handle a new review rule   → add one entry to ``RULE_PROMPT_LIBRARY``.
To handle a new issue category → add one entry to ``CATEGORY_PROMPT_LIBRARY``.
To improve rule auto-detection → add/update one entry in ``_RULE_DETECTORS``.
No orchestrator or pipeline code needs to change.

Invariants
----------
* The output always begins with the original prompt verbatim.
* Only a corrective instruction block is appended — the original scene content
  is never rewritten, expanded, or hallucinated.
* Each instruction is a single, self-contained corrective sentence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ytfactory.providers.vision.models import IssueSeverity, VisionIssue, VisionReviewResult


# ── Rule-Based Prompt Library ─────────────────────────────────────────────────
#
# Maps named hard-fail rule → one corrective instruction sentence.
# Keep entries precise: one problem, one fix, no scene content.

RULE_PROMPT_LIBRARY: dict[str, str] = {
    "hands_invalid": (
        "Natural five-finger hands with realistic anatomy, correct joint proportions, "
        "and natural finger spacing."
    ),
    "finger_count_invalid": (
        "Exactly five anatomically correct fingers on each visible hand with "
        "natural spacing and distinct digit separation."
    ),
    "impossible_walk_cycle": (
        "Natural walking gait with a realistic stride, balanced posture, "
        "and one foot planted firmly on the ground."
    ),
    "face_distorted": (
        "Photorealistic symmetrical facial features with natural eyes, nose, "
        "mouth, and authentic skin texture."
    ),
    "floating_person": (
        "Subject standing firmly on the ground with physically accurate foot "
        "placement and natural cast shadows."
    ),
    "weak_composition": (
        "Stronger cinematic framing with a clear focal point, greater visual depth, "
        "and intentional visual storytelling."
    ),
    "blurred_face": (
        "Sharp facial details with natural focus on the primary subject and "
        "crisp delineation of facial features."
    ),
    "content_mismatch": (
        "Ensure the scene content matches the described subject and setting exactly — "
        "no substituted subjects or unrelated backgrounds."
    ),
    "clothing_violation": (
        "Subject wearing contextually appropriate clothing that matches the "
        "period, culture, and setting described in the scene."
    ),
    "artifact_watermark": (
        "No watermarks, embedded text, logos, or digital compression artifacts — "
        "clean, unbranded image output."
    ),
    "pose_mismatch": (
        "Subject posture and body position match the described action — "
        "correct stance and natural weight distribution."
    ),
    "anatomy_general": (
        "Correct human body proportions with natural limb lengths, realistic "
        "posture, and no merged or twisted body parts."
    ),
}

# ── Category-Level Prompt Library ─────────────────────────────────────────────
#
# Fallback instructions used when no named rule covers an issue's category.

CATEGORY_PROMPT_LIBRARY: dict[str, str] = {
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
}

# ── Category normalization ────────────────────────────────────────────────────
#
# The vision model is instructed to return one of the canonical categories, but
# sometimes returns variants like "AI Artifacts" instead of "artifact".  When a
# broad category like "artifact" accompanies a description that contains
# hand/anatomy keywords, the issue is really an anatomy defect; normalising it
# to "anatomy" lets _RULE_DETECTORS match on category as well as keyword.

_ARTIFACT_ANATOMY_KEYWORDS: frozenset[str] = frozenset({
    "hand", "hands", "finger", "fingers", "thumb", "digit", "digits",
    "knuckle", "knuckles", "palm", "palms", "wrist", "wrists",
    "duplicated thumb", "extra finger", "missing finger", "fused digit",
})

_CATEGORY_ALIASES: dict[str, str] = {
    "ai artifacts": "artifact",
    "ai artifact": "artifact",
}


def _normalize_category(issue: "VisionIssue") -> str:
    """Return a canonical lowercase category for rule-detection purposes.

    ``"AI Artifacts"`` + an anatomy-keyword description → ``"anatomy"`` so that
    hand/anatomy rules match on category as well as keyword.
    Any other alias is collapsed to its canonical form; unknown values pass through.
    """
    cat = issue.category.lower()
    cat = _CATEGORY_ALIASES.get(cat, cat)
    if cat == "artifact":
        desc = issue.description.lower()
        if any(kw in desc for kw in _ARTIFACT_ANATOMY_KEYWORDS):
            return "anatomy"
    return cat


_FALLBACK_INSTRUCTION = (
    "High photographic quality, sharp focus, correct proportions, "
    "no artifacts — preserve all original scene elements."
)

_CORRECTION_HEADER = "Improve only the following while preserving the original scene:"

# ── Rule auto-detection ───────────────────────────────────────────────────────
#
# Each entry: (category_set, keyword_set, min_severity_string)
# A rule fires when severity >= min AND (category_match OR any keyword in description).

_SEVERITY_RANK: dict[str, int] = {
    "LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3,
}

_RULE_DETECTORS: dict[str, tuple[frozenset[str], frozenset[str], str]] = {
    "hands_invalid": (
        frozenset({"anatomy"}),
        frozenset({"hand", "finger", "thumb", "palm", "wrist", "knuckle", "duplicated thumb"}),
        "MEDIUM",
    ),
    "finger_count_invalid": (
        frozenset({"anatomy"}),
        frozenset({"finger", "digit", "thumb", "extra finger", "missing finger", "fused", "merged", "duplicated"}),
        "MEDIUM",
    ),
    "impossible_walk_cycle": (
        frozenset({"anatomy", "environment"}),
        frozenset({"walk", "gait", "stride", "foot", "feet", "hover", "float", "impossible"}),
        "HIGH",
    ),
    "face_distorted": (
        frozenset({"face"}),
        frozenset({"face", "distort", "warp", "asymm", "eye", "jaw", "deform", "disfigure"}),
        "HIGH",
    ),
    "floating_person": (
        frozenset({"anatomy", "environment"}),
        frozenset({"float", "hover", "levitat", "not grounded", "foot placement", "no shadow"}),
        "HIGH",
    ),
    "weak_composition": (
        frozenset({"cinematic"}),
        frozenset({"composition", "framing", "depth", "focal", "storytelling"}),
        "LOW",
    ),
    "blurred_face": (
        frozenset({"face"}),
        frozenset({"blur", "soft focus", "out of focus", "unclear", "fuzzy"}),
        "MEDIUM",
    ),
    "content_mismatch": (
        frozenset({"environment"}),
        frozenset({"mismatch", "wrong", "incorrect", "unrelated", "different subject"}),
        "HIGH",
    ),
    "clothing_violation": (
        frozenset({"anatomy", "environment"}),
        frozenset({"cloth", "attire", "dress", "costume", "bare", "naked", "exposed", "garment"}),
        "MEDIUM",
    ),
    "artifact_watermark": (
        frozenset({"artifact"}),
        frozenset({"watermark", "text artifact", "logo", "corrupt", "glitch"}),
        "MEDIUM",
    ),
    "pose_mismatch": (
        frozenset({"anatomy", "environment"}),
        frozenset({"pose", "posture", "position", "stance", "wrong pose"}),
        "MEDIUM",
    ),
    "anatomy_general": (
        frozenset({"anatomy"}),
        frozenset({"anatomy", "body", "limb", "proportion", "twisted", "deform"}),
        "HIGH",
    ),
}


# ── Input model ────────────────────────────────────────────────────────────────


@dataclass
class RemediationInput:
    """All information the builder needs to produce a refined prompt."""

    original_prompt: str
    scene: dict                       # scene dict from scene-plan.json
    result: VisionReviewResult        # vision provider output from the failed attempt
    narrative_score: float = 100.0   # 100 − environment deductions (0–100)
    technical_score: float = 100.0   # 100 − anatomy/face/artifact deductions (0–100)
    cinematic_score: float = 100.0   # 100 − lighting/cinematic deductions (0–100)
    detected_rules: list[str] = field(default_factory=list)
    attempt: int = 1


# ── Builder ────────────────────────────────────────────────────────────────────


class PromptRemediationBuilder:
    """Convert a vision review failure into a targeted prompt refinement.

    Responsibilities
    ----------------
    * Preserve the original artistic intent and scene meaning.
    * Preserve the script context — never hallucinate new content.
    * Preserve composition unless the composition failed.
    * Only add corrective instructions for detected issues.
    * Be driven entirely by the rule and category libraries above.

    The orchestrator calls ``build()`` between generation attempts.
    It never calls image generation or review directly.
    """

    def build(self, inp: RemediationInput) -> str:
        """Return a refined prompt correcting only the detected issues.

        If ``inp.detected_rules`` is empty, rules are auto-detected from the
        issues in ``inp.result`` via ``detect_rules()``.

        The output always starts with the original prompt and appends a
        structured correction block.
        """
        rules = inp.detected_rules or self.detect_rules(inp.result.issues)
        instructions = self._gather_instructions(rules, inp.result.issues, inp.cinematic_score)
        return self._format(inp.original_prompt, instructions)

    def detect_rules(self, issues: list[VisionIssue]) -> list[str]:
        """Infer named rule names from a list of VisionIssues.

        Uses keyword + category matching.  Each rule is returned at most once.
        Category is normalised via ``_normalize_category`` before matching so
        that model-returned variants like ``"AI Artifacts"`` resolve correctly.
        """
        detected: list[str] = []
        for rule, (categories, keywords, min_sev) in _RULE_DETECTORS.items():
            min_rank = _SEVERITY_RANK.get(min_sev, 1)
            for issue in issues:
                sev_str = (
                    issue.severity.value
                    if isinstance(issue.severity, IssueSeverity)
                    else str(issue.severity)
                )
                if _SEVERITY_RANK.get(sev_str, 0) < min_rank:
                    continue
                cat_match = _normalize_category(issue) in categories
                desc = issue.description.lower()
                kw_match = any(kw in desc for kw in keywords)
                if cat_match or kw_match:
                    detected.append(rule)
                    break  # this rule fired — move to next rule
        return detected

    # ── Internals ─────────────────────────────────────────────────────────

    def _gather_instructions(
        self,
        rules: list[str],
        issues: list[VisionIssue],
        cinematic_score: float,
    ) -> list[str]:
        seen: set[str] = set()
        instructions: list[str] = []

        def _add(instr: str) -> None:
            if instr and instr not in seen:
                seen.add(instr)
                instructions.append(instr)

        # Priority 1 — named rule instructions (highest quality, most specific)
        for rule in rules:
            _add(RULE_PROMPT_LIBRARY.get(rule, ""))

        # Priority 2 — category fallbacks for issues not covered by the rules above
        covered = _covered_categories(rules)
        for issue in issues:
            cat = issue.category.lower()
            if cat not in covered:
                _add(CATEGORY_PROMPT_LIBRARY.get(cat, ""))

        # Priority 3 — explicit cinematic boost when score is critically low
        if cinematic_score < 70 and "cinematic" not in covered:
            _add(
                RULE_PROMPT_LIBRARY.get("weak_composition")
                or CATEGORY_PROMPT_LIBRARY.get("cinematic", "")
            )

        # Fallback — when no specific instruction could be derived at all
        if not instructions:
            _add(_FALLBACK_INSTRUCTION)

        return instructions

    @staticmethod
    def _format(original_prompt: str, instructions: list[str]) -> str:
        lines = [_CORRECTION_HEADER]
        for instr in instructions:
            lines.append(f"- {instr}")
        correction_block = "\n".join(lines)
        return f"{original_prompt}\n\n{correction_block}"


# ── Module helper ─────────────────────────────────────────────────────────────


def _covered_categories(rules: list[str]) -> set[str]:
    """Return the union of all category sets for the given rule names."""
    covered: set[str] = set()
    for rule in rules:
        cats, _, _ = _RULE_DETECTORS.get(rule, (frozenset(), frozenset(), "MEDIUM"))
        covered |= cats
    return covered
