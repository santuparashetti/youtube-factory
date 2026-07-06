"""Video composition node — single-pass continuous render into final.mp4."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.video.pipeline import compose_continuous_video

console = Console()


def video_concatenator_node(state: VideoState) -> dict:
    """
    Compose all scene assets into final.mp4 via a single continuous render pass.

    Delegates to ``compose_continuous_video()`` — the same function used by
    ``VideoPipeline`` — so the agent-graph build path produces identical output
    to the ``ytfactory render`` CLI path.  Reads raw assets (PNG images, MP3
    narration, ASS/SRT subtitles) directly; per-scene clips are not used for
    composition.
    """
    project_id = state["project_id"]
    scene_plan = state.get("scene_plan", [])

    if not scene_plan:
        console.print("[yellow]⚠  No scene plan found — cannot compose final video[/yellow]")
        return {"stage_errors": ["No scene plan found for composition"]}

    settings = Settings()
    project_dir = Path(WORKSPACE_DIR) / project_id
    video_dir = project_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)

    scene_count = len(scene_plan)
    bgm_label = " + BGM" if settings.bgm_enabled else ""
    console.print(
        f"\n[bold cyan]🎬 Continuous Renderer[/bold cyan] — "
        f"composing {scene_count} scenes → final.mp4{bgm_label}\n"
    )

    final_path = video_dir / "final.mp4"

    try:
        compose_continuous_video(project_dir, video_dir, settings)

        size_mb = final_path.stat().st_size / (1024 * 1024)
        bgm_note = " with BGM mixed" if settings.bgm_enabled else ""
        console.print(
            Panel(
                f"[green]✓ final.mp4 created{bgm_note}[/green]\n"
                f"Path: {final_path}\n"
                f"Size: {size_mb:.1f} MB\n"
                f"Scenes: {scene_count}",
                title="Continuous Render",
                border_style="green",
            )
        )
        return {"final_video_path": str(final_path)}

    except Exception as exc:
        error_msg = f"Video composition failed: {exc}"
        console.print(f"[red]✗ Composition failed:[/red]\n{error_msg}")
        return {"stage_errors": [error_msg]}
