"""S1 — Short Opportunity Extractor.

The LLM extracts 3–5 candidate opportunities.
Python applies deterministic selection rules to choose the best two.
The LLM's candidate list is trusted; its selection is not.
"""

from __future__ import annotations

import json
import re
from itertools import combinations

from loguru import logger

from video_core.providers.llm.factory import get_llm_for_role
from ytfactory.config.settings import Settings
from ytfactory.shorts.models import OpportunityExtractionResult, ShortOpportunity
from ytfactory.shorts.prompts.opportunity_extractor import (
    SYSTEM_PROMPT,
    build_extraction_prompt,
)

# Minimum quality threshold — a short below this is not worth selecting
# regardless of diversity bonus
_MIN_HOOK_STRENGTH = 4.0


class ShortOpportunityExtractor:
    def __init__(self, settings: Settings) -> None:
        self._llm = get_llm_for_role(settings, "script")

    def extract(
        self, script_md: str, title: str, project_id: str
    ) -> OpportunityExtractionResult:
        prompt = build_extraction_prompt(script_md, title)
        response = self._llm.generate(
            prompt, system_prompt=SYSTEM_PROMPT, temperature=0.4, json_mode=True
        )

        text = _strip_fences(response.text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Opportunity extractor: LLM returned invalid JSON. "
                f"Preview: {text[:300]}"
            ) from exc

        opportunities_raw = data.get("opportunities", [])
        opportunities = [ShortOpportunity.model_validate(o) for o in opportunities_raw]

        # Python determines selection — never trust LLM's own selection
        selected = _select_two(opportunities)

        return OpportunityExtractionResult(
            parent_video_id=project_id,
            parent_video_title=data.get("parent_video_title", title),
            parent_core_thesis=data.get("parent_core_thesis", ""),
            opportunities=opportunities,
            selected=selected,
            extraction_rationale=data.get("extraction_rationale", ""),
        )


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _evidence_overlap(a: ShortOpportunity, b: ShortOpportunity) -> float:
    """Token-level overlap between primary_evidence strings (0.0–1.0).

    Uses a normalized Jaccard-style overlap so that partial matches (e.g.
    "pebble_story" vs "pebble_gathering") still register similarity.
    """
    ev_a = set(a.primary_evidence.lower().replace("-", "_").split("_"))
    ev_b = set(b.primary_evidence.lower().replace("-", "_").split("_"))
    ev_a.discard("")
    ev_b.discard("")
    if not ev_a or not ev_b:
        return 0.0
    intersection = len(ev_a & ev_b)
    union = len(ev_a | ev_b)
    return intersection / union if union > 0 else 0.0


def _pair_score(a: ShortOpportunity, b: ShortOpportunity) -> float:
    """Deterministic pairwise diversity + quality score.

    Higher is better. Bonuses for diversity; penalties for overlap.
    Quality remains the primary signal — diversity only breaks ties
    or tips comparably-scored pairs.
    """
    # Base quality (max 20.0 for two perfect 10s)
    quality = a.estimated_hook_strength + b.estimated_hook_strength

    # Angle diversity bonus
    angle_bonus = 2.0 if a.angle != b.angle else 0.0

    # Mechanism diversity bonus (stronger weight — this is the core problem)
    mech_bonus = 3.0 if a.primary_mechanism != b.primary_mechanism else 0.0

    # Source section diversity bonus
    source_bonus = 1.0 if not set(a.source_sections) & set(b.source_sections) else 0.0

    # Prefer story + non-story pairing
    has_story = "story" in (a.primary_mechanism, b.primary_mechanism)
    other_mechs = {a.primary_mechanism, b.primary_mechanism} - {"story"}
    conceptual_mechs = {"psychological_mechanism", "modern_example", "metaphor", "paradox"}
    conceptual_pairing_bonus = 1.5 if has_story and other_mechs & conceptual_mechs else 0.0

    # Evidence overlap penalty (0–5 based on overlap ratio)
    overlap = _evidence_overlap(a, b)
    evidence_penalty = overlap * 5.0

    return quality + angle_bonus + mech_bonus + source_bonus + conceptual_pairing_bonus - evidence_penalty


def _select_two(opportunities: list[ShortOpportunity]) -> list[str]:
    """Deterministic pairwise selection of the best two opportunities.

    Evaluates all (n choose 2) pairs and picks the pair with the highest
    combined quality + diversity score. Both candidates in the selected pair
    must meet the minimum quality threshold.
    """
    if not opportunities:
        logger.warning("Shorts extractor: no opportunities returned by LLM.")
        return []

    if len(opportunities) == 1:
        logger.warning(
            "Shorts extractor: only one opportunity returned — cannot generate two distinct Shorts."
        )
        return [opportunities[0].opportunity_id]

    # Filter out below-minimum quality candidates, but only if there are alternatives
    qualified = [o for o in opportunities if o.estimated_hook_strength >= _MIN_HOOK_STRENGTH]
    if len(qualified) < 2:
        logger.warning(
            "Shorts extractor: fewer than two opportunities meet minimum quality ({}). "
            "Using top-2 by hook strength without quality filter.",
            _MIN_HOOK_STRENGTH,
        )
        qualified = sorted(opportunities, key=lambda o: o.estimated_hook_strength, reverse=True)

    if len(qualified) == 1:
        return [qualified[0].opportunity_id]

    # Evaluate all pairs
    best_pair: tuple[ShortOpportunity, ShortOpportunity] | None = None
    best_score = float("-inf")

    for a, b in combinations(qualified, 2):
        score = _pair_score(a, b)
        if score > best_score:
            best_score = score
            best_pair = (a, b)

    assert best_pair is not None
    a, b = best_pair

    # Put higher hook_strength first
    if b.estimated_hook_strength > a.estimated_hook_strength:
        a, b = b, a

    selected = [a.opportunity_id, b.opportunity_id]
    logger.info(
        "Shorts extractor: selected {} (angle={}, mechanism={}) and {} "
        "(angle={}, mechanism={}) — pair_score={:.2f}",
        selected[0], a.angle, a.primary_mechanism,
        selected[1], b.angle, b.primary_mechanism,
        best_score,
    )

    if a.angle == b.angle:
        logger.warning(
            "Shorts extractor: both selected opportunities share the same angle '{}'. "
            "Mechanism diversity is {} vs {}.",
            a.angle, a.primary_mechanism, b.primary_mechanism,
        )

    return selected
