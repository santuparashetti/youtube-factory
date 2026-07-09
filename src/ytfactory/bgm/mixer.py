"""BGMMixer — mixes background music into the final video using FFmpeg.

V2 two-path filter architecture:

  BGM signal is split into two parallel paths:

  Path A — floor (always-on):
    BGM → volume(duck_floor) → fade-in/out → [bgm_floor]

  Path B — main (sidechain-ducked):
    BGM → volume(bgm_volume − duck_floor) → sidechaincompress(narration_gated) →
    fade-in/out → [bgm_main]

  V2 sidechain enhancement (when vad_enabled=True):
    Narration is passed through agate(hold=phrase_gap_ms) before feeding
    the sidechaincompress.  The hold parameter keeps the gate open across
    brief inter-word gaps so music stays ducked across a whole phrase,
    eliminating inter-word pumping.

  Combined:
    [bgm_floor] + [bgm_main] → amix → [bgm_ducked]

    During silence:     floor + main_volume  = bgm_volume
    During speech:      floor + main_ducked  ≈ duck_floor (10–20%)

  Final mix:
    narration (full gain) + [bgm_ducked] → amix → alimiter → [audio_out]

  Long-silence recovery:
    sidechaincompress release=350 ms means after 2 s of silence the BGM has
    recovered to ≥99% of target — the logarithmic envelope sidechaincompress
    provides naturally satisfies the spec's smooth logarithmic recovery rule.
"""

from __future__ import annotations

import json
import subprocess
from functools import lru_cache
from pathlib import Path

from loguru import logger

from .config import BGMConfig
from .models import BGMMixResult, BGMTrack


