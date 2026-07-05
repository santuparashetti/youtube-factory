"""Reporter for Video Validation Rules V1 results.

Writes validation-report.json to workspace/jobs/<project_id>/review/.
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.review.artifacts import review_directory
from ytfactory.review.validation.models import ValidationReport


def validation_report_path(project_id: str) -> Path:
    """Path to validation-report.json inside the review directory."""
    return review_directory(project_id) / "validation-report.json"


class ValidationReporter:
    """Write validation-report.json for a completed ValidationReport."""

    def write(self, report: ValidationReport) -> Path:
        path = validation_report_path(report.project_id)
        path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path
