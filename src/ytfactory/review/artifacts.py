"""File-system paths for review engine outputs."""

from __future__ import annotations

from pathlib import Path

from ytfactory.shared.constants import WORKSPACE_DIR


def review_directory(project_id: str) -> Path:
    """Return (and create) workspace/jobs/<project_id>/review/."""
    directory = Path(WORKSPACE_DIR) / project_id / "review"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def review_report_path(project_id: str) -> Path:
    return review_directory(project_id) / "review-report.md"


def scene_review_path(project_id: str) -> Path:
    return review_directory(project_id) / "scene-review.json"


def review_debug_path(project_id: str) -> Path:
    return review_directory(project_id) / "review-debug.json"


# ── Extension-point stubs (populated by future modules) ──────────────────────


def quality_score_path(project_id: str) -> Path:
    """Quality Scoring Engine V1 — overall score summary (replaces stub)."""
    return review_directory(project_id) / "quality-score.json"


def root_cause_report_path(project_id: str) -> Path:
    """Backward-compat alias — RCAReporter writes root-cause.json (full) and root-cause-report.md."""
    return review_directory(project_id) / "root-cause.json"


def engine_feedback_path(project_id: str) -> Path:
    """Reserved for future Engine Feedback Loop V1."""
    return review_directory(project_id) / "engine-feedback.json"


def validation_report_path(project_id: str) -> Path:
    """Path to the Video Validation Rules V1 report."""
    return review_directory(project_id) / "validation-report.json"
