"""ShortsMediaPipeline — Phase 1B.

Converts Phase 1A artifacts (scene-plan + user-supplied images) into a
finished vertical video:

  images/ (user-supplied)
      ↓  TTS
  audio/scene-NNN.mp3  +  audio/scene-NNN.timing.json
      ↓  subtitles
  subtitles/scene-NNN.ass  +  subtitles/scene-NNN.srt
      ↓  per-scene render
  video/scene-NNN.mp4
      ↓  continuous assembly (FFmpeg concat)
  video/final.work.mp4
      ↓  BGM mix
  video/final.mp4

All output lives under shorts/<short_id>/ — never in long-form directories.
Long-form pipeline classes (VoicePipeline, CaptionPipeline, VideoPipeline,
FFmpegRenderer, BGMMixer) are NOT modified; providers are called directly.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from loguru import logger
from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

from video_core.providers.tts.factory import get_tts_provider
from video_core.providers.tts.optimizer import SpeechOptimizer
from ytfactory.bgm.config import BGMConfig
from ytfactory.bgm.library import BGMLibrary
from ytfactory.bgm.mixer import BGMMixer
from ytfactory.config.settings import Settings
from ytfactory.providers.tts.pacing.injector import PauseInjector
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.shorts.ffmpeg import ShortsFFmpegRenderer
from ytfactory.shorts.models import ShortsScenePlan
from ytfactory.shorts.repository import ShortsRepository
from ytfactory.subtitles import SubtitleEngine
from ytfactory.storage.project_repository import ProjectRepository

console = Console()

_optimizer = SpeechOptimizer()
_pacer = PauseInjector()


# ── Result model ──────────────────────────────────────────────────────────────


class ShortsMediaResult(BaseModel):
    short_id: str
    parent_video_id: str

    images_ready: bool
    missing_images: list[str]

    tts_completed: bool
    subtitles_completed: bool
    render_completed: bool
    assembly_completed: bool
    bgm_completed: bool

    final_video_path: Optional[str]
    duration_seconds: Optional[float]

    errors: list[str]


# ── Settings patcher ──────────────────────────────────────────────────────────


def _make_shorts_settings(base: Settings) -> Settings:
    """Return a copy of *base* with 9:16 width/height overrides applied."""
    return base.model_copy(
        update={
            "video_width": base.shorts_video_width,
            "video_height": base.shorts_video_height,
            "video_fps": base.shorts_video_fps,
            "subtitle_ass_play_res_x": base.shorts_subtitle_play_res_x,
            "subtitle_ass_play_res_y": base.shorts_subtitle_play_res_y,
        }
    )


# ── Image gate ────────────────────────────────────────────────────────────────


def _check_images_ready(
    short_dir: Path,
    scene_plan: ShortsScenePlan,
) -> tuple[bool, list[str]]:
    """Return (all_ready, list_of_missing_filenames)."""
    images_dir = short_dir / "images"
    missing: list[str] = []
    for scene in scene_plan.scenes:
        filename = f"scene-{scene.index:03d}.png"
        if not (images_dir / filename).is_file():
            missing.append(filename)
    return (len(missing) == 0, missing)


# ── Timing helpers ────────────────────────────────────────────────────────────


def _actual_audio_duration(audio: Path, timing_path: Path, fallback: float) -> float:
    """Return best-estimate audio duration in seconds."""
    ffprobe_dur = 0.0
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio),
            ],
            capture_output=True, text=True, check=True, timeout=10,
        )
        ffprobe_dur = float(result.stdout.strip())
    except Exception:
        pass

    try:
        data = json.loads(timing_path.read_text(encoding="utf-8"))
        if data and isinstance(data, list):
            end = float(data[-1]["end"])
            if end > 0.0:
                return min(end, ffprobe_dur) if ffprobe_dur > 0.0 else end
    except Exception:
        pass

    return ffprobe_dur if ffprobe_dur > 0.0 else fallback


# ── TTS ───────────────────────────────────────────────────────────────────────


def _run_tts_for_short(
    short_dir: Path,
    scene_plan: ShortsScenePlan,
    settings: Settings,
    force: bool,
) -> tuple[bool, list[str]]:
    """Generate TTS audio for every scene in the Short.

    Returns (all_succeeded, error_list).
    Calls providers directly — does NOT go through VoicePipeline.run().
    """
    audio_dir = short_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    provider = get_tts_provider(settings)
    style = getattr(settings, "tts_pacing_profile", "spiritual")
    use_pacing = getattr(settings, "tts_pacing_enabled", True)
    skip_existing = getattr(settings, "tts_skip_existing", True)

    total = len(scene_plan.scenes)
    errors: list[str] = []

    for idx, scene in enumerate(scene_plan.scenes):
        output = audio_dir / f"scene-{scene.index:03d}.mp3"
        timing_output = audio_dir / f"scene-{scene.index:03d}.timing.json"

        if not force and skip_existing and output.is_file() and timing_output.is_file():
            logger.debug("Shorts TTS: skip scene {} (already exists)", scene.index)
            continue

        scene_position = idx / max(total - 1, 1)

        try:
            if use_pacing:
                _, boundaries = _pacer.generate(
                    narration=scene.narration,
                    output_path=output,
                    optimizer=_optimizer,
                    provider=provider,
                    profile=style,
                    style=style,
                    language="en",
                    scene_position=scene_position,
                    keywords=None,
                )
            else:
                optimized = _optimizer.optimize(
                    scene.narration,
                    style=style,
                    scene_position=scene_position,
                )
                _, boundaries = provider.generate_with_boundaries(
                    text=optimized,
                    output_path=output,
                    language="en",
                    style=style,
                    scene_position=scene_position,
                )

            timing_output.write_text(
                json.dumps(boundaries, indent=2),
                encoding="utf-8",
            )
            logger.info(
                "Shorts TTS: scene {} done ({} words)",
                scene.index,
                len(scene.narration.split()),
            )
        except Exception as exc:
            msg = f"TTS failed for scene {scene.index}: {exc}"
            logger.error(msg)
            errors.append(msg)

    return (len(errors) == 0, errors)


# ── Subtitles ─────────────────────────────────────────────────────────────────


def _run_subtitles_for_short(
    short_dir: Path,
    scene_plan: ShortsScenePlan,
    shorts_settings: Settings,
    project_id: str,
    force: bool,
) -> tuple[bool, list[str]]:
    """Generate ASS + SRT subtitle files for every scene.

    Calls SubtitleEngine directly — does NOT go through CaptionPipeline.run().
    Uses patched settings so PlayResX/Y match 1080×1920.
    """
    audio_dir = short_dir / "audio"
    subs_dir = short_dir / "subtitles"
    subs_dir.mkdir(parents=True, exist_ok=True)

    engine = SubtitleEngine.from_settings(shorts_settings)
    use_ass = str(getattr(shorts_settings, "subtitle_format", "ass")).lower() == "ass"
    errors: list[str] = []

    for scene in scene_plan.scenes:
        ass_path = subs_dir / f"scene-{scene.index:03d}.ass"
        srt_path = subs_dir / f"scene-{scene.index:03d}.srt"
        primary = ass_path if use_ass else srt_path

        if not force and primary.is_file():
            logger.debug("Shorts subtitles: skip scene {} (already exists)", scene.index)
            continue

        timing_file = audio_dir / f"scene-{scene.index:03d}.timing.json"
        boundaries: list[dict] = []
        if timing_file.is_file():
            try:
                data = timing_file.read_text(encoding="utf-8")
                boundaries = json.loads(data) if data.strip() else []
            except Exception:
                boundaries = []

        try:
            cues, _ = engine.build_cues(
                boundaries=boundaries,
                narration=scene.narration,
                scene_index=scene.index,
                project_id=project_id,
                total_duration=scene.duration_seconds,
            )

            if use_ass:
                ass_content = engine.ass_writer.write(cues)
                srt_content = engine.srt_writer.write(cues)
                ass_path.write_text(ass_content, encoding="utf-8")
                srt_path.write_text(srt_content, encoding="utf-8")
            else:
                srt_content = engine.srt_writer.write(cues)
                srt_path.write_text(srt_content, encoding="utf-8")

            logger.debug("Shorts subtitles: scene {} done", scene.index)
        except Exception as exc:
            msg = f"Subtitle generation failed for scene {scene.index}: {exc}"
            logger.error(msg)
            errors.append(msg)

    return (len(errors) == 0, errors)


# ── Per-scene render ──────────────────────────────────────────────────────────


def _run_render_for_short(
    short_dir: Path,
    scene_plan: ShortsScenePlan,
    shorts_settings: Settings,
    force: bool,
) -> tuple[bool, list[str]]:
    """Render per-scene MP4 clips using ShortsFFmpegRenderer (9:16, setdar=9/16)."""
    images_dir = short_dir / "images"
    audio_dir = short_dir / "audio"
    subs_dir = short_dir / "subtitles"
    video_dir = short_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)

    renderer = ShortsFFmpegRenderer(shorts_settings)
    errors: list[str] = []

    for scene in scene_plan.scenes:
        output = video_dir / f"scene-{scene.index:03d}.mp4"

        if not force and output.is_file():
            logger.debug("Shorts render: skip scene {} (already exists)", scene.index)
            continue

        image = images_dir / f"scene-{scene.index:03d}.png"
        audio = audio_dir / f"scene-{scene.index:03d}.mp3"
        timing = audio_dir / f"scene-{scene.index:03d}.timing.json"
        ass_sub = subs_dir / f"scene-{scene.index:03d}.ass"
        srt_sub = subs_dir / f"scene-{scene.index:03d}.srt"
        subtitle = ass_sub if ass_sub.is_file() else srt_sub

        if not image.is_file():
            msg = f"Scene {scene.index}: image missing at {image}"
            errors.append(msg)
            continue
        if not audio.is_file():
            msg = f"Scene {scene.index}: audio missing at {audio} (TTS may have failed)"
            errors.append(msg)
            continue
        if not subtitle.is_file():
            msg = f"Scene {scene.index}: subtitle missing at {ass_sub} or {srt_sub}"
            errors.append(msg)
            continue

        duration_hint = _actual_audio_duration(audio, timing, scene.duration_seconds)

        try:
            renderer.render(
                image=image,
                audio=audio,
                subtitle=subtitle,
                output=output,
                duration_hint=duration_hint,
            )
            logger.info("Shorts render: scene {} done ({:.1f}s)", scene.index, duration_hint)
        except Exception as exc:
            msg = f"Render failed for scene {scene.index}: {exc}"
            logger.error(msg)
            errors.append(msg)

    return (len(errors) == 0, errors)


# ── Continuous assembly ───────────────────────────────────────────────────────


def _shorts_assemble_continuous(
    short_dir: Path,
    scene_plan: ShortsScenePlan,
    shorts_settings: Settings,
    force: bool,
) -> tuple[bool, list[str]]:
    """Concatenate per-scene MP4s into a single final.work.mp4.

    Uses FFmpeg concat demuxer — no re-encoding of video stream.
    """
    video_dir = short_dir / "video"
    output = video_dir / "final.work.mp4"

    if not force and output.is_file():
        logger.debug("Shorts assembly: reusing existing final.work.mp4")
        return (True, [])

    # Collect scene clips in scene order
    clips: list[Path] = []
    for scene in scene_plan.scenes:
        clip = video_dir / f"scene-{scene.index:03d}.mp4"
        if not clip.is_file():
            return (
                False,
                [f"Assembly failed: scene clip missing: {clip}"],
            )
        clips.append(clip)

    if not clips:
        return (False, ["Assembly failed: no scene clips found"])

    # Build concat list
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        for clip in clips:
            f.write(f"file '{clip.resolve()}'\n")
        filelist = Path(f.name)

    W = shorts_settings.video_width
    H = shorts_settings.video_height
    fps = shorts_settings.video_fps

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(filelist),
                "-c:v", "libx264",
                "-preset", shorts_settings.video_preset,
                "-crf", str(shorts_settings.video_crf),
                "-pix_fmt", "yuv420p",
                "-profile:v", "high",
                "-g", str(shorts_settings.video_keyframe_interval),
                "-movflags", "+faststart+negative_cts_offsets",
                "-c:a", "aac",
                "-b:a", shorts_settings.video_audio_bitrate,
                "-ar", "48000",
                "-r", str(fps),
                "-s", f"{W}x{H}",
                "-vf", "setdar=9/16",
                str(output),
            ],
            check=True,
            capture_output=True,
            timeout=600,
        )
        logger.info("Shorts assembly: final.work.mp4 written ({} scenes)", len(clips))
        return (True, [])
    except subprocess.CalledProcessError as exc:
        err = exc.stderr.decode(errors="replace")[-500:] if exc.stderr else str(exc)
        return (False, [f"Assembly FFmpeg failed: {err}"])
    finally:
        filelist.unlink(missing_ok=True)


# ── BGM mix ───────────────────────────────────────────────────────────────────


def _run_bgm_for_short(
    short_dir: Path,
    shorts_settings: Settings,
    force: bool,
) -> tuple[bool, list[str]]:
    """Mix BGM into final.work.mp4 → final.mp4.

    BGMMixer is format-agnostic; call it exactly as the long-form pipeline does.
    When BGM is disabled or no tracks are found, final.work.mp4 is copied to
    final.mp4 without music.
    """
    video_dir = short_dir / "video"
    work_path = video_dir / "final.work.mp4"
    final_path = video_dir / "final.mp4"

    if not force and final_path.is_file():
        logger.debug("Shorts BGM: reusing existing final.mp4")
        return (True, [])

    if not work_path.is_file():
        return (False, ["BGM mix skipped: final.work.mp4 not found"])

    bgm_enabled = getattr(shorts_settings, "shorts_bgm_enabled", True)
    if not bgm_enabled or not getattr(shorts_settings, "bgm_enabled", True):
        logger.info("Shorts BGM: disabled — copying final.work.mp4 → final.mp4")
        import shutil
        shutil.copy2(str(work_path), str(final_path))
        return (True, [])

    config = _bgm_config_from_settings(shorts_settings)
    category = shorts_settings.bgm_category
    if category == "auto":
        category = "spiritual"  # default for Shorts

    track = BGMLibrary(config).find_track(category)
    if track is None:
        logger.warning(
            "Shorts BGM: no tracks found for category '{}' — using no-music render",
            category,
        )
        import shutil
        shutil.copy2(str(work_path), str(final_path))
        return (True, [])

    try:
        result = BGMMixer(config).mix(
            video_path=work_path,
            track=track,
            output_path=final_path,
            project_dir=short_dir,
        )
        if result.success:
            logger.info("Shorts BGM: mix complete → final.mp4")
            return (True, [])
        else:
            return (False, [f"BGM mix failed: {result.error[:300]}"])
    except Exception as exc:
        return (False, [f"BGM mix raised: {exc}"])


def _bgm_config_from_settings(settings: Settings) -> BGMConfig:
    return BGMConfig(
        enabled=settings.bgm_enabled,
        category=settings.bgm_category,
        library_path=settings.bgm_library_path,
        bgm_volume=settings.bgm_volume,
        duck_floor=settings.bgm_duck_floor,
        duck_threshold=settings.bgm_duck_threshold,
        duck_ratio=settings.bgm_duck_ratio,
        duck_attack_ms=settings.bgm_duck_attack_ms,
        duck_release_ms=settings.bgm_duck_release_ms,
        fade_in_seconds=settings.bgm_fade_in_seconds,
        fade_out_seconds=settings.bgm_fade_out_seconds,
        crossfade_seconds=settings.bgm_crossfade_seconds,
        random_track=settings.bgm_random_track,
        vad_enabled=settings.bgm_vad_enabled,
        vad_provider=settings.bgm_vad_provider,
        phrase_gap_ms=settings.bgm_phrase_gap_ms,
        long_silence_ms=settings.bgm_long_silence_ms,
        dynamic_ducking=settings.bgm_dynamic_ducking,
        restore_curve=settings.bgm_restore_curve,
        adaptive_mixing=settings.bgm_adaptive_mixing,
        hold_after_speech_ms=settings.bgm_hold_after_speech_ms,
        long_silence_threshold_ms=settings.bgm_long_silence_threshold_ms,
        narration_level_lufs=settings.bgm_narration_level_lufs,
        music_level_lufs=settings.bgm_music_level_lufs,
        transition_curve=settings.bgm_transition_curve,
    )


# ── Duration probe ────────────────────────────────────────────────────────────


def _probe_video_duration(path: Path) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", str(path),
            ],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return float(json.loads(result.stdout)["format"]["duration"])
    except Exception:
        return None


# ── Pipeline ──────────────────────────────────────────────────────────────────


class ShortsMediaPipeline:
    """Phase 1B pipeline: images → TTS → subtitles → render → assemble → BGM."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()
        self._repo = ShortsRepository()
        self._projects = ProjectRepository()

    def run(
        self,
        project_id: str,
        short_id: str,
        force: bool = False,
    ) -> ShortsMediaResult:
        """Run the full media pipeline for one Short.

        Returns a ShortsMediaResult regardless of success — never raises on
        recoverable failures (images not ready, a stage error) so the caller
        can continue to the next Short.
        """
        errors: list[str] = []

        # ── 1. Load scene plan ───────────────────────────────────────────
        scene_plan = self._repo.load_scene_plan(project_id, short_id)
        if scene_plan is None:
            return ShortsMediaResult(
                short_id=short_id,
                parent_video_id=project_id,
                images_ready=False,
                missing_images=[],
                tts_completed=False,
                subtitles_completed=False,
                render_completed=False,
                assembly_completed=False,
                bgm_completed=False,
                final_video_path=None,
                duration_seconds=None,
                errors=[f"No scene-plan.json found for {short_id}. Run generate-shorts first."],
            )

        short_dir = Path(WORKSPACE_DIR) / project_id / "shorts" / short_id
        shorts_settings = _make_shorts_settings(self._settings)

        # ── 2. Image gate ────────────────────────────────────────────────
        images_ready, missing_images = _check_images_ready(short_dir, scene_plan)
        if not images_ready:
            console.print(f"\n[yellow]Images not ready for {short_id}.[/yellow]")
            console.print(f"  Missing: {', '.join(missing_images)}")
            console.print(
                f"  Drop all images into:\n"
                f"    {short_dir / 'images'}\n"
                f"  Then re-run: ytfactory generate-shorts-video {project_id}"
            )
            return ShortsMediaResult(
                short_id=short_id,
                parent_video_id=project_id,
                images_ready=False,
                missing_images=missing_images,
                tts_completed=False,
                subtitles_completed=False,
                render_completed=False,
                assembly_completed=False,
                bgm_completed=False,
                final_video_path=None,
                duration_seconds=None,
                errors=[],
            )

        # ── 3. TTS ───────────────────────────────────────────────────────
        tts_ok, tts_errors = _run_tts_for_short(
            short_dir, scene_plan, shorts_settings, force
        )
        errors.extend(tts_errors)

        # ── 4. Subtitles ─────────────────────────────────────────────────
        subs_ok, subs_errors = _run_subtitles_for_short(
            short_dir, scene_plan, shorts_settings, project_id, force
        )
        errors.extend(subs_errors)

        # ── 5. Per-scene render ──────────────────────────────────────────
        render_ok, render_errors = _run_render_for_short(
            short_dir, scene_plan, shorts_settings, force
        )
        errors.extend(render_errors)

        # ── 6. Continuous assembly ───────────────────────────────────────
        assemble_ok, assemble_errors = _shorts_assemble_continuous(
            short_dir, scene_plan, shorts_settings, force
        )
        errors.extend(assemble_errors)

        # ── 7. BGM mix ───────────────────────────────────────────────────
        bgm_ok, bgm_errors = _run_bgm_for_short(short_dir, shorts_settings, force)
        errors.extend(bgm_errors)

        final_path = short_dir / "video" / "final.mp4"
        final_video_path = str(final_path) if final_path.is_file() else None
        duration = _probe_video_duration(final_path) if final_path.is_file() else None

        return ShortsMediaResult(
            short_id=short_id,
            parent_video_id=project_id,
            images_ready=True,
            missing_images=[],
            tts_completed=tts_ok,
            subtitles_completed=subs_ok,
            render_completed=render_ok,
            assembly_completed=assemble_ok,
            bgm_completed=bgm_ok,
            final_video_path=final_video_path,
            duration_seconds=duration,
            errors=errors,
        )

    def run_all(
        self,
        project_id: str,
        short_id_filter: str | None = None,
        force: bool = False,
    ) -> list[ShortsMediaResult]:
        """Run for all Shorts (or only the specified short_id)."""
        extraction = self._repo.load_opportunities(project_id)
        if extraction is None:
            console.print(
                "[red]No opportunities.json found. Run generate-shorts first.[/red]"
            )
            return []

        short_ids: list[str] = []
        for i, _ in enumerate(extraction.selected, start=1):
            sid = f"short-{i:03d}"
            if short_id_filter is None or sid == short_id_filter:
                short_ids.append(sid)

        if not short_ids:
            console.print(
                f"[yellow]No matching shorts found"
                f"{f' for {short_id_filter}' if short_id_filter else ''}.[/yellow]"
            )
            return []

        results: list[ShortsMediaResult] = []
        for short_id in short_ids:
            console.print(f"\nProcessing [bold]{short_id}[/bold]...")
            result = self.run(project_id, short_id, force=force)
            results.append(result)

        _print_media_summary(project_id, results)
        return results


