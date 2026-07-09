"""Smart change detection for the incremental pipeline.

Scans all stage output patterns against the stored manifest checksums,
reports what changed, and computes the set of pipeline stages that must
re-run (including all downstream dependencies).
"""

from __future__ import annotations

from pathlib import Path

from .deps import PIPELINE_STAGES, STAGE_OUTPUT_PATTERNS, downstream_stages
from .manifest import PipelineManifest
from .models import ChangeReport


class ChangeDetector:
    """Detect which assets changed and which stages must re-run."""

    def __init__(self, project_dir: Path, manifest: PipelineManifest) -> None:
        self._project_dir = project_dir
        self._manifest = manifest

    def detect(
        self,
        force_stages: set[str] | None = None,
        scene_filter: int | None = None,
    ) -> ChangeReport:
        """
        Compare on-disk assets against the manifest.

        Args:
            force_stages:  Stages to invalidate regardless of checksum state.
            scene_filter:  When set, only scan assets for this scene index.

        Returns:
            ChangeReport with changed/missing/new asset paths and the set of
            stages that need to re-run (including downstream propagation).
        """
        report = ChangeReport()
        changed_stages: set[str] = set(force_stages or ())

        for stage in PIPELINE_STAGES:
            patterns = STAGE_OUTPUT_PATTERNS.get(stage, [])
            for pattern in patterns:
                if "*" in pattern:
                    self._scan_glob(
                        stage, pattern, report, changed_stages, scene_filter
                    )
                else:
                    self._scan_file(stage, pattern, report, changed_stages)

        # Propagate invalidations to all downstream stages
        report.invalidated_stages = changed_stages | downstream_stages(changed_stages)
        return report

    # ── Internal ─────────────────────────────────────────────────────────────

    def _scan_glob(
        self,
        stage: str,
        pattern: str,
        report: ChangeReport,
        changed_stages: set[str],
        scene_filter: int | None,
    ) -> None:
        for abs_path in sorted(self._project_dir.glob(pattern)):
            rel_path = str(abs_path.relative_to(self._project_dir))

            # When a scene filter is active, only process files for that scene
            if scene_filter is not None and f"-{scene_filter:03d}." not in rel_path:
                continue

            entry = self._manifest.get(rel_path)
            if entry is None:
                report.new.append(rel_path)
                changed_stages.add(stage)
            elif self._manifest.is_changed(rel_path):
                report.changed.append(rel_path)
                changed_stages.add(stage)

    def _scan_file(
        self,
        stage: str,
        rel_path: str,
        report: ChangeReport,
        changed_stages: set[str],
    ) -> None:
        abs_path = self._project_dir / rel_path
        if not abs_path.exists():
            return
        entry = self._manifest.get(rel_path)
        if entry is None:
            report.new.append(rel_path)
            changed_stages.add(stage)
        elif self._manifest.is_changed(rel_path):
            report.changed.append(rel_path)
            changed_stages.add(stage)

    def missing_assets(self, stage: str) -> list[str]:
        """Return rel-paths of tracked assets for a stage that are no longer on disk."""
        missing = []
        for rel_path, entry in self._manifest.entries.items():
            if entry.stage == stage:
                if not (self._project_dir / rel_path).exists():
                    missing.append(rel_path)
        return missing

    def stage_is_complete(self, stage: str) -> bool:
        """True if at least one manifest entry exists for this stage with no missing files."""
        has_entry = False
        for entry in self._manifest.entries.values():
            if entry.stage == stage:
                has_entry = True
                if not (self._project_dir / entry.path).exists():
                    return False
        return has_entry
