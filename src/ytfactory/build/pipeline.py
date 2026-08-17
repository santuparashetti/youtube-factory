from loguru import logger
from rich.console import Console
from rich.rule import Rule

from ytfactory.config.settings import Settings
from ytfactory.incremental.engine import IncrementalBuildEngine
from ytfactory.scenes.repository.scene_repository import SceneRepository
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.shared.paths import safe_project_dir

from ytfactory.animate.pipeline import AnimatePipeline
from ytfactory.captions.pipeline import CaptionPipeline
from ytfactory.cta.pipeline import CTAPipeline
from ytfactory.images.pipeline import ImagePipeline
from ytfactory.publish.pipeline import PublishPipeline
from ytfactory.review.pipeline import ReviewPipeline
from ytfactory.review.remediation.config import RemediationConfig
from ytfactory.review.remediation.engine import AutoRemediationEngine
from ytfactory.scenes.pipeline import ScenePipeline
from ytfactory.light_normalization.pipeline import LightNormalizationPipeline
from ytfactory.retention.pre_render_gate import (
    link_scenes_to_segments,
    parse_script_to_segments,
    run_pre_render_gate,
)
from ytfactory.script_enhancer.pipeline import (
    DocumentaryScriptEnhancerPipeline,
    DocumentaryScriptEnhancerPipeline as ScriptEnhancerPipeline,  # noqa: F401 — backward compat for tests
)
from ytfactory.structural_retention.pipeline import StructuralRetentionPipeline
from ytfactory.editorial_qa.pipeline import EditorialQAPipeline
from ytfactory.composer.pipeline import ComposerPipeline
from ytfactory.composer.selection import run_composer_with_ab_selection
from ytfactory.source_refiner.pipeline import SourceRefinerPipeline
from ytfactory.storage.project_repository import ProjectRepository
from ytfactory.two_phase.pipeline import TwoPhasePipeline
from ytfactory.video.pipeline import VideoPipeline
from ytfactory.video.stitch_pipeline import StitchPipeline
from ytfactory.voice.pipeline import VoicePipeline
from ytfactory.shared.pipeline_status import PipelineAbort, PipelineStatusWriter, activate_writer, get_writer

console = Console()


