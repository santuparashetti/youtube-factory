"""Continuity validator — checks identity drift."""

from __future__ import annotations

from typing import Any

from video_core.visual_intelligence.consistency.identities import VisualIdentity


class ContinuityValidator:
    """Validate that generated images maintain identity continuity."""

    def validate(
        self,
        identity: VisualIdentity,
        detected_attributes: dict[str, Any],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for key, expected in identity.canonical_attributes.items():
            detected = detected_attributes.get(key)
            if detected and str(detected).lower() != str(expected).lower():
                issues.append({
                    "category": "identity_drift",
                    "attribute": key,
                    "expected": str(expected),
                    "detected": str(detected),
                    "severity": "MEDIUM",
                })
        return issues
