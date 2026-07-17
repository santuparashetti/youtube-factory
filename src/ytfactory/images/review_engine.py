"""Image Review Engine — per-scene vision quality gate.

Architecture:
  Image Generation → Technical QA (OpenCV) → Vision Provider →
    PASS → Continue
    FAIL → Prompt Refinement → New Seed → Regenerate → Review Again

The engine is called by ImagePipeline per scene.
It never downloads models directly — all model operations route through
the Local AI Model Manager via the VisionProvider.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from video_core.providers.image.base import ImageProvider
from video_core.providers.vision import VisionProvider, VisionReviewResult

from .human_detector import build_specialist_context, detect_critical_subject
from .review_config import ImageReviewConfig
from .review_models import (
    ImageQualitySummary,
    SceneRemediationArtifact,
    SceneReviewArtifact,
)


class ImageReviewEngine:
    """Review and auto-remediate AI-generated images per scene.

    Usage
    -----
        engine = ImageReviewEngine(config, vision_provider, image_provider)
        result = engine.review_scene(scene, image_path, output_dir)
    """

    def __init__(
        self,
        config: ImageReviewConfig,
        vision_provider: VisionProvider,
        image_provider: ImageProvider,
    ) -> None:
        self._config = config
        self._vision = vision_provider
        self._image_provider = image_provider

    # ── Public API ────────────────────────────────────────────────────────

    def review_scene(
        self,
        scene: dict,
        image_path: Path,
        output_dir: Path,
    ) -> SceneReviewArtifact:
        """Review one scene image; regenerate on failure up to max_attempts.

        Parameters
        ----------
        scene:
            Scene dict from scene-plan.json.
        image_path:
            Path to the generated image.
        output_dir:
            images/ directory for writing review artifacts.

        Returns
        -------
        SceneReviewArtifact
            The final review result after all attempts.
        """
        idx = scene.get("index", 0)
        visual_prompt = scene.get("visual_prompt", "")

        remediation = SceneRemediationArtifact(
            scene_index=idx,
            original_prompt=visual_prompt,
        )

        current_prompt = visual_prompt
        final_result: VisionReviewResult | None = None
        final_specialist_result: VisionReviewResult | None = None
        final_specialist_subject: str = ""

        for attempt in range(1, self._config.max_attempts + 1):
            if not image_path.exists():
                break

            # Technical QA first (fast, no model required)
            tqa_ok, tqa_msg = self._technical_qa(image_path)
            if not tqa_ok:
                logger.debug("Scene {}: technical QA failed — {}", idx, tqa_msg)

            # ── Overall vision review ─────────────────────────────────────────
            result = self._vision.review(
                image_path=image_path,
                visual_prompt=current_prompt,
                scene_context={"index": idx, "attempt": attempt, **scene},
            )
            final_result = result

            high_count = len(result.high_severity_issues)
            medium_count = len(result.medium_severity_issues)
            passes = self._config.passes(
                result.score, result.confidence, high_count, medium_count
            )

            attempt_record: dict = {
                "attempt": attempt,
                "status": result.status,
                "score": result.score,
                "confidence": result.confidence,
                "high_issues": high_count,
                "medium_issues": medium_count,
                "passed": passes,
                "prompt_length": len(current_prompt),
            }

            # ── Subject Specialist Review (ADR-0013) ──────────────────────────
            # Only runs when the overall review passes — "BOTH must pass" rule.
            specialist_result: VisionReviewResult | None = None
            specialist_subject = ""
            if passes and result.status not in ("SKIP", "ERROR"):
                specialist_subject = detect_critical_subject(current_prompt) or ""
                if specialist_subject:
                    specialist_result = self._specialist_review(
                        image_path, current_prompt, specialist_subject, scene, attempt
                    )
                    final_specialist_result = specialist_result
                    final_specialist_subject = specialist_subject

                    spec_high = len(specialist_result.high_severity_issues)
                    spec_medium = len(specialist_result.medium_severity_issues)
                    specialist_passes = self._config.passes(
                        specialist_result.score,
                        specialist_result.confidence,
                        spec_high,
                        spec_medium,
                    )
                    attempt_record.update(
                        {
                            "specialist_subject": specialist_subject,
                            "specialist_score": specialist_result.score,
                            "specialist_passed": specialist_passes,
                        }
                    )

                    if not specialist_passes:
                        passes = False
                        logger.info(
                            "Scene {}: specialist review FAIL subject='{}' score={:.0f}",
                            idx,
                            specialist_subject,
                            specialist_result.score,
                        )

            remediation.attempt_history.append(attempt_record)
            remediation.total_attempts = attempt

            if self._config.debug:
                self._write_review_prompt(idx, attempt, current_prompt, output_dir)

            if passes or result.status in ("SKIP", "ERROR"):
                break

            # FAIL → without remediation, accept the result and stop
            if not self._config.auto_remediate:
                break

            # FAIL → refine prompt and regenerate (if more attempts remain)
            if attempt < self._config.max_attempts:
                # When specialist failed, drive refinement from its issues
                refinement_result = (
                    specialist_result
                    if specialist_result is not None and specialist_subject
                    else result
                )
                current_prompt = self._refine_prompt(current_prompt, refinement_result)
                remediation.remediation_applied = True
                logger.info(
                    "Scene {}: review FAIL (score={:.0f}) — refining prompt, attempt {}/{}",
                    idx,
                    result.score,
                    attempt + 1,
                    self._config.max_attempts,
                )
                # Regenerate image with refined prompt and new seed
                self._regenerate(scene, current_prompt, image_path)

        if final_result is None:
            final_result = VisionReviewResult.skipped("Image not found")

        # Write per-scene artifacts
        artifact = SceneReviewArtifact(
            scene_index=idx,
            status=final_result.status,
            score=final_result.score,
            confidence=final_result.confidence,
            issues=[i.__dict__ for i in final_result.issues],
            attempts=remediation.total_attempts or 1,
            final_prompt=current_prompt,
            model_name=final_result.model_name,
            backend=final_result.backend,
            recommend_regeneration=final_result.recommend_regeneration,
            error=final_result.error,
            subject_critical=bool(final_specialist_subject),
            specialist_subject=final_specialist_subject,
            specialist_status=final_specialist_result.status if final_specialist_result else "",
            specialist_score=final_specialist_result.score if final_specialist_result else 0.0,
            specialist_issues=(
                [i.__dict__ for i in final_specialist_result.issues]
                if final_specialist_result else []
            ),
        )
        remediation.final_status = final_result.status

        self._write_review_artifact(artifact, output_dir)
        self._write_remediation_artifact(remediation, output_dir)

        return artifact

    # ── Helpers ───────────────────────────────────────────────────────────

    def _specialist_review(
        self,
        image_path: Path,
        original_prompt: str,
        subject: str,
        scene: dict,
        attempt: int,
    ) -> VisionReviewResult:
        """Run a focused specialist vision review for a critical subject (ADR-0013).

        The vision model is given the subject-specific checklist as primary context
        so it evaluates anatomy precisely rather than general scene quality.
        """
        checklist = build_specialist_context(subject)
        specialist_prompt = f"{checklist}\n\nORIGINAL SCENE DESCRIPTION: {original_prompt}"
        return self._vision.review(
            image_path=image_path,
            visual_prompt=specialist_prompt,
            scene_context={"specialist_subject": subject, "attempt": attempt, **scene},
        )

    def _technical_qa(self, image_path: Path) -> tuple[bool, str]:
        """Fast OpenCV-based checks: file size, sharpness."""
        size = image_path.stat().st_size
        if size < 1000:
            return False, f"Image too small: {size} bytes"

        try:
            import cv2  # type: ignore[import-not-found]

            img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                return False, "OpenCV could not read image"
            laplacian_var = float(cv2.Laplacian(img, cv2.CV_64F).var())
            if laplacian_var < 10.0:
                return (
                    False,
                    f"Image appears blurry (Laplacian var={laplacian_var:.1f})",
                )
        except ImportError:
            pass  # OpenCV optional — skip if not installed

        return True, "ok"

    def _refine_prompt(self, prompt: str, result: VisionReviewResult) -> str:
        """Append targeted improvements based on review findings.

        Never rewrites the original prompt — only appends corrections.
        """
        additions: list[str] = []

        for issue in result.high_severity_issues:
            cat = issue.category.lower()
            if "anatomy" in cat or "hand" in issue.description.lower():
                additions.append(
                    "anatomically correct hands with exactly five fingers per hand"
                )
            elif "face" in cat:
                additions.append(
                    "natural facial expression, symmetric face, realistic eyes"
                )
            elif "artifact" in cat or "watermark" in issue.description.lower():
                additions.append("no watermarks, no text artifacts, no distortions")
            elif "lighting" in cat:
                additions.append(
                    "correct lighting direction, realistic shadows and highlights"
                )

        for issue in result.medium_severity_issues:
            if "blur" in issue.description.lower():
                additions.append("sharp focus, high detail, crisp edges")
            elif "proportion" in issue.description.lower():
                additions.append("correct body proportions, natural posture")

        if not additions:
            additions.append("high quality, no artifacts, photorealistic, sharp focus")

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique = [a for a in additions if not (a in seen or seen.add(a))]  # type: ignore[func-returns-value]
        return prompt + ", " + ", ".join(unique)

    def _regenerate(
        self,
        scene: dict,
        refined_prompt: str,
        image_path: Path,
    ) -> None:
        """Delete existing image and regenerate with refined prompt."""
        from video_core.domain.image import ImageRequest

        image_path.unlink(missing_ok=True)
        request = ImageRequest(
            prompt=refined_prompt,
            output_path=image_path,
            width=scene.get("width", 1920),
            height=scene.get("height", 1080),
            seed=None,  # new random seed
        )
        try:
            self._image_provider.generate(request)
        except Exception as exc:
            logger.warning(
                "Regeneration failed for scene {}: {}", scene.get("index"), exc
            )

    # ── Artifact writers ──────────────────────────────────────────────────

    def _write_review_artifact(
        self, artifact: SceneReviewArtifact, output_dir: Path
    ) -> None:
        path = output_dir / f"image-review-{artifact.scene_index:03d}.json"
        try:
            path.write_text(
                json.dumps(artifact.__dict__, indent=2, default=str), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug("Could not write review artifact: {}", exc)

    def _write_remediation_artifact(
        self,
        rem: SceneRemediationArtifact,
        output_dir: Path,
    ) -> None:
        path = output_dir / f"image-remediation-{rem.scene_index:03d}.json"
        try:
            path.write_text(
                json.dumps(rem.__dict__, indent=2, default=str), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug("Could not write remediation artifact: {}", exc)

    def _write_review_prompt(
        self,
        scene_index: int,
        attempt: int,
        prompt: str,
        output_dir: Path,
    ) -> None:
        path = output_dir / f"image-review-prompt-{scene_index:03d}-{attempt}.txt"
        try:
            path.write_text(prompt, encoding="utf-8")
        except Exception:
            pass


def write_image_quality_summary(
    artifacts: list[SceneReviewArtifact],
    output_dir: Path,
) -> ImageQualitySummary:
    """Aggregate per-scene results and write image-quality-summary.json."""
    summary = ImageQualitySummary(total_scenes=len(artifacts))

    for a in artifacts:
        summary.total_attempts += a.attempts
        status = (a.status or "SKIP").upper()
        if status == "PASS":
            summary.reviewed += 1
            summary.passed += 1
        elif status == "FAIL":
            summary.reviewed += 1
            summary.failed += 1
        elif status == "ERROR":
            summary.errors += 1
        else:
            summary.skipped += 1

        summary.scenes.append(
            {
                "scene_index": a.scene_index,
                "status": a.status,
                "score": a.score,
                "confidence": a.confidence,
                "attempts": a.attempts,
                "issues_count": len(a.issues),
            }
        )

    summary.finalize()

    path = output_dir / "image-quality-summary.json"
    try:
        path.write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not write image quality summary: {}", exc)

    return summary
