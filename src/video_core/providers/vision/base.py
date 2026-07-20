"""Abstract base for all vision review providers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

from video_core.domain.visual_metadata import VisualMetadata
from video_core.visual_intelligence.prompt_package import PromptPackage

from .models import VisionReviewResult

# Keywords that indicate a hand-focal scene in the visual prompt.
# Whole-word regex match so "landscape" does not trigger on "land".
_HAND_FOCAL_PATTERN = re.compile(
    r"\b(hand|hands|palm|palms|finger|fingers|knuckle|knuckles|digit|digits|fist|wrist|wrists)\b",
    re.IGNORECASE,
)

# Targeted hand-anatomy block injected into the prompt when a hand-focal
# scene is detected.  Kept separate so it can be tested independently.
HAND_ANATOMY_PROMPT = """
## CRITICAL: Hand and Digit Anatomy Verification
This scene features hands prominently. Apply strict digit verification to every
visible hand in the image:

- **Digit count:** each hand must have exactly 5 digits — 4 fingers + 1 thumb.
  Flag as HIGH if any hand has more or fewer than 5 digits.
- **Thumb placement:** the thumb appears on ONE outer edge only (the radial/
  lateral side). A thumb-like digit on BOTH outer edges of the same hand is an
  AI generation error. Flag as HIGH with description "duplicated thumb — thumb-
  like digit appears on both outer edges of hand."
- **Digit topology:** fingers should be individually distinguishable from base
  to tip. Fused or merged fingers (two fingers blended into one wide digit) →
  MEDIUM if minor, HIGH if severe.
- **No ghost digits:** no partial or stub digits attached to the palm or between
  the main fingers.
- **Knuckle row symmetry:** each finger should have a consistent row of knuckles;
  asymmetric or duplicated knuckle rows indicate a generation artefact.

Treat any HIGH-severity hand anatomy finding as a FAIL regardless of overall
composition quality.
"""

# Era-aware anachronism constraints injected into the prompt when VisualMetadata
# is present.  Each era block lists rejected concepts and the severity/category
# to assign when detected.
_ERA_ANACHRONISM_BLOCKS: dict[str, str] = {
    "ANCIENT": """
## ERA CONSTRAINT: ANCIENT
Reject with HIGH severity / category "anachronism":
- drones, helicopters, aircraft, smartphones, cameras, roads, modern vehicles
- glass buildings, concrete highways, power lines, LED lighting, plastic
- modern clothing, laptops, televisions
recommend_regeneration=true when any anachronism is detected.
""",
    "HISTORICAL": """
## ERA CONSTRAINT: HISTORICAL
Require historical authenticity. Reject with HIGH severity / category "anachronism":
- anachronistic technology, modern infrastructure, inaccurate period details
recommend_regeneration=true when historical inaccuracy is detected.
""",
    "MODERN": """
## ERA CONSTRAINT: MODERN
Modern objects (smartphones, laptops, offices, traffic, apartments, airports,
coffee shops, contemporary clothing) are allowed unless they contradict the
narration. Do not reject modern technology without narrative justification.
""",
    "SYMBOLIC": """
## ERA CONSTRAINT: SYMBOLIC
Relaxed validation. Allow surreal imagery, floating objects, abstract light,
dreamlike environments. Reject only obvious unintended artifacts.
""",
    "TRANSITIONAL": """
## ERA CONSTRAINT: TRANSITIONAL
Intentional coexistence of Ancient, Historical, and Modern elements is allowed.
Only reject objects that contradict the intended comparison.
""",
}

# Narrative-role validation hints injected into the prompt.
_NARRATIVE_ROLE_BLOCKS: dict[str, str] = {
    "STORY": """
## NARRATIVE ROLE: STORY
Prioritize literal realism. Characters, objects, and environment must be
consistent with a believable depiction of the scene.
""",
    "ANALOGY": """
## NARRATIVE ROLE: ANALOGY
Validate conceptual consistency. The image should communicate the comparison
clearly, even if it sacrifices strict realism.
""",
    "METAPHOR": """
