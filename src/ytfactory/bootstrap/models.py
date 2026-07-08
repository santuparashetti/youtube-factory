"""Data models for the Bootstrap Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CheckStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"
    REPAIRED = "repaired"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    message: str
    detail: str = ""
    repaired: bool = False

    @property
    def ok(self) -> bool:
        return self.status in (CheckStatus.OK, CheckStatus.REPAIRED, CheckStatus.SKIPPED)


@dataclass
class BootstrapResult:
    checks: list[CheckResult] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        # Warnings are non-blocking; only ERRORs cause failure.
        return all(c.status != CheckStatus.ERROR for c in self.checks)

    @property
    def errors(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == CheckStatus.ERROR]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == CheckStatus.WARNING]

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)


@dataclass
class ProviderCheckResult:
    provider: str
    api_key_present: bool
    connectivity: bool
    message: str
    status: CheckStatus
