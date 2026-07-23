from __future__ import annotations

import subprocess
from pathlib import Path

from video_core.cinematic.ffmpeg_filters import _t_factor, build_zoompan_filter
from ytfactory.config.settings import Settings

# Legacy animation values (still supported when motion_spec is not provided).
# New callers should pass a MotionSpec dict via the motion_spec parameter.
_ANIMATIONS = frozenset({"slow_zoom", "slow_zoom_out", "drift", "static"})


class FFmpegRenderer:
    """Render a single YouTube-ready video scene."""

    def __init__(self) -> None:
        self.settings = Settings()

    # ── Spatial / motion (no subtitle) ───────────────────────────────────────

    def _vf_spatial(
        self,
        width: int,
        height: int,
        fps: int,
        motion: dict,
        duration_hint: float,
    ) -> str:
        """Build the spatial/motion filter chain from a MotionSpec dict.

        Delegates to video_core.cinematic.ffmpeg_filters.build_zoompan_filter —
        same logic, same output, now also callable from shorts_factory.
        """
        return build_zoompan_filter(width, height, fps, motion, duration_hint)

    def _vf_spatial_legacy(
        self,
        width: int,
        height: int,
        fps: int,
        animation: str | None,
        duration_hint: float,
    ) -> str:
        """
        Legacy spatial filter built from an animation string.
        Does NOT include the subtitle filter.
        """
        if not animation or animation == "static":
            return (
                f"scale={width}:{height}:"
                "force_original_aspect_ratio=increase,"
                f"crop={width}:{height}"
            )

        total_frames = max(1, int(duration_hint * fps))

        if animation == "slow_zoom":
            zoom_expr = f"'min(zoom+{0.15 / total_frames:.6f},1.15)'"
            x_expr = "'iw/2-(iw/zoom/2)'"
            y_expr = "'ih/2-(ih/zoom/2)'"
        elif animation == "slow_zoom_out":
            zoom_expr = f"'max(zoom-{0.15 / total_frames:.6f},1.0)'"
            x_expr = "'iw/2-(iw/zoom/2)'"
            y_expr = "'ih/2-(ih/zoom/2)'"
        else:  # drift
            zoom_expr = "'1.05'"
            x_expr = f"'(iw/zoom/2) + (on/{total_frames}) * (iw*(1-1/zoom))'"
            y_expr = "'ih/2-(ih/zoom/2)'"

        return (
            f"zoompan=z={zoom_expr}:x={x_expr}:y={y_expr}"
            f":d=1:s={width}x{height}:fps={fps}"
        )

    # ── Visual effects ────────────────────────────────────────────────────────

    def _effects_filters(self, effect_spec: dict | None) -> list[str]:
        """
        Build visual effect filter strings from an EffectSpec dict.

        Returns a list inserted BETWEEN the spatial filter and the subtitle
        burn-in so subtitle text renders clean on top of the processed image.

        Filter order within the list:
            blur → colour grade → vignette → film grain
        """
        if not effect_spec:
            return []

        filters: list[str] = []

        blur_sigma = float(effect_spec.get("blur_sigma", 0.0))
        if blur_sigma > 0.0:
            # Mild Gaussian blur — used for blur_dissolve transition scenes
            filters.append(f"gblur=sigma={blur_sigma:.1f}")

        color_grade = effect_spec.get("color_grade", "")
        if color_grade:
            filters.append(color_grade)

        if effect_spec.get("vignette"):
            # PI/5 ≈ 36° — subtle darkening around the frame edges
            filters.append("vignette=angle=PI/5")

        if effect_spec.get("film_grain"):
            # Luma-channel noise, temporal variation so it flickers per frame
            filters.append("noise=c0s=10:c0f=t+u")

        return filters

    # ── Transitions (fades) ───────────────────────────────────────────────────

    def _fade_filters(
        self,
        transition_in: dict | None,
        transition_out: dict | None,
        fps: int,
        duration_hint: float,
    ) -> list[str]:
        """
        Build FFmpeg fade filter strings from TransitionSpec dicts.

        hard_cut / match_cut (duration_frames == 0) produce no filter.
        Fade-out start time is estimated from duration_hint — a slight
        mismatch (< 0.5 s) is visually harmless for a 0.5 s fade.
        """
        filters: list[str] = []

        if transition_in:
            frames = int(transition_in.get("duration_frames", 0))
            if frames > 0:
                color = transition_in.get("color", "black")
                d = frames / fps
                filters.append(f"fade=t=in:st=0:d={d:.4f}:color={color}")

        if transition_out:
            frames = int(transition_out.get("duration_frames", 0))
            if frames > 0:
                color = transition_out.get("color", "black")
                d = frames / fps
                st = max(0.0, duration_hint - d)
                filters.append(f"fade=t=out:st={st:.4f}:d={d:.4f}:color={color}")

        return filters

    # ── Compatibility shims (subtitle included) ───────────────────────────────

    def _vf_from_motion(
        self,
        width: int,
        height: int,
        fps: int,
        subtitle: Path,
        motion: dict,
        duration_hint: float,
    ) -> str:
        """Compatibility shim — includes subtitle burn-in. Use _vf_spatial() in new code."""
        spatial = self._vf_spatial(width, height, fps, motion, duration_hint)
        return f"{spatial},subtitles='{subtitle}'"

    def _build_vf(
        self,
        width: int,
        height: int,
        fps: int,
        subtitle: Path,
        animation: str | None,
        duration_hint: float = 10.0,
    ) -> str:
        """Compatibility shim — includes subtitle burn-in. Use _vf_spatial_legacy() in new code."""
        spatial = self._vf_spatial_legacy(width, height, fps, animation, duration_hint)
        return f"{spatial},subtitles='{subtitle}'"

    # ── Public API ────────────────────────────────────────────────────────────

    def render_continuous(
        self,
        scenes: list[dict],
        durations: list[float],
        project_dir: Path,
        output_path: Path,
        intro_enabled: bool = False,
        intro_seconds: float = 1.5,
    ) -> None:
        """Render all scenes into one continuous MP4 using a single filter_complex pass.

        Produces a single H.264 stream with no GOP boundaries at scene cuts —
        YouTube's transcoder handles this cleanly with no inter-scene pauses.

        Each scene's raw assets (PNG image, MP3 narration, ASS/SRT subtitle) are
        fed directly as inputs; the existing _vf_spatial / _effects_filters /
        _fade_filters helpers build the per-scene filter chains, then the FFmpeg
        concat filter joins them before the single libx264 encode.

        Per-scene MP4 clips are still generated separately (by render()) for the
        review and remediation systems — this function only replaces the final
        composition step.
        """
        W = self.settings.video_width
        H = self.settings.video_height
        fps = self.settings.video_fps

        cmd: list[str] = ["ffmpeg", "-y", "-loglevel", "error"]
        filter_chains: list[str] = []
        concat_in_pads: list[str] = []
        inp = 0  # running input index

        # ── Optional intro (silent black clip) ───────────────────────────────
        if intro_enabled and intro_seconds > 0:
            d = intro_seconds
            cmd += [
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s={W}x{H}:r={fps}:d={d:.4f}",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
            ]
            filter_chains.append(
                f"[{inp}:v]trim=duration={d:.4f},setpts=PTS-STARTPTS[_iv]"
            )
            filter_chains.append(
                f"[{inp + 1}:a]atrim=duration={d:.4f},asetpts=PTS-STARTPTS,"
                f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[_ia]"
            )
            concat_in_pads += ["[_iv]", "[_ia]"]
            inp += 2

        # ── Per-scene inputs + filter chains ─────────────────────────────────
        for i, scene in enumerate(scenes):
            dur = durations[i]
            index = scene["index"]

            if scene.get("scene_type") == "asset":
                asset_path = Path(scene.get("asset_path", ""))
                if not asset_path.is_absolute():
                    asset_path = Path.cwd() / asset_path
                image = asset_path
            else:
                image = project_dir / "images" / f"scene-{index:03d}.png"

            audio = project_dir / "audio" / f"scene-{index:03d}.mp3"
            ass_sub = project_dir / "subtitles" / f"scene-{index:03d}.ass"
            srt_sub = project_dir / "subtitles" / f"scene-{index:03d}.srt"
            subtitle: Path | None = (
                ass_sub if ass_sub.exists() else srt_sub if srt_sub.exists() else None
            )

            vid_inp = inp
            aud_inp = inp + 1
            inp += 2

            # Image input: looped still, limited to narration duration
            cmd += [
                "-loop",
                "1",
                "-framerate",
                str(fps),
                "-t",
                f"{dur:.4f}",
                "-i",
                str(image),
            ]
            # Audio input
            cmd += ["-i", str(audio)]

            # Video filter chain — reuse existing private helpers
            motion_spec = scene.get("motion")
            effect_spec = scene.get("effects")
            t_in = scene.get("transition_in")
            t_out = scene.get("transition_out")

            if motion_spec is not None:
                spatial = self._vf_spatial(W, H, fps, motion_spec, dur)
            else:
                spatial = self._vf_spatial_legacy(
                    W, H, fps, scene.get("animation"), dur
                )

            vf_parts: list[str] = [spatial]
            vf_parts += self._effects_filters(effect_spec)
            vf_parts += self._fade_filters(t_in, t_out, fps, dur)

            # Cap to exact scene duration before subtitle rendering.
            # zoompan with d=1 produces exactly total_frames output frames,
            # matching the input duration, so the trim is a safety net for
            # any clock skew between the looped image and the audio track.
            vf_parts.append(f"trim=duration={dur:.4f},setpts=PTS-STARTPTS")

            if subtitle is not None:
                # Escape backslash and single-quote so the path survives the
                # filter_complex parser on Linux (colons are safe in Linux paths).
                sub_escaped = str(subtitle).replace("\\", "\\\\").replace("'", "\\'")
                vf_parts.append(f"subtitles='{sub_escaped}'")

            # format=yuv420p ensures all segments entering concat share a pixel format
            vf_parts.append("format=yuv420p")

            vf_chain = ",".join(vf_parts)
            filter_chains.append(f"[{vid_inp}:v]{vf_chain}[_v{i}]")
            filter_chains.append(
                f"[{aud_inp}:a]"
                f"atrim=duration={dur:.4f},asetpts=PTS-STARTPTS,"
                f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
                f"[_a{i}]"
            )
            concat_in_pads += [f"[_v{i}]", f"[_a{i}]"]

        # ── Concat filter ─────────────────────────────────────────────────────
        n_segments = len(scenes) + (1 if intro_enabled and intro_seconds > 0 else 0)
        pads_str = "".join(concat_in_pads)
        filter_chains.append(f"{pads_str}concat=n={n_segments}:v=1:a=1[_vout][_aout]")

        filter_complex = ";".join(filter_chains)

        # ── Encoding ──────────────────────────────────────────────────────────
        enc: list[str] = [
            "-c:v",
            "libx264",
            "-preset",
            self.settings.video_preset,
            "-crf",
            str(self.settings.video_crf),
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            "-g",
            str(self.settings.video_keyframe_interval),
            "-movflags",
            "+faststart+negative_cts_offsets",
            "-c:a",
            "aac",
            "-b:a",
            self.settings.video_audio_bitrate,
            "-ar",
            "48000",
        ]
        if self.settings.video_tune:
            enc += ["-tune", self.settings.video_tune]

        cmd += [
            "-filter_complex",
            filter_complex,
            "-map",
            "[_vout]",
            "-map",
            "[_aout]",
            "-r",
            str(fps),
            "-s",
            f"{W}x{H}",
            *enc,
            str(output_path),
        ]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(cmd, check=True)

    def render(
        self,
        image: Path,
        audio: Path,
        subtitle: Path,
        output: Path,
        animation: str | None = None,
        duration_hint: float = 10.0,
        motion_spec: dict | None = None,
        transition_in: dict | None = None,
        transition_out: dict | None = None,
        effect_spec: dict | None = None,
    ) -> None:
        """
        Render image + audio + subtitles → MP4.

        Filter chain order (all stages are optional):
            spatial / motion
            → effects (blur, colour grade, vignette, grain)
            → fade-in transition
            → fade-out transition
            → subtitle burn-in

        Subtitle burn-in runs AFTER fades so the text is always rendered at
        full brightness.  During fade-to-black the background darkens while
        the subtitle text stays white — readable through the entire transition.
        This also means an extended last-cue tail stays fully visible even
        when the image has already faded to black.

        Phase 3 params (take precedence when provided):
            motion_spec:    MotionSpec dict from MotionPlanner.
            transition_in:  TransitionSpec dict — fade=t=in.
            transition_out: TransitionSpec dict — fade=t=out.
            effect_spec:    EffectSpec dict from EffectsPlanner.

        Legacy param (used when motion_spec is None):
            animation: "slow_zoom" | "slow_zoom_out" | "drift" | "static" | None.

        Args:
            image:         Source image (AI-generated or local asset).
            audio:         Narration MP3.
            subtitle:      SRT file for subtitle burn-in.
            output:        Output MP4 path.
            duration_hint: Approximate scene duration in seconds.
        """
        output.parent.mkdir(parents=True, exist_ok=True)

        width = self.settings.video_width
        height = self.settings.video_height
        fps = self.settings.video_fps

        # 1. Spatial / motion
        if motion_spec is not None:
            spatial = self._vf_spatial(width, height, fps, motion_spec, duration_hint)
        else:
            spatial = self._vf_spatial_legacy(
                width, height, fps, animation, duration_hint
            )

        # 2. Visual effects — inserted before subtitle so text stays clean
        effect_parts = self._effects_filters(effect_spec)

        # 3. Subtitle burn-in
        sub_part = f"subtitles='{subtitle}'"

        # 4. Fade transitions — after subtitle for cohesive fade
        fade_parts = self._fade_filters(
            transition_in, transition_out, fps, duration_hint
        )

        vf = ",".join([spatial] + effect_parts + fade_parts + [sub_part])

        # Build the encoder argument list from settings so CRF, preset, tune,
        # keyframe interval, and audio bitrate are all configurable.
        enc_args: list[str] = [
            "-c:v",
            "libx264",
            "-preset",
            self.settings.video_preset,
            "-crf",
            str(self.settings.video_crf),
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            "-g",
            str(self.settings.video_keyframe_interval),
            "-movflags",
            "+faststart+negative_cts_offsets",
        ]
        if self.settings.video_tune:
            enc_args += ["-tune", self.settings.video_tune]

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                # ---------- Input ----------
                "-loop",
                "1",
                "-framerate",
                str(fps),
                "-t",
                f"{duration_hint:.4f}",
                "-i",
                str(image),
                "-i",
                str(audio),
                # ---------- Video ----------
                "-vf",
                vf,
                "-r",
                str(fps),
                "-s",
                f"{width}x{height}",
                *enc_args,
                # ---------- Audio ----------
                "-c:a",
                "aac",
                "-b:a",
                self.settings.video_audio_bitrate,
                "-ar",
                "48000",
                # ---------- Finish ----------
                "-shortest",
                str(output),
            ],
            check=True,
        )