# ── Summary table ─────────────────────────────────────────────────────────────


def _print_media_summary(project_id: str, results: list[ShortsMediaResult]) -> None:
    console.print("\n[bold]Shorts Video Generation[/bold]")
    console.print(f"Parent: [cyan]{project_id}[/cyan]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Short", min_width=10)
    table.add_column("Images", min_width=8)
    table.add_column("TTS", min_width=6)
    table.add_column("Subtitles", min_width=10)
    table.add_column("Render", min_width=8)
    table.add_column("BGM", min_width=6)
    table.add_column("Output", min_width=30)

    def _cell(ok: bool, label_ok: str = "DONE", label_fail: str = "FAIL") -> str:
        color = "green" if ok else "red"
        return f"[{color}]{label_ok if ok else label_fail}[/{color}]"

    for r in results:
        if not r.images_ready:
            missing_note = f"(images missing: {', '.join(r.missing_images[:2])}{'...' if len(r.missing_images) > 2 else ''})"
            table.add_row(
                r.short_id,
                "[yellow]WAITING[/yellow]",
                "[dim]-[/dim]", "[dim]-[/dim]", "[dim]-[/dim]", "[dim]-[/dim]",
                f"[dim]{missing_note}[/dim]",
            )
        else:
            output_cell = (
                f"[green]{r.short_id}/video/final.mp4[/green]"
                if r.final_video_path
                else "[red](no output)[/red]"
            )
            table.add_row(
                r.short_id,
                "[green]READY[/green]",
                _cell(r.tts_completed),
                _cell(r.subtitles_completed),
                _cell(r.render_completed),
                _cell(r.bgm_completed),
                output_cell,
            )

    console.print(table)