@lru_cache(maxsize=1)
def _ffmpeg_agate_has_hold() -> bool:
    """Return True if the installed FFmpeg agate filter supports the 'hold' option.

    The hold option was added in FFmpeg 5.x.  Ubuntu 22.04 ships 4.4.2 which
    does not have it, so the V2 agate path must omit hold on older installs.

    Detection: grep for '^  hold ' in the filter help output (the options table
    uses two leading spaces + option name + spaces; 'threshold' contains 'hold'
    as a substring so a plain 'in' check is a false positive).
    """
    import re

    try:
        r = subprocess.run(
            ["ffmpeg", "-h", "filter=agate"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Options table format: "  hold            <type>  ..."
        return bool(re.search(r"^\s+hold\s", r.stdout, re.MULTILINE))
    except Exception:
        return False


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
        project_dir: Path | None = None,
    ) -> BGMMixResult:
        """Mix *track* into *video_path* and write the result to *output_path*.

        The narration in the original video is always preserved at its
        original level.  The BGM is ducked via sidechain compression
        whenever narration is detected above the configured threshold.

        When *project_dir* is supplied and *config.vad_enabled* is True,
        a speech timeline is computed from the narration and five debug files
        are written to ``<project_dir>/bgm-debug/``.
        """
        cfg = self._config
        video_duration = self._probe_duration(video_path)
        fade_out_start = max(0.0, video_duration - cfg.fade_out_seconds)

        filter_complex = self._build_filter(video_duration, fade_out_start)

        # VAD pre-analysis + debug output (non-fatal if ffmpeg probe fails)
        if cfg.vad_enabled and project_dir is not None:
            try:
                from .debug import BGMDebugWriter
                from .vad import build_speech_timeline_from_kokoro, detect_speech

                # V3: try Kokoro timestamps first; fall back to FFmpeg silencedetect
                if cfg.adaptive_mixing:
                    timeline = build_speech_timeline_from_kokoro(
                        project_dir,
                        phrase_gap_ms=cfg.phrase_gap_ms,
                        long_silence_threshold_ms=cfg.long_silence_threshold_ms,
                    )
                    if timeline is None:
                        timeline = detect_speech(
                            video_path,
                            phrase_gap_ms=cfg.phrase_gap_ms,
                        )
                else:
                    timeline = detect_speech(
                        video_path,
                        phrase_gap_ms=cfg.phrase_gap_ms,
                    )

                # Determine actual attack/release used in the filter
                if cfg.adaptive_mixing:
                    actual_attack = 180
                    actual_release = 1800
                else:
                    actual_attack = cfg.duck_attack_ms
                    actual_release = cfg.duck_release_ms

                mix_profile = {
                    "bgm_volume": cfg.bgm_volume,
                    "duck_floor": cfg.duck_floor,
                    "duck_threshold": cfg.duck_threshold,
                    "duck_ratio": cfg.duck_ratio,
                    "duck_attack_ms": actual_attack,
                    "duck_release_ms": actual_release,
                    "phrase_gap_ms": cfg.phrase_gap_ms,
                    "hold_after_speech_ms": cfg.hold_after_speech_ms,
                    "long_silence_ms": cfg.long_silence_ms,
                    "long_silence_threshold_ms": cfg.long_silence_threshold_ms,
                    "dynamic_ducking": cfg.dynamic_ducking,
                    "restore_curve": cfg.restore_curve,
                    "vad_provider": cfg.vad_provider,
                    "adaptive_mixing": cfg.adaptive_mixing,
                    "narration_level_lufs": cfg.narration_level_lufs,
                    "music_level_lufs": cfg.music_level_lufs,
                    "transition_curve": cfg.transition_curve,
                }
                BGMDebugWriter(project_dir).write(
                    timeline,
                    mix_profile,
                    filter_complex,
                    long_silence_threshold_ms=cfg.long_silence_threshold_ms,
                )
            except Exception as exc:
                logger.warning("BGM debug write failed (non-fatal): {}", exc)

        cmd: list[str] = [
            "ffmpeg",
            "-y",
            # Video (with narration)
            "-i",
            str(video_path),
            # BGM — looped indefinitely at the input level so atrim can cut it
            "-stream_loop",
            "-1",
            "-i",
            str(track.path),
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v",
            "-map",
            "[audio_out]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            cfg.audio_bitrate,
            str(output_path),
        ]

        logger.info(
            "BGM mix: {} → {} (track: {})",
            video_path.name,
            output_path.name,
            track.title,
        )

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
            err = (
                exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
            )
            # Log the tail — FFmpeg always writes the version header first,
            # so the first ~500 chars are never the actual error.
            logger.error("BGM mix failed: {}", err[-800:])
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

        V2/V3 two-path architecture — see module docstring for signal flow.

        V3 adaptive mixing (adaptive_mixing=True):
          - agate hold = hold_after_speech_ms (default 2200 ms) — bridges all
            breaths, commas, dramatic pauses and sentence pauses so music stays
            ducked across any narration gap shorter than 2.2 s.
          - sidechaincompress attack = 180 ms (slow onset — cinematic)
          - sidechaincompress release = 1800 ms (slow recovery — no pumping)
          Only genuine long silence (>2.2 s) allows music to recover.

        V2 legacy mode (adaptive_mixing=False):
          - Uses phrase_gap_ms for agate hold (300 ms)
          - Uses duck_attack_ms / duck_release_ms directly (15 ms / 350 ms)
        """
        cfg = self._config

        # ── Select V3 or V2 timing params ────────────────────────────────────
        if cfg.adaptive_mixing:
            agate_hold_s = cfg.hold_after_speech_ms / 1000.0
            sc_attack_ms = 180  # cinematic onset — 150–250 ms spec range
            sc_release_ms = 1800  # slow recovery — 1500–2000 ms spec range
        else:
            agate_hold_s = cfg.phrase_gap_ms / 1000.0
            sc_attack_ms = cfg.duck_attack_ms
            sc_release_ms = cfg.duck_release_ms

        main_vol = max(0.0, cfg.bgm_volume - cfg.duck_floor)

        # ── Narration sidechain — V1 (no agate) or V2/V3 (agate phrase gate) ─
        if cfg.vad_enabled:
            agate_has_hold = _ffmpeg_agate_has_hold()
            if not agate_has_hold:
                logger.debug(
                    "BGM: agate 'hold' not supported by this FFmpeg — "
                    "using agate without hold (slight inter-word pumping possible)"
                )
            agate_params = (
                f"threshold={cfg.duck_threshold:.4f}:"
                + (f"hold={agate_hold_s:.3f}:" if agate_has_hold else "")
                + "attack=0.015:"
                "release=0.350:"
                "range=0.01"
            )
            nar_split = (
                f"[0:a]"
                f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                f"asplit=2"
                f"[nar_raw][nar_mix];"
                f"[nar_raw]agate={agate_params}[nar_sc];"
            )
        else:
            nar_split = (
                "[0:a]"
                "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                "asplit=2"
                "[nar_sc][nar_mix];"
            )

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
            f"[bgm_main_raw]volume={main_vol:.4f}[bgm_main_scaled];" + nar_split +
            # ── Narration split + phrase-grouping gate ────────────────────────
            # ── Sidechain compress: BGM ducks while narration gate is open ────
            # V3: attack=180 ms (cinematic), release=1800 ms (no pumping)
            # V2: attack/release from BGMConfig (15 ms / 350 ms legacy)
            f"[bgm_main_scaled][nar_sc]"
            f"sidechaincompress="
            f"threshold={cfg.duck_threshold:.4f}:"
            f"ratio={cfg.duck_ratio:.1f}:"
            f"attack={sc_attack_ms}:"
            f"release={sc_release_ms}:"
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
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return float(json.loads(result.stdout)["format"]["duration"])
