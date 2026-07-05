"""Audio validation rules (category F).

Rules:
  AUD_001 [critical] — Audio file exists for every scene
  AUD_002 [high]     — Audio file meets minimum size
  AUD_003 [high]     — Audio clip not suspiciously short (size heuristic)
  AUD_004 [medium]   — Voice clarity (SKIP — requires audio analysis library)
  AUD_005 [medium]   — Opening 300 ms not significantly quieter than rest of clip
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult


def _measure_mean_volume_db(audio_path: Path, start: float = 0.0, duration: float | None = None) -> float | None:
    """Return mean volume in dBFS for a segment of *audio_path* using ffmpeg volumedetect.

    Returns None on error or when the segment is too short to measure.
    """
    cmd = ["ffmpeg", "-nostdin"]
    if start > 0.0:
        cmd += ["-ss", f"{start:.4f}"]
    if duration is not None:
        cmd += ["-t", f"{duration:.4f}"]
    cmd += ["-i", str(audio_path), "-af", "volumedetect", "-f", "null", "-"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        for line in result.stderr.splitlines():
            m = re.search(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB", line)
            if m:
                return float(m.group(1))
    except Exception:
        pass
    return None


class AudioValidator(BaseValidator):
    category = "audio"
    responsible_engine = "VoiceGenerator"

    def validate(
        self,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> list[ValidationResult]:
        results: list[ValidationResult] = []

        if not scenes:
            for rule_id in ("AUD_001", "AUD_002", "AUD_003", "AUD_004", "AUD_005"):
                if self._config.is_enabled(rule_id):
                    results.append(self._skip(rule_id, "no scenes available"))
            return results

        for scene in scenes:
            idx = scene.get("index", 0)
            audio_path = project_dir / "audio" / f"scene-{idx:03d}.mp3"

            # AUD_001: Audio file exists
            if self._config.is_enabled("AUD_001"):
                if not audio_path.exists():
                    results.append(
                        self._fail(
                            "AUD_001",
                            f"Scene {idx}: audio file missing",
                            f"Expected: {audio_path.name}",
                            "critical",
                            scene_index=idx,
                        )
                    )
                    for rule_id in ("AUD_002", "AUD_003"):
                        if self._config.is_enabled(rule_id):
                            results.append(
                                self._skip(
                                    rule_id, "audio file unavailable", scene_index=idx
                                )
                            )
                    continue
                results.append(
                    self._pass(
                        "AUD_001",
                        f"Scene {idx} audio exists",
                        audio_path.name,
                        scene_index=idx,
                    )
                )

            if not audio_path.exists():
                continue

            size = audio_path.stat().st_size

            # AUD_002: Minimum size
            if self._config.is_enabled("AUD_002"):
                min_size = self._config.audio_min_size_bytes
                if size < min_size:
                    results.append(
                        self._fail(
                            "AUD_002",
                            f"Scene {idx}: audio file too small ({size} bytes)",
                            f"size_bytes={size}, min={min_size}",
                            "high",
                            scene_index=idx,
                            size_bytes=size,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "AUD_002",
                            f"Scene {idx} audio size OK",
                            f"{size} bytes",
                            scene_index=idx,
                        )
                    )

            # AUD_003: Not suspiciously short (size-based heuristic)
            if self._config.is_enabled("AUD_003"):
                short_threshold = self._config.audio_short_clip_bytes
                if 0 < size < short_threshold:
                    results.append(
                        self._warn(
                            "AUD_003",
                            f"Scene {idx}: audio clip may be very short ({size} bytes)",
                            f"size_bytes={size}, short_clip_threshold={short_threshold}",
                            "high",
                            scene_index=idx,
                            size_bytes=size,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "AUD_003",
                            f"Scene {idx} audio duration heuristic OK",
                            f"{size} bytes",
                            scene_index=idx,
                        )
                    )

        # AUD_004: Voice clarity — requires spectral analysis (SKIP)
        if self._config.is_enabled("AUD_004"):
            results.append(
                self._skip(
                    "AUD_004",
                    "voice clarity analysis requires librosa/scipy — not available",
                )
            )

        # AUD_005: Opening 300 ms not significantly quieter than rest of clip
        if self._config.is_enabled("AUD_005"):
            window = self._config.audio_quiet_start_window_seconds
            threshold = self._config.audio_quiet_start_threshold_db
            for scene in scenes:
                idx = scene.get("index", 0)
                audio_path = project_dir / "audio" / f"scene-{idx:03d}.mp3"
                if not audio_path.exists():
                    results.append(
                        self._skip("AUD_005", f"Scene {idx}: audio missing", scene_index=idx)
                    )
                    continue

                opening_db = _measure_mean_volume_db(audio_path, start=0.0, duration=window)
                body_db = _measure_mean_volume_db(audio_path, start=window)

                if opening_db is None or body_db is None:
                    results.append(
                        self._skip(
                            "AUD_005",
                            f"Scene {idx}: volumedetect unavailable",
                            scene_index=idx,
                        )
                    )
                    continue

                diff = body_db - opening_db
                if diff > threshold:
                    results.append(
                        self._warn(
                            "AUD_005",
                            f"Scene {idx}: opening {window:.0f}s is {diff:.1f} dB quieter than rest",
                            f"opening={opening_db:.1f} dBFS, body={body_db:.1f} dBFS, diff={diff:.1f} dB > {threshold} dB",
                            "medium",
                            scene_index=idx,
                            opening_db=opening_db,
                            body_db=body_db,
                            diff_db=diff,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "AUD_005",
                            f"Scene {idx}: opening volume OK",
                            f"opening={opening_db:.1f} dBFS, body={body_db:.1f} dBFS",
                            scene_index=idx,
                        )
                    )

        return results
