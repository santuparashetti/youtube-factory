"""Normalization utilities for continuity enforcement.

Time, location, entity, and state label normalization.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Time normalization
# ---------------------------------------------------------------------------

_TIME_ORDER: list[str] = [
    "SUNRISE",
    "MORNING",
    "MIDDAY",
    "AFTERNOON",
    "SUNSET",
    "DUSK",
    "NIGHT",
    "DEEP_NIGHT",
]

_TIME_ALIASES: dict[str, str] = {
    "dawn": "SUNRISE",
    "early morning": "MORNING",
    "noon": "MIDDAY",
    "midday": "MIDDAY",
    "after noon": "AFTERNOON",
    "late afternoon": "AFTERNOON",
    "golden hour": "SUNSET",
    "twilight": "DUSK",
    "dusk": "DUSK",
    "evening": "DUSK",
    "night": "NIGHT",
    "midnight": "DEEP_NIGHT",
    "late night": "DEEP_NIGHT",
    "deep night": "DEEP_NIGHT",
    "pitch black": "DEEP_NIGHT",
    "darkness": "DEEP_NIGHT",
    "dark": "DEEP_NIGHT",
    "full dark": "DEEP_NIGHT",
}

_TIME_JUMP_PATTERNS: list[str] = [
    r"\bnext day\b",
    r"\bfollowing morning\b",
    r"\bat sunrise\b",
    r"\bthe next morning\b",
    r"\bthe following day\b",
    r"\bthe next day\b",
    r"\bdaybreak\b",
    r"\bthe dawn\b",
    r"\bhours passed\b",
    r"\bpassed hours\b",
    r"\bnight fell\b",
    r"\bnight came\b",
    r"\bdarkness fell\b",
    r"\bdays? later\b",
    r"\bweeks? later\b",
    r"\bmonths? later\b",
    r"\byears? later\b",
    r"\btime passed\b",
    r"\btime jump\b",
    r"\btransition\b",
    r"\bthe sun rose\b",
    r"\bthe sun set\b",
    r"\bsunrise\b",
    r"\bsunset\b",
]


def normalize_time(label: str) -> str:
    """Normalize a free-form time-of-day string to a canonical label."""
    cleaned = label.strip()
    # Normalize separators so "deep_night" matches "deep night"
    lower = cleaned.lower().replace("_", " ")
    if lower in _TIME_ALIASES:
        return _TIME_ALIASES[lower]
    # Sort aliases by length descending so more specific matches take precedence
    for alias, canonical in sorted(_TIME_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if alias in lower:
            return canonical
    return cleaned.upper()


def time_progression_allowed(
    previous: str,
    proposed: str,
    narration: str = "",
) -> tuple[bool, str]:
    """Return (allowed, reason) for a proposed time transition.

    Allows forward progression within the day and explicit time jumps.
    Rejects obvious reversals without narrative support.
    """
    prev_norm = normalize_time(previous) if previous else ""
    prop_norm = normalize_time(proposed) if proposed else ""
    if not prev_norm or not prop_norm:
        return True, ""
    if prev_norm == prop_norm:
        return True, ""
    try:
        prev_idx = _TIME_ORDER.index(prev_norm)
        prop_idx = _TIME_ORDER.index(prop_norm)
    except ValueError:
        return True, ""
    if prop_idx > prev_idx:
        return True, ""
    if prop_idx < prev_idx:
        if narration:
            lower_nar = narration.lower()
            for pat in _TIME_JUMP_PATTERNS:
                if re.search(pat, lower_nar):
                    return True, ""
        return (
            False,
            f"Time reversed from {prev_norm} to {prop_norm} without explicit time-jump narration.",
        )
    return True, ""


def detect_time_jump(narration: str) -> bool:
    """True if narration explicitly describes a time transition."""
    lower = narration.lower()
    return any(re.search(pat, lower) for pat in _TIME_JUMP_PATTERNS)


# ---------------------------------------------------------------------------
# Location normalization
# ---------------------------------------------------------------------------

_LOCATION_NORMALIZATION: dict[str, str] = {
    "forest path": "forest_path",
    "forest clearing": "forest_clearing",
    "forest root bend": "forest_root_bend",
    "hermitage threshold": "hermitage_threshold",
    "rock shelter": "rock_shelter",
    "rock shelter cave": "rock_shelter",
    "cave entrance": "cave_entrance",
    "cave interior": "cave_interior",
    "mountain path": "mountain_path",
    "mountain peak": "mountain_peak",
    "mountain summit": "mountain_peak",
    "river bank": "river_bank",
    "riverbank": "river_bank",
    "river shore": "river_bank",
    "temple entrance": "temple_entrance",
    "temple interior": "temple_interior",
    "palace gate": "palace_gate",
    "palace interior": "palace_interior",
    "throne room": "throne_room",
    "village square": "village_square",
    "village center": "village_square",
    "city street": "city_street",
    "city gate": "city_gate",
    "city square": "city_square",
}


def normalize_location(label: str) -> str:
    """Normalize a location description to a canonical slug."""
    cleaned = label.strip().lower()
    if cleaned in _LOCATION_NORMALIZATION:
        return _LOCATION_NORMALIZATION[cleaned]
    return re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")


# ---------------------------------------------------------------------------
# Entity / canonical ID normalization
# ---------------------------------------------------------------------------

_ENTITY_ALIASES: dict[str, str] = {
    "the traveler": "traveler",
    "traveler": "traveler",
    "the old sage": "old_sage",
    "old sage": "old_sage",
    "sage": "old_sage",
    "the mentor": "mentor",
    "mentor": "mentor",
    "the antagonist": "antagonist",
    "antagonist": "antagonist",
    "the hero": "hero",
    "hero": "hero",
    "the heroine": "heroine",
    "heroine": "heroine",
    "the king": "king",
    "king": "king",
    "the queen": "queen",
    "queen": "queen",
    "the monk": "monk",
    "monk": "monk",
    "the warrior": "warrior",
    "warrior": "warrior",
    "the merchant": "merchant",
    "merchant": "merchant",
    "the guard": "guard",
    "guard": "guard",
    "the princess": "princess",
    "princess": "princess",
    "the child": "child",
    "child": "child",
    "the boy": "boy",
    "boy": "boy",
    "the girl": "girl",
    "girl": "girl",
    "the man": "man",
    "man": "man",
    "the woman": "woman",
    "woman": "woman",
    "the elder": "elder",
    "elder": "elder",
    "the teacher": "teacher",
    "teacher": "teacher",
    "the student": "student",
    "student": "student",
    "the father": "father",
    "father": "father",
    "the mother": "mother",
    "mother": "mother",
}


def canonical_entity_id(name: str) -> str:
    """Normalize a character name to a canonical ID slug."""
    cleaned = name.strip().lower()
    if cleaned in _ENTITY_ALIASES:
        return _ENTITY_ALIASES[cleaned]
    return re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")


def resolve_entity_name(name: str, known_ids: set[str]) -> str | None:
    """Resolve a name token to a known canonical ID, or None if not matched."""
    cid = canonical_entity_id(name)
    if cid in known_ids:
        return cid
    for known in known_ids:
        if known == cid or known.endswith(cid) or cid.endswith(known):
            return known
    return None


# ---------------------------------------------------------------------------
# State vocabulary normalization
# ---------------------------------------------------------------------------

_LIT_FAMILY = frozenset({"lit", "on", "burning", "glowing", "illuminated", "aflame", "lit_up", "lighted"})
_UNLIT_FAMILY = frozenset({"unlit", "off", "extinguished", "dark", "dead", "cold", "dim", "unlit"})
_FULL_FAMILY = frozenset({"full", "filled", "replenished", "refilled"})
_EMPTY_FAMILY = frozenset({"empty", "spent", "depleted", "exhausted", "drained", "used_up", "gone"})
_OPEN_FAMILY = frozenset({"open", "opened", "unsealed", "unlocked"})
_CLOSED_FAMILY = frozenset({"closed", "shut", "sealed", "locked"})
_DESTROYED_FAMILY = frozenset({"destroyed", "broken", "shattered", "ruined", "demolished"})
_BURIED_FAMILY = frozenset({"buried", "entombed", "interred", "underground"})
_CONSUMED_FAMILY = frozenset({"consumed", "eaten", "devoured", "swallowed"})
_LOST_FAMILY = frozenset({"lost", "missing", "gone", "vanished", "nowhere_to_be_found"})
_EXHAUSTED_FAMILY = frozenset({"exhausted", "depleted", "used_up", "spent", "drained"})

_STATE_FAMILIES: dict[str, frozenset[str]] = {
    "lit": _LIT_FAMILY,
    "unlit": _UNLIT_FAMILY,
    "full": _FULL_FAMILY,
    "empty": _EMPTY_FAMILY,
    "open": _OPEN_FAMILY,
    "closed": _CLOSED_FAMILY,
    "destroyed": _DESTROYED_FAMILY,
    "buried": _BURIED_FAMILY,
    "consumed": _CONSUMED_FAMILY,
    "lost": _LOST_FAMILY,
    "exhausted": _EXHAUSTED_FAMILY,
}

_TERMINAL_STATES: frozenset[str] = frozenset({
    "destroyed", "buried", "consumed", "lost", "exhausted",
    "closed", "dead", "dead_repr", "closed_permanently",
})


def normalize_state(state: str) -> str:
    """Normalize a state string to its canonical family name."""
    lower = state.lower().strip()
    for canonical, family in _STATE_FAMILIES.items():
        if lower in family:
            return canonical
    return lower


def is_terminal_state(state: str) -> bool:
    """True if the state is a terminal state that cannot be reverted."""
    norm = normalize_state(state)
    return norm in _TERMINAL_STATES


def state_family(state: str) -> str:
    """Return the canonical family name for a state string."""
    return normalize_state(state)


# ---------------------------------------------------------------------------
# Transfer language detection
# ---------------------------------------------------------------------------

_TRANSFER_PATTERNS: list[str] = [
    r"\bgives?\b",
    r"\bhands?\b",
    r"\bhands?\s+over\b",
    r"\bhands?\s+to\b",
    r"\breceives?\b",
    r"\btakes?\b",
    r"\bpicks?\s+up\b",
    r"\bputs?\s+down\b",
    r"\bdrops?\b",
    r"\bleaves?\b",
    r"\bcarries?\s+away\b",
    r"\btransfers?\b",
    r"\bpasses?\b",
    r"\bpasses?\s+to\b",
    r"\bgifted\b",
    r"\bhanded\b",
    r"\bgave\b",
    r"\bgranted\b",
    r"\bentrusted\b",
    r"\bplaced\s+in\b",
    r"\bplaced\s+into\b",
    r"\bslips?\s+into\b",
    r"\bslides?\s+into\b",
    r"\btucked\s+into\b",
    r"\bwrapped\s+around\b",
]


def detect_transfer_language(narration: str) -> bool:
    """True if narration contains explicit object transfer language."""
    lower = narration.lower()
    return any(re.search(pat, lower) for pat in _TRANSFER_PATTERNS)


def extract_transfer_target(narration: str, object_name: str) -> str | None:
    """Extract the character receiving an object from narration text.

    Returns canonical_id of the receiving character, or None.
    """
    lower = narration.lower()
    obj_lower = object_name.lower()
    # Try full name first, then progressively shorter tokens
    name_tokens = [t for t in obj_lower.split() if len(t) > 2]
    for token in name_tokens:
        for pat in [
            rf"\bgives?\b\s+(?:the\s+)?{re.escape(token)}\s+to\s+(?:the\s+)?(\w+)",
            rf"\bhands?\b\s+(?:the\s+)?{re.escape(token)}\s+to\s+(?:the\s+)?(\w+)",
            rf"\bhands?\b\s+(?:the\s+)?(\w+)\s+(?:the\s+)?{re.escape(token)}",
            rf"\bgives?\b\s+(?:the\s+)?(\w+)\s+(?:the\s+)?{re.escape(token)}",
            rf"\bpasses?\b\s+(?:the\s+)?{re.escape(token)}\s+to\s+(?:the\s+)?(\w+)",
            rf"\bpasses?\b\s+(?:the\s+)?(\w+)\s+(?:the\s+)?{re.escape(token)}",
            rf"\bgives?\b\s+(?:the\s+)?(\w+)\s+(?:the\s+)?{re.escape(token)}",
        ]:
            m = re.search(pat, lower)
            if m:
                return canonical_entity_id(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Lighting derivation
# ---------------------------------------------------------------------------

_LIGHTING_BY_TIME: dict[str, str] = {
    "SUNRISE": "soft golden sunrise light",
    "MORNING": "bright morning daylight",
    "MIDDAY": "bright overhead midday sun",
    "AFTERNOON": "warm afternoon sunlight",
    "SUNSET": "golden hour sunset light",
    "DUSK": "soft blue dusk light",
    "NIGHT": "dark night, moonlight or starlight",
    "DEEP_NIGHT": "pitch black deep night, minimal ambient light",
}


def derive_lighting(time_of_day: str, practical_lights: list[str] | None = None) -> str:
    """Derive a lighting description from time_of_day + practical lights."""
    practical = practical_lights or []
    base = _LIGHTING_BY_TIME.get(normalize_time(time_of_day).upper(), "natural lighting")
    if not practical:
        return base
    light_descriptors = []
    for light in practical:
        lower = light.lower()
        if "lamp" in lower or "oil" in lower:
            light_descriptors.append("oil lamp flame")
        elif "candle" in lower:
            light_descriptors.append("candle flame")
        elif "fire" in lower or "hearth" in lower:
            light_descriptors.append("firelight")
        elif "torch" in lower:
            light_descriptors.append("torch light")
        else:
            light_descriptors.append(light)
    return f"{base}, with {' and '.join(light_descriptors)} providing warm practical light"
