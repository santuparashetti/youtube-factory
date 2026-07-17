from pathlib import Path

from rich.console import Console
from rich.rule import Rule

from ytfactory.config.settings import Settings
from ytfactory.incremental.engine import IncrementalBuildEngine
from ytfactory.incremental.deps import FORCE_FLAG_TO_STAGE
from ytfactory.shared.constants import WORKSPACE_DIR

from ytfactory.captions.pipeline import CaptionPipeline
from ytfactory.cta.pipeline import CTAPipeline
from ytfactory.images.pipeline import ImagePipeline
from ytfactory.publish.pipeline import PublishPipeline
from ytfactory.review.pipeline import ReviewPipeline
from ytfactory.review.remediation.config import RemediationConfig
from ytfactory.review.remediation.engine import AutoRemediationEngine
from ytfactory.scenes.pipeline import ScenePipeline
from ytfactory.light_normalization.pipeline import LightNormalizationPipeline
from ytfactory.script_enhancer.pipeline import (
    DocumentaryScriptEnhancerPipeline,
    DocumentaryScriptEnhancerPipeline as ScriptEnhancerPipeline,  # backward compat for tests
)
from ytfactory.storage.project_repository import ProjectRepository
from ytfactory.video.pipeline import VideoPipeline
from ytfactory.voice.pipeline import VoicePipeline

console = Console()


class BuildPipeline:
    """Run the complete video production pipeline."""

    def __init__(self):
        settings = Settings()

        self.light_normalization = LightNormalizationPipeline(settings)
        self.documentary_script_enhancer = DocumentaryScriptEnhancerPipeline(settings)
        self.script_enhancer = self.documentary_script_enhancer  # backward compat alias
        self.scenes = ScenePipeline(settings)
        self.images = ImagePipeline(settings)
        self.voice = VoicePipeline(settings)
        self.captions = CaptionPipeline()
        self.video = VideoPipeline()
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
        target_minutes: int = 7,
    ) -> None:

        if not skip_script:
            project = ProjectRepository().load(project_id)
            self.light_normalization.run(project_id)
            self.documentary_script_enhancer.run(
                project_id,
                topic=project.title,
                style=style,
                target_minutes=target_minutes,
            )
        if not skip_scenes:
            self.scenes.run(project_id)
        if not skip_images:
            self.images.run(project_id)
        self.voice.run(project_id)
        self.captions.run(project_id)
        self.video.run(project_id)
        self.cta.run(project_id)

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

        self.publish.run(project_id)

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
        project_dir = Path(WORKSPACE_DIR) / project_id
        engine = IncrementalBuildEngine(project_dir)
        engine.initialize_workspace()

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

        # normalize + enhance — skipped when script.md is unchanged
        if _should_run("script"):
            project = ProjectRepository().load(project_id)
            self.light_normalization.run(project_id)
            self.documentary_script_enhancer.run(project_id, topic=project.title)
            engine.record_stage_outputs("script")

        # scenes — always skipped if scene-plan.json exists and unchanged
        if _should_run("scenes"):
            self.scenes.run(project_id)
            engine.record_stage_outputs("scenes")
            engine.initialize_workspace()

        # images
        if _should_run("images"):
            self.images.run(project_id)
            engine.record_stage_outputs("images")

        # voice
        if _should_run("voice"):
            self.voice.run(project_id)
            engine.record_stage_outputs("voice")

        # captions
        if _should_run("captions"):
            self.captions.run(project_id)
            engine.record_stage_outputs("captions")

        # video
        if _should_run("video"):
            self.video.run(project_id)
            engine.record_stage_outputs("video")

        # cta overlay (runs after video; rebuilds only CTA + final render when changed)
        if _should_run("cta"):
            self.cta.run(project_id)
            engine.record_stage_outputs("cta")

        # review
        if _should_run("review"):
            review_report = self.review.run(project_id)
            engine.record_stage_outputs("review")
            engine.update_workspace_from_review(review_report)
        else:
            review_report = None

        # remediate if needed (same logic as run())
        if review_report is not None and review_report.verdict == "FAIL":
            config = RemediationConfig(quality_threshold=70.0, max_retries=3, dry_run=False)
            AutoRemediationEngine(config=config).remediate(project_id, review_report)

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
            for stage in ["script", "scenes", "images", "voice", "captions", "video", "cta", "review", "publish"]:
                label = stage.title()
                if stage in rebuilt:
                    console.print(f"  [yellow]⚠[/yellow]  {label} rebuilt")
                elif stage in reused:
                    console.print(f"  [green]✓[/green]  {label} reused")
