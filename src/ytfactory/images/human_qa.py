"""Human Subject QA Gate — ADR-0015.

Staged QA pipeline for human subjects in generated images:
  Stage 1: Human QA          — anatomy, body parts, age/gender/ethnicity/emotion, crop
  Stage 2: Hand QA           — finger count, fused/missing fingers, thumb, palm, wrist, joints
  Stage 3: Clothing QA       — verify specified clothing appears in image (if applicable)
  Stage 4: Prompt Compliance — verify subject, clothing, pose, camera, environment, emotion, props

The gate is only triggered when the human is the primary storytelling subject
(close/medium shot type, or a critical body-part subject detected).
"""

from __future__ import annotations

from .human_detector import detect_critical_subject

# Shot types where the human occupies >20% of the frame (close/medium proximity).
_CLOSE_SHOT_TYPES = frozenset(
    {
        "close-up",
        "closeup",
        "close up",
        "extreme close-up",
        "portrait",
        "bust shot",
        "head shot",
        "face shot",
        "medium shot",
        "medium close-up",
        "over the shoulder",
        "two shot",
    }
)

# Trigger verbs/prepositions that introduce clothing descriptions.
_CLOTHING_TRIGGERS = (
    "wearing",
    "dressed in",
    "clothed in",
)

# Clothing nouns used to confirm a trigger refers to clothing.
_CLOTHING_ITEMS = (
    "shirt",
    "jacket",
    "coat",
    "dress",
    "saree",
    "sari",
    "kurta",
    "dhoti",
    "turban",
    "uniform",
    "robe",
    "gown",
    "suit",
    "pants",
    "trousers",
    "skirt",
    "blouse",
    "vest",
    "sweater",
    "hoodie",
    "cloak",
    "cape",
    "shawl",
    "armor",
    "armour",
    "tunic",
    "toga",
    "kimono",
    "sarong",
    "lungi",
    "dupatta",
    "scarf",
    "jeans",
    "shorts",
    "lehenga",
    "sherwani",
    "kaftan",
)


def is_human_critical(prompt: str, shot_type: str = "") -> bool:
    """Return True when the human subject dominates the frame.

    A subject is critical when:
    - the shot type is a close or medium shot (human fills the frame), OR
    - the scene has a critical anatomical subject (hand, face, eye, gesture, body)
      as identified by the existing ADR-0013 detector.
    """
    if shot_type.lower().strip() in _CLOSE_SHOT_TYPES:
        return True
    return detect_critical_subject(prompt) is not None


def has_clothing_specified(prompt: str) -> bool:
    """Return True when the prompt explicitly specifies clothing to wear.

    Requires BOTH a clothing trigger verb AND a known clothing noun anywhere
    in the prompt, to avoid false positives like "in a forest".
    """
    pl = prompt.lower()
    has_trigger = any(t in pl for t in _CLOTHING_TRIGGERS)
    has_item = any(item in pl for item in _CLOTHING_ITEMS)
    return has_trigger and has_item


def build_human_qa_context(prompt: str) -> str:
    """Return the vision review context for Human QA (anatomy and subject accuracy).

    This is passed as ``visual_prompt`` to the vision provider so the model
    evaluates the image against a structured anatomy checklist rather than a
    general scene quality template.
    """
    return (
        "HUMAN SUBJECT QA — ANATOMY AND SUBJECT ACCURACY\n\n"
        f"Scene description: {prompt}\n\n"
        "Review the generated image against the scene description. "
        "FAIL if ANY of the following defects are present in the image:\n\n"
        "- Missing body parts that should be present given the scene\n"
        "- Extra or duplicate body parts (e.g. three arms)\n"
        "- Broken anatomy: wrong joint placement, impossible limb angles, "
        "structural body deformities\n"
        "- Impossible pose that cannot be physically achieved by a human\n"
        "- Deformed face: asymmetric features, malformed eyes, distorted nose or mouth\n"
        "- Wrong age if age is explicitly stated in the scene description\n"
        "- Wrong gender if gender is explicitly stated in the scene description\n"
        "- Wrong ethnicity if ethnicity is explicitly stated in the scene description\n"
        "- Wrong emotion if emotion is explicitly stated and the expression clearly disagrees\n"
        "- Subject incorrectly cropped when the scene requires a full or partial view\n\n"
        "Evaluate with documentary-quality realism as the standard. "
        "PASS only if none of the above defects are present."
    )


def build_hand_qa_context(prompt: str) -> str:
    """Return the vision review context for Hand QA (finger/palm/wrist anatomy).

    If no hands are visible in the image the model should respond PASS.
    """
    return (
        "HAND ANATOMY QA — FINGER AND PALM ACCURACY\n\n"
        f"Scene description: {prompt}\n\n"
        "Inspect all visible hands in the image. "
        "FAIL if ANY of the following defects are present:\n\n"
        "- Incorrect finger count: each visible hand must have exactly 5 fingers\n"
        "- Fused fingers: two or more fingers merged or stuck together\n"
        "- Missing fingers: any finger absent from a visible hand\n"
        "- Duplicate fingers: extra fingers beyond the correct five per hand\n"
        "- Deformed thumb: thumb incorrectly positioned, absent, or disproportionate\n"
        "- Distorted palm: palm shape is unnatural or malformed\n"
        "- Unnatural wrist: wrist does not connect to the hand naturally\n"
        "- Impossible finger joints: joints bent in anatomically impossible directions\n\n"
        "If no hands are visible in the image, respond PASS. "
        "PASS only if all visible hands have correct anatomy."
    )


def build_clothing_qa_context(prompt: str) -> str:
    """Return the vision review context for Clothing Validation.

    Only called when the prompt explicitly specifies clothing to wear.
    """
    return (
        "CLOTHING VALIDATION QA\n\n"
        f"Scene description: {prompt}\n\n"
        "The scene description specifies clothing that MUST appear in the image. "
        "FAIL if any required clothing item is:\n\n"
        "- Entirely absent from the image\n"
        "- Significantly different in type from what is described "
        "(e.g. shirt described but subject is shirtless)\n"
        "- Present but on the wrong subject\n\n"
        "Minor stylistic or colour variations that preserve the core description are acceptable. "
        "PASS only if the described clothing matches what is visible."
    )


def build_prompt_compliance_context(prompt: str) -> str:
    """Return the vision review context for Prompt Compliance.

    Verifies all key attributes in the prompt appear correctly in the image.
    """
    return (
        "PROMPT COMPLIANCE REVIEW\n\n"
        f"Scene description: {prompt}\n\n"
        "Verify that the generated image correctly represents ALL specified attributes. "
        "FAIL only if there is a CRITICAL mismatch in any of the following:\n\n"
        "- Subject: the primary person or entity described is present and correct\n"
        "- Clothing: what the subject wears matches (if specified)\n"
        "- Pose or action: body position or activity matches (if specified)\n"
        "- Camera angle or viewpoint matches (if specified)\n"
        "- Environment or setting matches (if specified)\n"
        "- Emotion or facial expression matches (if specified)\n"
        "- Key props or objects are present (if specified)\n\n"
        "Minor stylistic differences that do not change the scene intent = PASS. "
        "FAIL only when a specified attribute is clearly wrong or absent."
    )