class BuildPipeline:
    """Run the complete video production pipeline."""

    def __init__(self):
        settings = Settings()
        self.settings = settings

        self.animate = AnimatePipeline()
        self.light_normalization = LightNormalizationPipeline(settings)
        self.composer = ComposerPipeline(settings)
        self.source_refiner = SourceRefinerPipeline(settings)
        # Archived, not deleted — no longer called in the active run()/
        # run_incremental() paths below. Kept importable/constructible for
        # manual use (CLI) until the composer is proven.
        self.documentary_script_enhancer = DocumentaryScriptEnhancerPipeline(settings)
        self.script_enhancer = self.documentary_script_enhancer  # backward compat alias
        self.structural_retention = StructuralRetentionPipeline(settings)
        self.editorial_qa = EditorialQAPipeline(settings)
        self.scenes = ScenePipeline(settings)
        self.images = ImagePipeline(settings)
        self.voice = VoicePipeline(settings)
        self.captions = CaptionPipeline()
        self.video = VideoPipeline()
        self.stitch = StitchPipeline(settings=settings)
        self.cta = CTAPipeline(settings=settings)
        self.review = ReviewPipeline()
        self.publish = PublishPipeline(settings=settings)

    def run(
        self,
        project_id: str,
        skip_script: bool = False,
        skip_scenes: bool = False,
        skip_images: bool = False,
        auto_remediate: bool = True,
        remediation_threshold: float = 70.0,
        remediation_max_retries: int = 3,
        style: str | None = None,
        target_minutes: int = 5,
    ) -> None:
        project_dir = safe_project_dir(project_id, WORKSPACE_DIR)
        writer = PipelineStatusWriter(project_id, project_dir / "pipeline-status.json")

        with activate_writer(writer):
            try:
                if not skip_script:
                    ProjectRepository().load(project_id)
                    self.light_normalization.run(project_id)
                    self.source_refiner.run(project_id)
                    run_composer_with_ab_selection(self.composer, project_id)
                    self.editorial_qa.run(project_id)
                if not skip_scenes:
                    self.scenes.run(project_id)
                    self._run_pre_render_gate(project_id)
                if not skip_images:
                    self.images.run(project_id)
                    self.animate.run(project_id)
                self.voice.run(project_id)
                self.captions.run(project_id)

                # Render individual scene clips only — no final stitch yet.
                self.video.run(project_id, stitch=False)

                # Pre-stitch review: validate scene clips.
                # AssetIntegrityStage auto-detects pre-stitch mode (scene clips present,
                # final.mp4 absent) and skips the final.mp4 check.
                # BGM validator auto-skips when final.mp4 is absent.
                review_report = self.review.run(project_id)

                if review_report.verdict == "FAIL":
                    if auto_remediate:
                        config = RemediationConfig(
                            quality_threshold=remediation_threshold,
                            max_retries=remediation_max_retries,
                            dry_run=False,
                        )
                        remediation_report = AutoRemediationEngine(config=config).remediate(
                            project_id, review_report
                        )
                        if remediation_report.final_verdict != "PASS":
                            raise RuntimeError(
                                f"Pipeline stopped: quality review failed after "
                                f"{remediation_report.total_cycles} remediation cycle(s) "
                                f"(reason: {remediation_report.stopped_reason}). "
                                "Publishing skipped. Run `ytfactory review <id>` to inspect "
                                "the report or fix issues manually."
                            )
                    else:
                        raise RuntimeError(
                            "Pipeline stopped: quality review FAIL. "
                            "Auto-remediation is disabled (--no-remediate). "
                            "Run `ytfactory remediate <id>` to attempt repair, "
                            "or inspect workspace/<id>/review/ for details."
                        )

                # All scene clips passed — now stitch into final.mp4 (overlays + BGM).
                self.stitch.run(project_id)
                self.cta.run(project_id)
                self._maybe_split_video(project_id)

                self.publish.run(project_id)

            except PipelineAbort as exc:
                _w = get_writer()
                if _w:
                    _w.stage_fail(f"Pipeline aborted: {exc.reason}")
                console.print()
                console.print(Rule("[bold red]PIPELINE ABORTED[/bold red]"))
                console.print()
                console.print(f"[bold]Stage:[/bold] {exc.stage}")
                console.print(f"[bold]Reason:[/bold] {exc.reason}")
                console.print()
                console.print("[bold]Downstream stages skipped:[/bold]")
                stages = [
                    ("Scene Planning", not skip_scenes),
                    ("Image Generation", not skip_images),
                    ("TTS", True),
                    ("Rendering", True),
                    ("Publishing", True),
                ]
                for name, would_run in stages:
                    if would_run:
                        console.print(f"  [yellow]✓ {name}[/yellow]")
                console.print()
                return

    def _run_pre_render_gate(self, project_id: str) -> None:
        """Read scene-plan.json + script.md, run pre-render retention gate."""
        import json

        settings = Settings()
        if not settings.pipeline_qa_enabled:
            return

        project_dir = safe_project_dir(project_id, WORKSPACE_DIR)
        script_path = project_dir / "script" / "script.md"
        scene_plan_path = project_dir / "scenes" / "scene-plan.json"

        if not script_path.is_file() or not scene_plan_path.is_file():
            console.print(
                "  [yellow]⚠[/yellow] Pre-render gate skipped: missing script or scene plan."
            )
            return

        script_md = script_path.read_text(encoding="utf-8")
        scene_plan_data = json.loads(scene_plan_path.read_text(encoding="utf-8"))
        scenes = scene_plan_data.get("scenes", [])

        segments = parse_script_to_segments(script_md)
        scenes = link_scenes_to_segments(scenes, segments)

        from ytfactory.scenes.models import Scene

        scene_objs = [
            Scene(
                index=s.get("index", i + 1),
                title=s.get("title", ""),
                narration=s.get("narration", ""),
                visual_prompt=s.get("visual_prompt", ""),
                duration_seconds=float(s.get("duration_seconds", 0.0)),
                pose=s.get("pose"),
                composition=s.get("composition"),
                motion_type=s.get("motion_type"),
                text_overlay=s.get("text_overlay"),
                text_reveal_segments=s.get("text_reveal_segments", []),
                hold_required=s.get("hold_required", False),
                linked_segment=s.get("linked_segment"),
            )
            for i, s in enumerate(scenes)
        ]

        result = run_pre_render_gate(segments, scene_objs, project_dir=project_dir)

        for v in result.violations:
            console.print(f"  [yellow]⚠[/yellow] {v}")

        if not result.passed:
            writer = get_writer()
            if writer:
                writer.stage_fail(
                    f"Pre-render gate failed (score {result.total}/100): "
                    + "; ".join(result.violations[:3])
                )

            hard_reject = (
                any("[P1a]" in v for v in result.violations)
                and settings.frame_naming_gate_enabled
            )
            if hard_reject:
                raise PipelineAbort(
                    stage="pre_render_gate",
                    reason=(
                        f"Frame naming gate failed (score {result.total}/100): "
                        + "; ".join(result.violations[:3])
                    ),
                )

        console.print(
            f"  [green]✓[/green] Pre-render gate passed (score {result.total}/100)"
        )

        # Persist enriched scene plan back to disk
        SceneRepository().save_scenes(project_dir, scene_plan_data)

    def _maybe_split_video(self, project_id: str) -> None:
        """Post-processing: split final.mp4 into parts at scene boundaries.

        Opt-in via VIDEO_SPLIT_ENABLED. Not a pipeline stage — does not touch
        pipeline-status.json or trigger review validators.
        """
        import json

        settings = self.settings
        if not settings.video_split_enabled:
            return

        from ytfactory.video.splitter import VideoSplitter

        project_dir = safe_project_dir(project_id, WORKSPACE_DIR)
        final_mp4_path = project_dir / "video" / "final.mp4"
        scene_plan_path = project_dir / "scenes" / "scene-plan.json"

        if not final_mp4_path.is_file() or not scene_plan_path.is_file():
            return

        scenes = json.loads(scene_plan_path.read_text(encoding="utf-8"))["scenes"]
        parts = VideoSplitter().split(
            input_path=final_mp4_path,
            scenes=scenes,
            output_dir=final_mp4_path.parent,
            audio_dir=project_dir / "audio",
            target_minutes=settings.video_split_length_minutes,
            gap_seconds=max(0.0, getattr(settings, "video_scene_gap_seconds", 0.0)),
        )
        if parts:
            logger.info(f"Video split into {len(parts)} parts: {[str(p) for p in parts]}")

    # ── Incremental / resume mode ─────────────────────────────────────────────

    def run_incremental(
        self,
        project_id: str,
        force_stages: set[str] | None = None,
        scene_filter: int | None = None,
        force_scene: int | None = None,
        debug: bool = False,
    ) -> None:
        """
        Run only the pipeline stages that need work.

        Stages are skipped when all their output assets are present and
        unchanged (verified via SHA-256 checksums in the pipeline manifest).
        ``force_stages`` explicitly marks stages as dirty regardless of
        checksum state; downstream stages are invalidated transitively.

        A locked scene (SceneState.LOCKED) is never auto-regenerated unless
        its index appears in ``force_scene``.
        """
        project_dir = safe_project_dir(project_id, WORKSPACE_DIR)
        engine = IncrementalBuildEngine(project_dir)
        engine.initialize_workspace()
        writer = PipelineStatusWriter(project_id, project_dir / "pipeline-status.json")

        # Build the set of forced stages from flag names
        all_force = set(force_stages or ())
        if force_scene is not None:
            # One scene forced → regenerate its per-scene assets
            all_force |= {"images", "voice", "captions", "video"}

        report = engine.analyze(force_stages=all_force, scene_filter=scene_filter)

        reused: set[str] = set()
        rebuilt: set[str] = set()

        def _should_run(stage: str) -> bool:
            needs = engine.needs_run(stage, report)
            if needs:
                rebuilt.add(stage)
            else:
                reused.add(stage)
            return needs

        console.print(Rule("[bold cyan]Incremental Build — Change Detection[/bold cyan]"))

        with activate_writer(writer):
            # normalize + enhance — skipped when script.md is unchanged
            if _should_run("script"):
                ProjectRepository().load(project_id)
                self.light_normalization.run(project_id)
                run_composer_with_ab_selection(self.composer, project_id)
                self.editorial_qa.run(project_id)
                engine.record_stage_outputs("script")

            # scenes — always skipped if scene-plan.json exists and unchanged
            if _should_run("scenes"):
                self.scenes.run(project_id)
                self._run_pre_render_gate(project_id)
                engine.record_stage_outputs("scenes")
                engine.initialize_workspace()

            # images
            if _should_run("images"):
                self.images.run(project_id)
                engine.record_stage_outputs("images")
                self.animate.run(project_id)

            # voice
            if _should_run("voice"):
                self.voice.run(project_id)
                engine.record_stage_outputs("voice")

            # captions
            if _should_run("captions"):
                self.captions.run(project_id)
                engine.record_stage_outputs("captions")

            # video — scene clips only (no final stitch)
            if _should_run("video"):
                self.video.run(project_id, stitch=False)
                engine.record_stage_outputs("video")

            # pre-stitch review: validate scene clips before assembling final.mp4
            # AssetIntegrityStage auto-detects pre-stitch mode and skips final.mp4 check.
            if _should_run("review"):
                review_report = self.review.run(project_id)
                engine.record_stage_outputs("review")
                engine.update_workspace_from_review(review_report)
            else:
                review_report = None

            # remediate failing scene clips before stitch
            if review_report is not None and review_report.verdict == "FAIL":
                config = RemediationConfig(quality_threshold=70.0, max_retries=3, dry_run=False)
                AutoRemediationEngine(config=config).remediate(project_id, review_report)

            # stitch: compose final.mp4 from passing scene clips (overlays + BGM)
            if _should_run("stitch"):
                self.stitch.run(project_id)
                engine.record_stage_outputs("stitch")

            # cta overlay (runs after stitch; rebuilds only when CTA config changes)
            if _should_run("cta"):
                self.cta.run(project_id)
                engine.record_stage_outputs("cta")
                self._maybe_split_video(project_id)

            # publish
            if _should_run("publish"):
                self.publish.run(project_id)
                engine.record_stage_outputs("publish")

        # Write scene-review.md
        engine.write_scene_review_md()

        if debug:
            engine.print_debug_report(report, reused, rebuilt)
        else:
            console.print(Rule("[bold green]Incremental Build Complete[/bold green]"))
            for stage in ["script", "scenes", "images", "voice", "captions", "video", "stitch", "cta", "review", "publish"]:
                label = stage.title()
                if stage in rebuilt:
                    console.print(f"  [yellow]⚠[/yellow]  {label} rebuilt")
                elif stage in reused:
                    console.print(f"  [green]✓[/green]  {label} reused")

    # ── Two-phase workflow ─────────────────────────────────────────────────────

    def run_prep_only(
        self,
        project_id: str,
        style: str | None = None,
        target_minutes: int = 5,
        auto: bool = False,
    ) -> None:
        """Run Phase 1 of the two-phase pipeline (prep only, no image generation)."""
        TwoPhasePipeline().run_prep_only(
            project_id=project_id,
            style=style,
            target_minutes=target_minutes,
            auto=auto,
        )

    def run_resume(self, project_id: str, overlay: bool = True) -> None:
        """Run Phase 2 of the two-phase pipeline (resume from manual images)."""
        TwoPhasePipeline().run_resume(project_id=project_id, overlay=overlay)