## NARRATIVE ROLE: METAPHOR
Symbolic imagery is allowed and expected. Abstract or conceptual representations
are valid as long as they serve the intended meaning.
""",
    "EXPLANATION": """
## NARRATIVE ROLE: EXPLANATION
Prioritize educational clarity. The focal point should be immediately clear.
Avoid ambiguous composition that could confuse the viewer.
""",
    "ESTABLISHING": """
## NARRATIVE ROLE: ESTABLISHING
Strong environment and context are paramount. Wide shots, clear setting,
atmospheric depth are preferred.
""",
    "CTA": """
## NARRATIVE ROLE: CTA
Clean composition with open space for text overlays. Avoid clutter in the
central area. Direct address framing is appropriate.
""",
}

# Environment validation hints.
_ENVIRONMENT_BLOCKS: dict[str, str] = {
    "TEMPLE": "Verify temple architecture, traditional materials, sacred atmosphere.",
    "ASHRAM": "Verify simple ashram setting, meditation halls, peaceful surroundings.",
    "KINGDOM": "Verify ancient kingdom architecture, palace, royal court, stone fortifications.",
    "FOREST": "Verify dense natural vegetation, trees, organic landscape.",
    "MOUNTAIN": "Verify mountain peaks, dramatic elevation, natural grandeur.",
    "RIVER": "Verify flowing water, riverbank, natural waterside environment.",
    "BATTLEFIELD": "Verify vast open landscape, dramatic sky, warfare landscape.",
    "CITY": "Verify urban environment, cityscape, contemporary architecture.",
    "OFFICE": "Verify modern workspace, professional interior, clean design.",
    "HOME": "Verify domestic interior, personal space, lived-in comfort.",
    "ABSTRACT": "Avoid forcing strict realism; conceptual or non-representational forms are acceptable.",
    "COSMIC": "Verify cosmic scale, celestial elements, vast universe imagery.",
}

# Mood validation hints.
_MOOD_BLOCKS: dict[str, str] = {
    "PEACEFUL": "Soft lighting, tranquil atmosphere, still compositions.",
    "MYSTERIOUS": "Fog, moonlight, deep shadows, atmospheric haze, low visibility.",
    "REVERENT": "Sacred glow, respectful composition, hushed mood, divine light.",
    "REFLECTIVE": "Soft evening light, contemplative mood, quiet space.",
    "HOPEFUL": "First light, warm sunrise, open sky, uplifting composition.",
    "FEARFUL": "Stormy contrast, dark shadows, dramatic tension, cold tones.",
    "CURIOUS": "Exploratory framing, intriguing details, discovery mood.",
    "LONELY": "Isolated figure, vast empty space, desaturated colors.",
    "DETERMINED": "Strong composition, purposeful stance, dramatic lighting.",
}

# Full vision review checklist — model-agnostic prompt template.
VISION_REVIEW_PROMPT = """You are a professional image quality reviewer for AI-generated video content.

Review the provided image and return a structured JSON assessment.

## Human Anatomy
- Hands: exactly 5 digits per hand (4 fingers + 1 thumb); thumb on one side only
- Feet, legs, arms — correct proportions and joint angles
- Neck, shoulders — natural alignment
- Body proportions, posture (walking, sitting, reaching)

## Face
- Eyes, ear placement, teeth
- Symmetry, expression consistency

## Lighting
- Light direction, shadows, reflections, exposure

## Environment
- Perspective, floating/duplicate/fused objects
- Missing object parts

## AI Artifacts
- Duplicated or misplaced thumbs; wrong digit count per hand
- Extra/missing fingers; fused or merged digits
- Twisted limbs, unrealistic poses, warped anatomy
- Distorted geometry, hallucinated textures
- Broken reflections, texture artifacts
- Watermarks, text artifacts
- Blurry focal subject

## Cinematic Quality
- Composition, framing, storytelling
- Emotional consistency, depth, realism

