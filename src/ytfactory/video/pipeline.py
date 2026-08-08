from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from loguru import logger
from rich.progress import track

from video_core.cinematic.effects import EffectsPlanner
from ytfactory.shared.pipeline_status import get_writer
from video_core.cinematic.motion import MotionPlanner
from video_core.cinematic.rebalancer import MotionRebalancer
from video_core.cinematic.transitions import TransitionPlanner
from ytfactory.config.settings import Settings
from ytfactory.scenes.repository.scene_repository import SceneRepository

from .artifacts import video_directory
from .ffmpeg import FFmpegRenderer
from .overlay import OverlayCompositor, resolve_blend_and_opacity


def _actual_audio_duration(audio: Path, timing_path: Path, fallback: float) -> float:
    """Return actual audio duration in seconds.

    Primary source: timing.json written by VoicePipeline (last entry's "end"),
    capped at the actual MP3 duration (Kokoro boundaries can exceed actual
    audio length when trailing silence is stripped during normalization).
    Fallback: ffprobe on the MP3 file.
    Final fallback: the supplied fallback value (scene plan estimate).
    """
    # Ground-truth MP3 duration — used to cap timing.json values and as fallback.
    ffprobe_dur = 0.0
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        ffprobe_dur = float(result.stdout.strip())
    except Exception:
        pass

    try:
        data = json.loads(timing_path.read_text(encoding="utf-8"))
        if data and isinstance(data, list):
            end = float(data[-1]["end"])
            if end > 0.0:
                # Cap against actual MP3: TTS boundaries may exceed real duration.
                return min(end, ffprobe_dur) if ffprobe_dur > 0.0 else end
    except Exception:
        pass

    if ffprobe_dur > 0.0:
        return ffprobe_dur

    return fallback


def _bgm_config_from_settings(settings: Settings):
    """Build a BGMConfig from application Settings."""
    from ytfactory.bgm.config import BGMConfig

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
        # V3 adaptive mixing
        adaptive_mixing=settings.bgm_adaptive_mixing,
        hold_after_speech_ms=settings.bgm_hold_after_speech_ms,
        long_silence_threshold_ms=settings.bgm_long_silence_threshold_ms,
        narration_level_lufs=settings.bgm_narration_level_lufs,
        music_level_lufs=settings.bgm_music_level_lufs,
        transition_curve=settings.bgm_transition_curve,
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


