"""BGMMixer — mixes background music into the final video using FFmpeg.

Filter chain (applied to the concatenated final.mp4):

  1.  Stream-loop the BGM track to cover the full video duration.
  2.  Trim to exactly the video duration and reset PTS.
  3.  Set BGM volume to the configured baseline (default 12 %).
  4.  Apply fade-in at the start and fade-out at the end.
  5.  Sidechain-compress the BGM using the narration track as the trigger
      signal — BGM ducks smoothly while speech is detected.
  6.  Mix the original narration and the ducked BGM with amix (no
      normalisation so narration retains its full gain).
  7.  Apply a hard limiter to the mixed output to prevent clipping.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from loguru import logger

from .config import BGMConfig
from .models import BGMMixResult, BGMTrack


class BGMMixer:
    """FFmpeg-based background music mixer with sidechain ducking."""

    def __init__(self, config: BGMConfig) -> None:
        self._config = config

    # ── Public API ────────────────────────────────────────────────────────

    def mix(
        self,
        video_path: Path,
        track: BGMTrack,
        output_path: Path,
    ) -> BGMMixResult:
        """Mix *track* into *video_path* and write the result to *output_path*.

        The narration in the original video is always preserved at its
        original level.  The BGM is ducked via sidechain compression
        whenever narration is detected above the configured threshold.
        """
        cfg = self._config
        video_duration = self._probe_duration(video_path)
        fade_out_start = max(0.0, video_duration - cfg.fade_out_seconds)

        filter_complex = self._build_filter(video_duration, fade_out_start)

        cmd: list[str] = [
            "ffmpeg", "-y",
            # Video (with narration)
            "-i", str(video_path),
            # BGM — looped indefinitely at the input level so atrim can cut it
            "-stream_loop", "-1",
            "-i", str(track.path),
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[audio_out]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", cfg.audio_bitrate,
            str(output_path),
        ]

        logger.info("BGM mix: {} → {} (track: {})", video_path.name, output_path.name, track.title)

        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
            logger.info("BGM mix complete: {}", output_path.name)
            return BGMMixResult(
                track=track,
                video_duration=video_duration,
                output_path=output_path,
                success=True,
                category=track.category,
                mix_command=cmd,
            )
        except subprocess.CalledProcessError as exc:
            err = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
            logger.error("BGM mix failed: {}", err[:500])
            return BGMMixResult(
                track=track,
                video_duration=video_duration,
                output_path=output_path,
                success=False,
                category=track.category,
                error=err,
                mix_command=cmd,
            )

    # ── Internal helpers ──────────────────────────────────────────────────

    def _build_filter(self, duration: float, fade_out_start: float) -> str:
        """Return the FFmpeg filter_complex string for BGM mixing with ducking.

        Graph:
          [1:a] BGM stream
              → atrim (cut to video duration)
              → asetpts (reset timestamps after trim)
              → volume (set baseline gain)
              → afade=in (smooth start)
              → afade=out (smooth end)
              → aformat (normalise sample format/rate for compressor)
              → [bgm_ready]

          [0:a] narration
              → aformat
              → asplit=2  ← split into [nar_sc] and [nar_mix]
                           (a named pad can only be consumed once;
                            sidechaincompress AND amix both need narration)

          [bgm_ready][nar_sc] sidechaincompress (duck BGM under speech)
              → [bgm_ducked]

          [nar_mix][bgm_ducked] amix (combine, no normalise)
              → [premix]

          [premix] alimiter (prevent clipping)
              → [audio_out]
        """
        cfg = self._config
        return (
            # ── BGM preparation ──────────────────────────────────────────
            f"[1:a]"
            f"atrim=0:{duration:.4f},"
            f"asetpts=PTS-STARTPTS,"
            f"volume={cfg.bgm_volume:.4f},"
            f"afade=t=in:ss=0:d={cfg.fade_in_seconds:.2f},"
            f"afade=t=out:st={fade_out_start:.4f}:d={cfg.fade_out_seconds:.2f},"
            f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
            f"[bgm_ready];"
            # ── Narration split — each named pad may only be consumed once ─
            f"[0:a]"
            f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"asplit=2"
            f"[nar_sc][nar_mix];"
            # ── Sidechain ducking ─────────────────────────────────────────
            # BGM is the main signal; [nar_sc] is the sidechain trigger.
            f"[bgm_ready][nar_sc]sidechaincompress="
            f"threshold={cfg.duck_threshold:.4f}:"
            f"ratio={cfg.duck_ratio:.1f}:"
            f"attack={cfg.duck_attack_ms}:"
            f"release={cfg.duck_release_ms}:"
            f"knee=2.0"
            f"[bgm_ducked];"
            # ── Mix: narration at full gain + ducked BGM ──────────────────
            f"[nar_mix][bgm_ducked]"
            f"amix=inputs=2:duration=first:normalize=0:weights=1 1"
            f"[premix];"
            # ── Hard limiter — prevent output clipping ────────────────────
            f"[premix]alimiter=level_in=1:level_out=1:limit=0.95:attack=5:release=50"
            f"[audio_out]"
        )

    @staticmethod
    def _probe_duration(path: Path) -> float:
        """Return media duration in seconds via ffprobe."""
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return float(json.loads(result.stdout)["format"]["duration"])
