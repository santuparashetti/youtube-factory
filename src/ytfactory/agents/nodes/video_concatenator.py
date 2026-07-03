"""Video concatenator node — stitch all scene clips into final.mp4."""

from __future__ import annotations

import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from ytfactory.agents.state import VideoState
from ytfactory.shared.constants import WORKSPACE_DIR

console = Console()


def video_concatenator_node(state: VideoState) -> dict:
    """
    Concatenate per-scene MP4 clips into a single final.mp4 using
    FFmpeg's concat demuxer (stream-copy, no re-encode → fast).
    """
    project_id = state["project_id"]
    scene_video_paths: dict[int, str] = state.get("scene_video_paths", {})

    if not scene_video_paths:
        console.print("[yellow]⚠  No scene videos to concatenate[/yellow]")
        return {"stage_errors": ["No scene videos found for concatenation"]}

    project_dir = Path(WORKSPACE_DIR) / project_id
    video_dir = project_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)

    sorted_indices = sorted(scene_video_paths.keys())
    console.print(
        f"\n[bold cyan]🔗 Video Concatenator[/bold cyan] — "
        f"stitching {len(sorted_indices)} clips into final.mp4\n"
    )

    # Write concat list (paths relative to video_dir so FFmpeg -safe 0 not needed)
    concat_file = video_dir / "concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for idx in sorted_indices:
            clip_path = Path(scene_video_paths[idx])
            # Use absolute path with safe escaping
            f.write(f"file '{clip_path.resolve()}'\n")

    final_path = video_dir / "final.mp4"

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",          # stream copy — no re-encode
                str(final_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        size_mb = final_path.stat().st_size / (1024 * 1024)
        console.print(Panel(
            f"[green]✓ final.mp4 created[/green]\n"
            f"Path: {final_path}\n"
            f"Size: {size_mb:.1f} MB\n"
            f"Scenes: {len(sorted_indices)}",
            title="Video Concatenator",
            border_style="green",
        ))
        return {"final_video_path": str(final_path)}

    except subprocess.CalledProcessError as exc:
        error_msg = f"FFmpeg concat failed: {exc.stderr[-500:]}"
        console.print(f"[red]✗ Concatenation failed:[/red]\n{error_msg}")
        return {"stage_errors": [error_msg]}
