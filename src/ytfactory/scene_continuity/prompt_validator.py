"""Prompt-level continuity validation.

Validates a generated visual prompt against canonical scene state to detect
contradictions such as absent characters, dead characters appearing alive,
temporal contradictions, object ownership violations, and clothing drift.
"""

from __future__ import annotations

import re
from typing import Any

from .models import (
    ContinuityFinding,
    SceneMode,
    StoryState,
    ValidationLevel,
    is_symbolic_mode,
)
from .normalization import (
    normalize_time,
)


# ---------------------------------------------------------------------------
# Vocabulary families for prompt-side detection
# ---------------------------------------------------------------------------

_CHARACTER_ACTION_RE = re.compile(
    r"\b(?:his|her|their|the\s+\w+['’]s)\s+(?:hand|arm|face|body|figure|form|shape|"
    r"back|shoulder|head|eyes|gaze|voice|presence|cloak|tunic|shirt|trousers|boots|"
    r"belt|robe|garment|clothing|body|posture|stance|movement|walk|step|reach|hold|"
    r"carry|grip|finger|hand|wrist|neck|chest)\b",
    re.IGNORECASE,
)

_DEATH_REVERSE_RE = re.compile(
    r"\b(?:alive|living|walks|walking|stands|standing|sits|sitting|talks|talking|"
    r"looks|looking|breathes|breathing|moves|moving|speaks|speaking|holds|holding|"
    r"carries|carrying|reaches|reaching|turns|turning|rises|rising|smiles|smiling)\b",
    re.IGNORECASE,
)

_LIT_WORDS = frozenset({"lit", "on", "burning", "glowing", "illuminated", "aflame", "lit_up"})
_UNLIT_WORDS = frozenset({"unlit", "off", "extinguished", "dark", "dead", "cold", "dim"})
_FULL_WORDS = frozenset({"full", "filled", "replenished"})
_EMPTY_WORDS = frozenset({"empty", "spent", "depleted", "exhausted", "drained"})


def _name_in_prompt(name: str, prompt: str) -> bool:
    """Case-insensitive word-boundary check for a character name in a prompt."""
    words = name.lower().split()
    prompt_lower = prompt.lower()
    if name.lower() in prompt_lower:
        return True
    for word in words:
        if len(word) > 3:
            if re.search(r"\b" + re.escape(word) + r"\b", prompt_lower):
                return True
    return False


def _has_body_part_reference(prompt: str) -> bool:
    """True if prompt contains a body part or action that implies character presence."""
    return bool(_CHARACTER_ACTION_RE.search(prompt))


def _proposed_prop_state(prompt: str, prop_name: str) -> str | None:
    """Heuristic extraction of a prop state from prompt text."""
    prompt_lower = prompt.lower()
    if prop_name.lower() not in prompt_lower:
        return None
    if any(w in prompt_lower for w in _LIT_WORDS):
        return "lit"
    if any(w in prompt_lower for w in _UNLIT_WORDS):
        return "unlit"
    if any(w in prompt_lower for w in _FULL_WORDS):
        return "full"
    if any(w in prompt_lower for w in _EMPTY_WORDS):
        return "empty"
    return None


