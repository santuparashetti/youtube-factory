"""Two-phase pipeline orchestration for manual image generation workflow.

Phase 1 (prep_only):
  Run all stages except image generation, write image_prompts_manifest.json,
  run QC checks, produce phase1_report.md, then halt.

Phase 2 (resume):
  Validate manually-placed images against the manifest, then run remaining
  stages (video, BGM, CTA, review, publish excluding thumbnail).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from ytfactory.agents.prompts.scene_planner import prepend_storyboard_header
from ytfactory.composer.selection import run_composer_with_ab_selection
from ytfactory.config.settings import Settings
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.shared.paths import safe_project_dir
from ytfactory.storage.project_repository import ProjectRepository

console = Console()

# Task 2.10 — v2, Storyboard Mode. Written to every Phase 1 job folder as
# image_generation_rules.md for the manual-image-gen workflow.
IMAGE_GENERATION_RULES_V2 = """\
# Image Generation Rules
**Version:** 2.0 — Storyboard Mode

---

## Source of Truth

- The `visual_prompt` is the **single source of truth** for what to generate.
- The narration provides **emotional tone and mood only** — it does not add subjects, actions, or environments.
- Never infer visual elements from the narration that are not in the `visual_prompt`.
- When uncertain whether to include something: **omit rather than invent**.

---

## Storyboard Mode (mandatory)

Every scene is an independent storyboard frame. Treat it as such:

- Generate **only** what is explicitly described in the `visual_prompt`.
- Do **not** continue characters, objects, or environments from previous scenes unless explicitly stated.
- Do **not** invent people, animals, props, furniture, architecture, or landscape elements not described.
- Preserve intentional emptiness and negative space — empty space in the prompt means empty space in the image.
- Match the requested shot type, camera angle, composition, lighting, and environment **exactly**.

---

## Camera & Composition

- Apply the exact shot type specified: establishing, wide, medium, close-up, extreme close-up, drone, low angle, high angle, POV, tracking, over-the-shoulder, profile, environmental portrait.
- Apply cinematic optics: Wide ~24–35mm, Medium ~50–85mm, Close-up ~85–135mm, natural depth of field.
- Respect subject placement, scale, framing, and negative space as described.
- Maintain realistic perspective — object size must change naturally with distance.

---

## Subject & Scale

- Maintain real-world physical scale for all subjects (humans, animals, objects, architecture, vegetation).
- Use realistic proportions — anatomically and structurally accurate humans, animals, and environments.
- Preserve environmental scale cues (terrain, rocks, trees, doors reinforce believable size relationships).

---

## Continuity

When scenes share a character, location, or setting:
- Same character appearance, costume, age, and build across scenes
- Same environment lighting, time of day, and visual style
- Same overall color palette unless the prompt specifies a change

---

## Quality

- Photorealistic cinematic quality
- Natural lighting, realistic materials, physically accurate shadows
- No text, no watermark, no artifacts, no cartoon, no illustration style
- Output: **1280×720 px (16:9)**

---

## Rejection Criteria (regenerate immediately)

