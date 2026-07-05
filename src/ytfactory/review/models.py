"""Domain models for the Video Quality Review Engine V1."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


# ── Per-stage result ──────────────────────────────────────────────────────────


@dataclass
class StageResult:
    """Outcome of a single validation stage."""

    stage_name: str
    passed: bool
    errors: list[str] = field(default_factory=list)  # critical — cause FAIL
    warnings: list[str] = field(default_factory=list)  # non-critical
    checks_run: int = 0
    checks_passed: int = 0
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# ── Per-scene review ──────────────────────────────────────────────────────────


@dataclass
class SceneReview:
    """Quality assessment for a single scene."""

    index: int
    scene_type: str = "generated_image"

    # Asset presence
    has_image: bool = False
    has_audio: bool = False
    has_subtitle: bool = False
    has_video_clip: bool = False

    # Asset validity
    image_size_bytes: int = 0
    audio_size_bytes: int = 0
    video_clip_size_bytes: int = 0

    # Content
    narration_word_count: int = 0
    has_visual_prompt: bool = False
    has_shot_type: bool = False

    # Duration
    declared_duration_seconds: float = 0.0

    issues: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.issues) == 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["passed"] = self.passed
        return d


# ── Overall review report ─────────────────────────────────────────────────────


@dataclass
class ReviewReport:
    """Top-level review report produced by VideoQualityReviewEngine."""

    project_id: str
    verdict: str  # "PASS" | "FAIL"
    timestamp: str

    # Aggregate counts
    total_scenes: int = 0
    scenes_passed: int = 0
    scenes_failed: int = 0

    # Stage breakdown
    stage_results: list[StageResult] = field(default_factory=list)

    # Per-scene detail
    scene_reviews: list[SceneReview] = field(default_factory=list)

    # Diagnostics
    all_errors: list[str] = field(default_factory=list)  # critical
    all_warnings: list[str] = field(default_factory=list)  # non-critical

    # Video summary
    final_video_path: str = ""
    final_video_size_mb: float = 0.0
    final_video_duration_seconds: float = 0.0

    # Timing
    processing_time_seconds: float = 0.0

    # Extension points for future modules
    # Root Cause Analysis Engine will populate this
    root_cause_hint: str = ""
    # Quality Scoring Engine will populate this
    quality_score: float | None = None
    # Engine Feedback Loop will populate this
    feedback_payload: dict = field(default_factory=dict)

    # Video Validation Rules V1 — populated by ValidationRunner
    validation_report: dict | None = None

    # Root Cause Analysis Engine V1 — populated by RootCauseAnalysisEngine
    rca_report: dict | None = None

    # Quality Scoring Engine V1 — populated by QualityScoringEngine
    quality_score_report: dict | None = None

    # Engine Feedback Loop V1 — populated by EngineFeedbackLoopEngine
    efl_report: dict | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stage_results"] = [s.to_dict() for s in self.stage_results]
        d["scene_reviews"] = [s.to_dict() for s in self.scene_reviews]
        return d
