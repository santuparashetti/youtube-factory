"""BaseValidator — abstract base class for all category validators.

Subclasses implement `validate()` and call the helper methods
`_pass`, `_fail`, `_warn`, and `_skip` to build ValidationResult objects.
Every helper accepts **meta kwargs that land in debug_metadata.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from ytfactory.review.validation.config import ValidationRulesConfig
from ytfactory.review.validation.models import ValidationResult


class BaseValidator(ABC):
    """Abstract base for all Video Validation Rules V1 category validators."""

    category: str = "unknown"
    responsible_engine: str = "Unknown"

    def __init__(self, config: ValidationRulesConfig) -> None:
        self._config = config

    # ── Core interface ────────────────────────────────────────────────────

    @abstractmethod
    def validate(
        self,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> list[ValidationResult]:
        """Run all rules in this category.

        Must not raise — catch all exceptions internally and produce SKIP
        results with the exception as evidence.
        """
        ...

    # ── Timestamp ─────────────────────────────────────────────────────────

    def _ts(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── Result builders ───────────────────────────────────────────────────

    def _pass(
        self,
        rule_id: str,
        description: str = "",
        evidence: str = "check passed",
        scene_index: int | None = None,
        confidence: float = 1.0,
        **meta,
    ) -> ValidationResult:
        return ValidationResult(
            rule_id=rule_id,
            category=self.category,
            status="PASS",
            severity=self._config.severity_for(rule_id, "low"),
            description=description or f"{rule_id} passed",
            evidence=evidence,
            confidence=confidence,
            responsible_engine=self.responsible_engine,
            timestamp=self._ts(),
            scene_index=scene_index,
            debug_metadata=dict(meta),
        )

    def _fail(
        self,
        rule_id: str,
        description: str,
        evidence: str,
        severity: str,
        scene_index: int | None = None,
        confidence: float = 0.9,
        **meta,
    ) -> ValidationResult:
        return ValidationResult(
            rule_id=rule_id,
            category=self.category,
            status="FAIL",
            severity=self._config.severity_for(rule_id, severity),
            description=description,
            evidence=evidence,
            confidence=confidence,
            responsible_engine=self.responsible_engine,
            timestamp=self._ts(),
            scene_index=scene_index,
            debug_metadata=dict(meta),
        )

    def _warn(
        self,
        rule_id: str,
        description: str,
        evidence: str,
        severity: str = "low",
        scene_index: int | None = None,
        confidence: float = 0.7,
        **meta,
    ) -> ValidationResult:
        return ValidationResult(
            rule_id=rule_id,
            category=self.category,
            status="WARNING",
            severity=self._config.severity_for(rule_id, severity),
            description=description,
            evidence=evidence,
            confidence=confidence,
            responsible_engine=self.responsible_engine,
            timestamp=self._ts(),
            scene_index=scene_index,
            debug_metadata=dict(meta),
        )

    def _skip(
        self,
        rule_id: str,
        reason: str,
        scene_index: int | None = None,
    ) -> ValidationResult:
        return ValidationResult(
            rule_id=rule_id,
            category=self.category,
            status="SKIP",
            severity="low",
            description=f"{rule_id} skipped: {reason}",
            evidence=reason,
            confidence=1.0,
            responsible_engine=self.responsible_engine,
            timestamp=self._ts(),
            scene_index=scene_index,
            debug_metadata={},
        )
