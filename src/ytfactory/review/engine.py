"""Video Quality Review Engine V1 — orchestrator.

Runs the four validation stages in order, aggregates results into a
ReviewReport, determines PASS / FAIL, and returns the report.

Extension points:
  - Root Cause Analysis Engine V1: implemented — populates review/root-cause*.json
  - Quality Scoring Engine V1: implemented — sets ReviewReport.quality_score
  - Engine Feedback Loop V1: implemented — populates review/engine-feedback*.json
  - Video Review Debug Mode V1: implemented — populates review/debug/ subdirectory
  - Auto Remediation Engine V1: consumes ReviewReport to trigger re-runs
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ytfactory.review.config import ReviewConfig
from ytfactory.review.debug.collector import DebugCollector
from ytfactory.review.debug.config import DebugConfig
from ytfactory.review.debug.reporter import DebugReporter
from ytfactory.review.efl.config import EFLConfig
from ytfactory.review.efl.engine import EngineFeedbackLoopEngine
from ytfactory.review.efl.reporter import EFLReporter
from ytfactory.review.models import ReviewReport, SceneReview
from ytfactory.review.rca.config import RCAConfig
from ytfactory.review.rca.engine import RootCauseAnalysisEngine
from ytfactory.review.rca.reporter import RCAReporter
from ytfactory.review.scoring.config import QualityScoringConfig
from ytfactory.review.scoring.engine import QualityScoringEngine
from ytfactory.review.scoring.reporter import QualityScoringReporter
from ytfactory.review.stages.asset_integrity import AssetIntegrityStage
from ytfactory.review.stages.content import ContentReviewStage
from ytfactory.review.stages.production import ProductionQualityStage
from ytfactory.review.stages.timeline import TimelineReviewStage
from ytfactory.review.validation.config import ValidationRulesConfig
from ytfactory.review.validation.models import ValidationReport, ValidationResult
from ytfactory.review.validation.reporter import ValidationReporter
from ytfactory.review.validation.runner import ValidationRunner
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.retention.scoring import build_post_render_score, combine_scores
from ytfactory.retention.models import RetentionScoreResult


class VideoQualityReviewEngine:
    """
    Orchestrate all four review stages, produce a ReviewReport, and
    determine PASS / FAIL.

    Usage:
        engine = VideoQualityReviewEngine()
        report = engine.review(project_id)
        if report.verdict == "FAIL":
            ...
    """

    def __init__(
        self,
        config: ReviewConfig | None = None,
        validation_config: ValidationRulesConfig | None = None,
        rca_config: RCAConfig | None = None,
        scoring_config: QualityScoringConfig | None = None,
        efl_config: EFLConfig | None = None,
        debug_config: DebugConfig | None = None,
    ) -> None:
        self._config = config or ReviewConfig()
        self._val_config = validation_config or ValidationRulesConfig()
        self._rca_config = rca_config or RCAConfig()
        self._scoring_config = scoring_config or QualityScoringConfig()
        self._efl_config = efl_config or EFLConfig()
        self._debug_config = debug_config or DebugConfig()
        self._stages = [
            AssetIntegrityStage(self._config),
            TimelineReviewStage(self._config),
            ContentReviewStage(self._config),
            ProductionQualityStage(self._config),
        ]

    # ── Public API ────────────────────────────────────────────────────────

    def review(
        self,
        project_id: str,
        pre_render_score: dict | None = None,
    ) -> ReviewReport:
        """Run the full review pipeline and return a ReviewReport."""
        t0 = time.perf_counter()
        timestamp = datetime.now(timezone.utc).isoformat()

        project_dir = Path(WORKSPACE_DIR) / project_id
        scenes = _load_scenes(project_dir)

        # Build per-scene review objects (shared across stages)
        scene_reviews = [
            SceneReview(
                index=s.get("index", i + 1),
                scene_type=s.get("scene_type", "generated_image"),
            )
            for i, s in enumerate(scenes)
        ]

        # Shared context dict — stages may deposit discovered values here
        context: dict = {}

        # Populate BGM status so BGMValidator can skip when music is disabled
        try:
            from ytfactory.config.settings import Settings as _Settings

            _s = _Settings()
            context["bgm_enabled"] = _s.bgm_enabled
            context["bgm_category"] = _s.bgm_category
            context["bgm_vad_enabled"] = _s.bgm_vad_enabled
            context["bgm_phrase_gap_ms"] = _s.bgm_phrase_gap_ms
            context["bgm_long_silence_ms"] = _s.bgm_long_silence_ms
        except Exception:
            context["bgm_enabled"] = False

        # Post-render artifact paths for retention QA detectors
        context["final_video_path"] = str(project_dir / "video" / "final.mp4")
        context["cta_timing_path"] = str(project_dir / "cta" / "cta-timing.json")
        context["script_md_path"] = str(project_dir / "script" / "script.md")
        context["subtitle_report_path"] = str(project_dir / "subtitles" / "subtitle-report.json")
        context["audio_dir"] = str(project_dir / "audio")
        context["scene_plan_path"] = str(project_dir / "scenes" / "scene-plan.json")

        # Debug collector — zero overhead when level is OFF
        debug = DebugCollector(self._debug_config.level)

        # ── Run stages ────────────────────────────────────────────────────
        stage_results = []
        with debug.time_layer("stages"):
            for stage in self._stages:
                result = stage.run(project_dir, scenes, scene_reviews, context)
                stage_results.append(result)

        # ── Aggregate errors / warnings ───────────────────────────────────
        all_errors: list[str] = []
        all_warnings: list[str] = []
        for sr in stage_results:
            all_errors.extend(sr.errors)
            all_warnings.extend(sr.warnings)

        # Add per-scene issues as warnings (not critical errors)
        for sv in scene_reviews:
            for issue in sv.issues:
                all_warnings.append(f"Scene {sv.index}: {issue}")

        # ── Validation Rules V1 ───────────────────────────────────────────
        val_runner = ValidationRunner(self._val_config)
        with debug.time_layer("validation"):
            val_report = val_runner.run(project_dir, scenes, context)
        ValidationReporter().write(val_report)

        # Critical validation failures bubble up into all_errors → affect verdict
        for failure in val_report.critical_failures:
            all_errors.append(f"[validation:{failure.rule_id}] {failure.description}")

        # ── Script Enhancer Feedback (editors_notes → synthetic validation results) ─
        enhancer_synthetic, enhancer_warnings = _load_enhancement_feedback(project_dir)
        val_report.results.extend(enhancer_synthetic)
        for w in enhancer_warnings:
            all_warnings.append(w)
        for sv in scene_reviews:
            sv.issues.extend(enhancer_warnings)

        # ── Pipeline QA Scoring ────────────────────────────────────────────
        post_render_score = build_post_render_score(val_report)
        if pre_render_score:
            pre_render = RetentionScoreResult(
                total=pre_render_score.get("total", 100.0),
                breakdown=pre_render_score.get("breakdown", {}),
                violations=pre_render_score.get("violations", []),
                passed=pre_render_score.get("passed", True),
            )
            pipeline_qa_score = combine_scores(pre_render, post_render_score)
        else:
            pipeline_qa_score = post_render_score

        hard_reject_keywords = ("[P1a]", "MOT_005", "STOR_006")
        has_hard_reject = any(
            kw in v for v in pipeline_qa_score.violations for kw in hard_reject_keywords
        )
        if pipeline_qa_score.total < 85.0:
            all_errors.append(
                f"[pipeline_qa] Score {pipeline_qa_score.total:.0f}/100 below upload gate "
                f"(≥85 required)"
            )
        if has_hard_reject:
            for v in pipeline_qa_score.violations:
                if any(kw in v for kw in hard_reject_keywords):
                    all_errors.append(f"[pipeline_qa:{v}]")

        # ── Root Cause Analysis Engine V1 ────────────────────────────────
        rca_engine = RootCauseAnalysisEngine(self._rca_config)
        with debug.time_layer("rca"):
            rca_report = rca_engine.analyze(project_dir, scenes, val_report, context)
        RCAReporter().write(rca_report)

        # ── Quality Scoring Engine V1 ─────────────────────────────────────
        score_engine = QualityScoringEngine(self._scoring_config)
        with debug.time_layer("scoring"):
            score_report = score_engine.score(
                project_dir, scenes, val_report, rca_report, context
            )
        QualityScoringReporter().write(score_report)

        # ── Engine Feedback Loop V1 ───────────────────────────────────────
        efl_engine = EngineFeedbackLoopEngine(self._efl_config)
        with debug.time_layer("efl"):
            efl_report = efl_engine.generate(
                project_dir, scenes, val_report, rca_report, score_report, context
            )
        EFLReporter().write(efl_report)

        # ── PASS / FAIL ───────────────────────────────────────────────────
        has_critical = bool(all_errors)
        if self._config.fail_on_warnings:
            verdict = "PASS" if not has_critical and not all_warnings else "FAIL"
        else:
            verdict = "PASS" if not has_critical else "FAIL"

        # ── Final video metadata ──────────────────────────────────────────
        final_video = project_dir / "video" / "final.mp4"
        final_size_mb = 0.0
        if final_video.exists():
            final_size_mb = final_video.stat().st_size / (1024 * 1024)

        elapsed = time.perf_counter() - t0

        # ── Video Review Debug Mode V1 ────────────────────────────────────
        debug_report_dict: dict | None = None
        if debug.enabled:
            debug_report = debug.build_report(
                project_id=project_id,
                timestamp=timestamp,
                overall_verdict=verdict,
                all_errors=all_errors,
                all_warnings=all_warnings,
                stage_results=stage_results,
                scene_reviews=scene_reviews,
                val_report=val_report,
                rca_report=rca_report,
                score_report=score_report,
                efl_report=efl_report,
            )
            DebugReporter().write(debug_report)
            debug_report_dict = debug_report.to_dict()

        report = ReviewReport(
            project_id=project_id,
            verdict=verdict,
            timestamp=timestamp,
            total_scenes=len(scenes),
            scenes_passed=sum(1 for sv in scene_reviews if sv.passed),
            scenes_failed=sum(1 for sv in scene_reviews if not sv.passed),
            stage_results=stage_results,
            scene_reviews=scene_reviews,
            all_errors=all_errors,
            all_warnings=all_warnings,
            final_video_path=str(final_video) if final_video.exists() else "",
            final_video_size_mb=round(final_size_mb, 2),
            final_video_duration_seconds=context.get(
                "final_video_duration_seconds", 0.0
            ),
            processing_time_seconds=round(elapsed, 3),
            validation_report=val_report.to_dict(),
            pipeline_qa_score={
                "total": pipeline_qa_score.total,
                "breakdown": pipeline_qa_score.breakdown,
                "violations": pipeline_qa_score.violations,
                "passed": pipeline_qa_score.passed,
            },
            rca_report=rca_report.to_dict(),
            quality_score=score_report.overall_score,
            quality_score_report=score_report.to_dict(),
            efl_report=efl_report.to_dict(),
            debug_report=debug_report_dict,
        )

        return report


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_scenes(project_dir: Path) -> list[dict]:
    """Load scene-plan.json; return empty list when missing."""
    scene_plan = project_dir / "scenes" / "scene-plan.json"
    if not scene_plan.exists():
        return []
    try:
        data = json.loads(scene_plan.read_text(encoding="utf-8"))
        return data.get("scenes", [])
    except (json.JSONDecodeError, OSError):
        return []


def _load_enhancement_feedback(
    project_dir: Path,
) -> tuple[list[ValidationResult], list[str]]:
    """Load enhancement-report.json editors_notes and convert into synthetic
    ValidationResult objects for retention scoring, plus per-scene warnings.

    Returns (synthetic_results, warnings).
    Degrades gracefully when the report or editors_notes is missing/empty.
    """
    report_path = project_dir / "script" / "enhancement-report.json"
    if not report_path.exists():
        return [], []

    try:
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], []

    editors_notes = report_data.get("editors_notes") or {}
    if not editors_notes:
        return [], []

    synthetic: list[ValidationResult] = []
    warnings: list[str] = []
    now = datetime.now(timezone.utc).isoformat()

    rule_skips = editors_notes.get("rule_skips", "")
    if rule_skips and rule_skips.lower() not in ("none", "", "n/a"):
        desc = f"Script enhancer skipped/partially applied structural rules: {rule_skips}"
        synthetic.append(
            ValidationResult(
                rule_id="ENH_SF_RULE",
                category="script",
                status="WARNING",
                severity="medium",
                description=desc,
                evidence="editors_notes.rule_skips",
                confidence=0.8,
                responsible_engine="script_enhancer",
                timestamp=now,
        debug_metadata={"source": "editors_notes"},
            )
        )
        warnings.append(f"[script_enhancer] {desc}")

    factual_gaps = editors_notes.get("factual_gaps", "")
    if factual_gaps and factual_gaps.lower() not in ("none", "", "n/a"):
        desc = f"Factual gaps noted by script enhancer: {factual_gaps}"
        synthetic.append(
            ValidationResult(
                rule_id="ENH_CONTENT",
                category="script",
                status="WARNING",
                severity="medium",
                description=desc,
                evidence="editors_notes.factual_gaps",
                confidence=0.8,
                responsible_engine="script_enhancer",
                timestamp=now,
        debug_metadata={"source": "editors_notes"},
            )
        )
        warnings.append(f"[script_enhancer] {desc}")

    dominant_symbol = editors_notes.get("dominant_visual_symbol", "")
    if dominant_symbol and dominant_symbol.lower() not in ("none", "", "n/a"):
        script_path = project_dir / "script" / "script.md"
        symbol_present = False
        if script_path.exists():
            try:
                script_text = script_path.read_text(encoding="utf-8").lower()
                symbol_present = dominant_symbol.lower() in script_text
            except OSError:
                pass

        if symbol_present:
            desc = f"Dominant visual symbol '{dominant_symbol}' is present in script."
            synthetic.append(
                ValidationResult(
                    rule_id="ENH_VISUAL",
                    category="script",
                    status="PASS",
                    severity="low",
                    description=desc,
                    evidence="editors_notes.dominant_visual_symbol",
                    confidence=1.0,
                    responsible_engine="script_enhancer",
                    timestamp=now,
            debug_metadata={"source": "editors_notes", "present_in_script": True},
                )
            )
        else:
            desc = (
                f"Dominant visual symbol '{dominant_symbol}' was identified by the "
                f"script enhancer but does not appear in the final script. "
                f"Verify this is represented in visual assets."
            )
            synthetic.append(
                ValidationResult(
                    rule_id="ENH_VISUAL",
                    category="script",
                    status="WARNING",
                    severity="medium",
                    description=desc,
                    evidence="editors_notes.dominant_visual_symbol",
                    confidence=0.6,
                    responsible_engine="script_enhancer",
                    timestamp=now,
            debug_metadata={"source": "editors_notes", "present_in_script": False},
                )
            )
            warnings.append(f"[script_enhancer] {desc}")

    return synthetic, warnings
