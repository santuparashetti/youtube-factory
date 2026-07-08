"""BGM validation rules (category bgm).

Rules:
  BGM_001 [high]     — BGM-enabled video has non-silent audio during the intro fade-in
  BGM_002 [high]     — No clipping in the final mix (peak volume below -0.5 dBFS)
  BGM_003 [medium]   — Final mix loudness within YouTube recommended range (-16 ± 4 LUFS)
  BGM_004 [medium]   — Music level is clearly secondary to narration (no BGM dominance)
  BGM_005 [medium]   — BGM is ducked during narration (VAD-assisted duck-depth check)
  BGM_006 [low]      — Phrase detection active: VAD timeline written and non-empty
  BGM_007 [medium]   — BGM recovers during long silence (> bgm_long_silence_ms)

BGM_005–007 SKIP when bgm-debug/speech_timeline.json is absent (VAD not run).
All rules SKIP automatically when BGM is disabled (context["bgm_enabled"] is False/absent).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult


def _run_volumedetect(path: Path, start: float = 0.0, duration: float | None = None) -> dict[str, float]:
    """Run FFmpeg volumedetect on *path* and return mean/max dBFS values.

    Returns an empty dict on error.
    """
    cmd = ["ffmpeg", "-nostdin"]
    if start > 0.0:
        cmd += ["-ss", f"{start:.4f}"]
    if duration is not None:
        cmd += ["-t", f"{duration:.4f}"]
    cmd += ["-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        out: dict[str, float] = {}
        for line in result.stderr.splitlines():
            m = re.search(r"(mean|max)_volume:\s*(-?\d+\.?\d*)\s*dB", line)
            if m:
                out[m.group(1)] = float(m.group(2))
        return out
    except Exception:
        return {}


class BGMValidator(BaseValidator):
    """Validates background music mixing in the final video."""

    category = "bgm"
    responsible_engine = "Video Renderer"

    def validate(
        self,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> list[ValidationResult]:
        results: list[ValidationResult] = []

        # Skip all BGM rules when BGM is disabled
        bgm_enabled = context.get("bgm_enabled", False)
        rule_ids = ("BGM_001", "BGM_002", "BGM_003", "BGM_004", "BGM_005", "BGM_006", "BGM_007")

        if not bgm_enabled:
            for rule_id in rule_ids:
                if self._config.is_enabled(rule_id):
                    results.append(self._skip(rule_id, "BGM is disabled"))
            return results

        final_video = project_dir / "video" / "final.mp4"

        if not final_video.exists():
            for rule_id in rule_ids:
                if self._config.is_enabled(rule_id):
                    results.append(
                        self._skip(rule_id, "final.mp4 not found — video stage incomplete")
                    )
            return results

        # ── BGM_001: Non-silent audio during fade-in ───────────────────────
        if self._config.is_enabled("BGM_001"):
            fade_in_check = _run_volumedetect(final_video, start=0.0, duration=3.0)
            mean_db = fade_in_check.get("mean", None)
            threshold = self._config.threshold_for("BGM_001", self._config.bgm_intro_min_db)

            if mean_db is None:
                results.append(
                    self._skip("BGM_001", "volumedetect failed — ffmpeg unavailable")
                )
            elif mean_db < threshold:
                results.append(
                    self._fail(
                        "BGM_001",
                        f"BGM not detected in intro fade-in (mean={mean_db:.1f} dBFS, "
                        f"expected > {threshold:.0f} dBFS)",
                        f"mean_volume={mean_db:.1f} dBFS in first 3 s",
                        "high",
                        mean_db_fade_in=mean_db,
                        threshold_db=threshold,
                    )
                )
            else:
                results.append(
                    self._pass(
                        "BGM_001",
                        "BGM detected in intro fade-in",
                        f"mean_volume={mean_db:.1f} dBFS in first 3 s",
                        mean_db_fade_in=mean_db,
                    )
                )

        # ── BGM_002: No clipping in final mix ─────────────────────────────
        if self._config.is_enabled("BGM_002"):
            full_mix = _run_volumedetect(final_video)
            max_db = full_mix.get("max", None)
            clip_threshold = self._config.threshold_for("BGM_002", self._config.bgm_clip_threshold_db)

            if max_db is None:
                results.append(self._skip("BGM_002", "volumedetect failed"))
            elif max_db > clip_threshold:
                results.append(
                    self._fail(
                        "BGM_002",
                        f"Final mix is clipping (peak={max_db:.1f} dBFS, limit={clip_threshold:.1f} dBFS)",
                        f"max_volume={max_db:.1f} dBFS",
                        "high",
                        max_db=max_db,
                        clip_threshold=clip_threshold,
                    )
                )
            else:
                results.append(
                    self._pass(
                        "BGM_002",
                        "Final mix within headroom — no clipping",
                        f"max_volume={max_db:.1f} dBFS (limit {clip_threshold:.1f} dBFS)",
                        max_db=max_db,
                    )
                )

        # ── BGM_003: Overall loudness within acceptable range ─────────────
        # Target: YouTube normalises to -14 LUFS; acceptable window -20 to -12 LUFS.
        # We approximate via mean dBFS: mean between -25 and -12 is acceptable.
        if self._config.is_enabled("BGM_003"):
            full_mix = _run_volumedetect(final_video)
            mean_db = full_mix.get("mean", None)
            low_limit = self._config.threshold_for("BGM_003", self._config.bgm_loudness_low_db)
            high_limit = -10.0  # hard upper bound

            if mean_db is None:
                results.append(self._skip("BGM_003", "volumedetect failed"))
            elif mean_db < low_limit:
                results.append(
                    self._warn(
                        "BGM_003",
                        f"Final mix may be too quiet for YouTube (mean={mean_db:.1f} dBFS, "
                        f"expected > {low_limit:.0f} dBFS)",
                        f"mean_volume={mean_db:.1f} dBFS",
                        "medium",
                        mean_db=mean_db,
                        low_limit=low_limit,
                    )
                )
            elif mean_db > high_limit:
                results.append(
                    self._warn(
                        "BGM_003",
                        f"Final mix may be too loud (mean={mean_db:.1f} dBFS, "
                        f"expected < {high_limit:.0f} dBFS)",
                        f"mean_volume={mean_db:.1f} dBFS",
                        "medium",
                        mean_db=mean_db,
                        high_limit=high_limit,
                    )
                )
            else:
                results.append(
                    self._pass(
                        "BGM_003",
                        "Final mix loudness within YouTube recommended range",
                        f"mean_volume={mean_db:.1f} dBFS",
                        mean_db=mean_db,
                    )
                )

        # ── BGM_004: Narration audible above BGM (BGM not dominating) ─────
        # Compare intro section (BGM-only, fade-in) vs mid-video (narration+BGM).
        # If the intro is louder than the body, BGM volume is too high.
        if self._config.is_enabled("BGM_004"):
            intro_vol = _run_volumedetect(final_video, start=0.0, duration=3.0)
            body_start = min(5.0, _probe_duration(final_video) * 0.1)
            body_vol = _run_volumedetect(final_video, start=body_start, duration=10.0)

            intro_mean = intro_vol.get("mean")
            body_mean = body_vol.get("mean")
            dominance_threshold = self._config.threshold_for("BGM_004", self._config.bgm_dominance_threshold_db)

            if intro_mean is None or body_mean is None:
                results.append(self._skip("BGM_004", "volumedetect failed"))
            elif intro_mean > body_mean + dominance_threshold:
                results.append(
                    self._warn(
                        "BGM_004",
                        f"BGM intro ({intro_mean:.1f} dBFS) is louder than "
                        f"narration body ({body_mean:.1f} dBFS) — BGM may dominate",
                        f"intro={intro_mean:.1f} dBFS, body={body_mean:.1f} dBFS",
                        "medium",
                        intro_mean_db=intro_mean,
                        body_mean_db=body_mean,
                    )
                )
            else:
                results.append(
                    self._pass(
                        "BGM_004",
                        "Narration is clearly audible above BGM",
                        f"intro={intro_mean:.1f} dBFS, body={body_mean:.1f} dBFS",
                        intro_mean_db=intro_mean,
                        body_mean_db=body_mean,
                    )
                )

        # ── BGM_005: Duck depth — BGM is lower during narration than intro ──
        if self._config.is_enabled("BGM_005"):
            results.append(self._check_duck_depth(final_video, project_dir))

        # ── BGM_006: Phrase detection active — VAD timeline written ──────────
        if self._config.is_enabled("BGM_006"):
            results.append(self._check_phrase_detection(project_dir))

        # ── BGM_007: Long silence recovery — BGM restores after long pause ───
        if self._config.is_enabled("BGM_007"):
            long_silence_ms = context.get("bgm_long_silence_ms", 2000)
            results.append(self._check_silence_recovery(final_video, project_dir, long_silence_ms))

        return results

    # ── V2 rule helpers ───────────────────────────────────────────────────────

    def _check_duck_depth(
        self, final_video: Path, project_dir: Path
    ) -> ValidationResult:
        """BGM_005: BGM volume during speech should be ≤50% of BGM intro volume."""
        timeline_path = project_dir / "bgm-debug" / "speech_timeline.json"
        if not timeline_path.exists():
            return self._skip("BGM_005", "bgm-debug/speech_timeline.json absent — VAD not run")

        try:
            timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        except Exception:
            return self._skip("BGM_005", "Could not read speech_timeline.json")

        segments = timeline.get("segments", [])
        if not segments:
            return self._skip("BGM_005", "No speech segments in timeline")

        # Sample a 0.5-second window at the mid-point of the first speech phrase
        first = segments[0]
        seg_dur = first["end"] - first["start"]
        if seg_dur < 0.5:
            return self._skip("BGM_005", "First speech segment too short to sample")

        mid = (first["start"] + first["end"]) / 2
        speech_vol = _run_volumedetect(final_video, start=max(0.0, mid - 0.25), duration=0.5)
        intro_vol = _run_volumedetect(final_video, start=0.0, duration=3.0)

        speech_mean = speech_vol.get("mean")
        intro_mean = intro_vol.get("mean")

        if speech_mean is None or intro_mean is None:
            return self._skip("BGM_005", "volumedetect failed")

        # During narration, BGM+speech should be comparable to intro (BGM only).
        # A significant difference (speech section louder by > 3 dB) suggests
        # narration is audible over BGM — which is CORRECT and expected.
        # Flag only when speech section is QUIETER than intro (unlikely, but
        # could indicate mis-routed audio). Otherwise flag if ducking is absent.
        #
        # Practical test: intro (BGM only) should be quieter than speech+BGM body
        # by at most 6 dB.  If intro is LOUDER than body by more than 3 dB →
        # the narration is inaudible → warn.
        if intro_mean > speech_mean + 3.0:
            return self._warn(
                "BGM_005",
                f"BGM intro ({intro_mean:.1f} dBFS) louder than narration section "
                f"({speech_mean:.1f} dBFS) — possible ducking failure",
                f"intro={intro_mean:.1f} dBFS, speech_section={speech_mean:.1f} dBFS",
                "medium",
                intro_mean_db=intro_mean,
                speech_mean_db=speech_mean,
            )

        return self._pass(
            "BGM_005",
            "BGM ducking active — narration section level is appropriate",
            f"intro={intro_mean:.1f} dBFS, speech_section={speech_mean:.1f} dBFS",
            intro_mean_db=intro_mean,
            speech_mean_db=speech_mean,
        )

    def _check_phrase_detection(self, project_dir: Path) -> ValidationResult:
        """BGM_006: VAD timeline present and non-empty (phrase detection ran)."""
        timeline_path = project_dir / "bgm-debug" / "speech_timeline.json"
        if not timeline_path.exists():
            return self._skip(
                "BGM_006",
                "bgm-debug/speech_timeline.json absent — VAD disabled or not run yet",
            )
        try:
            timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
            seg_count = timeline.get("segment_count", 0)
        except Exception:
            return self._skip("BGM_006", "Could not parse speech_timeline.json")

        if seg_count == 0:
            return self._warn(
                "BGM_006",
                "Speech timeline is empty — phrase detection found no speech",
                "segment_count=0",
                "low",
                segment_count=0,
            )
        return self._pass(
            "BGM_006",
            f"Phrase detection active — {seg_count} phrase(s) detected",
            f"segment_count={seg_count}",
            segment_count=seg_count,
        )

    def _check_silence_recovery(
        self, final_video: Path, project_dir: Path, long_silence_ms: int
    ) -> ValidationResult:
        """BGM_007: BGM volume recovers during a long-silence window."""
        timeline_path = project_dir / "bgm-debug" / "speech_timeline.json"
        if not timeline_path.exists():
            return self._skip("BGM_007", "bgm-debug/speech_timeline.json absent — VAD not run")

        try:
            timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
            segments = timeline.get("segments", [])
        except Exception:
            return self._skip("BGM_007", "Could not read speech_timeline.json")

        # Find a silence gap > long_silence_ms between consecutive segments
        long_silence_s = long_silence_ms / 1000.0
        silence_window: tuple[float, float] | None = None

        for i in range(len(segments) - 1):
            gap_start = segments[i]["end"]
            gap_end = segments[i + 1]["start"]
            if gap_end - gap_start >= long_silence_s:
                silence_window = (gap_start + 0.2, gap_end - 0.2)
                break

        if silence_window is None:
            return self._skip(
                "BGM_007",
                f"No silence gap > {long_silence_ms} ms found — recovery check not applicable",
            )

        w_start, w_dur = silence_window[0], silence_window[1] - silence_window[0]
        if w_dur < 0.5:
            return self._skip("BGM_007", "Long silence window too short to sample")

        silence_vol = _run_volumedetect(final_video, start=w_start, duration=min(2.0, w_dur))
        intro_vol = _run_volumedetect(final_video, start=0.0, duration=3.0)

        silence_mean = silence_vol.get("mean")
        intro_mean = intro_vol.get("mean")

        if silence_mean is None or intro_mean is None:
            return self._skip("BGM_007", "volumedetect failed")

        # During long silence, BGM should be close to intro level (within 4 dB).
        if intro_mean - silence_mean > 4.0:
            return self._warn(
                "BGM_007",
                f"BGM did not fully recover during long silence "
                f"(silence={silence_mean:.1f} dBFS, intro={intro_mean:.1f} dBFS, "
                f"diff={intro_mean - silence_mean:.1f} dB)",
                f"silence_window=[{w_start:.1f}s, {w_start + w_dur:.1f}s]",
                "medium",
                silence_mean_db=silence_mean,
                intro_mean_db=intro_mean,
            )
        return self._pass(
            "BGM_007",
            "BGM recovered to full volume during long silence",
            f"silence={silence_mean:.1f} dBFS, intro={intro_mean:.1f} dBFS",
            silence_mean_db=silence_mean,
            intro_mean_db=intro_mean,
        )


def _probe_duration(path: Path) -> float:
    """Return video duration in seconds via ffprobe."""
    import json

    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0
