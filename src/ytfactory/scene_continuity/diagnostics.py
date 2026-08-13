"""Continuity diagnostics — structured reports and human-readable output."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import ContinuityFinding, ValidationLevel
from .transitions import ContinuityViolation


@dataclass
class SceneContinuityStatus:
    """Continuity status for a single scene."""

    scene_index: int
    status: str  # PASS | REPAIRED | FAILED
    violations: list[ContinuityFinding] = field(default_factory=list)
    transition_violations: list[ContinuityViolation] = field(default_factory=list)
    prompt_violations: list[ContinuityFinding] = field(default_factory=list)
    repair_attempts: int = 0
    prompt_repairs: int = 0


@dataclass
class ContinuityReport:
    """Full continuity report for a scene plan."""

    total_scenes: int = 0
    scenes: dict[int, SceneContinuityStatus] = field(default_factory=dict)
    all_violations: list[ContinuityFinding] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    critical_count: int = 0
    repaired_count: int = 0
    failed_count: int = 0

    def record_scene(self, status: SceneContinuityStatus) -> None:
        self.scenes[status.scene_index] = status
        self.total_scenes = max(self.total_scenes, status.scene_index)
        for v in status.violations + status.prompt_violations:
            self.all_violations.append(v)
            if v.level == ValidationLevel.ERROR:
                self.error_count += 1
            elif v.level == ValidationLevel.WARNING:
                self.warning_count += 1
            elif v.level == ValidationLevel.CRITICAL:
                self.critical_count += 1
        if status.status == "REPAIRED":
            self.repaired_count += 1
        if status.status == "FAILED":
            self.failed_count += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_scenes": self.total_scenes,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "critical_count": self.critical_count,
            "repaired_count": self.repaired_count,
            "failed_count": self.failed_count,
            "scenes": {
                idx: {
                    "status": s.status,
                    "repair_attempts": s.repair_attempts,
                    "prompt_repairs": s.prompt_repairs,
                    "violations": [
                        {
                            "code": getattr(v, "code", ""),
                            "severity": v.level.value if hasattr(v.level, "value") else str(v.level),
                            "category": v.category,
                            "message": v.message,
                            "suggested_fix": v.suggested_fix,
                        }
                        for v in s.violations + s.prompt_violations
                    ],
                }
                for idx, s in sorted(self.scenes.items())
            },
        }

    def to_markdown(self) -> str:
        lines: list[str] = [
            "# Scene Continuity Report",
            "",
            f"Total scenes: {self.total_scenes}",
            f"Errors: {self.error_count} | Warnings: {self.warning_count} | "
            f"Critical: {self.critical_count}",
            f"Repaired: {self.repaired_count} | Failed: {self.failed_count}",
            "",
            "---",
            "",
        ]

        for idx in sorted(self.scenes.keys()):
            s = self.scenes[idx]
            icon = {
                "PASS": "✓",
                "REPAIRED": "⚠",
                "FAILED": "✗",
            }.get(s.status, "?")
            lines.append(f"## Scene {idx:03d} {icon} {s.status}")
            lines.append("")
            if s.violations:
                lines.append("### State Transitions")
                for v in s.violations:
                    sev = v.level.value if hasattr(v.level, "value") else str(v.level)
                    lines.append(f"- [{sev}] {v.category}: {v.message}")
                    if v.suggested_fix:
                        lines.append(f"  - Fix: {v.suggested_fix}")
                lines.append("")
            if s.prompt_violations:
                lines.append("### Prompt Violations")
                for v in s.prompt_violations:
                    sev = v.level.value if hasattr(v.level, "value") else str(v.level)
                    lines.append(f"- [{sev}] {v.category}: {v.message}")
                    if v.suggested_fix:
                        lines.append(f"  - Fix: {v.suggested_fix}")
                lines.append("")
            if s.repair_attempts or s.prompt_repairs:
                lines.append(
                    f"Repairs: {s.repair_attempts} state, {s.prompt_repairs} prompt"
                )
                lines.append("")

        if not self.scenes:
            lines.append("No continuity data available.")
            lines.append("")

        return "\n".join(lines)

    def write_report(self, project_dir: Path) -> Path:
        """Write continuity report to scenes/continuity-report.md."""
        scenes_dir = project_dir / "scenes"
        scenes_dir.mkdir(parents=True, exist_ok=True)
        md_path = scenes_dir / "continuity-report.md"
        md_path.write_text(self.to_markdown(), encoding="utf-8")
        json_path = scenes_dir / "continuity-report.json"
        json_path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return md_path
