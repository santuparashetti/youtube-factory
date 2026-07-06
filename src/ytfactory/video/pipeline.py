from __future__ import annotations

import json
import subprocess
from pathlib import Path

from loguru import logger
from rich.progress import track

from ytfactory.cinematic.effects import EffectsPlanner
from ytfactory.cinematic.motion import MotionPlanner
from ytfactory.cinematic.transitions import TransitionPlanner
from ytfactory.config.settings import Settings

from .artifacts import video_directory
from .ffmpeg import FFmpegRenderer


def _actual_audio_duration(audio: Path, timing_path: Path, fallback: float) -> float:
    """Return actual audio duration in seconds.

    Primary source: timing.json written by VoicePipeline (last entry's "end").
    Fallback: ffprobe on the MP3 file.
    Final fallback: the supplied fallback value (scene plan estimate).
    """
    try:
        data = json.loads(timing_path.read_text(encoding="utf-8"))
        if data and isinstance(data, list):
            end = float(data[-1]["end"])
            if end > 0.0:
                return end
    except Exception:
        pass

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        val = float(result.stdout.strip())
        if val > 0.0:
            return val
    except Exception:
        pass

    return fallback


def _generate_intro_clip(
    output_dir: Path,
    width: int,
    height: int,
    fps: int,
    duration: float,
    settings: Settings | None = None,
) -> Path:
    """Generate a silent black intro clip for the cinematic opening."""
    intro_path = output_dir / "intro.mp4"
    if intro_path.exists():
        return intro_path

    cfg = settings or Settings()
    enc_args: list[str] = [
        "-c:v", "libx264",
        "-preset", cfg.video_preset,
        "-crf", str(cfg.video_crf),
        "-pix_fmt", "yuv420p",
        "-profile:v", "high",
        "-movflags", "+faststart",
    ]
    if cfg.video_tune:
        enc_args += ["-tune", cfg.video_tune]

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:s={width}x{height}:r={fps}:d={duration:.4f}",
            "-f", "lavfi",
            "-i", "anullsrc=r=48000:cl=stereo",
            "-t", f"{duration:.4f}",
            *enc_args,
            "-c:a", "aac",
            "-b:a", cfg.video_audio_bitrate,
            "-ar", "48000",
            str(intro_path),
        ],
        check=True,
    )
    return intro_path


def _bgm_config_from_settings(settings: Settings):
    """Build a BGMConfig from application Settings."""
    from ytfactory.bgm.config import BGMConfig

    return BGMConfig(
        enabled=settings.bgm_enabled,
        category=settings.bgm_category,
        library_path=settings.bgm_library_path,
        bgm_volume=settings.bgm_volume,
        duck_threshold=settings.bgm_duck_threshold,
        duck_ratio=settings.bgm_duck_ratio,
        duck_attack_ms=settings.bgm_duck_attack_ms,
        duck_release_ms=settings.bgm_duck_release_ms,
        fade_in_seconds=settings.bgm_fade_in_seconds,
        fade_out_seconds=settings.bgm_fade_out_seconds,
        crossfade_seconds=settings.bgm_crossfade_seconds,
        random_track=settings.bgm_random_track,
    )


def _resolve_bgm_category(settings: Settings, project_dir: Path) -> str:
    """Return the BGM category to use — explicit setting or auto-detected from content."""
    if settings.bgm_category != "auto":
        return settings.bgm_category

    from ytfactory.bgm.detector import detect_category

    title = project_dir.name
    try:
        data = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
        title = data.get("title", title)
    except Exception:
        pass

    scene_titles: list[str] = []
    try:
        data = json.loads(
            (project_dir / "scenes" / "scene-plan.json").read_text(encoding="utf-8")
        )
        scene_titles = [s.get("title", "") for s in data.get("scenes", [])]
    except Exception:
        pass

    return detect_category(title, scene_titles)


