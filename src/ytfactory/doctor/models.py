"""Data models for the Doctor pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ytfactory.bootstrap.models import CheckResult, CheckStatus


@dataclass
class DoctorReport:
    checks: list[CheckResult] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def errors(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == CheckStatus.ERROR]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == CheckStatus.WARNING]

    @property
    def repaired(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == CheckStatus.REPAIRED]