def validate_prompt_against_state(
    prompt: str,
    canonical_state: StoryState,
    scene_index: int,
    scene_mode: SceneMode = SceneMode.LITERAL,
    scene_analysis: Any = None,
) -> list[ContinuityFinding]:
    """Validate a generated visual prompt against canonical story state.

    Checks for contradictions between the prompt content and the authoritative
    canonical state. Does NOT modify the prompt.

    Args:
        prompt: The generated visual prompt text
        canonical_state: The accumulated StoryState before this scene
        scene_index: Current scene index
        scene_mode: LITERAL or symbolic
        scene_analysis: Optional scene analysis with allowed_characters

    Returns:
        List of ContinuityFinding instances (empty = no violations)
    """
    findings: list[ContinuityFinding] = []

    if is_symbolic_mode(scene_mode):
        return findings

    if not prompt or not prompt.strip():
        return findings

    char_states, prop_states = canonical_state.get_state_before_scene(scene_index)
    prompt_lower = prompt.lower()

    # ── Absent character + body part check ─────────────────────────────
    for cid, char_state in char_states.items():
        if char_state.present_in_story or not char_state.alive:
            continue
        if _name_in_prompt(char_state.name, prompt):
            if _has_body_part_reference(prompt):
                findings.append(
                    ContinuityFinding(
                        scene_id=scene_index,
                        level=ValidationLevel.ERROR,
                        category="CHARACTER_CONTINUITY",
                        message=(
                            f"Absent character '{char_state.name}' appears in prompt "
                            f"with body part/action reference in scene {scene_index}."
                        ),
                        suggested_fix=(
                            f"Remove '{char_state.name}' from the prompt. "
                            "Absent characters cannot contribute body parts."
                        ),
                    )
                )

    # ── Dead character alive in prompt ─────────────────────────────────
    for cid, char_state in char_states.items():
        if char_state.alive:
            continue
        if _name_in_prompt(char_state.name, prompt):
            if _DEATH_REVERSE_RE.search(prompt):
                findings.append(
                    ContinuityFinding(
                        scene_id=scene_index,
                        level=ValidationLevel.CRITICAL,
                        category="CHARACTER_RESURRECTION",
                        message=(
                            f"Dead character '{char_state.name}' appears alive in prompt "
                            f"for scene {scene_index}."
                        ),
                        suggested_fix=(
                            f"Remove '{char_state.name}' from the prompt, or mark this scene "
                            "SYMBOLIC_RECONSTRUCTION if it is a flashback/memory."
                        ),
                    )
                )

    # ── Prop state contradiction ───────────────────────────────────────
    for prop_cid, prop_state in prop_states.items():
        if not prop_state.current_state:
            continue
        if not _name_in_prompt(prop_state.name, prompt):
            continue
        proposed = _proposed_prop_state(prompt, prop_state.name)
        if proposed is None:
            continue
        ok, reason = prop_state.can_be_in_state(proposed)
        if not ok:
            findings.append(
                ContinuityFinding(
                    scene_id=scene_index,
                    level=ValidationLevel.ERROR,
                    category="PROP_STATE",
                    message=(
                        f"Prop '{prop_state.name}' shown as '{proposed}' in scene {scene_index} "
                        f"but {reason}."
                    ),
                    suggested_fix=(
                        f"Update the prompt to show '{prop_state.name}' as "
                        f"'{prop_state.current_state}' to match canonical state."
                    ),
                )
            )

    # ── Object ownership contradiction ─────────────────────────────────
    for prop_cid, prop_state in prop_states.items():
        if not prop_state.owner:
            continue
        owner_name = prop_state.owner
        owner_char_state = char_states.get(prop_state.owner)
        if owner_char_state:
            owner_name = owner_char_state.name
        # Check if the prompt implies someone else holds the object
        holds_patterns = [
            rf"\b(?:holds?|holding|carries?|carrying|grips?|gripping)\b.*\b{re.escape(prop_state.name)}\b",
            rf"\b{re.escape(prop_state.name)}\b.*\b(?:in\s+(?:his|her|their)\s+(?:hand|hands))\b",
        ]
        for pat in holds_patterns:
            if re.search(pat, prompt_lower):
                # Check if the implied holder is the canonical owner
                if not _name_in_prompt(owner_name, prompt):
                    findings.append(
                        ContinuityFinding(
                            scene_id=scene_index,
                            level=ValidationLevel.ERROR,
                            category="OBJECT_OWNERSHIP",
                            message=(
                                f"Prompt implies someone holds '{prop_state.name}' but "
                                f"canonical owner is '{owner_name}' in scene {scene_index}."
                            ),
                            suggested_fix=(
                                f"Either show '{owner_name}' holding the object, "
                                f"or remove it from the prompt."
                            ),
                        )
                    )
                break

    # ── Temporal contradiction ─────────────────────────────────────────
    canonical_time = canonical_state.current_time_of_day
    if canonical_time:
        # Check for obvious temporal contradictions in prompt lighting
        time_mentions = {
            "SUNRISE": ["sunrise", "dawn", "early morning"],
            "MORNING": ["morning", "mid-morning"],
            "MIDDAY": ["midday", "noon", "mid-day", "midday sun"],
            "AFTERNOON": ["afternoon", "late afternoon"],
            "SUNSET": ["sunset", "golden hour"],
            "DUSK": ["dusk", "twilight", "evening"],
            "NIGHT": ["night", "nighttime"],
            "DEEP_NIGHT": ["deep night", "midnight", "pitch black", "full dark", "darkness"],
        }
        forbidden = time_mentions.get(normalize_time(canonical_time), [])
        for term in forbidden:
            # Only flag if the prompt explicitly contradicts, not if it just mentions night
            # when canonical is deep_night (night is compatible with deep_night)
            if term in ["night", "nighttime"] and normalize_time(canonical_time) in ("NIGHT", "DEEP_NIGHT"):
                continue
            if term in prompt_lower:
                # Check for explicit contradictory terms
                contradictory_terms = {
                    "SUNRISE": ["sunset", "dusk", "night", "dark"],
                    "MORNING": ["sunset", "dusk", "night", "dark"],
                    "MIDDAY": ["sunset", "dusk", "night", "dark"],
                    "AFTERNOON": ["night", "dark", "midnight"],
                    "SUNSET": ["sunrise", "dawn", "midday", "noon"],
                    "DUSK": ["sunrise", "dawn", "midday"],
                    "NIGHT": ["sunrise", "dawn", "midday", "noon", "sunset", "golden hour"],
                    "DEEP_NIGHT": ["sunrise", "dawn", "midday", "noon", "sunset", "golden hour", "dusk", "twilight"],
                }
                contradictions = contradictory_terms.get(normalize_time(canonical_time), [])
                if any(c in prompt_lower for c in contradictions):
                    findings.append(
                        ContinuityFinding(
                            scene_id=scene_index,
                            level=ValidationLevel.ERROR,
                            category="TEMPORAL_CONTINUITY",
                            message=(
                                f"Prompt suggests '{term}' but canonical time is "
                                f"'{canonical_time}' in scene {scene_index}."
                            ),
                            suggested_fix=(
                                f"Adjust prompt lighting to match canonical time '{canonical_time}'."
                            ),
                        )
                    )
                break

    # ── Canonical clothing drift ───────────────────────────────────────
    for cid, char_state in char_states.items():
        if not char_state.clothing:
            continue
        if not _name_in_prompt(char_state.name, prompt):
            continue
        # Check for contradictory clothing terms in prompt
        canonical_clothing_lower = char_state.clothing.lower()
        # Extract key clothing items from canonical description
        canonical_items = set(re.findall(r"\b\w+\b", canonical_clothing_lower))
        # Common clothing terms that might contradict
        contradictory_terms = {
            "cloak": ["tunic", "shirt", "jacket"],
            "tunic": ["cloak", "robe", "jacket"],
            "robe": ["cloak", "tunic", "jacket"],
            "boots": ["barefoot", "sandals", "bare feet"],
            "barefoot": ["boots", "shod", "wearing boots"],
            "crown": ["no crown", "uncrowned"],
            "belt": ["no belt", "beltless"],
        }
        for term, contradictions in contradictory_terms.items():
            if term in canonical_items:
                for contra in contradictions:
                    if contra in prompt_lower:
                        findings.append(
                            ContinuityFinding(
                                scene_id=scene_index,
                                level=ValidationLevel.WARNING,
                                category="CLOTHING_DRIFT",
                                message=(
                                    f"Canonical clothing for '{char_state.name}' includes "
                                    f"'{term}' but prompt suggests '{contra}' in scene {scene_index}."
                                ),
                                suggested_fix=(
                                    f"Inject canonical character description for '{char_state.name}' "
                                    f"or update prompt to match canonical clothing."
                                ),
                            )
                        )
                        break

    return findings
