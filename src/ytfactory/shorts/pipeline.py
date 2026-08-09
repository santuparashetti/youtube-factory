"""Shorts pipeline — Phase 1A orchestrator.

S1 → S2 × 2 → S2b (individual QA + cross-short QA + targeted recomposition) × 2
   → S3 × valid Shorts → S4 × valid Shorts
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.table import Table

from ytfactory.config.settings import Settings
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.shorts.extractor import ShortOpportunityExtractor
from ytfactory.shorts.generator import ShortScriptGenerator
from ytfactory.shorts.image_prompts import ShortsImagePromptEngine
from ytfactory.shorts.models import (
    CrossShortQAResult,
    OpportunityExtractionResult,
    ShortOpportunity,
    ShortsScript,
    ShortsScriptQAReport,
    ValidationReport,
)
from ytfactory.shorts.recomposer import ShortScriptRecomposer
from ytfactory.shorts.repository import ShortsRepository
from ytfactory.shorts.scene_planner import ShortsScenePlanner
from ytfactory.shorts.validator import ShortScriptValidator
from ytfactory.storage.project_repository import ProjectRepository

console = Console()


class ShortsPipeline:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()
        self._projects = ProjectRepository()
        self._repo = ShortsRepository()
        self._extractor = ShortOpportunityExtractor(self._settings)
        self._generator = ShortScriptGenerator(self._settings)
        self._validator = ShortScriptValidator(self._settings)
        self._recomposer = ShortScriptRecomposer(self._settings)
        self._planner = ShortsScenePlanner(self._settings)
        self._image_engine = ShortsImagePromptEngine()

    def run(self, project_id: str, force: bool = False) -> None:
        # ── Load parent project ──────────────────────────────────────────
        project = self._projects.load(project_id)
        script_path = Path(WORKSPACE_DIR) / project_id / "script" / "script.md"
        if not script_path.exists():
            raise FileNotFoundError(
                f"No script found at {script_path}. "
                "Run 'import-script' or write a script before generating Shorts."
            )
        script_md = script_path.read_text(encoding="utf-8")

        console.print("\n[bold]YouTube Shorts Generator[/bold]")
        console.print(f"  Parent: [cyan]{project_id}[/cyan]")
        console.print(f"  Script: {len(script_md.split())} words\n")

        # ── S1: Opportunity extraction ───────────────────────────────────
        extraction = self._run_s1(project_id, script_md, project.title, force)

        # ── Phase A: Generate all scripts (S2) ───────────────────────────
        short_items: list[tuple[str, ShortOpportunity]] = []
        for short_index, opportunity_id in enumerate(extraction.selected, start=1):
            opportunity = next(
                (o for o in extraction.opportunities if o.opportunity_id == opportunity_id),
                None,
            )
            if opportunity is None:
                logger.warning(
                    "Shorts pipeline: selected opportunity_id '{}' not found — skipping.",
                    opportunity_id,
                )
                continue
            short_id = f"short-{short_index:03d}"
            short_items.append((short_id, opportunity))

        # ── Phase B: Individual QA + recomposition (S2b) ─────────────────
        scripts: dict[str, ShortsScript] = {}
        reports: dict[str, ValidationReport] = {}
        qa_reports: dict[str, ShortsScriptQAReport] = {}
        freshly_generated: dict[str, bool] = {}

        for short_id, opportunity in short_items:
            if force:
                self._repo.delete_short_artifacts(project_id, short_id)

            script, report, qa_report, was_generated = self._run_s2_with_individual_qa(
                project_id=project_id,
                short_id=short_id,
                opportunity=opportunity,
                parent_title=project.title,
                parent_script_md=script_md,
                force=force,
            )
            scripts[short_id] = script
            reports[short_id] = report
            qa_reports[short_id] = qa_report
            freshly_generated[short_id] = was_generated

        # ── Phase C: Cross-short QA ──────────────────────────────────────
        short_ids = [sid for sid, _ in short_items]
        if len(short_ids) >= 2:
            sid_a, sid_b = short_ids[0], short_ids[1]
            script_a = scripts.get(sid_a)
            script_b = scripts.get(sid_b)

            # Skip cross-short QA if both scripts were loaded from cache (idempotency)
            any_fresh = freshly_generated.get(sid_a, True) or freshly_generated.get(sid_b, True)

            if (
                any_fresh
                and script_a is not None and script_a.validation_passed
                and script_b is not None and script_b.validation_passed
            ):
                console.print(
                    f"\n  Running [bold]cross-short QA[/bold]: {sid_a} ↔ {sid_b}..."
                )
                cross_result = self._validator.evaluate_cross_short(script_a, script_b)

                if cross_result.similarity_problem:
                    logger.info(
                        "Cross-short QA: similarity detected — {}",
                        cross_result.overlap_reason,
                    )
                    console.print(
                        f"  [yellow]⚠[/yellow] Cross-short similarity detected: "
                        f"{cross_result.overlap_reason}"
                    )
                    # Recompose the second script with cross-short context
                    script_b, report_b, qa_b = self._run_recomposition(
                        project_id=project_id,
                        short_id=sid_b,
                        script=script_b,
                        qa_report=qa_reports[sid_b],
                        cross_short_result=cross_result,
                        sibling_scripts=[script_a],
                        parent_script_md=script_md,
                    )
                    scripts[sid_b] = script_b
                    reports[sid_b] = report_b
                    qa_reports[sid_b] = qa_b
                else:
                    logger.info("Cross-short QA: no similarity problem detected.")
                    console.print("  [green]✓[/green] Cross-short QA: no similarity problem.")

        # ── Phase D: Save scripts + S3 + S4 for passing Shorts ───────────
        results: list[dict] = []
        for short_id, opportunity in short_items:
            _script = scripts.get(short_id)
            _report = reports.get(short_id)
            if _script is None or _report is None:
                continue
            short_script: ShortsScript = _script
            short_report: ValidationReport = _report

            self._repo.save_script(project_id, short_id, short_script)
            self._repo.save_validation_report(project_id, short_id, short_report)

            if not short_script.validation_passed:
                console.print(
                    f"  [red]✗[/red] {short_id} validation failed: {short_report.failure_reasons}"
                )
                results.append({
                    "short_id": short_id,
                    "angle": opportunity.angle,
                    "duration": short_script.target_duration_seconds,
                    "validation": "FAILED",
                    "scenes": None,
                    "failure_reasons": short_report.failure_reasons,
                    "qa_status": qa_reports[short_id].status if short_id in qa_reports else "FAIL",
                })
                continue

            qa_status = qa_reports[short_id].status if short_id in qa_reports else "PASS"
            if qa_status == "PASS_WITH_WARNING":
                console.print(
                    f"  [yellow]⚠[/yellow] {short_id} PASS_WITH_WARNING: "
                    f"{qa_reports[short_id].warning_dimensions}"
                )
            else:
                console.print(
                    f"  [green]✓[/green] {short_id} script validated"
                )

            # S3: Scene planning
            plan = self._run_s3(project_id, short_id, short_script, force)

            # S4: Image prompts
            self._run_s4(project_id, short_id, plan, force)

            results.append({
                "short_id": short_id,
                "angle": opportunity.angle,
                "duration": plan.total_estimated_duration,
                "validation": qa_status,
                "scenes": plan.scene_count,
                "failure_reasons": [],
            })

        self._print_summary(project_id, results)

    def run_extract_only(self, project_id: str, force: bool = False) -> None:
        """S1 only: extract opportunities and save opportunities.json."""
        project = self._projects.load(project_id)
        script_path = Path(WORKSPACE_DIR) / project_id / "script" / "script.md"
        if not script_path.exists():
            raise FileNotFoundError(f"No script found at {script_path}.")
        script_md = script_path.read_text(encoding="utf-8")
        extraction = self._run_s1(project_id, script_md, project.title, force)
        console.print(
            f"\n[green]✓[/green] Extracted {len(extraction.opportunities)} opportunities "
            f"→ selected: {extraction.selected}"
        )

    def run_plan_only(
        self, project_id: str, short_id: str, force: bool = False
    ) -> None:
        """S3 only: re-plan scenes for one valid Short."""
        script = self._repo.load_script(project_id, short_id)
        if script is None:
            raise FileNotFoundError(
                f"No script found for {short_id}. Run generate-shorts first."
            )
        if not script.validation_passed:
            raise ValueError(
                f"{short_id} has validation_passed=false. "
                "Cannot plan scenes for a failed script."
            )

        plan_path = self._repo.short_dir(project_id, short_id) / "scene-plan.json"
        if plan_path.exists() and not force:
            console.print(f"[dim]Reusing existing scene plan for {short_id}[/dim]")
            return

        console.print(f"Planning scenes for [cyan]{short_id}[/cyan]...")
        plan = self._planner.plan(script)
        self._repo.save_scene_plan(project_id, short_id, plan)

        # Invalidate stale image manifest if scene plan changed
        manifest_path = (
            self._repo.short_dir(project_id, short_id) / "images" / "image-prompts.json"
        )
        if manifest_path.exists():
            manifest_path.unlink()
            logger.info(
                "Shorts pipeline: deleted stale image-prompts.json after scene plan regeneration."
            )

        console.print(
            f"[green]✓[/green] Scene plan written: {plan.scene_count} scenes, "
            f"{plan.total_estimated_duration:.1f}s"
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _run_s1(
        self,
        project_id: str,
        script_md: str,
        title: str,
        force: bool,
    ) -> OpportunityExtractionResult:
        existing = self._repo.load_opportunities(project_id)
        if existing is not None and not force:
            console.print("[dim]Reusing existing opportunities.json[/dim]")
            return existing
        console.print("Running [bold]S1[/bold] — opportunity extraction...")
        extraction = self._extractor.extract(script_md, title, project_id)
        self._repo.save_opportunities(project_id, extraction)
        console.print(
            f"  [green]✓[/green] {len(extraction.opportunities)} opportunities found, "
            f"selected: {extraction.selected}"
        )
        return extraction

    def _run_s2_with_individual_qa(
        self,
        project_id: str,
        short_id: str,
        opportunity: ShortOpportunity,
        parent_title: str,
        parent_script_md: str,
        force: bool,
    ) -> tuple[ShortsScript, ValidationReport, ShortsScriptQAReport, bool]:
        """S2 generation + S2b individual QA with one recomposition attempt on failure.

        Returns (script, report, qa_report, freshly_generated). freshly_generated is
        False when the script was loaded from cache; True when it was actually generated.
        """
        console.print(f"\nProcessing [bold]{short_id}[/bold] (angle: {opportunity.angle})")

        # Idempotency: reuse existing script + report if not force
        existing_script = self._repo.load_script(project_id, short_id)
        existing_report = self._repo.load_validation_report(project_id, short_id)
        if existing_script is not None and existing_report is not None and not force:
            console.print(f"  [dim]Reusing existing script for {short_id}[/dim]")
            # Build a minimal qa_report from the existing report
            qa = _report_to_qa_report(existing_report, short_id)
            return existing_script, existing_report, qa, False

        # Attempt 1: S2 generation
        short_index = int(short_id.split("-")[-1])
        console.print("  Running [bold]S2[/bold] — script generation...")
        script = self._generator.generate(
            opportunity, parent_title, parent_script_md, project_id, short_index
        )

        # S2b individual QA
        script, report, qa_report = self._validator.evaluate_with_qa(
            script, short_id, attempt=1, regenerated=False
        )

        if script.validation_passed:
            _log_qa_outcome(short_id, qa_report)
            return script, report, qa_report, True

        # Attempt 2: recomposition (targeted — NOT full regeneration)
        console.print(
            f"  [yellow]⚠[/yellow] {short_id} QA: FAIL "
            f"({qa_report.failed_dimensions}). Recomposing..."
        )
        script, report, qa_report = self._run_recomposition(
            project_id=project_id,
            short_id=short_id,
            script=script,
            qa_report=qa_report,
            cross_short_result=None,
            sibling_scripts=[],
            parent_script_md=parent_script_md,
            attempt=2,
        )
        return script, report, qa_report, True

    def _run_recomposition(
        self,
        project_id: str,
        short_id: str,
        script: ShortsScript,
        qa_report: ShortsScriptQAReport,
        cross_short_result: CrossShortQAResult | None,
        sibling_scripts: list[ShortsScript],
        parent_script_md: str,
        attempt: int = 2,
    ) -> tuple[ShortsScript, ValidationReport, ShortsScriptQAReport]:
        """Run targeted recomposition + re-QA once. Maximum one recomposition per Short."""
        console.print(f"  Running [bold]recomposer[/bold] for {short_id}...")

        # Merge cross-short info into qa_report if provided
        if cross_short_result and cross_short_result.similarity_problem:
            rewrite = list(set(qa_report.rewrite_sections) | set(cross_short_result.rewrite_sections))
            preserve = [s for s in qa_report.preserve_sections if s not in rewrite]
            instruction = cross_short_result.specific_instruction or qa_report.specific_instruction
            qa_report = qa_report.model_copy(update={
                "cross_short": cross_short_result,
                "rewrite_sections": rewrite,
                "preserve_sections": preserve,
                "specific_instruction": instruction,
                "failed_dimensions": list(set(qa_report.failed_dimensions) | {"cross_short_similarity"}),
            })

        recomposed = self._recomposer.recompose(
            script, qa_report, sibling_scripts, parent_script_md
        )

        # Re-QA the recomposed script
        recomposed, new_report, new_qa = self._validator.evaluate_with_qa(
            recomposed,
            short_id,
            attempt=attempt,
            regenerated=False,
            cross_short_result=cross_short_result,
        )

        # Mark that recomposition happened + invalidate stale downstream artifacts
        was_recomposed = True
        recomposition_reason = "; ".join(qa_report.failed_dimensions)
        new_report = new_report.model_copy(update={
            "recomposed": was_recomposed,
            "recomposition_reason": recomposition_reason,
            "final_status": new_qa.status,
        })

        _invalidate_stale_artifacts(self._repo, project_id, short_id)

        if new_report.validation_passed:
            console.print(
                f"  [green]✓[/green] {short_id} recomposed → final QA: {new_qa.status}"
            )
        else:
            console.print(
                f"  [red]✗[/red] {short_id} still failing after recomposition: "
                f"{new_report.failure_reasons}"
            )
            logger.error(
                "Shorts pipeline: {} failed final QA after recomposition: {}",
                short_id,
                new_report.failure_reasons,
            )

        return recomposed, new_report, new_qa

    def _run_s3(self, project_id: str, short_id: str, script: ShortsScript, force: bool):
        existing = self._repo.load_scene_plan(project_id, short_id)
        if existing is not None and not force:
            console.print(f"  [dim]Reusing existing scene plan for {short_id}[/dim]")
            return existing
        console.print("  Running [bold]S3[/bold] — scene planning...")
        plan = self._planner.plan(script)
        self._repo.save_scene_plan(project_id, short_id, plan)
        console.print(
            f"  [green]✓[/green] {plan.scene_count} scenes, {plan.total_estimated_duration:.1f}s"
        )
        return plan

    def _run_s4(self, project_id: str, short_id: str, plan, force: bool):
        existing = self._repo.load_image_manifest(project_id, short_id)
        if existing is not None and not force:
            console.print(f"  [dim]Reusing existing image prompts for {short_id}[/dim]")
            return existing
        console.print("  Running [bold]S4[/bold] — image prompt generation...")
        manifest = self._image_engine.generate(plan, project_id, short_id)
        console.print(
            f"  [green]✓[/green] {len(manifest.images)} image prompts written"
        )
        return manifest

    def _print_summary(self, project_id: str, results: list[dict]) -> None:
        console.print("\n[bold]Shorts Generation Complete[/bold]")
        console.print(f"Parent: [cyan]{project_id}[/cyan]\n")

        table = Table(show_header=True, header_style="bold")
        table.add_column("Short", min_width=10)
        table.add_column("Angle", min_width=16)
        table.add_column("Duration", min_width=10)
        table.add_column("QA Status", min_width=18)
        table.add_column("Scenes", min_width=7)

        failed_details: list[str] = []
        for r in results:
            val = r["validation"]
            if val == "PASS":
                val_str = "[green]PASS[/green]"
            elif val == "PASS_WITH_WARNING":
                val_str = "[yellow]PASS_WITH_WARNING[/yellow]"
            else:
                val_str = "[red]FAILED[/red]"
            scenes_str = str(r["scenes"]) if r["scenes"] else "-"
            duration_str = (
                f"{r['duration']:.1f}s" if isinstance(r["duration"], float) else "-"
            )
            table.add_row(
                r["short_id"], r["angle"], duration_str, val_str, scenes_str,
            )
            if r["failure_reasons"]:
                failed_details.append(
                    f"{r['short_id']} failure: {'; '.join(r['failure_reasons'])}"
                )

        console.print(table)
        for detail in failed_details:
            console.print(f"\n[red]{detail}[/red]")


# ── Module-level helpers ───────────────────────────────────────────────────────

def _log_qa_outcome(short_id: str, qa: ShortsScriptQAReport) -> None:
    if qa.status == "PASS":
        logger.info("Shorts QA: {} PASS", short_id)
    elif qa.status == "PASS_WITH_WARNING":
        logger.info(
            "Shorts QA: {} PASS_WITH_WARNING — warnings: {}", short_id, qa.warning_dimensions
        )
    else:
        logger.info(
            "Shorts QA: {} FAIL — failed: {}", short_id, qa.failed_dimensions
        )


def _report_to_qa_report(report: ValidationReport, short_id: str) -> ShortsScriptQAReport:
    """Convert an existing ValidationReport to a minimal ShortsScriptQAReport."""
    raw_status = report.final_status or ("PASS" if report.validation_passed else "FAIL")
    # Ensure the status is a valid Literal value
    if raw_status not in ("PASS", "PASS_WITH_WARNING", "FAIL"):
        raw_status = "PASS" if report.validation_passed else "FAIL"
    status: str = raw_status  # type: ignore[assignment]
    return ShortsScriptQAReport(
        short_id=short_id,
        status=status,  # type: ignore[arg-type]
        failed_dimensions=report.failure_reasons,
    )


def _invalidate_stale_artifacts(
    repo: ShortsRepository, project_id: str, short_id: str
) -> None:
    """Delete scene plan and image manifest if they exist (stale after recomposition)."""
    short_dir = repo.short_dir(project_id, short_id)
    for artifact in ("scene-plan.json", "scene-plan.md"):
        path = short_dir / artifact
        if path.exists():
            path.unlink()
            logger.info(
                "Shorts pipeline: deleted stale {} after recomposition of {}.",
                artifact, short_id,
            )
    manifest = short_dir / "images" / "image-prompts.json"
    if manifest.exists():
        manifest.unlink()
        logger.info(
            "Shorts pipeline: deleted stale image-prompts.json after recomposition of {}.",
            short_id,
        )
