"""Image Remediation Orchestrator.

Owns the generate → review → remediate loop for a single scene image.

Responsibilities (this module only)
------------------------------------
* Call ImageReviewEngine once per attempt (single-shot, read-only).
* On FAIL: call PromptRemediationBuilder to produce a refined prompt.
* Regenerate the image with the refined prompt.
* Repeat until PASS or max_attempts is reached.
* Persist per-attempt history to  images/remediation/scene-NNN/attempt-N/.
* Return a SceneReviewArtifact that the pipeline consumes unchanged.

Non-responsibilities
--------------------
* Does NOT know how prompts are refined — that is PromptRemediationBuilder.
* Does NOT call the vision provider directly — that is ImageReviewEngine.
* Does NOT know about scenes, project IDs, or manifests — that is ImagePipeline.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from loguru import logger

from ytfactory.images.review_config import ImageReviewConfig
from ytfactory.images.review_engine import ImageReviewEngine
from ytfactory.images.review_models import SceneReviewArtifact
from ytfactory.prompts.prompt_remediation_builder import (
    PromptRemediationBuilder,
    RemediationInput,
)
from ytfactory.providers.image.base import ImageProvider
from ytfactory.providers.vision.base import VisionProvider
from ytfactory.providers.vision.models import IssueSeverity, VisionIssue, VisionReviewResult


# ── QA sub-score derivation ───────────────────────────────────────────────────

_QA_DEDUCTIONS: dict[str, int] = {"CRITICAL": 50, "HIGH": 30, "MEDIUM": 15, "LOW": 5}
_TECHNICAL_CATS: frozenset[str] = frozenset({"anatomy", "face", "artifact"})
_NARRATIVE_CATS: frozenset[str] = frozenset({"environment"})
_CINEMATIC_CATS: frozenset[str] = frozenset({"lighting", "cinematic"})


def _qa_scores(issues: list[dict]) -> tuple[float, float, float]:
    """Return (narrative, technical, cinematic) scores from a raw issues list."""
    ded_n = ded_t = ded_c = 0
    for issue in issues:
        cat = issue.get("category", "").lower()
        sev = issue.get("severity", "MEDIUM")
        pts = _QA_DEDUCTIONS.get(sev, _QA_DEDUCTIONS["MEDIUM"])
        if cat in _TECHNICAL_CATS:
            ded_t += pts
        elif cat in _NARRATIVE_CATS:
            ded_n += pts
        elif cat in _CINEMATIC_CATS:
            ded_c += pts
    return max(0.0, 100.0 - ded_n), max(0.0, 100.0 - ded_t), max(0.0, 100.0 - ded_c)


def _dict_to_vision_issue(d: dict) -> VisionIssue:
    sev_str = d.get("severity", "MEDIUM")
    try:
        severity = IssueSeverity(sev_str)
    except ValueError:
        severity = IssueSeverity.MEDIUM
    return VisionIssue(
        category=d.get("category", ""),
        description=d.get("description", ""),
        severity=severity,
        location=d.get("location", ""),
    )


# ── Orchestrator ──────────────────────────────────────────────────────────────


class ImageRemediationOrchestrator:
    """Orchestrate image review and automatic remediation for a single scene.

    The orchestrator is the only component that knows:
    * how many attempts to make
    * when to refine the prompt
    * when to accept a FAIL result as final

    All other concerns are delegated:
    * VisionProvider → ImageReviewEngine
    * Prompt refinement → PromptRemediationBuilder
    * Image regeneration → ImageProvider

    Public API mirrors ImageReviewEngine.review_scene() so ImagePipeline
    requires minimal changes.
    """

    def __init__(
        self,
        config: ImageReviewConfig,
        vision_provider: VisionProvider,
        image_provider: ImageProvider,
        builder: PromptRemediationBuilder | None = None,
    ) -> None:
        self._config = config
        self._image_provider = image_provider
        self._builder = builder or PromptRemediationBuilder()

        # Single-attempt review engine: orchestrator owns the retry loop.
        single_shot = dataclasses.replace(config, max_attempts=1, auto_remediate=False)
        self._review_engine = ImageReviewEngine(single_shot, vision_provider, image_provider)

    # ── Public API ────────────────────────────────────────────────────────

    def review_scene(
        self,
        scene: dict,
        image_path: Path,
        output_dir: Path,
    ) -> SceneReviewArtifact:
        """Review one scene image; refine prompt and regenerate on failure.

        Parameters
        ----------
        scene:
            Scene dict from scene-plan.json (must contain ``index`` and
            ``visual_prompt``).
        image_path:
            Path to the current generated image file.
        output_dir:
            images/ directory for review artifacts and attempt history.

        Returns
        -------
        SceneReviewArtifact
            Final review result after all attempts.  The ``attempts`` field
            reflects the total number of orchestrator-level attempts.
        """
        idx = scene.get("index", 0)
        original_prompt = scene.get("visual_prompt", "")
        current_prompt = original_prompt

        attempt_base = output_dir / "remediation" / f"scene-{idx:03d}"
        history: list[dict] = []
        final_artifact: SceneReviewArtifact | None = None
        write_history = self._config.auto_remediate and self._config.max_attempts > 1

        for attempt in range(1, self._config.max_attempts + 1):
            if not image_path.exists():
                logger.warning("Scene {:03d} | Attempt {}/{} | image missing", idx, attempt, self._config.max_attempts)
                break

            # Single-attempt review (engine writes image-review-NNN.json each call)
            scene_for_attempt = {**scene, "visual_prompt": current_prompt}
            artifact = self._review_engine.review_scene(scene_for_attempt, image_path, output_dir)
            final_artifact = artifact
            passed = artifact.status == "PASS"

            logger.info(
                "Scene {:03d} | Attempt {}/{} | {} (score={:.0f}, confidence={:.0f})",
                idx, attempt, self._config.max_attempts,
                artifact.status, artifact.score, artifact.confidence,
            )

            history.append({
                "attempt": attempt,
                "status": artifact.status,
                "score": artifact.score,
                "confidence": artifact.confidence,
                "passed": passed,
                "prompt_length": len(current_prompt),
            })

            if write_history:
                self._write_attempt(attempt_base, attempt, current_prompt, artifact)

            if passed or artifact.status in ("SKIP", "ERROR"):
                if passed:
                    logger.info("Scene {:03d} | Approved ✓", idx)
                break

            if not self._config.auto_remediate or attempt >= self._config.max_attempts:
                logger.warning(
                    "Scene {:03d} | {} after {} attempt(s) — MANUAL_REVIEW recommended",
                    idx, artifact.status, attempt,
                )
                break

            # Derive QA sub-scores and build refined prompt
            narrative_score, technical_score, cinematic_score = _qa_scores(artifact.issues)
            refined = self._builder.build(
                RemediationInput(
                    original_prompt=original_prompt,
                    scene=scene,
                    result=VisionReviewResult(
                        status=artifact.status,
                        score=artifact.score,
                        confidence=artifact.confidence,
                        issues=[_dict_to_vision_issue(i) for i in artifact.issues],
                    ),
                    narrative_score=narrative_score,
                    technical_score=technical_score,
                    cinematic_score=cinematic_score,
                    attempt=attempt,
                )
            )
            current_prompt = refined
            logger.info(
                "Scene {:03d} | Refining prompt → attempt {}/{}",
                idx, attempt + 1, self._config.max_attempts,
            )
            self._regenerate(scene, current_prompt, image_path)

        if final_artifact is None:
            final_artifact = SceneReviewArtifact(
                scene_index=idx,
                status="SKIP",
                score=100.0,
                confidence=100.0,
                attempts=1,
                final_prompt=original_prompt,
            )

        # Update attempt count to reflect orchestrator-level total
        final_artifact.attempts = len(history) or 1
        final_artifact.final_prompt = current_prompt

        if write_history and history:
            self._write_final(attempt_base, final_artifact, original_prompt, len(history))

        return final_artifact

    # ── Helpers ───────────────────────────────────────────────────────────

    def _regenerate(self, scene: dict, refined_prompt: str, image_path: Path) -> None:
        """Delete existing image and regenerate with the refined prompt."""
        from ytfactory.domain.image import ImageRequest

        image_path.unlink(missing_ok=True)
        request = ImageRequest(
            prompt=refined_prompt,
            output_path=image_path,
            width=scene.get("width", 1920),
            height=scene.get("height", 1080),
            seed=None,  # new random seed for diversity
        )
        try:
            self._image_provider.generate(request)
        except Exception as exc:
            logger.warning("Scene {:03d} | Regeneration failed: {}", scene.get("index", 0), exc)

    def _write_attempt(
        self,
        base_dir: Path,
        attempt: int,
        prompt: str,
        artifact: SceneReviewArtifact,
    ) -> None:
        """Write per-attempt prompt and review result to the attempt history directory."""
        attempt_dir = base_dir / f"attempt-{attempt}"
        try:
            attempt_dir.mkdir(parents=True, exist_ok=True)
            (attempt_dir / "prompt.md").write_text(prompt, encoding="utf-8")
            (attempt_dir / "review.json").write_text(
                json.dumps(artifact.__dict__, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("Could not write attempt history: {}", exc)

    def _write_final(
        self,
        base_dir: Path,
        artifact: SceneReviewArtifact,
        original_prompt: str,
        total_attempts: int,
    ) -> None:
        """Write the final approved (or best-effort) result to the final/ directory."""
        final_dir = base_dir / "final"
        try:
            final_dir.mkdir(parents=True, exist_ok=True)
            (final_dir / "review.json").write_text(
                json.dumps(artifact.__dict__, indent=2, default=str),
                encoding="utf-8",
            )
            metadata = {
                "scene_index": artifact.scene_index,
                "final_status": artifact.status,
                "final_score": artifact.score,
                "total_attempts": total_attempts,
                "remediation_applied": total_attempts > 1,
                "original_prompt": original_prompt,
                "final_prompt": artifact.final_prompt,
            }
            (final_dir / "metadata.json").write_text(
                json.dumps(metadata, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug("Could not write final artifacts: {}", exc)