class VideoPipeline:
    """Render all scenes into individual clips, then compose into final.mp4.

    Composition (``_compose_final_video``) concatenates all scene clips and,
    when BGM is enabled, immediately mixes background music — producing a
    single ``final.mp4`` that contains video, narration, subtitles, and music.
    BGM is not a separate post-processing step; it is sealed inside composition
    so every code path that calls ``VideoPipeline.run()`` — including the
    Auto Remediation engine — always produces the fully-mixed output.
    """

    def __init__(self):
        self.renderer = FFmpegRenderer()
        self._settings = Settings()
        self._profile = self._settings.render_profile
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
            # Use the scene plan estimate as the initial fallback; actual audio
            # duration (from timing.json or ffprobe) takes precedence so that
            # fade-out and zoompan frame counts cover the full narration.
            plan_duration = float(scene.get("duration_seconds", 10))
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
            timing_path = project_dir / "audio" / f"scene-{index:03d}.timing.json"

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
                # Measure actual audio duration so fade-out and zoompan frame
                # counts are anchored to the real narration length, not the
                # scene plan estimate.  This prevents black frames appearing
                # when TTS produces audio longer than duration_seconds.
                duration_hint = _actual_audio_duration(audio, timing_path, plan_duration)

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

        print("\n✓ All scenes rendered. Composing final video...\n")

        final_video = output_dir / "final.mp4"

        # Build the clip list: optional intro + all scene clips.
        clips_to_concat: list[Path] = []
        if self._settings.video_intro_enabled and self._settings.video_intro_seconds > 0:
            intro_clip = _generate_intro_clip(
                output_dir,
                self._settings.video_width,
                self._settings.video_height,
                self._settings.video_fps,
                self._settings.video_intro_seconds,
                settings=self._settings,
            )
            clips_to_concat.append(intro_clip)
        clips_to_concat.extend(scene_clips)

        # Compose: concatenate scenes + apply BGM in one indivisible step.
        self._compose_final_video(project, clips_to_concat, final_video)

        print(f"✓ Final video: {final_video}\n")

    # ── Composition ───────────────────────────────────────────────────────────

    def _compose_final_video(
        self,
        project_id: str,
        clips: list[Path],
        output_path: Path,
    ) -> None:
        """Concatenate all clips and apply BGM (when enabled) in one composition step.

        Writes a single ``output_path`` (final.mp4) that contains video,
        narration audio, burned-in subtitles, and — when ``bgm_enabled`` is
        True — background music with sidechain ducking.

        Uses a temporary ``.concat.mp4`` intermediate so that a failed BGM mix
        never corrupts or removes the concatenated-only version.
        """
        concat_list = output_path.parent / "concat_list.txt"
        concat_list.write_text(
            "\n".join(f"file '{clip.resolve()}'" for clip in clips),
            encoding="utf-8",
        )

        # Step 1 — concatenate all scene clips (lossless stream copy).
        tmp = output_path.with_suffix(".concat.mp4")
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list),
                "-c", "copy",
                str(tmp),
            ],
            check=True,
        )
        concat_list.unlink()

        # Step 2 — BGM mixing (structural part of composition, not post-process).
        if self._settings.bgm_enabled:
            from ytfactory.bgm.library import BGMLibrary
            from ytfactory.bgm.mixer import BGMMixer

            config = _bgm_config_from_settings(self._settings)
            project_dir = output_path.parent.parent
            category = _resolve_bgm_category(self._settings, project_dir)

            track = BGMLibrary(config).find_track(category)
            if track:
                logger.info("BGM composition: {} ({})", track.title, category)
                result = BGMMixer(config).mix(tmp, track, output_path)
                tmp.unlink(missing_ok=True)
                if not result.success:
                    raise RuntimeError(f"BGM mixing failed: {result.error[:300]}")
                return
            else:
                logger.warning(
                    "BGM enabled but no tracks found for category '{}' — composing without music",
                    category,
                )

        # No BGM (or no tracks found): promote temp file to the final output.
        tmp.rename(output_path)