def _apply_overlays(
    tmp: Path,
    output_path: Path,
    settings: Settings,
    scenes: list[dict],
    durations: list[float],
    intro_seconds: float,
) -> None:
    """Composite mood overlays (per-scene, time-gated) + grain (global, always
    last) onto the continuous single-stream render, before BGM mixing.

    *tmp* is the just-rendered continuous video (all scenes + subtitle
    burn-in, one stream, no per-scene boundaries). Overlays are matched to
    time windows computed from *durations* rather than sliced/re-concatenated,
    preserving the single continuous stream (no GOP boundaries reintroduced).

    Falls back to a plain rename when overlays are disabled, the manifest is
    missing, or no scene matches any category — never blocks the render.
    """
    if not settings.overlay_enabled:
        logger.info("Overlay: all overlays disabled (OVERLAY_ENABLED=false)")
        tmp.rename(output_path)
        return

    compositor = OverlayCompositor(
        manifest_path=settings.overlay_manifest_path,
        skip=settings.skip_overlays,
        assets_dir=settings.overlay_assets_dir,
    )
    if compositor.skip or not compositor.manifest:
        tmp.rename(output_path)
        return

    width = settings.video_width
    height = settings.video_height
    fps = settings.video_fps
    assets_base = (
        compositor.assets_dir
        if compositor.assets_dir.is_absolute()
        else Path.cwd() / compositor.assets_dir
    )

    windows: list[tuple[float, float]] = []
    t = max(0.0, intro_seconds)
    for dur in durations:
        windows.append((t, t + dur))
        t += dur
    total_duration = t

    cmd: list[str] = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp)]
    filter_chains: list[str] = []
    # Both blend inputs must share a pixel format — feeding blend a yuv420p
    # base (tmp is encoded yuv420p) against an rgba overlay (base left
    # unformatted) is what produces a magenta/pink cast. Normalize once,
    # up front, so every blend stage below operates on matching formats.
    filter_chains.append("[0:v]format=rgba[base0]")
    current_label = "base0"
    stage = 0

    category_flags = {
        "smoke": settings.overlay_smoke_enabled,
        "particles": settings.overlay_particles_enabled,
        "god_rays": settings.overlay_god_rays_enabled,
        "rain": settings.overlay_rain_enabled,
    }

    for i, scene in enumerate(scenes):
        category, motion_type = compositor.select_category(scene)
        if not category:
            continue

        # "fog" has no manifest category of its own (aliases to "smoke") —
        # gate fog-triggered scenes by their own flag instead of smoke's.
        is_fog_origin = motion_type in ("fog", "visual:fog")
        category_enabled = (
            settings.overlay_fog_enabled
            if is_fog_origin
            else category_flags.get(category, True)
        )
        if not category_enabled:
            logger.info(
                "Overlay: {} disabled by setting (scene {})",
                "fog" if is_fog_origin else category,
                scene.get("index", i),
            )
            continue

        clips = compositor.manifest.get(category, [])
        if not clips:
            continue
        clip = clips[i % len(clips)]
        clip_path = assets_base / clip["file"]
        if not clip_path.is_file():
            logger.warning(
                "Overlay clip missing for scene {} (category={}): {} — skipping",
                scene.get("index", i),
                category,
                clip_path,
            )
            continue

        stage += 1
        start, end = windows[i]
        blend_mode, opacity = resolve_blend_and_opacity(category, clip)
        ov_in = f"{stage}:v"
        ov_label = f"ov{stage}"
        out_label = f"s{stage}"
        cmd += ["-stream_loop", "-1", "-t", f"{total_duration:.4f}", "-i", str(clip_path)]
        filter_chains.append(
            f"[{ov_in}]scale={width}:{height},setsar=1,format=rgba,"
            f"colorchannelmixer=aa={opacity:.3f}[{ov_label}]"
        )
        filter_chains.append(
            f"[{current_label}][{ov_label}]blend=all_mode={blend_mode}:"
            f"enable='between(t,{start:.4f},{end:.4f})'[{out_label}]"
        )
        current_label = out_label

    # Grain: conditional (Task 2.9) — global whole-video, layered last on top
    # of any mood overlay, but only when overall composition warrants it.
    grain_clips = compositor.manifest.get("grain", [])
    if not settings.overlay_grain_enabled:
        logger.info("Overlay: grain skipped (OVERLAY_GRAIN_ENABLED=false)")
    elif not grain_clips:
        logger.info("Overlay: grain skipped (no grain clip in manifest)")
    elif not compositor._should_apply_grain(scenes):
        logger.info(
            "Overlay: grain skipped (no scene era/mood/style warrants grain — "
            "contemporary/realistic composition)"
        )
    else:
        clip = grain_clips[0]
        clip_path = assets_base / clip["file"]
        if not clip_path.is_file():
            logger.warning("Grain overlay clip missing: {} — skipping", clip_path)
        else:
            stage += 1
            blend_mode, opacity = resolve_blend_and_opacity("grain", clip)
            ov_in = f"{stage}:v"
            ov_label = f"ov{stage}"
            out_label = f"s{stage}"
            cmd += ["-stream_loop", "-1", "-t", f"{total_duration:.4f}", "-i", str(clip_path)]
            filter_chains.append(
                f"[{ov_in}]scale={width}:{height},setsar=1,format=rgba,"
                f"colorchannelmixer=aa={opacity:.3f}[{ov_label}]"
            )
            filter_chains.append(
                f"[{current_label}][{ov_label}]blend=all_mode={blend_mode}[{out_label}]"
            )
            current_label = out_label
            logger.info(
                "Overlay: applying grain (whole-video, opacity={:.2f})", opacity
            )

    if stage == 0:
        tmp.rename(output_path)
        return

    filter_chains.append(f"[{current_label}]format=yuv420p[outv]")
    cmd += [
        "-filter_complex",
        "; ".join(filter_chains),
        "-map",
        "[outv]",
        "-map",
        "0:a?",
        "-c:a",
        "copy",
        "-r",
        str(fps),
        str(output_path),
    ]

    t0 = time.perf_counter()
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace")[-800:] if exc.stderr else ""
        logger.error(
            "Overlay compositing failed ({} stage(s)) — falling back to render without "
            "overlays: {}",
            stage,
            stderr,
        )
        tmp.rename(output_path)
        return

    elapsed = time.perf_counter() - t0
    logger.info(
        "Overlay compositing: {} stage(s) (mood + grain) in {:.2f}s",
        stage,
        elapsed,
    )
    tmp.unlink(missing_ok=True)


