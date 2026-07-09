"""Clothing & Cultural Authenticity Policy for the Image Prompt Engine.

Enforces documentary-quality, respectful, culturally authentic clothing in every
visual prompt that involves a human subject.

Policy summary
──────────────
• Every human subject must wear contextually appropriate clothing.
• Violations (nudity, shirtless, bare-chested, revealing, sensationalized exposure)
  are detected and corrected by appending enforcement phrases.
• Authentic cultural/historical exceptions are recognised and allowed, but must
  still be depicted respectfully without sexualisation or exaggeration.
• Clothing is inferred from scene context when not explicitly specified.

Architecture
────────────
• detect_violation(prompt)        — True when the prompt contains a violation term
                                    without an authentic exception context.
• is_authentic_exception(prompt)  — True when the prompt's context justifies
                                    reduced/traditional clothing (sadhu, Jain monk,
                                    ancient ascetic, historical yogi, etc.).
• apply_clothing_policy(prompt, scene) — Main entry point.  Returns a (possibly
                                    modified) prompt and a ClothingPolicyResult.
• infer_clothing(scene)           — Infer appropriate clothing from scene context.
• get_negative_clothing_terms()   — Additional negative-prompt terms for providers
                                    that support negative prompts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── Violation terms ───────────────────────────────────────────────────────────
# Whole-word or phrase matches (checked case-insensitively).
# Ordered from most specific to least specific to avoid double-counting.

_VIOLATION_PHRASES: tuple[str, ...] = (
    # Explicit nudity
    "nude",
    "nudity",
    "naked",
    "unclothed",
    "undressed",
    "no clothing",
    "no clothes",
    "no shirt",
    "without clothes",
    "without clothing",
    # Bare torso / chest
    "shirtless",
    "bare-chested",
    "bare chested",
    "bare chest",
    "bare torso",
    "bare upper body",
    "bare upper-body",
    "topless",
    # Sexualisation
    "skimpy",
    "revealing clothing",
    "revealing outfit",
    "revealing attire",
    "sensual attire",
    "seductive clothing",
    "provocative clothing",
    "sensationalized",
    "sexualized",
    "body exposure",
)

# Compiled for fast matching — phrase or whole-word pattern.
_VIOLATION_RE: list[re.Pattern] = [
    re.compile(r"\b" + re.escape(v) + r"\b", re.IGNORECASE) for v in _VIOLATION_PHRASES
]


# ── Authentic exception contexts ──────────────────────────────────────────────
# When ANY of these phrases are present alongside a violation term, the scene
# is treated as a culturally/historically authentic exception.

_AUTHENTIC_EXCEPTION_TERMS: tuple[str, ...] = (
    # Hindu / Vedic ascetics
    "sadhu",
    "sadhus",
    "naga sadhu",
    "naga sadhus",
    "hindu monk",
    "hindu monks",
    "ancient sadhu",
    # Jain monks (Digambara tradition — sky-clad)
    "jain monk",
    "jain monks",
    "digambara",
    # Buddhist monks (robes — not bare, but partial traditional dress)
    "buddhist monk",
    "buddhist monks",
    "theravada monk",
    "zen monk",
    # Ancient ascetics and yogis
    "ancient ascetic",
    "ancient ascetics",
    "vedic ascetic",
    "yogi",
    "yogis",
    "ancient yogi",
    # Historical / indigenous
    "indigenous traditional",
    "ancient warrior",  # historical battle context
    "traditional indigenous",
    # Ayurvedic / historical medical
    "ancient bath",
    "historical bathing ritual",
)

_AUTHENTIC_EXCEPTION_RE: list[re.Pattern] = [
    re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE)
    for t in _AUTHENTIC_EXCEPTION_TERMS
]

# Enforcement phrase appended to authentic exceptions.
_EXCEPTION_RESPECTFUL_PHRASE = (
    ", depicted respectfully and with cultural dignity, "
    "no exaggerated musculature, no glamour posing, "
    "no sexualization, authentic historical accuracy"
)

# Marker used to detect if exception phrase is already in prompt.
_EXCEPTION_MARKER = "cultural dignity"


# ── Clothing-by-context inference ─────────────────────────────────────────────
# Keyed by context keyword (matched as substring in narration / scene title).
# Value is the clothing phrase injected when no explicit clothing is mentioned.

_CONTEXT_CLOTHING: list[tuple[tuple[str, ...], str]] = [
    # Ancient / historical Indian
    (
        (
            "sadhu",
            "ashram",
            "vedic",
            "ancient india",
            "ancient indian",
            "mahabharata",
            "ramayana",
            "gita",
            "brahmin",
            "vedantic",
            "rishikesh",
            "varanasi ghat",
            "river ghat",
        ),
        "simple traditional dhoti and angavastram, modest historical Indian attire",
    ),
    # Spiritual / temple / meditation (modern)
    (
        (
            "temple",
            "meditation",
            "spiritual",
            "mandir",
            "puja",
            "prayer",
            "bhakti",
            "devotee",
            "pilgrim",
        ),
        "simple modest traditional attire — kurta, dhoti, or regional devotional dress",
    ),
    # Yoga / wellness (modern)
    (
        ("yoga", "yogi", "pranayama", "breathing exercise", "mindfulness"),
        "simple modest yoga attire — loose cotton trousers and fitted top",
    ),
    # Office / professional
    (
        (
            "office",
            "boardroom",
            "meeting room",
            "corporate",
            "desk",
            "laptop",
            "conference",
            "workspace",
            "cubicle",
            "professional",
        ),
        "professional office attire — shirt, blazer, or formal business clothing",
    ),
    # Home / domestic
    (
        (
            "home",
            "apartment",
            "kitchen",
            "living room",
            "bedroom",
            "house",
            "dining room",
            "sofa",
            "couch",
        ),
        "casual everyday home clothing — t-shirt, jeans, or comfortable casual wear",
    ),
    # Park / outdoor casual
    (
        (
            "park",
            "garden",
            "trail",
            "hiking",
            "beach walk",
            "street",
            "market",
            "café",
            "coffee shop",
        ),
        "casual everyday outdoor clothing — t-shirt, jacket, or hoodie",
    ),
    # Historical India (Mughal, medieval)
    (
        (
            "mughal",
            "sultan",
            "maharaja",
            "rajput",
            "medieval india",
            "durbar",
            "court scene",
        ),
        "historically accurate Mughal-era or Rajput court attire — jama, angarkha, or period robes",
    ),
    # Ancient Greek
    (
        (
            "greek",
            "athens",
            "agora",
            "socrates",
            "plato",
            "aristotle",
            "greece",
            "hellenistic",
        ),
        "authentic ancient Greek attire — draped chiton and himation",
    ),
    # Buddhist / East Asian
    (
        (
            "buddhist",
            "buddha",
            "monastery",
            "zen",
            "daoist",
            "tao",
            "bamboo grove",
            "japanese temple",
            "chinese temple",
        ),
        "traditional Buddhist monk's robes — grey or saffron",
    ),
    # Medieval / historical Europe
    (
        (
            "medieval",
            "castle",
            "feudal",
            "knight",
            "monk medieval",
            "monastery medieval",
        ),
        "period-accurate medieval attire — wool tunic, cloak, or period clothing",
    ),
    # Sub-Saharan African
    (
        ("african village", "savannah village", "tribal", "traditional african"),
        "authentic traditional regional African attire and textiles",
    ),
]

# Fallback clothing phrase when no context keyword matches.
_DEFAULT_CLOTHING = (
    "contextually appropriate everyday clothing — "
    "t-shirt, shirt, kurta, or casual regional dress"
)


# ── Negative prompt additions ─────────────────────────────────────────────────

_CLOTHING_NEGATIVE_TERMS = (
    "nudity, nude, naked, shirtless, bare chest, bare torso, topless, "
    "revealing clothing, skimpy outfit, sexualized, sensationalized body, "
    "exposed skin, provocative attire"
)


# ── Result dataclass ──────────────────────────────────────────────────────────


@dataclass
class ClothingPolicyResult:
    """Outcome of applying the clothing policy to one prompt."""

    original_prompt: str
    final_prompt: str

    violation_found: bool = False
    is_exception: bool = False
    violation_terms: list[str] = field(default_factory=list)
    clothing_injected: str = ""
    action: str = "none"  # "none" | "enforced" | "exception_framed" | "clothing_added"


# ── Public API ────────────────────────────────────────────────────────────────


def detect_violation(prompt: str) -> list[str]:
    """Return list of violation terms found in *prompt* (empty = clean)."""
    found = []
    for term, pattern in zip(_VIOLATION_PHRASES, _VIOLATION_RE):
        if pattern.search(prompt):
            found.append(term)
    return found


def is_authentic_exception(prompt: str) -> bool:
    """True when *prompt* contains an authentic cultural/historical exception context."""
    for pattern in _AUTHENTIC_EXCEPTION_RE:
        if pattern.search(prompt):
            return True
    return False


def infer_clothing(scene: dict) -> str:
    """Infer appropriate clothing from scene title, narration, and visual_prompt."""
    combined = " ".join(
        [
            scene.get("title", ""),
            scene.get("narration", ""),
            scene.get("visual_prompt", ""),
        ]
    ).lower()

    for keywords, clothing in _CONTEXT_CLOTHING:
        if any(kw in combined for kw in keywords):
            return clothing

    return _DEFAULT_CLOTHING


def get_negative_clothing_terms() -> str:
    """Return negative prompt terms that prevent inappropriate clothing generation."""
    return _CLOTHING_NEGATIVE_TERMS


def apply_clothing_policy(
    prompt: str, scene: dict | None = None
) -> ClothingPolicyResult:
    """
    Apply the clothing & cultural authenticity policy to one visual prompt.

    Decision tree:
      1. No human in prompt → return unchanged (policy only applies to humans).
      2. Violation terms found AND authentic exception context present
             → frame respectfully, do not block.
      3. Violation terms found AND no exception context
             → append clothing enforcement phrase.
      4. No violation found, human present, no clothing context mentioned
             → append inferred appropriate clothing hint.
      5. No violation, no human → pass through unchanged.

    Returns ClothingPolicyResult with the (possibly modified) final_prompt.
    """
    from ytfactory.images.human_detector import detect_human_presence

    result = ClothingPolicyResult(original_prompt=prompt, final_prompt=prompt)

    # Policy applies to human scenes.  Exception subjects (sadhu, yogi, monk, etc.)
    # are always human even if not in the standard human-indicator list.
    if not detect_human_presence(prompt) and not is_authentic_exception(prompt):
        return result  # policy only applies to human scenes

    violations = detect_violation(prompt)
    exception = is_authentic_exception(prompt)

    if violations and exception:
        # Authentic exception — allow but enforce respectful framing
        result.violation_found = True
        result.is_exception = True
        result.violation_terms = violations
        result.action = "exception_framed"
        if _EXCEPTION_MARKER not in prompt.lower():
            result.final_prompt = prompt + _EXCEPTION_RESPECTFUL_PHRASE
            result.clothing_injected = _EXCEPTION_RESPECTFUL_PHRASE.strip(", ")
        return result

    if violations and not exception:
        # Violation without exception — enforce appropriate clothing
        clothing = infer_clothing(scene or {})
        enforcement = (
            f", wearing {clothing}, "
            "no bare torso, no nudity, no revealing clothing, "
            "clothing appropriate to the cultural and narrative context"
        )
        result.violation_found = True
        result.is_exception = False
        result.violation_terms = violations
        result.action = "enforced"
        result.clothing_injected = clothing
        result.final_prompt = prompt + enforcement
        return result

    # No violation — check if clothing context is present for human scenes.
    # If not mentioned at all, add a gentle inference hint.
    clothing_mentioned = _clothing_context_present(prompt)
    if not clothing_mentioned:
        clothing = infer_clothing(scene or {})
        hint = f", {clothing}"
        result.action = "clothing_added"
        result.clothing_injected = clothing
        result.final_prompt = prompt + hint
    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

# Keywords that indicate clothing is already described in the prompt.
_CLOTHING_INDICATORS: tuple[str, ...] = (
    "shirt",
    "kurta",
    "dhoti",
    "robe",
    "attire",
    "clothing",
    "dress",
    "jacket",
    "sweater",
    "hoodie",
    "suit",
    "blazer",
    "tunic",
    "gown",
    "cloak",
    "sari",
    "saree",
    "salwar",
    "jeans",
    "trouser",
    "pants",
    "coat",
    "uniform",
    "turban",
    "armour",
    "armor",
    "angavastram",
    "chiton",
    "himation",
    "jama",
    "angarkha",
    "traditional wear",
    "traditional dress",
    "traditional attire",
    "period attire",
    "traditional clothing",
    "modest attire",
    "casual wear",
    "everyday wear",
)


def _clothing_context_present(prompt: str) -> bool:
    """True when the prompt already mentions clothing."""
    p_lower = prompt.lower()
    return any(kw in p_lower for kw in _CLOTHING_INDICATORS)
