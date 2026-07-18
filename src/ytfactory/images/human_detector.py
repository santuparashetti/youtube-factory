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

# ── Subject Criticality (ADR-0013) ─────────────────────────────────────────────
# When a prompt's PRIMARY storytelling subject is one of these critical body-part
# types, the image must pass a Subject Specialist Review in addition to the overall
# vision review.  Priority order (most defect-prone first) determines which type
# is returned when multiple keywords are present.

_CRITICAL_SUBJECT_KEYWORDS: dict[str, frozenset[str]] = {
    "hand": frozenset({"hand", "hands", "finger", "fingers", "palm", "fist", "knuckle", "grip"}),
    "gesture": frozenset({"gesture", "gestures", "reaching", "pointing", "outstretched", "clasped"}),
    "face": frozenset({"face", "faces", "portrait", "expression", "lips", "mouth"}),
    "eye": frozenset({"eye", "eyes", "gaze", "stare"}),
    "body": frozenset({"body", "figure", "torso", "silhouette"}),
}

# Specialist review context strings — passed as visual_prompt to the vision model
# for the second, focused review pass.  Each checklist maps directly to the
# Subject Criticality Rule checklist in ADR-0013.
_SPECIALIST_CONTEXT: dict[str, str] = {
    "hand": (
        "SUBJECT SPECIALIST REVIEW — Human hand anatomy (ADR-0013).\n"
        "Inspect the hand(s) against every item below. Any failure = FAIL.\n"
        "1. Exactly five fingers (unless intentionally hidden behind another surface)\n"
        "2. Natural thumb attachment on the correct lateral side of the palm\n"
        "3. Correct palm proportions — not too wide, too narrow, or disproportionate\n"
        "4. Natural wrist transition — no abrupt seam or anatomical break\n"
        "5. Correct finger joint placement — three joints per finger, two per thumb\n"
        "6. No fused fingers — every digit is individually distinct\n"
        "7. No duplicated fingers — total count is exactly five\n"
        "8. No stretched, melted, or otherwise distorted anatomy anywhere on the hand\n"
        "9. Natural pose — resting or active but within the human range of motion\n"
        "10. Photorealistic skin texture — visible knuckle creases, natural color gradient"
    ),
    "gesture": (
        "SUBJECT SPECIALIST REVIEW — Human gesture / hand anatomy (ADR-0013).\n"
        "A gesture scene requires correct hand anatomy. Inspect against every item.\n"
        "1. Exactly five fingers visible, or consistently hidden behind another surface\n"
        "2. Natural thumb attachment — on the correct lateral side of the palm\n"
        "3. No fused or duplicated fingers\n"
        "4. Natural wrist and forearm alignment consistent with the gesture direction\n"
        "5. Gesture falls within the natural human range of motion — no impossible angles\n"
        "6. No stretched or melted anatomy anywhere on the hand or wrist"
    ),
    "face": (
        "SUBJECT SPECIALIST REVIEW — Human face anatomy (ADR-0013).\n"
        "Inspect the face against every item below. Any failure = FAIL.\n"
        "1. Natural bilateral facial symmetry — eyes, ears, and nose correctly placed\n"
        "2. Exactly two eyes — no missing, extra, or asymmetrically-sized eyes\n"
        "3. Realistic iris and pupil — no distorted shape or unnatural color\n"
        "4. Natural nose structure — correct bridge height, no melted or misplaced nostrils\n"
        "5. Mouth and lips correctly shaped — no fused lips, no impossible tooth rows\n"
        "6. Natural skin texture — no patchwork blending, smoothing artifacts, or seams\n"
        "7. No duplicated or extra facial features anywhere on the face"
    ),
    "eye": (
        "SUBJECT SPECIALIST REVIEW — Human eye anatomy (ADR-0013).\n"
        "Inspect the eye(s) against every item below. Any failure = FAIL.\n"
        "1. Exactly two eyes visible (unless clearly a single-eye close-up shot)\n"
        "2. Realistic iris with natural color variation and limbal ring\n"
        "3. Correct pupil — circular in normal light, not distorted or rectangular\n"
        "4. Natural sclera (white) — no unnatural coloring, veining is acceptable\n"
        "5. Natural eyelid and lash rendering — no melted lids or missing lashes\n"
        "6. No melted, missing, or extra eye structures anywhere in the frame"
    ),
    "body": (
        "SUBJECT SPECIALIST REVIEW — Human body anatomy (ADR-0013).\n"
        "Inspect the full body against every item below. Any failure = FAIL.\n"
        "1. Correct head-to-body proportions — realistic for the depicted age/build\n"
        "2. Natural limb attachment — no floating, disconnected, or phasing limbs\n"
        "3. Natural posture — no impossible joint angles or contorted positions\n"
        "4. Consistent clothing where present — no clipping or phasing through the body\n"
        "5. No extra or missing limbs"
    ),
}


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


