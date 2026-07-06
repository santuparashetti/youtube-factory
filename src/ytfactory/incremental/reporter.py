"""Incremental pipeline reporter.

Produces:
  - Console debug output (spec section 8) for incremental runs
  - workspace/jobs/<id>/review/scene-review.md (spec section 12)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from .manifest import PipelineManifest
from .models import ChangeReport, SceneState
from .scene_workspace import SceneWorkspace

console = Console()

_STATE_LABELS: dict[SceneState, str] = {
    SceneState.DRAFT: "🔘 Draft",
    SceneState.NEEDS_REVIEW: "👁  Needs Review",
    SceneState.NEEDS_REVISION: "⚠️  Needs Revision",
    SceneState.APPROVED: "✅ Approved",
    SceneState.LOCKED: "🔒 Locked",
}


class IncrementalReporter:
    """Produce console output and reports for incremental builds."""

    def print_change_report(
        self,
        report: ChangeReport,
        reused_stages: set[str],
        rebuilt_stages: set[str],
    ) -> None:
        """Print per-stage reuse/rebuild summary (spec section 8 format)."""
        from .deps import PIPELINE_STAGES

        for stage in PIPELINE_STAGES:
            label = stage.title().replace("_", " ")
            if stage in rebuilt_stages:
                console.print(f"  [yellow]⚠[/yellow]  {label} rebuilt")
            elif stage in reused_stages:
                console.print(f"  [green]✓[/green]  {label} reused")

        if report.changed:
            console.print("\n[yellow]Modified assets:[/yellow]")
            for p in report.changed[:20]:
                console.print(f"  ⚠  {p}")
        if report.new:
            console.print("\n[cyan]New assets:[/cyan]")
            for p in report.new[:20]:
                console.print(f"  +  {p}")

    def write_scene_review_md(
        self,
        project_dir: Path,
        workspace: SceneWorkspace,
        manifest: PipelineManifest,
    ) -> Path:
        """Write workspace/jobs/<id>/review/scene-review.md (spec section 12)."""
        plan_path = project_dir / "scenes" / "scene-plan.json"
        out = project_dir / "review" / "scene-review.md"
        out.parent.mkdir(parents=True, exist_ok=True)

        if not plan_path.exists():
            out.write_text("# Scene Review Report\n\nNo scene plan found.\n", encoding="utf-8")
            return out

        scenes = json.loads(plan_path.read_text(encoding="utf-8")).get("scenes", [])
        lines = [
            "# Scene Review Report",
            "",
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"Project: `{project_dir.name}`",
            f"Total scenes: {len(scenes)}",
            "",
        ]

        for scene in scenes:
            idx = scene["index"]
            state = workspace.get_state(idx)
            notes = workspace.get_notes(idx)

            image_path = project_dir / "images" / f"scene-{idx:03d}.png"
            audio_path = project_dir / "audio" / f"scene-{idx:03d}.mp3"
            ass_path = project_dir / "subtitles" / f"scene-{idx:03d}.ass"
            srt_path = project_dir / "subtitles" / f"scene-{idx:03d}.srt"
            video_path = project_dir / "video" / f"scene-{idx:03d}.mp4"

            img_check = "✓" if image_path.exists() else "✗"
            aud_check = "✓" if audio_path.exists() else "✗"
            sub_check = "✓" if ass_path.exists() or srt_path.exists() else "✗"
            vid_check = "✓" if video_path.exists() else "✗"

            motion = scene.get("animation") or (
                (scene.get("motion") or {}).get("motion_type") or "none"
            )
            narration = scene.get("narration", "").strip()
            duration = scene.get("duration_seconds", 0)

            lines += [
                "---",
                "",
                f"## Scene {idx:03d} — {scene.get('title', '')}",
                "",
                f"**Status:** {_STATE_LABELS.get(state, state.value)}",
            ]
            if notes:
                lines.append(f"**Notes:** {notes}")

            lines += [
                "",
                f"**Motion:** {motion}",
                f"**Duration:** {duration}s",
                "",
                "**Narration:**",
                f"> {narration}",
                "",
                "**Assets:**",
                f"- Image: {img_check} `images/scene-{idx:03d}.png`",
                f"- Audio: {aud_check} `audio/scene-{idx:03d}.mp3`",
                f"- Subtitles: {sub_check}",
                f"- Scene video: {vid_check} `video/scene-{idx:03d}.mp4`",
                "",
            ]

        out.write_text("\n".join(lines), encoding="utf-8")
        return out
