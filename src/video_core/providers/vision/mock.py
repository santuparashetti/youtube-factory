"""Mock vision provider — returns configurable results for tests.

Never performs real inference.  Useful for unit tests, CI, and
dry-run validation scenarios.
"""

from __future__ import annotations

from pathlib import Path

from .base import VisionProvider
from video_core.domain.visual_metadata import VisualMetadata
from video_core.visual_intelligence.prompt_package import PromptPackage
from .models import VisionReviewResult


class MockVisionProvider(VisionProvider):
    """Deterministic mock that returns a fixed result.

    Default: always PASS with score=95, confidence=90.

    Parameters
    ----------
    result:
        If supplied, this exact result is returned for every call.
    fail_scenes:
        Set of scene indices that should return FAIL results.
    fail_score:
        Score returned for failed scenes (default 40).
    """

    def __init__(
        self,
        result: VisionReviewResult | None = None,
        fail_scenes: set[int] | None = None,
        fail_score: float = 40.0,
    ) -> None:
        self._default_result = result
        self._fail_scenes: set[int] = fail_scenes or set()
        self._fail_score = fail_score

    def review(
        self,
        image_path: Path,
        visual_prompt: str,
        scene_context: dict | None = None,
        visual_metadata: VisualMetadata | None = None,
        prompt_package: PromptPackage | None = None,
    ) -> VisionReviewResult:
        if self._default_result is not None:
            return self._default_result

        scene_idx = (scene_context or {}).get("index", -1)
        if scene_idx in self._fail_scenes:
            return VisionReviewResult(
                status="FAIL",
                score=self._fail_score,
                confidence=90.0,
                recommend_regeneration=True,
                model_name="mock",
                backend="mock",
            )

        return VisionReviewResult(
            status="PASS",
            score=95.0,
            confidence=90.0,
            recommend_regeneration=False,
            model_name="mock",
            backend="mock",
        )
