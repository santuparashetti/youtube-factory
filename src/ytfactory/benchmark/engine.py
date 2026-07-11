"""Benchmark engine — orchestrates production ImageReviewEngine across models.

Design
------
The engine never reimplements review logic. It wires together the existing
production components in the same order ImagePipeline does:

    get_vision_provider(model_key)
    → ImageReviewEngine(config, vision_provider, _NullImageProvider())
    → engine.review_scene(scene_dict, image_path, output_dir)

``auto_remediate=False`` and ``max_attempts=1`` ensure benchmark runs are
read-only (no image regeneration). The Technical QA check (OpenCV sharpness)
still runs because it is part of ``ImageReviewEngine.review_scene()``.

To add a new model to the benchmark: add a registry entry and download the
bundle. No code changes here.
"""

from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

from ytfactory.domain.image import ImageRequest, ImageResponse
from ytfactory.images.review_config import ImageReviewConfig
from ytfactory.images.review_engine import ImageReviewEngine
from video_core.providers.image.base import ImageProvider
from video_core.providers.vision.factory import get_vision_provider

from .dataset import BenchmarkDataset
from .hard_fails import detect_hard_fails
from .models import (
    BenchmarkReport,
    BenchmarkScene,
    ModelMetrics,
    SceneResult,
)

# ── Severity → deduction table ────────────────────────────────────────────────

_DEDUCTIONS = {"LOW": 5, "MEDIUM": 15, "HIGH": 30, "CRITICAL": 50}

# Issue category → QA dimension
_TECHNICAL_CATS = frozenset({"anatomy", "face", "artifact"})
_CINEMATIC_CATS = frozenset({"lighting", "cinematic"})
_NARRATIVE_CATS = frozenset({"environment"})


# ── Null image provider (benchmark never regenerates images) ──────────────────


class _NullImageProvider(ImageProvider):
    """Satisfies ImageReviewEngine's constructor — generate() is never called
    when ``auto_remediate=False``."""

    def generate(self, request: ImageRequest) -> ImageResponse:  # pragma: no cover
        return ImageResponse(
            file=request.output_path,
            provider="null",
            width=request.width,
            height=request.height,
        )


# ── QA sub-score helpers ──────────────────────────────────────────────────────


def _qa_scores(raw_issues: list[dict]) -> tuple[float, float, float]:
    """Derive (narrative, technical, cinematic) sub-scores from raw issue dicts.

    Each sub-score starts at 100 and is reduced by the severity deduction of
    every issue whose category maps to that dimension.
    """
    narrative = 100.0
    technical = 100.0
    cinematic = 100.0

    for issue in raw_issues:
        cat = str(issue.get("category", "")).lower()
        sev = str(issue.get("severity", "MEDIUM")).upper()
        deduct = float(_DEDUCTIONS.get(sev, 15))

        if cat in _TECHNICAL_CATS:
            technical = max(0.0, technical - deduct)
        elif cat in _CINEMATIC_CATS:
            cinematic = max(0.0, cinematic - deduct)
        elif cat in _NARRATIVE_CATS:
            narrative = max(0.0, narrative - deduct)

    return narrative, technical, cinematic


def _recommendation(artifact) -> str:  # SceneReviewArtifact
    status = (artifact.status or "SKIP").upper()
    if status == "PASS":
        return "PASS"
    if status in ("SKIP", "ERROR"):
        return status
    # FAIL
    if artifact.recommend_regeneration:
        return "REGENERATE"
    return "MANUAL_REVIEW"


# ── Public API ────────────────────────────────────────────────────────────────


def _scene_index(scene_id: str) -> int:
    """Extract numeric index from scene id such as 'scene-037' → 37."""
    parts = scene_id.split("-")
    for part in reversed(parts):
        if part.isdigit():
            return int(part)
    return 1


def resolve_installed_vision_models() -> list[str]:
    """Return registry keys for all enabled models with image_review capability."""
    from ytfactory.models import LocalAIModelManager

    manager = LocalAIModelManager()
    return [
        name
        for name, entry in manager._registry.items()
        if entry.enabled and "image_review" in entry.capabilities
    ]


