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
from video_core.domain.visual_metadata import VisualMetadata
from video_core.visual_intelligence.prompt_package import PromptPackage

from .human_detector import build_specialist_context, detect_critical_subject, detect_human_presence, has_intentional_hands
from .human_qa import (
    build_clothing_qa_context,
    build_hand_qa_context,
    build_human_qa_context,
    build_prompt_compliance_context,
    has_clothing_specified,
    is_human_critical,
)
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
        visual_metadata = self._extract_visual_metadata(scene)
        prompt_package = self._extract_prompt_package(scene)

        remediation = SceneRemediationArtifact(
            scene_index=idx,
            original_prompt=visual_prompt,
        )

        current_prompt = visual_prompt
        final_result: VisionReviewResult | None = None
        final_specialist_result: VisionReviewResult | None = None
        final_specialist_subject: str = ""
        final_human_qa_stage: dict = {}
        final_hand_passes: bool = True

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
                visual_metadata=visual_metadata,
                prompt_package=prompt_package,
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

            # ── ADR-0015: Human Subject QA Gate ──────────────────────────────
            # Runs only when both overall and specialist reviews pass, and only
            # for human-critical scenes (primary subject or close/medium shot).
            human_qa_failing_result: VisionReviewResult | None = None
            _hqa_stage: dict = {}
            if (
                passes
                and result.status not in ("SKIP", "ERROR")
                and self._config.human_qa_enabled
                and detect_human_presence(current_prompt)
            ):
                hqa_passes, _hqa_stage, human_qa_failing_result = self._run_human_qa_gate(
                    image_path, current_prompt, scene, attempt
                )
                attempt_record.update(_hqa_stage)
                if not hqa_passes:
                    passes = False
            final_human_qa_stage = _hqa_stage

            # ── Hand Avoidance Presence Gate ──────────────────────────────────
            # For scenes where hands are not narratively required, check whether
            # any hands are visible and trigger regeneration if they are.
            hand_presence_failing_result: VisionReviewResult | None = None
            if (
                passes
                and result.status not in ("SKIP", "ERROR")
                and self._config.hand_avoidance_check_enabled
                and detect_human_presence(current_prompt)
                and not has_intentional_hands(
                    scene.get("narration", "") + " " + current_prompt
                )
            ):
                hp_passes, hand_presence_failing_result = self._check_hand_presence(
                    image_path, current_prompt, scene, attempt
                )
                if not hp_passes:
                    passes = False
                    attempt_record["hand_presence_detected"] = True
                final_hand_passes = hp_passes

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
                # Refinement priority: Hand Presence > Human QA gate > specialist > overall
                refinement_result = (
                    hand_presence_failing_result
                    if hand_presence_failing_result is not None
                    else human_qa_failing_result
                    if human_qa_failing_result is not None
                    else specialist_result
                    if specialist_result is not None and specialist_subject
                    else result
                )
                refined_prompt, sections_changed = self._refine_prompt(current_prompt, refinement_result)
                attempt_record.update(
                    {
                        "failure_category": ", ".join(
                            sorted({i.category for i in refinement_result.issues if i.severity in ("HIGH", "CRITICAL")})
                        ) or "score_only",
                        "confidence": result.confidence,
                        "root_cause": "; ".join(
                            {i.description for i in refinement_result.issues if i.severity in ("HIGH", "CRITICAL")}
                        ) or "quality below threshold",
                        "sections_changed": sections_changed,
                    }
                )
                current_prompt = refined_prompt
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

        hqa_passes = final_human_qa_stage.get("human_qa_passed", True)
        critical = self._compute_overall(
            result=final_result,
            specialist_result=final_specialist_result,
            hand_passes=final_hand_passes,
            hqa_passes=hqa_passes,
        )

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
            error=final_result.error,
            subject_critical=bool(final_specialist_subject),
            specialist_subject=final_specialist_subject,
            specialist_status=final_specialist_result.status if final_specialist_result else "",
            specialist_score=final_specialist_result.score if final_specialist_result else 0.0,
            specialist_issues=(
                [i.__dict__ for i in final_specialist_result.issues]
                if final_specialist_result else []
            ),
            # ADR-0015 Human Subject QA Gate — final attempt outcome
            human_qa_triggered=final_human_qa_stage.get("human_qa_triggered", False),
            human_qa_passed=final_human_qa_stage.get("human_qa_passed", False),
            human_qa_status=final_human_qa_stage.get("human_qa_status", ""),
            hand_qa_status=final_human_qa_stage.get("hand_qa_status", ""),
            clothing_qa_status=final_human_qa_stage.get("clothing_qa_status", ""),
            prompt_compliance_status=final_human_qa_stage.get("prompt_compliance_status", ""),
            # Critical Validation Rule — two-stage evaluation
            overall_status=critical["overall_status"],
            overall_score=critical["overall_score"],
            recommend_regeneration=critical["recommend_regeneration"],
            hard_constraints=critical["hard_constraints"],
            quality_scores=critical["quality_scores"],
            failure_categories=critical["failure_categories"],
            summary=critical["summary"],
        )
        remediation.final_status = final_result.status

        self._write_review_artifact(artifact, output_dir)
        self._write_remediation_artifact(remediation, output_dir)

        return artifact

    # ── Helpers ───────────────────────────────────────────────────────────

    def _run_staged_qa(
        self,
        image_path: Path,
        prompt: str,
        scene: dict,
        attempt: int,
        qa_context: str,
        stage_name: str,
    ) -> VisionReviewResult:
        """Run one Human QA stage through the vision provider with a targeted context."""
        try:
            return self._vision.review(
                image_path=image_path,
                visual_prompt=qa_context,
                scene_context={"stage": stage_name, "attempt": attempt, **scene},
            )
        except Exception as exc:
            logger.warning(
                "Scene {}: {} error — {}", scene.get("index"), stage_name, exc
            )
            return VisionReviewResult.skipped(f"{stage_name} error: {exc}")

    def _run_human_qa_gate(
        self,
        image_path: Path,
        prompt: str,
        scene: dict,
        attempt: int,
    ) -> tuple[bool, dict, VisionReviewResult | None]:
        """Run staged Human Subject QA (ADR-0015).

        Returns:
            (all_passed, stage_dict, failing_result)
            - all_passed: False when any required stage failed
            - stage_dict: per-stage status/pass keys for attempt_record
            - failing_result: VisionReviewResult of the failing stage (for prompt refinement),
              or None when all stages passed or the scene is not human-critical
        """
        idx = scene.get("index", 0)
        shot_type = scene.get("shot_type", "")
        stage: dict = {"human_qa_triggered": False}

        if not is_human_critical(prompt, shot_type):
            return True, stage, None

        stage["human_qa_triggered"] = True

        def _check(result: VisionReviewResult) -> bool:
            return self._config.passes(
                result.score,
                result.confidence,
                len(result.high_severity_issues),
                len(result.medium_severity_issues),
            )

        # Stage 2: Human QA (anatomy + subject accuracy)
        hqa = self._run_staged_qa(
            image_path, prompt, scene, attempt,
            build_human_qa_context(prompt), "human_qa",
        )
        hqa_passes = _check(hqa)
        stage["human_qa_status"] = hqa.status
        stage["human_qa_passed"] = hqa_passes
        if not hqa_passes:
            logger.info(
                "Scene {}: Human QA FAIL (score={:.0f}) attempt {}/{}",
                idx, hqa.score, attempt, self._config.max_attempts,
            )
            return False, stage, hqa

        # Stage 3: Hand QA (finger/palm/wrist anatomy)
        hnd = self._run_staged_qa(
            image_path, prompt, scene, attempt,
            build_hand_qa_context(prompt), "hand_qa",
        )
        hnd_passes = _check(hnd)
        stage["hand_qa_status"] = hnd.status
        stage["hand_qa_passed"] = hnd_passes
        if not hnd_passes:
            logger.info(
                "Scene {}: Hand QA FAIL (score={:.0f}) attempt {}/{}",
                idx, hnd.score, attempt, self._config.max_attempts,
            )
            return False, stage, hnd

        # Stage 4: Clothing QA (only when clothing is specified in prompt)
        if has_clothing_specified(prompt):
            cl = self._run_staged_qa(
                image_path, prompt, scene, attempt,
                build_clothing_qa_context(prompt), "clothing_qa",
            )
            cl_passes = _check(cl)
            stage["clothing_qa_status"] = cl.status
            stage["clothing_qa_passed"] = cl_passes
            if not cl_passes:
                logger.info(
                    "Scene {}: Clothing QA FAIL (score={:.0f}) attempt {}/{}",
                    idx, cl.score, attempt, self._config.max_attempts,
                )
                return False, stage, cl

        # Stage 5: Prompt Compliance
        pc = self._run_staged_qa(
            image_path, prompt, scene, attempt,
            build_prompt_compliance_context(prompt), "prompt_compliance",
        )
        pc_passes = _check(pc)
        stage["prompt_compliance_status"] = pc.status
        stage["prompt_compliance_passed"] = pc_passes
        if not pc_passes:
            logger.info(
                "Scene {}: Prompt Compliance FAIL (score={:.0f}) attempt {}/{}",
                idx, pc.score, attempt, self._config.max_attempts,
            )
            return False, stage, pc

        stage["human_qa_gate_passed"] = True
        return True, stage, None

    def _check_hand_presence(
        self,
        image_path: Path,
        prompt: str,
        scene: dict,
        attempt: int,
    ) -> tuple[bool, VisionReviewResult | None]:
        """Check whether visible hands appear in a scene that should avoid them.

        Returns ``(passes, failing_result)``.  When passes is True, failing_result
        is None.  SKIP/ERROR results always count as passing (fail-safe).
        """
        hand_context = (
            "HAND PRESENCE CHECK\n"
            "This scene was composed to keep hands out of frame.\n"
            "Carefully examine the image for any visible human hands, fingers, or palms.\n"
            "Score 100 if NO hands are visible. Score 0 if hands are clearly visible.\n"
            "Issue a HIGH severity issue labelled 'hand_presence' if any hands or fingers "
            "appear in the frame."
        )
        result = self._run_staged_qa(
            image_path, prompt, scene, attempt, hand_context, "hand_presence_check"
        )
        idx = scene.get("index", 0)
        if result.status in ("SKIP", "ERROR"):
            return True, None
        passes = self._config.passes(
            result.score,
            result.confidence,
            len(result.high_severity_issues),
            len(result.medium_severity_issues),
        )
        if not passes:
            logger.info(
                "Scene {}: Hand Presence FAIL (score={:.0f}) attempt {}/{}",
                idx, result.score, attempt, self._config.max_attempts,
            )
            return False, result
        return True, None

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

    def _refine_prompt(self, prompt: str, result: VisionReviewResult) -> tuple[str, list[str]]:
        """Append targeted improvements based on review findings.

        Never rewrites the original prompt — only appends corrections.
        Returns (refined_prompt, sections_changed).
        """
        additions: list[str] = []
        sections_changed: list[str] = []

        for issue in result.high_severity_issues:
            cat = issue.category.lower()
            desc = issue.description.lower()
            if "anatomy" in cat or "hand" in desc:
                additions.append(
                    "anatomically correct hands with exactly five fingers per hand"
                )
                if "subject" not in sections_changed:
                    sections_changed.append("subject")
                if "composition" not in sections_changed:
                    sections_changed.append("composition")
            elif "face" in cat:
                additions.append("natural facial expression, symmetric face, realistic eyes")
                if "subject" not in sections_changed:
                    sections_changed.append("subject")
            elif "artifact" in cat or "watermark" in desc:
                additions.append("no watermarks, no text artifacts, no distortions")
                if "negative_constraints" not in sections_changed:
                    sections_changed.append("negative_constraints")
            elif "lighting" in cat:
                additions.append("correct lighting direction, realistic shadows and highlights")
                if "lighting" not in sections_changed:
                    sections_changed.append("lighting")

        for issue in result.medium_severity_issues:
            desc = issue.description.lower()
            if "blur" in desc:
                additions.append("sharp focus, high detail, crisp edges")
                if "style" not in sections_changed:
                    sections_changed.append("style")
            elif "proportion" in desc:
                additions.append("correct body proportions, natural posture")
                if "subject" not in sections_changed:
                    sections_changed.append("subject")

        if not additions:
            additions.append("high quality, no artifacts, photorealistic, sharp focus")
            if "style" not in sections_changed:
                sections_changed.append("style")

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique = [a for a in additions if not (a in seen or seen.add(a))]  # type: ignore[func-returns-value]
        return prompt + ", " + ", ".join(unique), sections_changed

    def _compute_overall(
        self,
        result: VisionReviewResult,
        specialist_result: VisionReviewResult | None,
        hand_passes: bool,
        hqa_passes: bool,
    ) -> dict:
        issues = list(result.issues)
        if specialist_result:
            issues.extend(specialist_result.issues)

        hard_constraints = self._compute_hard_constraints(result, specialist_result, hand_passes, hqa_passes)
        quality_scores = self._compute_quality_scores(result, issues)
        composite = sum(quality_scores.values()) / max(len(quality_scores), 1) if quality_scores else 0.0

        anatomy_floor = getattr(self._config, "anatomy_floor_threshold", 6.0)
        anatomy_cap = getattr(self._config, "anatomy_quality_cap", 6.0)
        anatomy_component = quality_scores.get("anatomy")
        if anatomy_component is not None and anatomy_component < anatomy_floor:
            composite = min(composite, anatomy_cap)

        target_score = getattr(self._config, "target_quality_score", 85.0)

        all_hard_pass = all(c["passed"] for c in hard_constraints.values())
        if not all_hard_pass:
            overall_status = "FAIL"
            recommend_regeneration = True
        elif composite >= target_score:
            overall_status = "PASS"
            recommend_regeneration = False
        else:
            overall_status = "FAIL"
            recommend_regeneration = True

        failure_categories = [
            name
            for name, constraint in hard_constraints.items()
            if not constraint["passed"]
        ]
        # Add categories from quality score failures when all hard pass but score fails
        if (
            all_hard_pass
            and overall_status == "FAIL"
            and not failure_categories
        ):
            for key, score in quality_scores.items():
                if score < target_score:
                    failure_categories.append(key)

        summary_parts = []
        if not all_hard_pass:
            summary_parts.append("hard constraint failure")
        if failure_categories:
            summary_parts.append(f"failures: {', '.join(failure_categories)}")
        if not all_hard_pass:
            summary_parts.append("regeneration required")
        elif overall_status == "FAIL":
            summary_parts.append("below quality threshold")
        if overall_status == "PASS":
            summary_parts.append("all checks passed")

        return {
            "overall_status": overall_status,
            "overall_score": round(composite, 1),
            "recommend_regeneration": recommend_regeneration,
            "hard_constraints": hard_constraints,
            "quality_scores": {k: round(v, 1) for k, v in quality_scores.items()},
            "failure_categories": list(dict.fromkeys(failure_categories)),
            "summary": "; ".join(summary_parts) if summary_parts else "validated",
        }

    def _prompt_compliance_passed(self, result: VisionReviewResult) -> bool:
        categories = [i.category.lower() for i in result.issues]
        descriptions = " ".join(i.description.lower() for i in result.issues)
        if (
            any("prompt" in c and "compliance" in c for c in categories)
            or "prompt compliance" in descriptions
        ):
            failing = any(
                i.severity in ("HIGH", "CRITICAL")
                and ("prompt" in i.category.lower() or "compliance" in i.description.lower())
                for i in result.issues
            )
            return not failing
        return True

    def _compute_hard_constraints(
        self,
        result: VisionReviewResult,
        specialist_result: VisionReviewResult | None,
        hand_passes: bool,
        hqa_passes: bool,
    ) -> dict:
        issues = list(result.issues)
        if specialist_result:
            issues.extend(specialist_result.issues)

        def _high_sev(category_keywords: list[str]) -> bool:
            return any(
                i.severity in ("HIGH", "CRITICAL")
                and any(kw in i.category.lower() for kw in category_keywords)
                for i in issues
            )

        # Prompt compliance
        prompt_compliance_passed = self._prompt_compliance_passed(result)
        # Required visibility
        required_visibility_passed = hand_passes
        # Composition
        composition_passed = not _high_sev(["composition", "crop", "framing", "foreground", "background"])
        # Required objects
        required_objects_passed = not _high_sev(["object", "missing", "required"])
        # Anatomy
        anatomy_passed = not _high_sev(["anatomy", "hand", "finger", "face", "eye", "body", "limb", "arm", "leg", "proportion"])
        # Text / watermark
        text_watermark_passed = not _high_sev(["text", "watermark", "logo", "letter", "word", "subtitle", "signature"])

        def _reason(passed: bool) -> str:
            if passed:
                return "passed"
            return "failed"

        return {
            "prompt_compliance": {"passed": prompt_compliance_passed, "reason": _reason(prompt_compliance_passed)},
            "required_visibility": {"passed": required_visibility_passed, "reason": _reason(required_visibility_passed)},
            "composition": {"passed": composition_passed, "reason": _reason(composition_passed)},
            "required_objects": {"passed": required_objects_passed, "reason": _reason(required_objects_passed)},
            "anatomy": {"passed": anatomy_passed, "reason": _reason(anatomy_passed)},
            "text_watermark": {"passed": text_watermark_passed, "reason": _reason(text_watermark_passed)},
        }

    def _compute_quality_scores(self, result: VisionReviewResult, issues: list[VisionIssue]) -> dict:
        base = result.score if result.score > 0 else 85.0
        scores = {
            "prompt_adherence": base,
            "composition": base,
            "lighting": base,
            "anatomy": base,
            "realism": base,
            "storytelling": base,
        }
        sev_deduction = {"HIGH": 18.0, "CRITICAL": 20.0, "MEDIUM": 8.0, "LOW": 3.0}

        for issue in issues:
            category = issue.category.lower()
            deduction = sev_deduction.get(issue.severity, 8.0)

            if "composition" in category or "crop" in category or "framing" in category:
                scores["composition"] = max(0.0, scores["composition"] - deduction)
            if "lighting" in category or "shadow" in category:
                scores["lighting"] = max(0.0, scores["lighting"] - deduction)
            if any(
                kw in category
                for kw in ["anatomy", "hand", "finger", "face", "eye", "body", "limb", "arm", "leg"]
            ):
                scores["anatomy"] = max(0.0, scores["anatomy"] - deduction)
                scores["realism"] = max(0.0, scores["realism"] - deduction)
            if any(
                kw in category
                for kw in ["text", "watermark", "logo", "letter", "word", "subtitle", "signature"]
            ):
                scores["storytelling"] = max(0.0, scores["storytelling"] - deduction)

        return scores

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

    # ── VisualMetadata / PromptPackage helpers ───────────────────────────

    @staticmethod
    def _extract_visual_metadata(scene: dict) -> VisualMetadata | None:
        raw = scene.get("visual_metadata")
        if not raw or not isinstance(raw, dict):
            return None
        try:
            return VisualMetadata.model_validate(raw)
        except Exception:
            return None

    @staticmethod
    def _extract_prompt_package(scene: dict) -> PromptPackage | None:
        raw = scene.get("_prompt_package")
        if not raw or not isinstance(raw, dict):
            return None
        try:
            return PromptPackage(
                final_prompt=raw.get("final_prompt", ""),
                negative_prompt=raw.get("negative_prompt"),
                visual_profile=raw.get("visual_profile", ""),
                prompt_fingerprint=raw.get("prompt_fingerprint", ""),
                metadata_snapshot=raw.get("metadata_snapshot", {}),
                assembly_report=raw.get("assembly_report"),
            )
        except Exception:
            return None


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