def detect_critical_subject(prompt: str) -> str | None:
    """Return the primary critical subject type found in *prompt*, or None.

    Critical subjects (ADR-0013): hand, gesture, face, eye, body.
    Returns the first matching type in priority order (most defect-prone first)
    so that when multiple keywords are present the highest-risk subject drives
    the specialist review.
    """
    lower = prompt.lower()
    for subject_type, keywords in _CRITICAL_SUBJECT_KEYWORDS.items():
        if any(re.search(r"\b" + re.escape(kw) + r"\b", lower) for kw in keywords):
            return subject_type
    return None


def build_specialist_context(subject: str) -> str:
    """Return the specialist review checklist context string for *subject*.

    The returned string is prepended to the original visual prompt and passed
    as *visual_prompt* to the VisionProvider for the specialist review call.
    Returns an empty string for unknown subject types.
    """
    return _SPECIALIST_CONTEXT.get(subject, "")


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


# ── Hand avoidance (composition-level) ───────────────────────────────────────

_INTENTIONAL_HAND_PHRASES: frozenset[str] = frozenset({
    "mudra", "namaste", "anjali", "ashirvad", "abhaya", "varada", "pranam",
    "blessing", "consecrate", "anoint", "laying hands", "healing touch",
    "prasad", "diya", "pouring water", "pouring milk", "offering flowers",
    "writing with", "inscribing", "folded hands", "clasped hands",
    "hands joined", "praying hands", "open palms", "outstretched hand",
    "holding a lamp", "holding a torch", "holding a bowl", "sacred gesture",
})

_HAND_AVOIDANCE_SENTINEL = "hands out of frame"

_HAND_AVOIDANCE_PHRASE = (
    ", compose to keep hands out of frame, prefer figure from behind or in profile, "
    "wide-angle framing where hands fall naturally outside view, "
    "hands occluded by clothing folds, robe, or held object"
)


def has_intentional_hands(narration: str) -> bool:
    """True when the narration requires visible hands as a storytelling element."""
    text = narration.lower()
    return any(phrase in text for phrase in _INTENTIONAL_HAND_PHRASES)


def add_hand_avoidance_composition(prompt: str) -> str:
    """Append hand-avoidance framing guidance to *prompt* (idempotent)."""
    if _HAND_AVOIDANCE_SENTINEL not in prompt:
        prompt += _HAND_AVOIDANCE_PHRASE
    return prompt


# ── Back/profile-view hand orientation (intentional-hands exception) ──────────
# When a scene composition is back-view or profile-view AND hands are narratively
# required, visible hand/wrist joints must be rendered with correct rotation for
# that camera angle.  QA cannot reliably catch orientation mismatches, so the
# correction lives here at prompt-generation time.

_BACK_PROFILE_KEYWORDS: frozenset[str] = frozenset({
    "from behind", "seen from behind", "figure from behind", "viewed from behind",
    "back view", "back-view", "from the back",
    "from the side", "seen from the side",
    "profile view", "shot in profile", "in profile",
    "rear view", "from the rear",
    "over-the-shoulder",
})

_ORIENTATION_SENTINEL = "wrist rotation consistent"

_BACK_VIEW_ORIENTATION_PHRASE = (
    ", hand and wrist rotation consistent with camera angle "
    "(back-view or profile-view — avoid front-facing palm orientation), "
    "arm reaches naturally as seen from behind or from the side, "
    "joint angles follow the body's direction away from camera"
)


def is_back_or_profile_view(prompt: str) -> bool:
    """True when the prompt specifies a back-view or profile-view composition."""
    lower = prompt.lower()
    return any(kw in lower for kw in _BACK_PROFILE_KEYWORDS)


def add_back_view_hand_orientation(prompt: str) -> str:
    """Append wrist/hand orientation guidance for back- or profile-view scenes (idempotent)."""
    if _ORIENTATION_SENTINEL not in prompt:
        prompt += _BACK_VIEW_ORIENTATION_PHRASE
    return prompt
