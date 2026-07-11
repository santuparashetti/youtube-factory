"""Abstract base for all vision review providers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

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

Return ONLY valid JSON with this exact structure:
{
  "status": "PASS" or "FAIL",
  "score": <integer 0-100>,
  "confidence": <integer 0-100>,
  "issues": [
    {
      "category": "<anatomy|face|lighting|environment|artifact|cinematic>",
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


class VisionProvider(ABC):
    """Abstract interface for all vision review providers."""

    @abstractmethod
    def review(
        self,
        image_path: Path,
        visual_prompt: str,
        scene_context: dict | None = None,
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

        Returns
        -------
        VisionReviewResult
            Structured review result.  Never raises — errors are returned as
            an ``error_result()``.
        """
        raise NotImplementedError
