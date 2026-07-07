"""BGMMixer — mixes background music into the final video using FFmpeg.

Two-path filter architecture (applied to the concatenated final.mp4):

  BGM signal is split into two parallel paths:

  Path A — floor (always-on):
    BGM → volume(duck_floor) → fade-in/out → [bgm_floor]
    Always present at the configured floor level regardless of narration.

  Path B — main (sidechain-ducked):
    BGM → volume(bgm_volume − duck_floor) → sidechaincompress(narration) →
    fade-in/out → [bgm_main]
    Carries the bulk of the BGM volume; ducks smoothly when narration is active.

  Combined:
    [bgm_floor] + [bgm_main] → amix → [bgm_ducked]

    During silence:     floor + main_volume  = bgm_volume  (e.g. 35%)
    During speech:      floor + main_ducked  ≈ duck_floor + small residual
                                              (e.g. 5–11% depending on ratio)

  Final mix:
    narration (full gain) + [bgm_ducked] → amix → alimiter → [audio_out]
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

        Two-path architecture — see module docstring for the full signal flow.
        """
        cfg = self._config
        # Volume carried by the sidechain-compressed main path.
        # The floor path always contributes cfg.duck_floor regardless of speech.
        main_vol = max(0.0, cfg.bgm_volume - cfg.duck_floor)

        return (
            # ── Prepare BGM: trim to video length, reset PTS, normalise format ─
            f"[1:a]"
            f"atrim=0:{duration:.4f},"
            f"asetpts=PTS-STARTPTS,"
            f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"asplit=2"
            f"[bgm_floor_raw][bgm_main_raw];"

            # ── Path A: floor — always-on at duck_floor volume ────────────────
            f"[bgm_floor_raw]"
            f"volume={cfg.duck_floor:.4f},"
            f"afade=t=in:ss=0:d={cfg.fade_in_seconds:.2f},"
            f"afade=t=out:st={fade_out_start:.4f}:d={cfg.fade_out_seconds:.2f}"
            f"[bgm_floor];"

            # ── Path B: main — scaled then sidechain-compressed ───────────────
            f"[bgm_main_raw]volume={main_vol:.4f}[bgm_main_scaled];"

            # ── Narration split (each pad consumed exactly once) ──────────────
            f"[0:a]"
            f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"asplit=2"
            f"[nar_sc][nar_mix];"

            # ── Sidechain compress: BGM ducks while narration is above threshold ─
            f"[bgm_main_scaled][nar_sc]"
            f"sidechaincompress="
            f"threshold={cfg.duck_threshold:.4f}:"
            f"ratio={cfg.duck_ratio:.1f}:"
            f"attack={cfg.duck_attack_ms}:"
            f"release={cfg.duck_release_ms}:"
            f"knee=2.0"
            f"[bgm_main_compressed];"

            # ── Fades on main path (applied after compression) ────────────────
            f"[bgm_main_compressed]"
            f"afade=t=in:ss=0:d={cfg.fade_in_seconds:.2f},"
            f"afade=t=out:st={fade_out_start:.4f}:d={cfg.fade_out_seconds:.2f}"
            f"[bgm_main_faded];"

            # ── Combine floor + main → full BGM with floor guarantee ──────────
            f"[bgm_floor][bgm_main_faded]"
            f"amix=inputs=2:normalize=0"
            f"[bgm_ducked];"

            # ── Final mix: narration at full gain + ducked BGM ────────────────
            f"[nar_mix][bgm_ducked]"
            f"amix=inputs=2:duration=first:normalize=0:weights=1 1"
            f"[premix];"

            # ── Hard limiter — catch any transient peaks ──────────────────────
            f"[premix]"
            f"alimiter=level_in=1:level_out=1:limit=0.95:attack=5:release=50"
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
