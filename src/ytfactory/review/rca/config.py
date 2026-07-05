"""Configuration for the Root Cause Analysis Engine V1."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RCAConfig:
    """Configuration controlling RCA analysis behaviour."""

    enabled: bool = True

    # Number of times a (engine, root_cause_code) pair must appear across
    # distinct scenes before it is flagged as a recurring systemic issue.
    recurring_threshold: int = 2

    # Suppress issues whose confidence is below this value (0–100).
    min_confidence_to_report: int = 0

    # Whether to generate RCA issues for WARNING-status validation results
    # (in addition to FAIL-status results).
    include_warnings: bool = True

    # Per-rule overrides: rule_id → {"enabled": bool}
    rule_overrides: dict[str, dict] = field(default_factory=dict)

    def is_rule_enabled(self, rule_id: str) -> bool:
        override = self.rule_overrides.get(rule_id, {})
        return override.get("enabled", True)
