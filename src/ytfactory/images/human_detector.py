"""Human subject detection and quality reinforcement for the Image Prompt Engine.

Detects human presence in visual prompts and enforces three quality behaviours:

  1. Prompt reinforcement — appends quality markers (face detail, eyes, posture…)
     whenever a human is present so the image generator produces documentary-quality
     results rather than blurry or anatomy-distorted figures.

  2. Subject Dominance Rule — for wide/establishing/drone shots that contain a human,
     appends a sentence that keeps the person visually prominent despite the wide
     environment.

  3. Image sharpness estimation — uses Pillow (no numpy) to compute a sharpness score
     via edge-detection variance.  Used by ImagePipeline to decide whether to
     regenerate a scene that failed human quality standards.
"""

from __future__ import annotations

import re
from pathlib import Path

# Words that strongly signal a human is the subject of the scene.
# All entries use whole-word regex matching (\bINDICATOR\b) to avoid false
# positives (e.g. "surface" must not match "face", "natural human anatomy"
# must not match "man" or "human").
# NOTE: "human" is intentionally excluded because the anatomy reinforcement
# phrase "natural human anatomy" would otherwise cause false positives.
_HUMAN_INDICATORS: frozenset[str] = frozenset(
    {
        # Demographic
        "man",
        "woman",
        "person",
        "people",
        "child",
        "children",
        "boy",
        "girl",
        "elder",
        "baby",
        # Occupational / role
        "monk",
        "warrior",
        "farmer",
        "leader",
        "soldier",
        "scholar",
        "ruler",
        "priest",
        "guru",
        "sage",
        "philosopher",
        "king",
        "queen",
        "emperor",
        "mother",
        "father",
        "villager",
        "peasant",
        "merchant",
        "artisan",
        # Physical — body parts that commonly appear alone in prompts and
        # are frequent sources of AI anatomy glitches (fingers, hands, feet)
        "face",
        "portrait",
        "hand",
        "hands",
        "finger",
        "fingers",
        "palm",
        "fist",
        "feet",
        "foot",
        "arm",
        "arms",
        "body",
        # Social
        "crowd",
        "audience",
    }
)

# Exact sub-phrases from _HUMAN_QUALITY_PHRASE.  Chosen so none is a substring
# of another, which prevents over-counting (e.g. "facial expression" vs
# "natural facial expression").
# `has_human_quality_reinforcement()` requires ≥ 2 of these to return True.
_HUMAN_QUALITY_MARKERS: frozenset[str] = frozenset(
    {
        "highly detailed human face",
        "natural facial expression",
        "realistic eyes",
        "authentic skin texture",
        "natural posture",
        "seamless integration with the environment",
        "documentary-quality realism",
    }
)

# Phrase appended to the positive prompt for every human scene.
_HUMAN_QUALITY_PHRASE = (
    ", highly detailed human face, natural facial expression, realistic eyes, "
    "authentic skin texture, natural posture, seamless integration with the environment, "
    "documentary-quality realism"
)

# Shot types (lower-case, must match values in shot_planner.SHOT_TYPES) that
# represent wide-angle framings where the Subject Dominance Rule applies.
_WIDE_SHOT_TYPES: frozenset[str] = frozenset(
    {
        "wide shot",
        "establishing shot",
        "drone",
        "wide cinematic",
        "high angle",
    }
)

# Phrase appended when a human appears in a wide-angle shot.
_SUBJECT_DOMINANCE_PHRASE = (
    ", subject remains visually prominent and detailed despite wide framing"
)

# ── Targeted anatomy constraints ───────────────────────────────────────────────
# Applied when the prompt explicitly mentions a specific body part — more precise
# than the generic _ANATOMY_REINFORCEMENT in prompt_engine.py.

_HAND_KEYWORDS: frozenset[str] = frozenset({"hand", "hands", "finger", "fingers", "palm", "fist"})
_FOOT_KEYWORDS: frozenset[str] = frozenset({"feet", "foot", "toe", "toes"})
_FACE_KEYWORDS: frozenset[str] = frozenset({"face", "faces", "portrait", "expression", "eyes", "lips", "mouth"})

