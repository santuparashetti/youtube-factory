"""Abstract base class for all review stages."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from ytfactory.review.config import ReviewConfig
from ytfactory.review.models import SceneReview, StageResult


class BaseReviewStage(ABC):
    """Each concrete stage runs a set of named checks and returns a StageResult.

    Subclasses implement ``_run_checks`` which receives the full artifact
    context dict and fills ``self._errors`` / ``self._warnings``.
    """

    name: str = "unnamed_stage"

    def __init__(self, config: ReviewConfig) -> None:
        self._config = config
        self._errors: list[str] = []
        self._warnings: list[str] = []
        self._checks_run: int = 0
        self._checks_passed: int = 0

    # ── Internal helpers ──────────────────────────────────────────────────

    def _check(self, condition: bool, error_msg: str, warning_msg: str = "") -> bool:
        """Record a check result.  Returns True when the check passed."""
        self._checks_run += 1
        if condition:
            self._checks_passed += 1
            return True
        if warning_msg:
            self._warnings.append(warning_msg)
        else:
            self._errors.append(error_msg)
        return False

    def _error(self, msg: str) -> None:
        self._checks_run += 1
        self._errors.append(msg)

    def _warn(self, msg: str) -> None:
        self._warnings.append(msg)

    def _ok(self) -> None:
        self._checks_run += 1
        self._checks_passed += 1

    # ── Abstract API ──────────────────────────────────────────────────────

    @abstractmethod
    def _run_checks(
        self,
        project_dir: "Path",  # noqa: F821
        scenes: list[dict],
        scene_reviews: list[SceneReview],
        context: dict,
    ) -> None:
        """Perform all checks for this stage.  Mutate self._errors / warnings."""

    # ── Public API ────────────────────────────────────────────────────────

    def run(
        self,
        project_dir: "Path",  # noqa: F821
        scenes: list[dict],
        scene_reviews: list[SceneReview],
        context: dict,
    ) -> StageResult:
        """Execute the stage and return a StageResult."""
        self._errors = []
        self._warnings = []
        self._checks_run = 0
        self._checks_passed = 0

        t0 = time.perf_counter()
        try:
            self._run_checks(project_dir, scenes, scene_reviews, context)
        except Exception as exc:
            self._errors.append(f"Stage {self.name} raised unexpected error: {exc}")

        elapsed = time.perf_counter() - t0
        passed = len(self._errors) == 0

        return StageResult(
            stage_name=self.name,
            passed=passed,
            errors=list(self._errors),
            warnings=list(self._warnings),
            checks_run=self._checks_run,
            checks_passed=self._checks_passed,
            duration_seconds=round(elapsed, 4),
        )
