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
        # Physical — "face" and "portrait" appear as standalone words in prompts
        "face",
        "portrait",
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
