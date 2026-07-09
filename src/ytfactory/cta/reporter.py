"""CTA reporter — writes cta/ workspace artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from .models import CTAResult


class CTAReporter:
    """Write CTA timing metadata and review report to workspace/jobs/<id>/cta/."""

    def write(self, project_dir: Path, result: CTAResult) -> None:
        """Write cta-timing.json and cta-review-report.json."""
        cta_dir = project_dir / "cta"
        cta_dir.mkdir(parents=True, exist_ok=True)

        # cta-timing.json
        timing_path = cta_dir / "cta-timing.json"
        timing_data = result.to_dict()
        timing_path.write_text(json.dumps(timing_data, indent=2), encoding="utf-8")

        # cta-review-report.json (separate, human-readable focus)
        review_path = cta_dir / "cta-review-report.json"
        review_data = {
            "enabled": result.enabled,
            "success": result.success,
            "passed": result.review.passed,
            "errors": result.review.errors,
            "warnings": result.review.warnings,
            "retry_count": result.review.retry_count,
            "fallback_template": result.review.fallback_template,
            "reason_code": result.review.reason_code,
            "checks": {
                "timing_valid": result.review.timing_valid,
                "subtitle_safe": result.review.subtitle_safe,
                "branding_loaded": result.review.branding_loaded,
                "animation_completed": result.review.animation_completed,
                "bgm_duck_applied": result.review.bgm_duck_applied,
            },
        }
        if result.placement:
            review_data["placement"] = {
                "timestamp": result.placement.timestamp,
                "duration": result.placement.duration,
                "variant": result.placement.variant.value,
                "placement_path": result.placement.placement_path.value,
                "zone": result.placement.zone.value,
                "pause_type": result.placement.pause_type,
            }
        review_path.write_text(json.dumps(review_data, indent=2), encoding="utf-8")