def _apply_bgm(
    tmp: Path,
    output_path: Path,
    settings: Settings,
    project_dir: Path,
) -> None:
    """Mix BGM into *tmp* and write *output_path*, or rename when BGM is off.

    Any exception from the BGM mixer is logged and treated as a non-fatal
    fallback: tmp is renamed to output_path without music rather than leaving
    no final.mp4 at all.
    """
    if settings.bgm_enabled:
        from ytfactory.bgm.library import BGMLibrary
        from ytfactory.bgm.mixer import BGMMixer

        config = _bgm_config_from_settings(settings)
        category = _resolve_bgm_category(settings, project_dir)
        track = BGMLibrary(config).find_track(category)
        if track:
            logger.info("BGM composition: {} ({})", track.title, category)
            try:
                result = BGMMixer(config).mix(
                    tmp, track, output_path, project_dir=project_dir
                )
            except Exception as exc:
                logger.error(
                    "BGM mixing raised an exception — falling back to no-music render: {}",
                    exc,
                )
                tmp.rename(output_path)
                return
            tmp.unlink(missing_ok=True)
            if not result.success:
                logger.error(
                    "BGM mixing failed — falling back to no-music render: {}",
                    result.error[:300],
                )
                # tmp already deleted; output_path may be absent or partial
                if not output_path.exists():
                    # FFmpeg wrote nothing — we lost the raw render; nothing to rename
                    raise RuntimeError(
                        f"BGM mixing failed and raw render is gone: {result.error[:300]}"
                    )
            return
        logger.warning(
            "BGM enabled but no tracks found for category '{}' — composing without music",
            category,
        )
    tmp.rename(output_path)


def compose_continuous_video(
    project_dir: Path,
    output_dir: Path,
    settings: Settings,
) -> None:
    """Single-pass compose final.mp4 from raw scene assets.

    Loads the scene plan, runs cinematic planners (motion / transitions /
    effects), resolves per-scene audio durations from timing.json or ffprobe,
    then delegates to ``FFmpegRenderer.render_continuous()`` for a single
    ``filter_complex`` encode pass.  Applies BGM as a second pass when enabled.

    Used by both ``VideoPipeline._compose_final_video_continuous()`` and the
    agent-graph ``video_concatenator_node`` so both build paths produce
    identical output from the same code.
    """
    scene_plan_path = project_dir / "scenes" / "scene-plan.json"
    if not scene_plan_path.exists():
        raise FileNotFoundError(f"Scene plan not found: {scene_plan_path}")

    scenes: list[dict] = json.loads(scene_plan_path.read_text(encoding="utf-8"))[
        "scenes"
    ]
    profile = settings.render_profile
    scenes = MotionPlanner().plan(scenes, profile=profile)
    scenes = TransitionPlanner().plan(scenes, profile=profile)
    scenes = EffectsPlanner().plan(scenes, profile=profile)

    # Validate all narration audio files before touching FFmpeg — a missing
    # audio would pass .exists() if the path resolved to "." (a directory).
    missing_audio: list[str] = []
    if not getattr(settings, "voice_enabled", True):
        from ytfactory.providers.tts.pacing.injector import _generate_silence

        for scene in scenes:
            index = scene["index"]
            audio = project_dir / "audio" / f"scene-{index:03d}.mp3"
            if not audio.is_file():
                _generate_silence(audio, float(scene.get("duration_seconds", 10)))
    else:
        for scene in scenes:
            index = scene["index"]
            audio = project_dir / "audio" / f"scene-{index:03d}.mp3"
            if not audio.is_file():
                missing_audio.append(
                    f"Scene {index}: narration audio missing — TTS failed earlier. "
                    f"Expected: {audio}"
                )
        if missing_audio:
            summary = "\n".join(f"  • {m}" for m in missing_audio)
            raise RuntimeError(
                f"compose_continuous_video: cannot build final.mp4 — "
                f"{len(missing_audio)} scene(s) have missing narration audio:\n"
                f"{summary}\n"
                "Fix the TTS failures and re-run the render stage."
            )

    durations: list[float] = []
    for scene in scenes:
        index = scene["index"]
        audio = project_dir / "audio" / f"scene-{index:03d}.mp3"
        timing = project_dir / "audio" / f"scene-{index:03d}.timing.json"
        durations.append(
            _actual_audio_duration(
                audio, timing, float(scene.get("duration_seconds", 10))
            )
        )

    renderer = FFmpegRenderer()
    output_path = output_dir / "final.mp4"
    tmp = output_path.with_suffix(".work.mp4")

    renderer.render_continuous(
        scenes=scenes,
        durations=durations,
        project_dir=project_dir,
        output_path=tmp,
        intro_enabled=settings.video_intro_enabled,
        intro_seconds=settings.video_intro_seconds,
    )

    # Persist the enriched motion / transitions / effects so the on-disk
    # scene-plan.json always reflects exactly what was rendered.
    SceneRepository().save_scenes(project_dir, scenes)

    overlay_tmp = output_path.with_suffix(".overlay.tmp.mp4")
    _apply_overlays(
        tmp, overlay_tmp, settings, scenes, durations,
        settings.video_intro_seconds if settings.video_intro_enabled else 0.0,
    )
    _apply_bgm(overlay_tmp, output_path, settings, project_dir)


