"""CTA validation rules (category: cta).

Rules:
  CTA_001 [high]   — CTA timing report exists and timestamp is within video bounds
  CTA_002 [medium] — CTA placement is subtitle-safe (or valid fallback)
  CTA_003 [medium] — CTA animation completed without error
  CTA_004 [medium] — Branding loaded and precedence applied correctly
  CTA_005 [low]    — BGM secondary duck applied at CTA timestamp

All rules SKIP automatically when CTA is disabled (cta-timing.json has enabled=false
or file is absent).
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult


def _load_cta_timing(project_dir: Path) -> dict | None:
    """Load cta/cta-timing.json; return None if absent."""
    path = project_dir / "cta" / "cta-timing.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _probe_video_duration(project_dir: Path) -> float:
    """Estimate video duration from timing.json files."""
    audio_dir = project_dir / "audio"
    total = 0.0
    for p in sorted(audio_dir.glob("scene-*.timing.json")):
        try:
            data = json.loads(p.read_text())
            if isinstance(data, list) and data:
                total += float(data[-1].get("end", 0.0)) + 0.1
        except Exception:
            pass
    return total


class CTAValidator(BaseValidator):
    """Validates the CTA Overlay Engine outputs."""

    category = "cta"
    responsible_engine = "CTA Overlay Engine"

    def validate(
        self,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        rule_ids = ("CTA_001", "CTA_002", "CTA_003", "CTA_004", "CTA_005")

        timing = _load_cta_timing(project_dir)

        # Skip all rules when CTA is disabled or output is absent
        if timing is None or not timing.get("enabled", True):
            for rule_id in rule_ids:
                if self._config.is_enabled(rule_id):
                    reason = (
                        "CTA is disabled"
                        if timing is not None
                        else "cta/cta-timing.json absent — CTA stage not yet run"
                    )
                    results.append(self._skip(rule_id, reason))
            return results

        review_data = timing.get("review", {})
        placement = timing.get("timing_metadata") or {}

        # ── CTA_001: Timing valid ──────────────────────────────────────────
        if self._config.is_enabled("CTA_001"):
            results.append(self._check_timing(timing, placement, project_dir))

        # ── CTA_002: Subtitle safety ───────────────────────────────────────
        if self._config.is_enabled("CTA_002"):
            results.append(self._check_subtitle_safety(review_data, placement))

        # ── CTA_003: Animation completed ───────────────────────────────────
        if self._config.is_enabled("CTA_003"):
            results.append(self._check_animation(review_data))

        # ── CTA_004: Branding loaded ───────────────────────────────────────
        if self._config.is_enabled("CTA_004"):
            results.append(self._check_branding(review_data))

        # ── CTA_005: BGM secondary duck ────────────────────────────────────
        if self._config.is_enabled("CTA_005"):
            results.append(self._check_bgm_duck(review_data))

        return results

    # ── Rule helpers ──────────────────────────────────────────────────────────

    def _check_timing(
        self,
        timing: dict,
        placement: dict,
        project_dir: Path,
    ) -> ValidationResult:
        """CTA_001: CTA timestamp within video bounds, no narration interruption."""
        if not timing.get("success", False):
            return self._fail(
                "CTA_001",
                "CTA pipeline did not succeed",
                f"success=False, errors={timing.get('review', {}).get('errors', [])}",
                "high",
            )

        ts = placement.get("timestamp")
        dur = placement.get("duration")

        if ts is None or dur is None:
            return self._fail(
                "CTA_001",
                "CTA timing metadata missing timestamp or duration",
                "placement={None}",
                "high",
            )

        video_dur = _probe_video_duration(project_dir)
        if video_dur > 0 and (ts < 0 or ts >= video_dur):
            return self._fail(
                "CTA_001",
                f"CTA timestamp {ts:.1f}s is outside video bounds (duration={video_dur:.1f}s)",
                f"timestamp={ts:.1f}s, video_duration={video_dur:.1f}s",
                "high",
                cta_timestamp=ts,
                video_duration=video_dur,
            )

        review = timing.get("review", {})
        if not review.get("timing_valid", True):
            return self._fail(
                "CTA_001",
                "CTA timing_valid=False in review report",
                f"timestamp={ts:.1f}s",
                "high",
                cta_timestamp=ts,
            )

        return self._pass(
            "CTA_001",
            f"CTA timing valid: timestamp={ts:.1f}s, duration={dur:.1f}s",
            f"timestamp={ts:.1f}s, duration={dur:.1f}s, variant={placement.get('variant', '?')}",
            cta_timestamp=ts,
            cta_duration=dur,
        )

    def _check_subtitle_safety(
        self, review_data: dict, placement: dict
    ) -> ValidationResult:
        """CTA_002: Subtitle safety check."""
        path_val = placement.get("placement_path", "")
        is_fallback = path_val == "fallback_timing"
        subtitle_safe = review_data.get("subtitle_safe", True)
        zone = placement.get("zone", "unknown")

        if is_fallback and not subtitle_safe:
            return self._warn(
                "CTA_002",
                "CTA placed via fallback_timing — subtitle overlap possible (expected in edge cases)",
                f"placement_path=fallback_timing, zone={zone}",
                "low",
                placement_path=path_val,
                zone=zone,
            )

        if not subtitle_safe:
            return self._warn(
                "CTA_002",
                f"CTA may overlap subtitles (zone={zone})",
                f"subtitle_safe=False, zone={zone}",
                "medium",
                zone=zone,
            )

        return self._pass(
            "CTA_002",
            f"CTA is subtitle-safe (zone={zone})",
            f"subtitle_safe=True, zone={zone}, placement_path={path_val}",
            zone=zone,
            placement_path=path_val,
        )

    def _check_animation(self, review_data: dict) -> ValidationResult:
        """CTA_003: Animation completed without error."""
        animation_completed = review_data.get("animation_completed", False)
        retry_count = review_data.get("retry_count", 0)
        fallback_template = review_data.get("fallback_template")

        if not animation_completed:
            return self._fail(
                "CTA_003",
                "CTA animation did not complete — render failed",
                f"animation_completed=False, retry_count={retry_count}",
                "medium",
                retry_count=retry_count,
            )

        if fallback_template:
            return self._warn(
                "CTA_003",
                f"CTA animation completed using fallback template '{fallback_template}'",
                f"animation_completed=True, fallback_template={fallback_template}",
                "low",
                fallback_template=fallback_template,
                retry_count=retry_count,
            )

        return self._pass(
            "CTA_003",
            f"CTA animation completed (retry_count={retry_count})",
            f"animation_completed=True, retry_count={retry_count}",
            retry_count=retry_count,
        )

    def _check_branding(self, review_data: dict) -> ValidationResult:
        """CTA_004: Branding loaded and precedence applied."""
        branding_loaded = review_data.get("branding_loaded", False)
        if not branding_loaded:
            return self._warn(
                "CTA_004",
                "CTA branding could not be fully loaded — default colors used",
                "branding_loaded=False",
                "medium",
                branding_loaded=False,
            )
        return self._pass(
            "CTA_004",
            "CTA branding loaded and precedence applied",
            "branding_loaded=True",
            branding_loaded=True,
        )

    def _check_bgm_duck(self, review_data: dict) -> ValidationResult:
        """CTA_005: BGM secondary duck applied."""
        bgm_duck = review_data.get("bgm_duck_applied", False)
        if not bgm_duck:
            return self._warn(
                "CTA_005",
                "BGM secondary duck not applied at CTA timestamp",
                "bgm_duck_applied=False",
                "low",
                bgm_duck_applied=False,
            )
        return self._pass(
            "CTA_005",
            "BGM secondary duck applied at CTA timestamp",
            "bgm_duck_applied=True",
            bgm_duck_applied=True,
        )
