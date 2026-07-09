"""Incremental Build Engine — smart dependency-aware pipeline orchestrator.

Manages incremental pipeline execution:
  1. Loads the pipeline manifest
  2. Runs change detection (checksums + forced stages)
  3. Skips stages whose assets are valid and unchanged
  4. Runs only the stages that need work
  5. Records all new/updated assets into the manifest
  6. Updates scene workspace states from review results

Usage (from BuildPipeline):
    engine = IncrementalBuildEngine(project_dir)
    report = engine.analyze(force_stages={"images"}, scene_filter=8)
    should_run = engine.needs_run("video", report)
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from .change_detector import ChangeDetector
from .deps import STAGE_OUTPUT_PATTERNS
from .manifest import PipelineManifest
from .models import ChangeReport, SceneState
from .reporter import IncrementalReporter
from .scene_workspace import SceneWorkspace

console = Console()


class IncrementalBuildEngine:
    """Coordinate manifest, change detection, and scene workspace for incremental builds."""

    def __init__(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._manifest = PipelineManifest(project_dir)
        self._workspace = SceneWorkspace(project_dir)
        self._detector = ChangeDetector(project_dir, self._manifest)
        self._reporter = IncrementalReporter()

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def manifest(self) -> PipelineManifest:
        return self._manifest

    @property
    def workspace(self) -> SceneWorkspace:
        return self._workspace

    @property
    def reporter(self) -> IncrementalReporter:
        return self._reporter

    # ── Analysis ──────────────────────────────────────────────────────────────

    def analyze(
        self,
        force_stages: set[str] | None = None,
        scene_filter: int | None = None,
    ) -> ChangeReport:
        """
        Detect changes and compute which stages must re-run.

        Args:
            force_stages:  Stages to forcibly invalidate (from --force-* flags).
            scene_filter:  When set, scan only assets for this scene index.

        Returns:
            ChangeReport with the set of stages that need to re-run.
        """
        return self._detector.detect(
            force_stages=force_stages, scene_filter=scene_filter
        )

    def needs_run(self, stage: str, report: ChangeReport) -> bool:
        """True when a stage must run (is in the invalidated set)."""
        return stage in report.invalidated_stages

    def is_complete(self, stage: str) -> bool:
        """True when all manifest entries for this stage still exist on disk."""
        return self._detector.stage_is_complete(stage)

    # ── Scene lock guard ──────────────────────────────────────────────────────

    def is_locked(self, scene_index: int) -> bool:
        return self._workspace.is_locked(scene_index)

    def locked_scenes(self) -> list[int]:
        """Return indices of all locked scenes."""
        return [
            idx
            for idx, state in self._workspace.all_states().items()
            if state == SceneState.LOCKED
        ]

    # ── Manifest recording ────────────────────────────────────────────────────

    def record_stage_outputs(self, stage: str) -> None:
        """Snapshot all output files for a stage into the manifest, then save."""
        patterns = STAGE_OUTPUT_PATTERNS.get(stage, [])
        for pattern in patterns:
            if "*" in pattern:
                for abs_path in sorted(self._project_dir.glob(pattern)):
                    rel_path = str(abs_path.relative_to(self._project_dir))
                    self._manifest.record(rel_path, stage)
            else:
                abs_path = self._project_dir / pattern
                if abs_path.exists():
                    self._manifest.record(pattern, stage)
        self._manifest.save()

    def record_scene_asset(self, scene_index: int, stage: str, filename: str) -> None:
        """Record a single scene asset (e.g., images/scene-008.png) into the manifest."""
        rel_path = filename
        abs_path = self._project_dir / rel_path
        if abs_path.exists():
            self._manifest.record(rel_path, stage)
            self._manifest.save()

    # ── Scene workspace updates ───────────────────────────────────────────────

    def initialize_workspace(self) -> None:
        """Ensure all scenes from the scene plan have workspace entries."""
        indices = self._load_scene_indices()
        self._workspace.initialize_scenes(indices)

    def update_workspace_from_review(self, review_report: object) -> None:
        """
        Propagate per-scene quality results into scene states.

        - Failed scenes → Needs Revision (unless Locked)
        - Passed scenes in Draft → Needs Review (ready for creator approval)
        """
        scene_reviews = getattr(review_report, "scene_reviews", [])
        for sr in scene_reviews:
            idx = sr.index
            if self._workspace.is_locked(idx):
                continue
            if not sr.passed:
                self._workspace.mark_needs_revision(
                    idx, notes="; ".join(sr.issues[:3]) if sr.issues else ""
                )
            else:
                self._workspace.mark_needs_review(idx)

    # ── Reporting ─────────────────────────────────────────────────────────────

    def print_debug_report(
        self,
        report: ChangeReport,
        reused: set[str],
        rebuilt: set[str],
    ) -> None:
        self._reporter.print_change_report(report, reused, rebuilt)

    def write_scene_review_md(self) -> Path:
        return self._reporter.write_scene_review_md(
            self._project_dir, self._workspace, self._manifest
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_scene_indices(self) -> list[int]:
        plan_path = self._project_dir / "scenes" / "scene-plan.json"
        if not plan_path.exists():
            return []
        try:
            data = json.loads(plan_path.read_text(encoding="utf-8"))
            return [s["index"] for s in data.get("scenes", [])]
        except (json.JSONDecodeError, KeyError):
            return []
