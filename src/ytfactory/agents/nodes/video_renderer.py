"""Video renderer node — per-scene MP4 via FFmpeg."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.progress import track

from ytfactory.agents.state import VideoState
from video_core.cinematic.config import CinematicConfig
from video_core.cinematic.effects import EffectsPlanner
from video_core.cinematic.motion import MotionPlanner
from video_core.cinematic.rebalancer import MotionRebalancer
from video_core.cinematic.transitions import TransitionPlanner
from ytfactory.config.settings import Settings
from ytfactory.scenes.repository.scene_repository import SceneRepository
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.video.ffmpeg import FFmpegRenderer

_settings = Settings()
_motion_planner = MotionPlanner()
_transition_planner = TransitionPlanner()
_effects_planner = EffectsPlanner()

console = Console()


def video_renderer_node(state: VideoState) -> dict:
    """
    Render each scene: image + audio + subtitle → scene-NNN.mp4.
    Reads paths from VideoState (populated by parallel scene_assets nodes).
    Skips scenes with missing assets and records errors.
    """
    project_id = state["project_id"]
    scene_plan = state.get("scene_plan", [])

    image_paths: dict[int, str] = state.get("image_paths", {})
    audio_paths: dict[int, str] = state.get("audio_paths", {})
    srt_paths: dict[int, str] = state.get("srt_paths", {})

    project_dir = Path(WORKSPACE_DIR) / project_id
    video_dir = project_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)

    cinematic_cfg = CinematicConfig(
        profile=state.get("render_profile") or _settings.render_profile
    )

    # Build emotional intensity mapping from linked_segment metadata
    intensity_map: dict[int, str] = {}
    for scene in scene_plan:
        seg = scene.get("linked_segment") or {}
        raw = seg.get("emotional_intensity", "normal")
        intensity_map[scene["index"]] = str(raw).lower() if isinstance(raw, str) else "normal"

    scene_plan = _motion_planner.plan(
        list(scene_plan),
        profile=cinematic_cfg.profile,
        emotional_intensity=intensity_map,
    )
    scene_plan = _transition_planner.plan(scene_plan, profile=cinematic_cfg.profile)
    scene_plan = _effects_planner.plan(scene_plan, profile=cinematic_cfg.profile)

    scene_plan = MotionRebalancer().rebalance(scene_plan)

    SceneRepository().save_scenes(project_dir, scene_plan)

    renderer = FFmpegRenderer()
    errors: list[str] = []
    scene_video_paths: dict[int, str] = {}

    console.print(
        f"\n[bold cyan]🎥 Video Renderer[/bold cyan] — rendering {len(scene_plan)} scenes\n"
    )

    for scene in track(scene_plan, description="Rendering scenes"):
        index: int = scene["index"]
        duration_hint = float(scene.get("duration_seconds", 10))
        motion_spec: dict | None = scene.get("motion")
        t_in: dict | None = scene.get("transition_in")
        t_out: dict | None = scene.get("transition_out")
        effect_spec: dict | None = scene.get("effects")

        output = video_dir / f"scene-{index:03d}.mp4"

        # Use .get() → None so a missing entry is distinguishable from an empty
        # string.  Path("") == Path(".") which is always a valid directory, so
        # the old .exists() guard silently passed and FFmpeg received "-i .".
        image_str = image_paths.get(index)
        audio_str = audio_paths.get(index)
        subtitle_str = srt_paths.get(index)

        if image_str is None or not Path(image_str).is_file():
            errors.append(f"Scene {index}: missing image, skipped")
            console.print(f"  [yellow]⚠[/yellow] Scene {index} skipped — no image")
            continue

        if audio_str is None or not Path(audio_str).is_file():
            # TTS failed for this scene earlier in the pipeline
            expected = Path(WORKSPACE_DIR) / project_id / "audio" / f"scene-{index:03d}.mp3"
            errors.append(
                f"Scene {index}: narration audio missing — TTS failed earlier. "
                f"Expected: {expected}. Render skipped."
            )
            console.print(f"  [yellow]⚠[/yellow] Scene {index} skipped — no audio (TTS failed)")
            continue

        if subtitle_str is None or not Path(subtitle_str).is_file():
            errors.append(f"Scene {index}: missing subtitle, skipped")
            console.print(f"  [yellow]⚠[/yellow] Scene {index} skipped — no subtitle")
            continue

        image = Path(image_str)
        audio = Path(audio_str)
        subtitle = Path(subtitle_str)

        try:
            renderer.render(
                image=image,
                audio=audio,
                subtitle=subtitle,
                output=output,
                duration_hint=duration_hint,
                motion_spec=motion_spec,
                transition_in=t_in,
                transition_out=t_out,
                effect_spec=effect_spec,
            )
            scene_video_paths[index] = str(output)
        except Exception as exc:
            errors.append(f"Scene {index} render failed: {exc}")
            console.print(f"  [red]✗[/red] Scene {index} render error: {exc}")

    console.print(
        f"\n  [green]✓[/green] Rendered {len(scene_video_paths)}/{len(scene_plan)} scenes"
    )

    return {
        "scene_video_paths": scene_video_paths,
        "scene_plan": scene_plan,
        "stage_errors": errors,
    }