class BenchmarkEngine:
    """Runs the production review pipeline across models and scenes.

    Parameters
    ----------
    base_dir:
        Repo root — passed to LAMM and VisionProvider.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or Path.cwd()

    # ── Public entry point ────────────────────────────────────────────────

    def run(
        self,
        dataset: BenchmarkDataset,
        models: list[str],
        output_dir: Path,
    ) -> BenchmarkReport:
        """Run the benchmark and return a ``BenchmarkReport``.

        Parameters
        ----------
        dataset:
            Loaded ``BenchmarkDataset`` (scenes + expected failures).
        models:
            Registry keys to evaluate (one run per model per scene).
        output_dir:
            Root directory for per-scene JSON files.
            Structure: ``output_dir/<model_key>/<scene_id>.json``
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        all_results: dict[str, list[SceneResult]] = {}
        all_metrics: dict[str, ModelMetrics] = {}

        for model_key in models:
            logger.info("Benchmarking model: {}", model_key)
            model_out = output_dir / model_key
            model_out.mkdir(parents=True, exist_ok=True)

            results = self._run_model(model_key, dataset.scenes, model_out)
            all_results[model_key] = results
            all_metrics[model_key] = self._compute_metrics(model_key, results)

        winner = self._pick_winner(all_metrics)

        return BenchmarkReport(
            dataset_path=str(dataset.path),
            total_scenes=len(dataset.scenes),
            bad_scenes=len(dataset.bad_scenes),
            good_scenes=len(dataset.good_scenes),
            models=list(models),
            scene_results=all_results,
            metrics=all_metrics,
            winner=winner,
        )

    # ── Per-model runner ──────────────────────────────────────────────────

    def _run_model(
        self,
        model_key: str,
        scenes: list[BenchmarkScene],
        model_out: Path,
    ) -> list[SceneResult]:
        """Run all scenes through the production review engine for *model_key*."""
        try:
            vision = get_vision_provider("local", local_model=model_key, base_dir=self._base_dir)
        except Exception as exc:
            logger.error("Cannot create vision provider for '{}': {}", model_key, exc)
            return [
                self._error_result(scene, model_key, f"Provider init failed: {exc}")
                for scene in scenes
            ]

        config = ImageReviewConfig(
            enabled=True,
            provider="local",
            local_model=model_key,
            max_attempts=1,       # benchmark is read-only — no regeneration
            auto_remediate=False,
        )
        engine = ImageReviewEngine(config, vision, _NullImageProvider())

        results: list[SceneResult] = []
        for scene in scenes:
            result = self._run_scene(engine, scene, model_key, model_out)
            results.append(result)
            # Write per-scene JSON immediately
            _write_json(result.to_dict(), model_out / f"{scene.id}.json")

        return results

    # ── Per-scene runner ──────────────────────────────────────────────────

    def _run_scene(
        self,
        engine: ImageReviewEngine,
        scene: BenchmarkScene,
        model_key: str,
        model_out: Path,
    ) -> SceneResult:
        if not scene.image.exists():
            return self._error_result(
                scene, model_key, f"Image not found: {scene.image}"
            )

        scene_dict = {
            "index": _scene_index(scene.id),
            "visual_prompt": scene.visual_prompt or scene.notes or scene.id,
            "scene_type": "generated_image",
            "width": 1920,
            "height": 1080,
        }

        t0 = time.perf_counter()
        try:
            artifact = engine.review_scene(scene_dict, scene.image, model_out)
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.warning("review_scene error for {} / {}: {}", scene.id, model_key, exc)
            return self._error_result(scene, model_key, str(exc), elapsed)
        elapsed = (time.perf_counter() - t0) * 1000

        raw_issues: list[dict] = list(artifact.issues)  # already list[dict]
        narrative, technical, cinematic = _qa_scores(raw_issues)
        recommendation = _recommendation(artifact)
        detected, matches = detect_hard_fails(
            # Re-parse issues as VisionIssue objects for the matcher
            _dicts_to_vision_issues(raw_issues),
            scene.expected_failures,
        )

        return SceneResult(
            scene=scene.id,
            model=model_key,
            narrative_score=narrative,
            technical_score=technical,
            cinematic_score=cinematic,
            overall_score=float(artifact.score),
            recommendation=recommendation,
            hard_fail=recommendation == "REGENERATE",
            detected_failures=detected,
            expected_failures=list(scene.expected_failures),
            hard_fail_matches=matches,
            latency_ms=elapsed,
            confidence=float(artifact.confidence),
            raw_issues=raw_issues,
            error=artifact.error or "",
        )

    # ── Metrics aggregation ───────────────────────────────────────────────

    def _compute_metrics(
        self,
        model_key: str,
        results: list[SceneResult],
    ) -> ModelMetrics:
        m = ModelMetrics(model=model_key)

        for r in results:
            if r.recommendation in ("SKIP", "ERROR"):
                continue

            m.scene_count += 1
            m.total_latency_ms += r.latency_ms
            m.total_narrative += r.narrative_score
            m.total_technical += r.technical_score
            m.total_cinematic += r.cinematic_score

            is_bad = bool(r.expected_failures)
            predicted_fail = r.recommendation == "REGENERATE"

            if is_bad and predicted_fail:
                m.tp += 1
            elif not is_bad and predicted_fail:
                m.fp += 1
            elif not is_bad and not predicted_fail:
                m.tn += 1
            else:  # is_bad and not predicted_fail
                m.fn += 1

        return m

    # ── Winner selection ──────────────────────────────────────────────────

    @staticmethod
    def _pick_winner(metrics: dict[str, ModelMetrics]) -> str | None:
        if len(metrics) < 2:
            return None
        ranked = sorted(metrics.values(), key=lambda m: m.f1, reverse=True)
        if len(ranked) >= 2 and ranked[0].f1 == ranked[1].f1:
            return None  # tied
        return ranked[0].model if ranked else None

    # ── Error result helper ───────────────────────────────────────────────

    @staticmethod
    def _error_result(
        scene: BenchmarkScene,
        model: str,
        error: str,
        latency_ms: float = 0.0,
    ) -> SceneResult:
        return SceneResult(
            scene=scene.id,
            model=model,
            narrative_score=0.0,
            technical_score=0.0,
            cinematic_score=0.0,
            overall_score=0.0,
            recommendation="ERROR",
            hard_fail=False,
            detected_failures=[],
            expected_failures=list(scene.expected_failures),
            hard_fail_matches=[],
            latency_ms=latency_ms,
            error=error,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _dicts_to_vision_issues(raw: list[dict]):
    """Convert raw issue dicts from SceneReviewArtifact back to VisionIssue."""
    from video_core.providers.vision.models import IssueSeverity, VisionIssue

    issues = []
    for d in raw:
        try:
            sev = IssueSeverity(str(d.get("severity", "MEDIUM")).upper())
        except ValueError:
            sev = IssueSeverity.MEDIUM
        issues.append(
            VisionIssue(
                category=str(d.get("category", "artifact")),
                description=str(d.get("description", "")),
                severity=sev,
                location=str(d.get("location", "")),
            )
        )
    return issues


def _write_json(data: dict, path: Path) -> None:
    import json

    try:
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not write benchmark JSON {}: {}", path, exc)