Regenerate without hesitation if:
- Wrong or missing primary subject
- Invented subject not in the prompt
- Wrong camera angle or shot type
- Wrong environment or setting
- Text or watermark visible
- Wrong lighting or time of day
- Non-photorealistic or illustrated look
- Incorrect aspect ratio or resolution
"""


class TwoPhasePipeline:
    """Orchestrate Phase 1 (prep) and Phase 2 (resume) of the two-phase workflow."""

    def __init__(self):
        self._settings = Settings()

    # ── Phase 1 ────────────────────────────────────────────────────────────────

    def run_prep_only(
        self,
        project_id: str,
        *,
        style: str | None = None,
        target_minutes: int = 7,
        auto: bool = False,
    ) -> None:
        """Run Phase 1: all stages except image generation, then halt.

        Resume-skip: if a finalized script.md already exists for this
        project, the enhancer / structural pass / QA regeneration are
        skipped entirely and Phase 1 resumes at the review checkpoint (which
        itself hash-guards script.md — unchanged means QA is still valid;
        hand-edited means QA re-runs on the edit before continuing).
        """
        from ytfactory.build.pipeline import BuildPipeline
        from ytfactory.editorial_qa.review_gate import FinalScriptReviewGate

        project_dir = safe_project_dir(project_id, WORKSPACE_DIR)
        writer = _PhaseStatusWriter(project_id, project_dir / "pipeline-status.json")

        console.print(Rule("[bold cyan]YouTube Factory — Phase 1 (Prep)[/bold cyan]"))
        console.print(f"[cyan]Project:[/cyan] [bold]{project_id}[/bold]\n")

        pipeline = BuildPipeline()
        script_file = project_dir / "script" / "script.md"

        with _activate_writer(writer):
            if script_file.exists():
                console.print(
                    "[dim]Finalized script.md already exists — skipping composer / "
                    "QA regeneration, resuming at review.[/dim]"
                )
            else:
                ProjectRepository().load(project_id)
                pipeline.light_normalization.run(project_id)
                run_composer_with_ab_selection(pipeline.composer, project_id)
                pipeline.editorial_qa.run(project_id)

            script_text = script_file.read_text(encoding="utf-8")
            FinalScriptReviewGate(self._settings).run(project_id, script_text, auto_mode=auto)

            # scene planning + pre-render gate
            pipeline.scenes.run(project_id)
            pipeline._run_pre_render_gate(project_id)

            # voice / audio generation
            pipeline.voice.run(project_id)

            # subtitle generation
            pipeline.captions.run(project_id)

        # Write manifest and report after stages complete
        manifest_path = self._write_image_prompts_manifest(project_id)
        report_path = self._write_phase1_report(project_id, manifest_path)

        console.print()
        console.print(Rule("[bold green]Phase 1 Complete[/bold green]"))
        console.print(
            Panel(
                f"[bold]Project:[/bold] {project_id}\n"
                f"[bold]Image prompts:[/bold] {manifest_path}\n"
                f"[bold]Phase 1 report:[/bold] {report_path}\n"
                f"[bold]Images folder:[/bold] {project_dir / 'images'}\n\n"
                "[yellow]Generate images externally, place them in the images folder, "
                "then run Phase 2 to continue.[/yellow]",
                title="Phase 1 Stop",
                border_style="green",
            )
        )
        console.print()

    # ── Phase 2 ────────────────────────────────────────────────────────────────

    def run_resume(self, project_id: str, overlay: bool = True) -> None:
        """Run Phase 2: validate images, then run remaining stages."""
        from ytfactory.build.pipeline import BuildPipeline

        project_dir = safe_project_dir(project_id, WORKSPACE_DIR)
        writer = _PhaseStatusWriter(project_id, project_dir / "pipeline-status.json")

        console.print(Rule("[bold cyan]YouTube Factory — Phase 2 (Resume)[/bold cyan]"))
        console.print(f"[cyan]Project:[/cyan] {project_id}\n")

        # Validate images first
        missing = self._validate_images(project_id)
        if missing:
            console.print(
                f"[red]✗ Phase 2 validation failed — {len(missing)} missing image(s):[/red]"
            )
            for scene_id, filename in missing:
                console.print(f"  [red]•[/red] Scene {scene_id}: {filename}")
            console.print(
                "\n[yellow]Place the missing images in the images folder and re-run.[/yellow]"
            )
            raise RuntimeError(
                f"Phase 2 validation failed: {len(missing)} missing images. "
                "See output above for details."
            )

        console.print("[green]✓[/green] All expected images present\n")

        pipeline = BuildPipeline()

        with _activate_writer(writer):
            # animate scenes with motion engine (LLM vision → effects → MP4)
            pipeline.animate.run(project_id)

            # video render (includes BGM mixing)
            pipeline.video.run(project_id, overlay=overlay)

            # CTA overlay
            pipeline.cta.run(project_id)

            # post-processing: split final.mp4 into parts (opt-in via VIDEO_SPLIT_ENABLED)
            pipeline._maybe_split_video(project_id)

            # quality review
            review_report = pipeline.review.run(project_id)

            # auto-remediation if needed
            if review_report.verdict == "FAIL":
                from ytfactory.review.remediation.config import RemediationConfig
                from ytfactory.review.remediation.engine import AutoRemediationEngine

                config = RemediationConfig(
                    quality_threshold=70.0,
                    max_retries=3,
                    dry_run=False,
                )
                remediation_report = AutoRemediationEngine(config=config).remediate(
                    project_id, review_report
                )
                if remediation_report.final_verdict != "PASS":
                    raise RuntimeError(
                        f"Pipeline stopped: quality review failed after "
                        f"{remediation_report.total_cycles} remediation cycle(s) "
                        f"(reason: {remediation_report.stopped_reason})."
                    )

            # publish (skip thumbnail — user reviews manually-placed images directly)
            from ytfactory.publish.config import PublishConfig

            publish_config = PublishConfig(skip_thumbnail=True)
            pipeline.publish = type(pipeline.publish)(
                config=publish_config, settings=self._settings
            )
            pipeline.publish.run(project_id)

        console.print()
        console.print(Rule("[bold green]Phase 2 Complete[/bold green]"))
        console.print(f"[bold]Project:[/bold] {project_id}")
        console.print()

    # ── Manifest ───────────────────────────────────────────────────────────────

    def _write_image_prompts_manifest(self, project_id: str) -> Path:
        """Write image_prompts_manifest.json with per-scene prompt metadata."""
        project_dir = safe_project_dir(project_id, WORKSPACE_DIR)
        scene_plan_path = project_dir / "scenes" / "scene-plan.json"

        if not scene_plan_path.exists():
            raise FileNotFoundError(f"Scene plan not found: {scene_plan_path}")

        scene_plan = json.loads(scene_plan_path.read_text(encoding="utf-8"))
        scenes = scene_plan.get("scenes", [])

        images_dir = project_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        manifest: list[dict] = []
        for scene in scenes:
            index = scene.get("index", 0)
            filename = f"scene-{index:03d}.png"
            scene_type = scene.get("scene_type", "generated_image")
            visual_prompt = scene.get("visual_prompt", "")
            if scene_type != "brand_card":
                visual_prompt = prepend_storyboard_header(visual_prompt)
            manifest.append(
                {
                    "scene_id": index,
                    "expected_filename": filename,
                    "visual_prompt": visual_prompt,
                    "shot_type": scene.get("shot_type", ""),
                    "motion_type": scene.get("motion_type") or "",
                    "scene_type": scene_type,
                    "narration": scene.get("narration", ""),
                }
            )

        manifest_path = project_dir / "image_prompts_manifest.json"
        manifest_path.write_text(
            json.dumps({"project_id": project_id, "scenes": manifest}, indent=2),
            encoding="utf-8",
        )
        console.print(f"[green]✓[/green] Image prompts manifest: {manifest_path}")

        rules_path = project_dir / "image_generation_rules.md"
        rules_path.write_text(IMAGE_GENERATION_RULES_V2, encoding="utf-8")
        console.print(f"[green]✓[/green] Image generation rules: {rules_path}")
        return manifest_path

    def _write_phase1_report(
        self, project_id: str, manifest_path: Path
    ) -> Path:
        """Write phase1_report.md and phase1_report.json summarizing Phase 1 completion."""
        project_dir = safe_project_dir(project_id, WORKSPACE_DIR)
        scene_plan_path = project_dir / "scenes" / "scene-plan.json"

        scene_count = 0
        total_duration = 0.0
        if scene_plan_path.exists():
            scene_plan = json.loads(scene_plan_path.read_text(encoding="utf-8"))
            scenes = scene_plan.get("scenes", [])
            scene_count = len(scenes)
            total_duration = sum(s.get("duration_seconds", 0) for s in scenes)

        audio_dir = project_dir / "audio"
        subtitle_dir = project_dir / "subtitles"
        audio_count = len(list(audio_dir.glob("scene-*.mp3"))) if audio_dir.exists() else 0
        subtitle_count = (
            len(list(subtitle_dir.glob("scene-*.srt"))) if subtitle_dir.exists() else 0
        )

        images_folder = project_dir / "images"

        qc = self._run_qc_for_report(project_id, scene_plan_path)
        faithfulness_gate = self._read_faithfulness_gate(project_dir)

        report = f"""# Phase 1 Report — {project_id}

