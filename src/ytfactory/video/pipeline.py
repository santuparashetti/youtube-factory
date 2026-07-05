from __future__ import annotations

import json
import subprocess
from pathlib import Path

from rich.progress import track

from ytfactory.cinematic.effects import EffectsPlanner
from ytfactory.cinematic.motion import MotionPlanner
from ytfactory.cinematic.transitions import TransitionPlanner
from ytfactory.config.settings import Settings

from .artifacts import video_directory
from .ffmpeg import FFmpegRenderer


class VideoPipeline:
    """Render all scenes into individual clips, then concatenate into final.mp4."""

    def __init__(self):
        self.renderer = FFmpegRenderer()
        settings = Settings()
        self._profile = settings.render_profile
        self._motion_planner = MotionPlanner()
        self._transition_planner = TransitionPlanner()
        self._effects_planner = EffectsPlanner()

    def run(
        self,
        project: str,
    ) -> None:

        project_dir = Path("workspace") / "jobs" / project

        scene_plan = project_dir / "scenes" / "scene-plan.json"

        if not scene_plan.exists():
            raise FileNotFoundError(f"Missing scene plan: {scene_plan}")

        with open(
            scene_plan,
            encoding="utf-8",
        ) as f:
            scenes = json.load(f)["scenes"]

        # Apply cinematic motion, transitions, and effects (profile from Settings)
        scenes = self._motion_planner.plan(scenes, profile=self._profile)
        scenes = self._transition_planner.plan(scenes, profile=self._profile)
        scenes = self._effects_planner.plan(scenes, profile=self._profile)

        output_dir = video_directory(project)

        print(f"\nRendering {len(scenes)} video scenes [profile: {self._profile}]...\n")

        scene_clips: list[Path] = []

        for scene in track(
            scenes,
            description="Rendering",
        ):
            index = scene["index"]
            duration_hint = float(scene.get("duration_seconds", 10))
            motion_spec = scene.get("motion")
            t_in = scene.get("transition_in")
            t_out = scene.get("transition_out")
            effect_spec = scene.get("effects")

            # Asset scenes reference their asset_path directly instead of
            # an AI-generated image in the images/ directory.
            if scene.get("scene_type") == "asset":
                asset_path = Path(scene.get("asset_path", ""))
                if not asset_path.is_absolute():
                    asset_path = Path.cwd() / asset_path
                image = asset_path
            else:
                image = project_dir / "images" / f"scene-{index:03d}.png"

            audio = project_dir / "audio" / f"scene-{index:03d}.mp3"

            # Prefer ASS (styled) over SRT — both may exist after the caption stage
            ass_sub = project_dir / "subtitles" / f"scene-{index:03d}.ass"
            srt_sub = project_dir / "subtitles" / f"scene-{index:03d}.srt"
            subtitle = ass_sub if ass_sub.exists() else srt_sub

            output = output_dir / f"scene-{index:03d}.mp4"

            if not image.exists():
                raise FileNotFoundError(image)

            if not audio.exists():
                raise FileNotFoundError(audio)

            if not subtitle.exists():
                raise FileNotFoundError(
                    f"No subtitle file found for scene {index}. "
                    f"Expected {ass_sub} or {srt_sub}."
                )

            if not output.exists():
                self.renderer.render(
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

            scene_clips.append(output)

        print("\n✓ All scenes rendered. Concatenating final video...\n")

        final_video = output_dir / "final.mp4"
        concat_list = output_dir / "concat_list.txt"

        concat_list.write_text(
            "\n".join(f"file '{clip.resolve()}'" for clip in scene_clips),
            encoding="utf-8",
        )

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(final_video),
            ],
            check=True,
        )

        concat_list.unlink()

        print(f"✓ Final video: {final_video}\n")
