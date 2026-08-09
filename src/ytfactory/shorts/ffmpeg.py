"""ShortsFFmpegRenderer — FFmpegRenderer subclass for 9:16 vertical video.

Overrides the per-scene render() method to directly enforce:
  • scale=1080:1920 (from patched Settings.video_width/height)
  • setdar=9/16 (appended explicitly to the filter chain)

All spatial/motion, effects, fade, and subtitle helpers are inherited from
the parent unchanged.  The continuous assembly path (render_continuous) is
NOT overridden because Phase 1B uses its own _shorts_assemble_continuous()
which already emits setdar=9/16 in its own command.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger

from ytfactory.config.settings import Settings
from ytfactory.video.ffmpeg import FFmpegRenderer


class ShortsFFmpegRenderer(FFmpegRenderer):
    """FFmpegRenderer pre-configured for 9:16 vertical composition.

    Instantiate with a Settings object already patched to
    video_width=1080 / video_height=1920.  render() builds its vf chain
    using the inherited helpers and appends setdar=9/16 directly.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        # Replace the Settings() instance created by the parent __init__
        # (which would give 1280×720) with the caller-supplied patched object.
        self.settings = settings

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
        scene_type: str | None = None,
        animated_video: Path | None = None,
    ) -> None:
        """Render one scene as a 9:16 MP4.

        Builds the filter chain through the inherited helper methods and
        appends ``setdar=9/16`` explicitly so the display aspect ratio is
        always correct for vertical video.  No subprocess interception or
        string replacement is used.

        Fast path: when animated_video is supplied the parent's
        _render_animated path handles it (that path does not add setdar,
        which is fine — the final assembly step enforces it).
        """
        # Delegate pre-animated scenes to the parent unchanged.
        if animated_video is not None and animated_video.is_file():
            super().render(
                image=image,
                audio=audio,
                subtitle=subtitle,
                output=output,
                animation=animation,
                duration_hint=duration_hint,
                motion_spec=motion_spec,
                transition_in=transition_in,
                transition_out=transition_out,
                effect_spec=effect_spec,
                scene_type=scene_type,
                animated_video=animated_video,
            )
            return

        output.parent.mkdir(parents=True, exist_ok=True)

        width = self.settings.video_width    # 1080 (patched)
        height = self.settings.video_height  # 1920 (patched)
        fps = self.settings.video_fps

        # 1. Spatial / motion — inherited helpers use patched width/height.
        if motion_spec is not None:
            spatial = self._vf_spatial(width, height, fps, motion_spec, duration_hint)
        else:
            spatial = self._vf_spatial_legacy(width, height, fps, animation, duration_hint)

        # 2. Visual effects (blur, colour grade, vignette, grain).
        effect_parts = self._effects_filters(effect_spec)

        # 3. Fade transitions.
        fade_parts = self._fade_filters(transition_in, transition_out, fps, duration_hint)

        # 4. Subtitle burn-in.
        if scene_type == "brand_card":
            sub_parts: list[str] = []
        elif not self.settings.subtitle_burn_enabled:
            logger.info(
                "Shorts scene | subtitle burn skipped (SUBTITLE_BURN_ENABLED=false): {}",
                output,
            )
            sub_parts = []
        else:
            sub_parts = [f"subtitles='{subtitle}'"]

        # 5. Explicitly enforce 9:16 display aspect ratio.
        vf = ",".join([spatial] + effect_parts + fade_parts + sub_parts + ["setdar=9/16"])

        enc_args: list[str] = [
            "-c:v", "libx264",
            "-preset", self.settings.video_preset,
            "-crf", str(self.settings.video_crf),
            "-pix_fmt", "yuv420p",
            "-profile:v", "high",
            "-g", str(self.settings.video_keyframe_interval),
            "-movflags", "+faststart+negative_cts_offsets",
        ]
        if self.settings.video_tune:
            enc_args += ["-tune", self.settings.video_tune]

        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-loop", "1",
                "-framerate", str(fps),
                "-t", f"{duration_hint:.4f}",
                "-i", str(image),
                "-i", str(audio),
                "-vf", vf,
                "-r", str(fps),
                "-s", f"{width}x{height}",
                *enc_args,
                "-c:a", "aac",
                "-b:a", self.settings.video_audio_bitrate,
                "-ar", "48000",
                "-shortest",
                str(output),
            ],
            check=True,
        )