_HAND_ANATOMY_PHRASE = (
    ", exactly five anatomically correct fingers on each visible hand, "
    "realistic knuckle structure, natural finger spacing, thumb correctly positioned on one side, "
    "no extra, missing, or merged digits"
)
_FOOT_ANATOMY_PHRASE = (
    ", exactly five toes per visible foot, natural foot arch and proportions, "
    "realistic heel and ankle, no extra or fused toes"
)
_FACE_ANATOMY_PHRASE = (
    ", natural facial symmetry, correctly placed eyes and ears, realistic nose bridge, "
    "no distorted or duplicated facial features"
)

# Sentinel substrings used by has_anatomy_constraints() to avoid double-appending.
_HAND_ANATOMY_SENTINEL = "exactly five anatomically correct fingers"
_FOOT_ANATOMY_SENTINEL = "exactly five toes per visible foot"
_FACE_ANATOMY_SENTINEL = "natural facial symmetry"


def add_anatomy_constraints(prompt: str) -> str:
    """Append targeted anatomy constraints based on body parts mentioned in the prompt.

    Called during prompt enrichment so the image model receives precise guidance
    before generation — complementing the post-generation vision review layer.
    Only appends each constraint once (idempotent).
    """
    lower = prompt.lower()

    if any(kw in lower for kw in _HAND_KEYWORDS) and _HAND_ANATOMY_SENTINEL not in prompt:
        prompt += _HAND_ANATOMY_PHRASE

    if any(kw in lower for kw in _FOOT_KEYWORDS) and _FOOT_ANATOMY_SENTINEL not in prompt:
        prompt += _FOOT_ANATOMY_PHRASE

    if any(kw in lower for kw in _FACE_KEYWORDS) and _FACE_ANATOMY_SENTINEL not in prompt:
        prompt += _FACE_ANATOMY_PHRASE

    return prompt


def detect_human_presence(prompt: str) -> bool:
    """Return True when *prompt* describes a scene that contains a human subject.

    Uses whole-word regex for every indicator so compound words do not produce
    false positives (e.g. "surface" ≠ "face", "natural human anatomy" ≠ "man").
    """
    p_lower = prompt.lower()
    for indicator in _HUMAN_INDICATORS:
        if re.search(r"\b" + re.escape(indicator) + r"\b", p_lower):
            return True
    return False


def has_human_quality_reinforcement(prompt: str) -> bool:
    """Return True when *prompt* already contains at least 2 quality markers."""
    p_lower = prompt.lower()
    count = sum(1 for m in _HUMAN_QUALITY_MARKERS if m in p_lower)
    return count >= 2


def add_human_quality_reinforcement(prompt: str) -> str:
    """Append human quality markers to *prompt* unless already present."""
    if has_human_quality_reinforcement(prompt):
        return prompt
    return prompt + _HUMAN_QUALITY_PHRASE


def apply_subject_dominance_rule(prompt: str, shot_type: str = "") -> str:
    """Append a subject-prominence hint when the scene is a wide shot with a human.

    Appended only when ALL three conditions hold:
      - A human is detected in *prompt*
      - *shot_type* is a wide/establishing/drone variant
      - The hint is not already present in the prompt
    """
    if not detect_human_presence(prompt):
        return prompt
    if shot_type.lower().strip() not in _WIDE_SHOT_TYPES:
        return prompt
    hint = _SUBJECT_DOMINANCE_PHRASE.lstrip(", ")
    if hint in prompt:
        return prompt
    return prompt + _SUBJECT_DOMINANCE_PHRASE


def compute_sharpness(image_path: Path) -> float:
    """Estimate image sharpness using edge-detection variance.

    Downsamples to 512 × 288 before analysis so runtime is constant regardless
    of source resolution.  Returns 0.0 on any error (missing file, corrupt
    image, Pillow not installed).

    Score interpretation:
      < 8   — visibly blurry; likely blurry face or low-detail figure
      8–15  — marginal; may be acceptable depending on scene content
      > 15  — sharp; documentary-quality detail
    """
    try:
        from PIL import Image, ImageFilter, ImageStat

        img = Image.open(image_path).convert("L").resize((512, 288))
        edges = img.filter(ImageFilter.FIND_EDGES)
        return ImageStat.Stat(edges).stddev[0]
    except Exception:
        return 0.0