**Generated:** {datetime.now(tz=timezone.utc).isoformat()}

## Summary

| Field | Value |
|-------|-------|
| Project | {project_id} |
| Scenes | {scene_count} |
| Estimated duration | {total_duration:.0f}s (~{total_duration / 60:.1f} min) |
| Audio files | {audio_count} |
| Subtitle files | {subtitle_count} |

## Stages Completed

- [x] Script enhancement
- [x] Scene planning
- [x] Pre-render gate (QC)
- [x] TTS / audio generation
- [x] Subtitle generation

## Skipped

- [ ] Image generation (manual step required)

## Outputs

- **Image prompts manifest:** `{manifest_path.name}` in project root
- **Images folder:** `{images_folder}`
- **Scene plan:** `scenes/scene-plan.json`

## Next Steps

1. Open `{manifest_path.name}` and use the prompts to generate images externally.
2. Name each image exactly as `expected_filename` in the manifest (e.g. `scene-001.png`).
3. Place all images in: `{images_folder}`
4. Run Phase 2:
    ```bash
    ytfactory run --phase=resume --project {project_id}
    ```
"""

        if qc:
            report += f"""
## QC Warnings

**Pre-render gate score:** {qc.get("score", "N/A")}/100
**Passed:** {"Yes" if qc.get("passed") else "No"}

