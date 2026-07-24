from __future__ import annotations

import json
from pathlib import Path

from ytfactory.config.settings import Settings
from video_core.domain.image import ImageRequest
from ytfactory.images.human_detector import compute_sharpness, detect_human_presence
from ytfactory.images.models import (
    ImageArtifact,
    ImageGenerationResult,
    ImageManifest,
)
from ytfactory.images.prompt_engine import (
    _DEFAULT_NEGATIVE_PROMPT,
    _PROVIDERS_WITH_NEGATIVE_PROMPTS,
    apply_hand_avoidance,
)
from ytfactory.images.repository import ImageRepository
from ytfactory.images.review_config import EscalationConfig, ImageReviewConfig
from ytfactory.images.review_engine import write_image_quality_summary
from ytfactory.images.review_models import SceneReviewArtifact
from video_core.providers.image.factory import get_image_provider
from ytfactory.workflow.image_remediation_orchestrator import ImageRemediationOrchestrator
from ytfactory.shared.pipeline_status import get_writer


class ImagePipeline:
    """Generate YouTube-ready images.

    Two independent remediation mechanisms exist in this pipeline:
      (a) tier-escalation loop in ``_run_generation_strategy`` — runs for every
          scene and can see ``overall_status`` from Vision QA.
      (b) ``ImageRemediationOrchestrator`` — runs only for scenes with humans,
          after tier-escalation has finished, and has its own ``max_attempts``/``auto_remediate``
          config with deeper anatomy/hand-avoidance passes.

    Do not merge these without a design decision: (b) may do something
    genuinely different from (a)'s generic escalation path.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._provider = get_image_provider(settings)
        self._repository = ImageRepository()
        self._uses_negative_prompts = (
            settings.image_provider.lower() in _PROVIDERS_WITH_NEGATIVE_PROMPTS
        )
        self._review_config = ImageReviewConfig.from_settings(settings)
        self._escalation_config = EscalationConfig.from_settings(settings)
        self._orchestrator: ImageRemediationOrchestrator | None = self._build_orchestrator()
        self._flagged_scenes: dict[int, dict] = {}

    def _build_orchestrator(self) -> ImageRemediationOrchestrator | None:
        """Build the remediation orchestrator if image review is enabled."""
        if not self._review_config.enabled:
            return None
        try:
            from video_core.providers.vision.factory import get_vision_provider

            vision = get_vision_provider(
                self._review_config.provider,
                local_model=self._review_config.local_model,
            )
            return ImageRemediationOrchestrator(self._review_config, vision, self._provider, settings=self._settings)
        except Exception:
            return None

    def _is_hero_scene(self, scene: dict) -> bool:
        importance = scene.get("importance", "").upper()
        shot_type = scene.get("shot_type", "").upper()
        return importance in ("HERO", "CLIMAX") or shot_type in ("HERO", "CLIMAX")

    def _adapt_prompt_for_tier(self, prompt: str, tier: int) -> str:
        tier_config = self._settings.image_model_registry.for_tier(tier) if hasattr(self._settings, "image_model_registry") else None
        if tier_config is None:
            return prompt
        tier_id = tier_config.id.lower()
        if "qwen-image" in tier_id:
            return f"{prompt}, cinematic lighting, rich environmental detail, enhanced realism, strong atmosphere"
        if "flux.1-dev" in tier_id:
            return (
                f"{prompt}, maximum realism, fine texture detail, rich environmental complexity, "
                "fine cinematic lighting, highest prompt fidelity"
            )
        return prompt

    def _score_image(
        self,
        scene: dict,
        image_path: Path,
        scoring_dir: Path,
    ) -> tuple[float, str, str]:
        scoring_dir.mkdir(parents=True, exist_ok=True)
        reviewer = self._create_single_shot_reviewer()
        if reviewer is None:
            return 0.0, "SKIP", "no_reviewer"
        try:
            artifact = reviewer.review_scene(scene, image_path, scoring_dir)
            overall_status = getattr(artifact, "overall_status", "") or artifact.status
            failure_reason = ""
            if overall_status == "FAIL":
                failure_categories = getattr(artifact, "failure_categories", [])
                if failure_categories:
                    failure_reason = ", ".join(failure_categories)
                else:
                    failure_reason = artifact.status
            return artifact.score, overall_status, failure_reason
        except Exception:
            return 0.0, "ERROR", "scoring_exception"

    def _run_generation_strategy(
        self,
        scene: dict,
        request: ImageRequest,
        output_path: Path,
        scene_with_dims: dict,
        output_dir: Path,
    ) -> Path:
        """Adaptive quality optimization with two-candidate generation and tier escalation."""
        base_prompt = request.prompt
        scoring_dir = output_dir / "scoring" / f"scene-{scene['index']:03d}"
        scoring_dir.mkdir(parents=True, exist_ok=True)

        target = self._escalation_config.target_quality_score
        retry_threshold = self._escalation_config.retry_threshold
        premium_threshold = self._escalation_config.premium_model_threshold

        # Hero scenes: skip tier 1, generate directly with tier 2
        if self._is_hero_scene(scene):
            tier2 = self._settings.image_model_registry.for_tier(2)
            hero_request = ImageRequest(
                prompt=self._adapt_prompt_for_tier(base_prompt, 2),
                output_path=output_path,
                width=request.width,
                height=request.height,
                negative_prompt=request.negative_prompt,
                model=tier2.id,
                provider=tier2.provider,
            )
            self._provider.generate(hero_request)
            score, overall_status, _ = self._score_image(scene_with_dims, output_path, scoring_dir / "hero")
            if score < target or overall_status == "FAIL":
                tier3 = self._settings.image_model_registry.for_tier(3)
                tier3_request = ImageRequest(
                    prompt=self._adapt_prompt_for_tier(base_prompt, 3),
                    output_path=output_path,
                    width=request.width,
                    height=request.height,
                    negative_prompt=request.negative_prompt,
                    model=tier3.id,
                    provider=tier3.provider,
                )
                output_path.unlink(missing_ok=True)
                self._provider.generate(tier3_request)
            return output_path

        # Stage 1: Two tier-1 candidates, keep highest scoring
        candidates = self._generate_two_candidates(
            scene, request, output_path, scene_with_dims, output_dir
        )
        if not candidates:
            return output_path

        best_score, best_path, best_overall_status, best_failure_reason = max(
            candidates, key=lambda item: item[0]
        )
        if best_path != output_path:
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            best_path.rename(output_path)
        for _, path, status, reason in candidates:
            if path.exists() and path != output_path:
                path.unlink(missing_ok=True)

        # Stage 2: Accept if quality target met and no hard-constraint failure
        if best_overall_status == "PASS" and best_score >= target:
            return output_path

        # Stage 2a: retry threshold met → refine and retry tier 1 up to max_prompt_refinements times
        refinement_count = 0
        current_score = best_score
        current_overall_status = best_overall_status
        current_failure_reason = best_failure_reason
        current_prompt = request.prompt
        max_refinements = self._escalation_config.max_prompt_refinements

        while (
            refinement_count < max_refinements
            and current_score < target
            and current_score >= retry_threshold
            and current_overall_status != "PASS"
        ):
            refined_prompt = self._refine_prompt_from_score(
                current_prompt, current_score, current_failure_reason
            )
            tier1 = self._settings.image_model_registry.for_tier(1)
            retry_request = ImageRequest(
                prompt=refined_prompt,
                output_path=output_path,
                width=request.width,
                height=request.height,
                negative_prompt=request.negative_prompt,
                model=tier1.id,
                provider=tier1.provider,
                seed=42,
            )
            output_path.unlink(missing_ok=True)
            self._provider.generate(retry_request)
            retry_score, retry_overall_status, retry_reason = self._score_image(
                scene_with_dims, output_path, scoring_dir / f"retry-{refinement_count + 1}"
            )
            refinement_count += 1
            if retry_overall_status == "PASS" and retry_score >= target:
                return output_path
            current_score = retry_score
            current_overall_status = retry_overall_status
            current_failure_reason = retry_reason
            current_prompt = refined_prompt

        best_score = current_score
        best_overall_status = current_overall_status
        best_failure_reason = current_failure_reason

        # Stage 3: Escalate to tier 2
        if best_score < premium_threshold or best_overall_status == "FAIL":
            tier2 = self._settings.image_model_registry.for_tier(2)
            tier2_request = ImageRequest(
                prompt=self._adapt_prompt_for_tier(base_prompt, 2),
                output_path=output_path,
                width=request.width,
                height=request.height,
                negative_prompt=request.negative_prompt,
                model=tier2.id,
                provider=tier2.provider,
            )
            output_path.unlink(missing_ok=True)
            self._provider.generate(tier2_request)
            tier2_score, tier2_overall_status, tier2_reason = self._score_image(
                scene_with_dims, output_path, scoring_dir / "tier2"
            )
            if tier2_score < premium_threshold or tier2_overall_status == "FAIL":
                tier3 = self._settings.image_model_registry.for_tier(3)
                tier3_request = ImageRequest(
                    prompt=self._adapt_prompt_for_tier(base_prompt, 3),
                    output_path=output_path,
                    width=request.width,
                    height=request.height,
                    negative_prompt=request.negative_prompt,
                    model=tier3.id,
                    provider=tier3.provider,
                )
                output_path.unlink(missing_ok=True)
                self._provider.generate(tier3_request)
                tier3_score, tier3_overall_status, tier3_reason = self._score_image(
                    scene_with_dims, output_path, scoring_dir / "tier3"
                )
                if tier3_overall_status == "FAIL" or tier3_score < target:
                    self._flagged_scenes[scene.get("index", 0)] = {
                        "status": "flagged_below_target",
                        "score": tier3_score,
                        "reason": tier3_reason,
                    }

        return output_path

    def _refine_prompt_from_score(self, prompt: str, score: float, failed_constraint: str = "") -> str:
        adaptations = []
        constraint_lower = failed_constraint.lower()
        if "anatomy" in constraint_lower or "hand" in constraint_lower:
            adaptations.append("anatomically correct hands with exactly five fingers per hand")
        if "composition" in constraint_lower or "crop" in constraint_lower or "framing" in constraint_lower:
            adaptations.append("strong composition, single focal point, natural leading lines")
        if "lighting" in constraint_lower or "shadow" in constraint_lower:
            adaptations.append("cinematic lighting, realistic shadows and highlights")
        if "face" in constraint_lower or "eye" in constraint_lower:
            adaptations.append("natural facial expression, symmetric face, realistic eyes")
        if "text" in constraint_lower or "watermark" in constraint_lower:
            adaptations.append("no text, no watermark, no artifacts")
        if "realism" in constraint_lower or "style" in constraint_lower:
            adaptations.append("photorealistic, high detail, correct anatomy, sharp focus")
        if not adaptations:
            if score < 8.5:
                adaptations.append("cinematic lighting, strong atmosphere")
            adaptations.append("photorealistic, high detail, correct anatomy, sharp focus")
        return f"{prompt}, {', '.join(adaptations)}"

    def _create_single_shot_reviewer(self) -> ImageReviewEngine | None:
        """Create a single-attempt review engine for candidate scoring."""
        try:
            from video_core.providers.vision.factory import get_vision_provider
            from dataclasses import replace

            vision = get_vision_provider(
                self._review_config.provider,
                local_model=self._review_config.local_model,
            )
            single_shot = replace(self._review_config, max_attempts=1, auto_remediate=False)
            return ImageReviewEngine(single_shot, vision, self._provider)
        except Exception:
            return None

    def _generate_two_candidates(
        self,
        scene: dict,
        request: ImageRequest,
        output_path: Path,
        scene_with_dims: dict,
        output_dir: Path,
    ) -> list[tuple[float, Path, str, str]]:
        """Generate two tier-1 candidates, score both with Vision QA, return candidate tuples."""
        scoring_dir = output_dir / "scoring" / f"scene-{scene['index']:03d}"
        scoring_dir.mkdir(parents=True, exist_ok=True)

        candidates: list[tuple[float, Path, str, str]] = []
        reviewer = self._create_single_shot_reviewer()

        for i, seed in enumerate([None, 42], start=1):
            candidate_path = output_path.with_suffix(f".candidate{i}.png")
            candidate_request = ImageRequest(
                prompt=request.prompt,
                output_path=candidate_path,
                width=request.width,
                height=request.height,
                negative_prompt=request.negative_prompt,
                model=request.model,
                provider=request.provider,
                seed=seed,
            )

            try:
                self._provider.generate(candidate_request)
            except Exception:
                continue

            score, overall_status, failure_reason = (0.0, "SKIP", "generation_failed")
            if reviewer is not None:
                score, overall_status, failure_reason = self._score_image(
                    scene_with_dims, candidate_path, scoring_dir / f"candidate{i}"
                )

            candidates.append((score, candidate_path, overall_status, failure_reason))

        if not candidates:
            try:
                self._provider.generate(request)
            except Exception:
                pass
            return candidates

        return candidates

    def run(
        self,
        project_id: str,
    ) -> ImageGenerationResult:

        project_dir = Path("workspace/jobs") / project_id

        scene_plan_file = project_dir / "scenes" / "scene-plan.json"

        if not scene_plan_file.exists():
            raise FileNotFoundError(f"Scene plan not found: {scene_plan_file}")

        with open(
            scene_plan_file,
            encoding="utf-8",
        ) as f:
            scene_plan = json.load(f)

        scenes = scene_plan["scenes"]
        scenes = apply_hand_avoidance(scenes, self._settings.image_provider)

        output_dir = project_dir / "images"
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        manifest = ImageManifest()
        review_artifacts: list[SceneReviewArtifact] = []
        self._flagged_scenes = {}

        total = len(scenes)

        _w = get_writer()
        if _w:
            _w.stage_start("image_generation", total=total)
        else:
            print(
                f"\nGenerating {total} YouTube images "
                f"({self._settings.image_width}x{self._settings.image_height})\n"
            )

        for index, scene in enumerate(
            scenes,
            start=1,
        ):
            filename = f"scene-{scene['index']:03d}.png"

            output_path = output_dir / filename

            # Asset scenes skip AI image generation and vision review entirely.
            if scene.get("scene_type") in ("asset", "brand_card"):
                asset_path = Path(scene.get("asset_path", ""))
                if not _w:
                    print(f"[{index}/{total}] {filename} (asset — skipping generation)")
                manifest.images.append(
                    ImageArtifact(
                        scene_index=scene["index"],
                        prompt="",
                        filename=filename,
                        path=asset_path if asset_path.exists() else output_path,
                    )
                )
                if _w:
                    _w.stage_progress(index)
                continue

            # Apply Visual Intelligence Prompt Builder if metadata is populated.
            _vi_negative_prompt: str | None = None
            _visual_metadata_raw = scene.get("visual_metadata", {})
            if _visual_metadata_raw:
                try:
                    from video_core.visual_intelligence.prompt_builder import PromptBuilder
                    _prompt_builder = PromptBuilder()
                    _package = _prompt_builder.build_from_scene(scene)
                    if _package.visual_profile:
                        scene = {**scene, "visual_prompt": _package.final_prompt}
                        _vi_negative_prompt = _package.negative_prompt
                except Exception:
                    _vi_negative_prompt = None

            negative_prompt = (
                scene.get("negative_prompt") or _DEFAULT_NEGATIVE_PROMPT
                if self._uses_negative_prompts
                else None
            )
            from video_core.visual_intelligence.prompt_builder import merge_negative_prompts
            negative_prompt = merge_negative_prompts(negative_prompt, _vi_negative_prompt)
            tier1 = self._settings.image_model_registry.for_tier(1)
            request = ImageRequest(
                prompt=scene["visual_prompt"],
                output_path=output_path,
                width=self._settings.image_width,
                height=self._settings.image_height,
                negative_prompt=negative_prompt,
                model=tier1.id,
                provider=tier1.provider,
            )

            image_was_new = not output_path.exists()

            prompt_text = scene.get("visual_prompt", "")
            has_humans = detect_human_presence(prompt_text)

            if image_was_new:
                if not _w:
                    print(f"[{index}/{total}] {filename}")

                scene_with_dims = {
                    **scene,
                    "width": self._settings.image_width,
                    "height": self._settings.image_height,
                }
                if (
                    self._review_config.enabled
                    and self._orchestrator is not None
                ):
                    output_path = self._run_generation_strategy(
                        scene, request, output_path, scene_with_dims, output_dir
                    )
                else:
                    self._provider.generate(request)

                # Human quality validation: regenerate if sharpness is below threshold
                if (
                    has_humans
                    and self._settings.image_human_max_retries > 0
                ):
                    sharpness = compute_sharpness(output_path)
                    threshold = self._settings.image_human_min_sharpness
                    max_retries = self._settings.image_human_max_retries
                    for attempt in range(max_retries):
                        if sharpness >= threshold:
                            break
                        if _w:
                            _w.stage_retry(attempt + 1, max_retries, message=f"Scene {index}: sharpness {sharpness:.1f} < {threshold}")
                        else:
                            print(
                                f"  ↻ Human scene sharpness {sharpness:.1f} < {threshold} — "
                                f"retry {attempt + 1}/{max_retries}"
                            )
                        output_path.unlink(missing_ok=True)
                        self._provider.generate(request)
                        sharpness = compute_sharpness(output_path)
                    if sharpness < threshold and not _w:
                        print(
                            f"  ⚠ {filename}: sharpness {sharpness:.1f} still below "
                            f"{threshold} after {max_retries} retries"
                        )
            elif not _w:
                print(f"[{index}/{total}] {filename} (skip generation)")

            # Vision review + auto-remediation — only for newly generated images
            # that contain humans. Non-human scenes (landscapes, objects, abstract)
            # don't need anatomical review; skipping them cuts total time ~60-70%.
            if (
                image_was_new
                and has_humans
                and self._orchestrator is not None
                and output_path.exists()
            ):
                scene_with_dims = {
                    **scene,
                    "width": self._settings.image_width,
                    "height": self._settings.image_height,
                }
                review_artifact = self._orchestrator.review_scene(
                    scene=scene_with_dims,
                    image_path=output_path,
                    output_dir=output_dir,
                )
                review_artifacts.append(review_artifact)
                display_status = getattr(review_artifact, "overall_status", "") or review_artifact.status
                status_tag = (
                    "PASS"
                    if display_status == "PASS"
                    else display_status
                )
                if not _w:
                    print(
                        f"  ✦ Vision review: {status_tag} "
                        f"(score={review_artifact.score:.0f}, "
                        f"attempts={review_artifact.attempts})"
                    )

            flagged = self._flagged_scenes.get(scene["index"], {})
            manifest.images.append(
                ImageArtifact(
                    scene_index=scene["index"],
                    prompt=scene["visual_prompt"],
                    filename=filename,
                    path=output_path,
                    qa_status=flagged.get("status", ""),
                    qa_score=flagged.get("score", 0.0),
                    qa_failure_reason=flagged.get("reason", ""),
                )
            )
            if _w:
                _w.stage_progress(index)

        # Write global image quality summary
        if review_artifacts:
            write_image_quality_summary(review_artifacts, output_dir)

        self._repository.save_manifest(
            output_dir,
            manifest,
        )

        if self._flagged_scenes:
            flagged_path = output_dir / "flagged_scenes.json"
            flagged_path.write_text(
                json.dumps(
                    [
                        {"scene_index": idx, **data}
                        for idx, data in self._flagged_scenes.items()
                    ],
                    indent=2,
                ),
                encoding="utf-8",
            )

        if _w:
            _w.stage_complete()
        else:
            print("\nImage generation completed.\n")

        return ImageGenerationResult(
            manifest=manifest,
            output_directory=output_dir,
        )
