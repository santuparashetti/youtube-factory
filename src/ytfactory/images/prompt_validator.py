"""Prompt contradiction validator for assembled image-generation prompts.

Detects semantic contradictions within a fully assembled prompt — cases where
the positive description and the negative constraints (or different sections of
the positive description) are mutually exclusive.

These checks are deterministic and do not require an LLM.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Semantic conflict groups
# Each entry is (positive_terms, negative_terms, conflict_label, same_word_required).
#
# same_word_required=True  — fires only when the matched positive word also appears
#   as a substring of the matched negative term.  Use for object-specific bans
#   where cross-synonym matches are false positives: "lamp" in positive + "torch"
#   in negative is NOT a contradiction (they are different objects).
#
# same_word_required=False — fires when ANY positive term matches AND ANY negative
#   term matches.  Use for blanket bans where any member of the positive group
#   contradicts any member of the negative group: "person" in positive + "no
#   character" in negative IS a contradiction regardless of exact word.
# ---------------------------------------------------------------------------

_POSITIVE_NEGATIVE_CONFLICT_GROUPS: list[tuple[frozenset[str], frozenset[str], str, bool]] = [
    (
        frozenset({"lamp", "lantern", "torch", "flame", "candle"}),
        frozenset({"lamp", "lantern", "torch", "candle"}),
        "LAMP_FLAME_CONFLICT",
        True,   # same_word_required: only fires when the SAME word appears in both
                # positive and negative.  lamp+torch does NOT fire (different objects).
    ),
    (
        frozenset({"human", "person", "traveler", "traveller", "sage", "man", "woman", "figure"}),
        frozenset({"no human", "no person", "no character", "no visible character"}),
        "HUMAN_PRESENCE_CONFLICT",
        False,  # blanket ban: any human term + "no character" is a conflict
    ),
    (
        frozenset({"eagle", "bird", "chick", "animal"}),
        frozenset({"no animal", "no bird", "no eagle"}),
        "ANIMAL_PRESENCE_CONFLICT",
        False,  # blanket ban: bird + "no animal" is a conflict
    ),
    (
        frozenset({"coin", "gold", "coins"}),
        frozenset({"coin", "gold", "coins"}),  # same words as pos_terms so intersection works
        "COIN_GOLD_CONFLICT",
        True,   # same_word_required: "gold" (golden light) + "coin" in NEGATIVE does NOT fire
    ),
    (
        frozenset({"house", "shelter", "building", "cottage"}),
        frozenset({"house", "shelter", "building", "cottage"}),  # same words
        "BUILDING_CONFLICT",
        True,   # same_word_required: shelter in positive + "house" in NEGATIVE does NOT fire
    ),
]


# Phrases that signal the positive description says "no character present"
_ENVIRONMENT_ONLY_MARKERS: frozenset[str] = frozenset({
    "no character present",
    "environment-only",
    "environment only",
    "no human figure",
    "no visible character",
    "character absent",
    "no character",
    "no human characters",
})

# Phrases that indicate a visible character in the scene (scene-specific, not style-language).
# Do NOT include generic style descriptors like "storybook character" or "illustrated character"
# — those appear in the STYLE block of every assembled prompt and are not character-presence signals.
_CHARACTER_PRESENCE_MARKERS: frozenset[str] = frozenset({
    "lean young man",
    "lean young woman",
    "kai:",
    "traveler:",
    "sage:",
    "young man",
    "young woman",
    "shown in strict",
    "back-facing",
    "standing beside",
    "seated beside",
    "walks along",
})

# Phrases indicating photorealistic character rendering (forbidden for illustrated style)
_PHOTOREALISTIC_CHARACTER_MARKERS: frozenset[str] = frozenset({
    "photorealistic human",
    "photorealistic character",
    "realistic human photo",
    "real photo person",
    "documentary-quality realism",  # OK for environment, NOT for character
})


def validate_prompt_contradictions(prompt: str, scene_idx: int) -> list[str]:
    """Check a fully assembled prompt for self-contradictions.

    Checks:
    A. "no character present" language coexisting with visible character descriptions.
    B. KAI: block coexisting with "no character present" language.
    C. Positive content names an object that the NEGATIVE section also prohibits.
    D. Photorealistic character language despite global illustrated-character constraint.

    Returns a list of human-readable error strings (empty = no contradictions found).
    Does not raise — safe to call on any prompt text.
    """
    if not prompt:
        return []

    errors: list[str] = []
    prompt_lower = prompt.lower()

    # Split into positive body vs. NEGATIVE section (if present)
    positive_body, negative_section = _split_positive_negative(prompt_lower)

    # ── Check A: "no character present" + visible character in positive body ──
    no_char_declared = any(m in positive_body for m in _ENVIRONMENT_ONLY_MARKERS)
    if no_char_declared:
        for char_marker in _CHARACTER_PRESENCE_MARKERS:
            if char_marker in positive_body:
                errors.append(
                    f"ERROR: Scene {scene_idx} declares 'no character present' but "
                    f"positive prompt contains character description: '{char_marker}'. "
                    "Remove the contradictory section or reclassify the scene."
                )
                break

    # ── Check B: KAI: block + "no character present" language ─────────────────
    has_kai_block = "kai:" in positive_body
    if has_kai_block and no_char_declared:
        errors.append(
            f"ERROR: Scene {scene_idx} has KAI: character reference block but also "
            "declares 'no character present'. KAI block must be removed for "
            "environment-only scenes."
        )

    # ── Check C: positive/negative object conflicts ────────────────────────────
    if negative_section:
        for pos_terms, neg_terms, label, same_word_required in _POSITIVE_NEGATIVE_CONFLICT_GROUPS:
            if same_word_required:
                # Fires only when a shared word (pos_terms ∩ neg_terms) appears in
                # BOTH the positive body AND the negative section.  This prevents
                # cross-synonym false positives: "lamp" in positive + "torch" in
                # NEGATIVE is not a contradiction (different objects).
                shared = pos_terms & neg_terms
                conflict_word = next(
                    (t for t in shared if t in positive_body and t in negative_section),
                    None,
                )
                if conflict_word:
                    errors.append(
                        f"ERROR: Scene {scene_idx} [{label}] — positive prompt contains "
                        f"'{conflict_word}' but NEGATIVE also prohibits '{conflict_word}'. "
                        "Either remove from NEGATIVE or remove from positive description."
                    )
            else:
                # Blanket ban: any positive term + any negative term is a conflict.
                pos_hit = next((t for t in pos_terms if t in positive_body), None)
                neg_hit = next((t for t in neg_terms if t in negative_section), None)
                if pos_hit and neg_hit:
                    errors.append(
                        f"ERROR: Scene {scene_idx} [{label}] — positive prompt contains "
                        f"'{pos_hit}' but NEGATIVE prohibits '{neg_hit}'. "
                        "Either remove from NEGATIVE or remove from positive description."
                    )

    # ── Check D: photorealistic character language ─────────────────────────────
    # The marker strings are specific enough ("photorealistic human",
    # "photorealistic character") that they always indicate a character render
    # style violation — no need to gate on other character presence markers.
    # "photorealistic environment" does NOT match these markers.
    for marker in _PHOTOREALISTIC_CHARACTER_MARKERS:
        if marker == "documentary-quality realism":
            continue
        if marker in positive_body:
            errors.append(
                f"WARNING: Scene {scene_idx} — positive prompt contains "
                f"photorealistic character language ('{marker}') despite "
                "global illustrated-character constraint."
            )
            break

    return errors


def check_positive_negative_conflicts(
    positive_content: str,
    negative_items: list[str],
    scene_idx: int = 0,
) -> list[str]:
    """Check whether any item in negative_items contradicts positive_content.

    Used by _assemble_export_prompt to filter safe negative constraints.

    Returns list of (item, reason) tuples for items that conflict.
    """
    if not positive_content or not negative_items:
        return []

    pos_lower = positive_content.lower()
    conflicts: list[str] = []

    for item in negative_items:
        item_lower = item.lower()
        # Check each significant word in the negative item
        words = [w for w in item_lower.split() if len(w) > 3]
        for word in words:
            if word in pos_lower:
                conflicts.append(
                    f"Scene {scene_idx}: forbidden_objects item '{item}' conflicts with "
                    f"positive content (word '{word}' appears in positive prompt)."
                )
                break

    return conflicts


def _split_positive_negative(prompt_lower: str) -> tuple[str, str]:
    """Split a prompt into (positive_body, negative_section).

    Looks for a 'NEGATIVE:' label. Returns (full_prompt, '') if no negative section found.
    """
    neg_idx = prompt_lower.find("\nnegative:")
    if neg_idx < 0:
        neg_idx = prompt_lower.find("negative:")
    if neg_idx < 0:
        return prompt_lower, ""
    return prompt_lower[:neg_idx], prompt_lower[neg_idx:]