## Issue Categories (use these exact values)
- anatomy, face, lighting, environment, artifact, cinematic, anachronism,
  historical_accuracy, mood, composition, camera, text, style

Return ONLY valid JSON with this exact structure:
{
  "status": "PASS" or "FAIL",
  "score": <integer 0-100>,
  "confidence": <integer 0-100>,
  "issues": [
    {
      "category": "<anatomy|face|lighting|environment|artifact|cinematic|anachronism|historical_accuracy|mood|composition|camera|text|style>",
      "description": "<concise description>",
      "severity": "<LOW|MEDIUM|HIGH|CRITICAL>",
      "location": "<optional location hint>"
    }
  ],
  "recommend_regeneration": <true|false>
}

Score >= 90, confidence >= 80, no HIGH issues, maximum one MEDIUM issue → "PASS".
Otherwise → "FAIL" with recommend_regeneration: true.
"""


def is_hand_focal(visual_prompt: str) -> bool:
    """Return True when the visual prompt describes a hand-focal scene."""
    return bool(_HAND_FOCAL_PATTERN.search(visual_prompt))


def build_era_aware_prompt(
    visual_prompt: str,
    visual_metadata: VisualMetadata | None = None,
    prompt_package: PromptPackage | None = None,
) -> str:
    """Build a vision review prompt with era-aware constraints.

    If ``visual_metadata`` is None or not populated, returns the standard
    prompt unchanged (backward compatibility).
    """
    blocks: list[str] = [VISION_REVIEW_PROMPT]

    if visual_metadata and visual_metadata.is_populated:
        era_key = visual_metadata.era.value if visual_metadata.era else None
        if era_key and era_key in _ERA_ANACHRONISM_BLOCKS:
            blocks.append(_ERA_ANACHRONISM_BLOCKS[era_key])

        role_key = visual_metadata.narrative_role.value if visual_metadata.narrative_role else None
        if role_key and role_key in _NARRATIVE_ROLE_BLOCKS:
            blocks.append(_NARRATIVE_ROLE_BLOCKS[role_key])

        env_key = visual_metadata.environment.value if visual_metadata.environment else None
        if env_key and env_key in _ENVIRONMENT_BLOCKS:
            blocks.append(f"## ENVIRONMENT VALIDATION\n{_ENVIRONMENT_BLOCKS[env_key]}")

        mood_key = visual_metadata.mood.value if visual_metadata.mood else None
        if mood_key and mood_key in _MOOD_BLOCKS:
            blocks.append(f"## MOOD VALIDATION\n{_MOOD_BLOCKS[mood_key]}")

    hand_block = HAND_ANATOMY_PROMPT if is_hand_focal(visual_prompt) else ""
    if hand_block:
        blocks.append(hand_block)

    base = "\n\n".join(blocks)
    prompt_source = prompt_package.final_prompt if prompt_package and prompt_package.final_prompt else visual_prompt
    return f"{base}\n\nThe image was generated with this prompt:\n{prompt_source}\n\nReview the image against all criteria above and return your JSON assessment."


class VisionProvider(ABC):
    """Abstract interface for all vision review providers."""

    @abstractmethod
    def review(
        self,
        image_path: Path,
        visual_prompt: str,
        scene_context: dict | None = None,
        visual_metadata: VisualMetadata | None = None,
        prompt_package: PromptPackage | None = None,
    ) -> VisionReviewResult:
        """Review a single image and return a structured assessment.

        Parameters
        ----------
        image_path:
            Path to the image file to review.
        visual_prompt:
            The original visual prompt used to generate the image.
        scene_context:
            Optional dict with scene metadata (index, shot_type, etc.).
        visual_metadata:
            Structured VisualMetadata for era-aware validation.
        prompt_package:
            PromptPackage produced by the Prompt Builder.

        Returns
        -------
        VisionReviewResult
            Structured review result.  Never raises — errors are returned as
            an ``error_result()``.
        """
        raise NotImplementedError
