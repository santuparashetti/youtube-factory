"""Abstract base for all vision review providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .models import VisionReviewResult

# Full vision review checklist — model-agnostic prompt template.
VISION_REVIEW_PROMPT = """You are a professional image quality reviewer for AI-generated video content.

Review the provided image and return a structured JSON assessment.

## Human Anatomy
- Hands (fingers, joints, proportions)
- Feet, legs, arms
- Neck, shoulders
- Body proportions, posture (walking, sitting)

## Face
- Eyes, ear placement, teeth
- Symmetry, expression consistency

## Lighting
- Light direction, shadows, reflections, exposure

## Environment
- Perspective, floating/duplicate/fused objects
- Missing object parts

## AI Artifacts
- Extra/missing fingers
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
