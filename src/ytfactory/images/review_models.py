"""Data models for per-scene and global image review artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SceneReviewArtifact:
    """Written to workspace/jobs/<id>/images/image-review.json per scene."""

    scene_index: int
    status: str  # PASS | FAIL | SKIP | ERROR
    score: float = 0.0
    confidence: float = 0.0
    issues: list[dict] = field(default_factory=list)
    attempts: int = 1
    final_prompt: str = ""
    model_name: str = ""
    backend: str = ""
    recommend_regeneration: bool = False
    error: str = ""
    # Subject Specialist Review (ADR-0013) — populated when a critical subject
    # is detected in the visual prompt.
    subject_critical: bool = False
    specialist_subject: str = ""   # "hand" | "face" | "eye" | "body" | "gesture" | ""
    specialist_status: str = ""    # PASS | FAIL | SKIP | ""
    specialist_score: float = 0.0
    specialist_issues: list[dict] = field(default_factory=list)
    # Human Subject QA Gate (ADR-0015) — staged checks for human-critical scenes.
    human_qa_triggered: bool = False   # True when scene is human-critical
    human_qa_passed: bool = False      # True when all triggered stages passed
    human_qa_status: str = ""          # Human QA stage: PASS | FAIL | SKIP | ""
    hand_qa_status: str = ""           # Hand QA stage: PASS | FAIL | SKIP | ""
    clothing_qa_status: str = ""       # Clothing QA stage: PASS | FAIL | SKIP | ""
    prompt_compliance_status: str = "" # Prompt Compliance stage: PASS | FAIL | SKIP | ""
    # Two-stage critical validation result
    overall_status: str = ""
    overall_score: float = 0.0
    recommend_regeneration: bool = False
    # Critical Validation Rule outputs
    hard_constraints: dict = field(default_factory=dict)
    quality_scores: dict = field(default_factory=dict)
    failure_categories: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class SceneRemediationArtifact:
    """Written to workspace/jobs/<id>/images/image-remediation.json per scene."""

    scene_index: int
    original_prompt: str
    attempt_history: list[dict] = field(default_factory=list)
    final_status: str = "SKIP"
    total_attempts: int = 0
    remediation_applied: bool = False


@dataclass
class ImageQualitySummary:
    """Written to workspace/jobs/<id>/images/image-quality-summary.json."""

    total_scenes: int = 0
    reviewed: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    total_attempts: int = 0
    scenes: list[dict] = field(default_factory=list)
    overall_pass_rate: float = 0.0

    def finalize(self) -> None:
        if self.reviewed > 0:
            self.overall_pass_rate = round(self.passed / self.reviewed, 3)

    def to_dict(self) -> dict:
        return {
            "total_scenes": self.total_scenes,
            "reviewed": self.reviewed,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
            "total_attempts": self.total_attempts,
            "overall_pass_rate": self.overall_pass_rate,
            "scenes": self.scenes,
        }
