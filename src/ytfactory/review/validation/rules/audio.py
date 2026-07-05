"""Audio validation rules (category F).

Rules:
  AUD_001 [critical] — Audio file exists for every scene
  AUD_002 [high]     — Audio file meets minimum size
  AUD_003 [high]     — Audio clip not suspiciously short (size heuristic)
  AUD_004 [medium]   — Voice clarity (SKIP — requires audio analysis library)
"""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult


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
            for rule_id in ("AUD_001", "AUD_002", "AUD_003", "AUD_004"):
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

        return results