class VideoPipeline:
    """Render all scenes into individual clips, then compose into final.mp4.

    Scene clips (scene-NNN.mp4) are still generated per-scene for the review
    and remediation systems.  The final video is produced by a single
    ``filter_complex`` FFmpeg pass that feeds all raw scene assets (PNG images,
    MP3 narration, ASS subtitles) through one continuous timeline — no GOP
    boundaries at scene cuts, no stream-copy splices.  This produces a file
    that YouTube's transcoder handles cleanly with no inter-scene pauses.

    When BGM is enabled it is applied as a second FFmpeg pass immediately
    after the single-pass render, producing a fully-mixed ``final.mp4``.
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
        project_id: str,
        overlay: bool = True,
    ) -> None:

        project_dir = Path("workspace") / "jobs" / project_id

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

        # Post-planning rebalance: break long identical-motion runs without
        # changing the underlying emotion assignments.
        scenes = MotionRebalancer().rebalance(scenes)

        # Persist enriched metadata back to scene-plan.json so downstream
        # quality_review sees the same motion/transition/effects that were rendered.
        SceneRepository().save_scenes(project_dir, scenes)

        output_dir = video_directory(project_id)

        _w = get_writer()
        if _w:
            _w.stage_start("scene_rendering", total=len(scenes))
        else:
            print(f"\nRendering {len(scenes)} video scenes [profile: {self._profile}]...\n")

        scene_clips: list[Path] = []
        durations: list[float] = []
        scene_errors: list[str] = []
        scene_num = 0

        scene_iter = scenes if _w else track(scenes, description="Rendering")
        for scene in scene_iter:
            scene_num += 1
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
            if scene.get("scene_type") in ("asset", "brand_card"):
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

            # Validate required assets before invoking FFmpeg.
            # Use .is_file() instead of .exists() to reject directories (including
            # Path("."), which .exists() incorrectly accepts as True).
            if not image.is_file():
                scene_errors.append(f"Scene {index}: missing image — {image}")
                continue

            if not audio.is_file():
                scene_errors.append(
                    f"Scene {index}: narration audio missing — TTS failed earlier. "
                    f"Expected: {audio}. Render skipped."
                )
                continue

            if not subtitle.is_file():
                scene_errors.append(
                    f"Scene {index}: no subtitle file found. "
                    f"Expected {ass_sub} or {srt_sub}."
                )
                continue

            # Measure actual audio duration — needed by both the per-scene
            # renderer (fade-out timing, zoompan frame count) and the single-pass
            # final composition (filter_complex -t duration per image input).
            duration_hint = _actual_audio_duration(audio, timing_path, plan_duration)
            durations.append(duration_hint)

            # Re-render if the output is absent OR the audio/subtitle source is newer.
            # This prevents stale per-scene clips from persisting when voice or captions
            # are regenerated (e.g. after fixing the H1-heading narration issue).
            output_mtime = output.stat().st_mtime if output.exists() else 0.0
            source_mtime = max(
                audio.stat().st_mtime if audio.is_file() else 0.0,
                subtitle.stat().st_mtime if subtitle.is_file() else 0.0,
            )
            needs_render = not output.exists() or source_mtime > output_mtime

            if needs_render:
                animated_clip = project_dir / "animated" / f"scene-{index:03d}.mp4"
                try:
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
                        scene_type=scene.get("scene_type"),
                        animated_video=animated_clip if animated_clip.is_file() else None,
                    )
                except Exception as exc:
                    scene_errors.append(f"Scene {index} render failed: {exc}")
                    continue

            scene_clips.append(output)
            if _w:
                _w.stage_progress(scene_num)

        if scene_errors:
            error_summary = "\n".join(f"  • {e}" for e in scene_errors)
            if _w:
                _w.stage_fail(f"{len(scene_errors)} scene(s) failed to render")
            raise RuntimeError(
                f"Video rendering incomplete — {len(scene_errors)} scene(s) failed:\n"
                f"{error_summary}\n"
                "Resolve the asset generation failures above, then re-run `ytfactory render`."
            )

        if _w:
            _w.stage_complete()
            _w.stage_start("video_merge")
        else:
            print("\n✓ All scenes rendered. Composing final video...\n")

        final_video = output_dir / "final.mp4"

        # Single-pass composition: render all scene assets through one continuous
        # filter_complex timeline, producing a single H.264 stream with no GOP
        # boundaries at scene cuts. Required for clean YouTube transcoding.
        self._compose_final_video_continuous(
            scenes, durations, project_dir, final_video, overlay=overlay
        )

        if _w:
            _w.stage_complete()
        else:
            print(f"✓ Final video: {final_video}\n")

    # ── Composition ───────────────────────────────────────────────────────────

    def _compose_final_video_continuous(
        self,
        scenes: list[dict],
        durations: list[float],
        project_dir: Path,
        output_path: Path,
        overlay: bool = True,
    ) -> None:
        """Single-pass render from raw assets → final.mp4, then apply BGM.

        Delegates to ``compose_continuous_video()`` using the pre-computed
        *scenes* (already enriched with motion / transitions / effects specs)
        and *durations* so the CLI path avoids re-reading from disk.
        """
        tmp = output_path.with_suffix(".work.mp4")

        overlay_tmp = output_path.with_suffix(".overlay.tmp.mp4")
        intro_seconds = (
            self._settings.video_intro_seconds if self._settings.video_intro_enabled else 0.0
        )

        # Resume guard: if a previous run was interrupted after render_continuous
        # but before overlay/BGM mixing completed, tmp exists but output_path does not.
        # Skip the expensive re-render and jump straight to overlays + BGM.
        if tmp.exists() and not output_path.exists():
            logger.info(
                "Resuming overlay/BGM mix from existing {} (render already complete)",
                tmp.name,
            )
            if overlay:
                _apply_overlays(
                    tmp, overlay_tmp, self._settings, scenes, durations, intro_seconds
                )
            _apply_bgm(
                overlay_tmp if overlay else tmp,
                output_path,
                self._settings,
                project_dir,
            )
            return

        self.renderer.render_continuous(
            scenes=scenes,
            durations=durations,
            project_dir=project_dir,
            output_path=tmp,
            intro_enabled=self._settings.video_intro_enabled,
            intro_seconds=self._settings.video_intro_seconds,
        )
        if overlay:
            _apply_overlays(
                tmp, overlay_tmp, self._settings, scenes, durations, intro_seconds
            )
        _apply_bgm(
            overlay_tmp if overlay else tmp,
            output_path,
            self._settings,
            project_dir,
        )
