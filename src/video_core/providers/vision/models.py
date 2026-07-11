"""Data models for vision review results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class IssueSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class VisionIssue:
    """A single detected issue in the reviewed image."""

    category: str  # e.g. "anatomy", "face", "artifact", "cinematic"
    description: str  # human-readable description
    severity: IssueSeverity = IssueSeverity.MEDIUM
    location: str = ""  # optional location hint (e.g. "left hand")


@dataclass
class VisionReviewResult:
    """Structured result from a vision model image review.

    JSON contract (returned by all VisionProvider implementations):
    {
        "status": "PASS" | "FAIL",
        "score": 0-100,
        "confidence": 0-100,
        "issues": [{"category": ..., "description": ..., "severity": ..., "location": ...}],
        "recommend_regeneration": true|false
    }
    """

    status: str  # "PASS" | "FAIL" | "SKIP" | "ERROR"
    score: float = 0.0  # 0–100
    confidence: float = 0.0  # 0–100
    issues: list[VisionIssue] = field(default_factory=list)
    recommend_regeneration: bool = False
    model_name: str = ""
    backend: str = ""
    raw_response: str = ""  # raw LLM/model output for debugging
    error: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    @property
    def high_severity_issues(self) -> list[VisionIssue]:
        return [
            i
            for i in self.issues
            if i.severity in (IssueSeverity.HIGH, IssueSeverity.CRITICAL)
        ]

    @property
    def medium_severity_issues(self) -> list[VisionIssue]:
        return [i for i in self.issues if i.severity == IssueSeverity.MEDIUM]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "score": self.score,
            "confidence": self.confidence,
            "issues": [
                {
                    "category": i.category,
                    "description": i.description,
                    "severity": i.severity.value,
                    "location": i.location,
                }
                for i in self.issues
            ],
            "recommend_regeneration": self.recommend_regeneration,
            "model_name": self.model_name,
            "backend": self.backend,
            "error": self.error,
        }

    @classmethod
    def skipped(cls, reason: str) -> "VisionReviewResult":
        return cls(status="SKIP", score=100.0, confidence=100.0, error=reason)

    @classmethod
    def error_result(cls, error: str) -> "VisionReviewResult":
        return cls(
            status="ERROR",
            score=0.0,
            confidence=0.0,
            recommend_regeneration=False,
            error=error,
        )