"""
            if qc.get("violations"):
                for v in qc["violations"]:
                    report += f"- {v}\n"

        if faithfulness_gate:
            report += f"""
## Faithfulness Gate (image prompt story fidelity)

**Passed:** {"Yes" if faithfulness_gate.get("passed") else "No"}
**Scenes:** {faithfulness_gate.get("passed_count", 0)} PASS, {faithfulness_gate.get("failed_count", 0)} FAILED, {faithfulness_gate.get("skipped_count", 0)} SKIPPED

"""
            for s in faithfulness_gate.get("failed_scenes", []):
                report += f"- Scene {s.get('index')}: {s.get('violation', '')}\n"

        report_path = project_dir / "phase1_report.md"
        report_path.write_text(report, encoding="utf-8")
        console.print(f"[green]✓[/green] Phase 1 report: {report_path}")

        json_report = {
            "project_id": project_id,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "summary": {
                "scenes": scene_count,
                "estimated_duration_seconds": total_duration,
                "audio_files": audio_count,
                "subtitle_files": subtitle_count,
            },
            "stages_completed": [
                "script_enhancement",
                "scene_planning",
                "pre_render_gate",
                "tts_audio_generation",
                "subtitle_generation",
            ],
            "stages_skipped": ["image_generation"],
            "qc": qc or {},
            "faithfulness_gate": faithfulness_gate or {},
            "outputs": {
                "manifest": str(manifest_path),
                "images_folder": str(images_folder),
                "scene_plan": str(scene_plan_path),
            },
            "next_steps": [
                "Open image_prompts_manifest.json and generate images externally",
                "Name each image exactly as expected_filename",
                "Place all images in the images folder",
                "Run Phase 2: ytfactory run --phase=resume --project <project_id>",
            ],
        }

        json_path = project_dir / "phase1_report.json"
        json_path.write_text(
            json.dumps(json_report, indent=2), encoding="utf-8"
        )
        console.print(f"[green]✓[/green] Phase 1 report (JSON): {json_path}")
        return report_path

    def _run_qc_for_report(
        self, project_id: str, scene_plan_path: Path
    ) -> dict | None:
        """Run pre-render gate QC check for the report."""
        try:
            from ytfactory.retention.pre_render_gate import (
                link_scenes_to_segments,
                parse_script_to_segments,
                run_pre_render_gate,
            )
            from ytfactory.scenes.models import Scene

            settings = Settings()
            if not settings.pipeline_qa_enabled:
                return None

            project_dir = safe_project_dir(project_id, WORKSPACE_DIR)
            script_path = project_dir / "script" / "script.md"
            if not script_path.is_file() or not scene_plan_path.is_file():
                return None

            script_md = script_path.read_text(encoding="utf-8")
            scene_plan_data = json.loads(scene_plan_path.read_text(encoding="utf-8"))
            scenes = scene_plan_data.get("scenes", [])

            segments = parse_script_to_segments(script_md)
            scenes = link_scenes_to_segments(scenes, segments)

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

            return {
                "score": result.total,
                "passed": result.passed,
                "breakdown": result.breakdown,
                "violations": result.violations,
            }
        except Exception:
            return None

    def _read_faithfulness_gate(self, project_dir: Path) -> dict | None:
        """Read scenes/faithfulness-gate.json written by scene_planner_node, if present."""
        gate_path = project_dir / "scenes" / "faithfulness-gate.json"
        if not gate_path.is_file():
            return None
        try:
            return json.loads(gate_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    # ── Validation ─────────────────────────────────────────────────────────────

    def _validate_images(self, project_id: str) -> list[tuple[int, str]]:
        """Validate that all expected images from the manifest exist.

        Returns a list of (scene_id, filename) tuples for missing images.
        """
        project_dir = safe_project_dir(project_id, WORKSPACE_DIR)
        manifest_path = project_dir / "image_prompts_manifest.json"

        if not manifest_path.exists():
            raise FileNotFoundError(
                f"image_prompts_manifest.json not found in {project_dir}. "
                "Run Phase 1 first."
            )

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        scenes = manifest.get("scenes", [])

        images_dir = project_dir / "images"
        missing: list[tuple[int, str]] = []

        for scene in scenes:
            scene_type = scene.get("scene_type", "generated_image")
            if scene_type in ("asset", "brand_card"):
                continue
            filename = scene.get("expected_filename", "")
            if not filename:
                continue
            candidates = [filename]
            if "_" in filename:
                candidates.append(filename.replace("_", "-"))
            elif "-" in filename:
                candidates.append(filename.replace("-", "_"))
            if not any((images_dir / c).is_file() for c in candidates):
                missing.append((scene.get("scene_id", 0), filename))

        return missing


# ── Context manager for pipeline status writer ────────────────────────────────


class _PhaseStatusWriter:
    """Minimal pipeline status writer for two-phase stages."""

    def __init__(self, project_id: str, status_path: Path):
        self._project_id = project_id
        self._path = status_path
        self._data: dict = {"stages": {}}

    def stage_start(self, name: str, total: int = 0) -> None:
        self._data["stages"][name] = {
            "status": "running",
            "started_at": datetime.now(tz=timezone.utc).isoformat(),
            "total": total,
            "completed": 0,
        }
        self._save()

    def stage_progress(self, current: int) -> None:
        stage = self._data.get("stages", {}).get("current")
        if stage:
            stage["completed"] = current
            self._save()

    def stage_complete(self) -> None:
        for stage in self._data.get("stages", {}).values():
            if stage.get("status") == "running":
                stage["status"] = "completed"
                stage["completed"] = stage.get("total", 0)
                stage["completed_at"] = datetime.now(tz=timezone.utc).isoformat()
                break
        self._save()

    def stage_fail(self, reason: str) -> None:
        for stage in self._data.get("stages", {}).values():
            if stage.get("status") == "running":
                stage["status"] = "failed"
                stage["error"] = reason
                stage["completed_at"] = datetime.now(tz=timezone.utc).isoformat()
                break
        self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2), encoding="utf-8"
        )


class _ActivateWriter:
    """Context manager that activates a PipelineStatusWriter-compatible object."""

    def __init__(self, writer):
        self._writer = writer
        self._previous = None

    def __enter__(self):
        from ytfactory.shared.pipeline_status import activate_writer, get_writer

        self._previous = get_writer()
        activate_writer(self._writer)
        return self._writer

    def __exit__(self, exc_type, exc_val, exc_tb):
        from ytfactory.shared.pipeline_status import activate_writer

        activate_writer(self._previous)


def _activate_writer(writer):
    return _ActivateWriter(writer)
