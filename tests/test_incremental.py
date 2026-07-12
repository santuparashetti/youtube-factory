"""Tests for src/ytfactory/incremental/ — all V1 incremental pipeline features.

Coverage:
  - PipelineManifest: record, checksum, is_changed, is_missing, save/load
  - ChangeDetector: glob scan, file scan, force_stages, scene_filter, downstream propagation
  - SceneWorkspace: state transitions, locked guard, persistence
  - IncrementalBuildEngine: analyze, needs_run, record_stage_outputs, lock guard
  - IncrementalReporter: print_change_report (smoke test), write_scene_review_md
  - BuildPipeline.run_incremental: script stage called when dirty, skipped when clean (MW-005)
  - deps: downstream_stages, stages_to_run
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ytfactory.incremental.change_detector import ChangeDetector
from ytfactory.incremental.deps import (
    FORCE_FLAG_TO_STAGE,
    PIPELINE_STAGES,
    downstream_stages,
    stages_to_run,
)
from ytfactory.incremental.engine import IncrementalBuildEngine
from ytfactory.incremental.manifest import PipelineManifest
from ytfactory.incremental.models import ChangeReport, SceneState
from ytfactory.incremental.reporter import IncrementalReporter
from ytfactory.incremental.scene_workspace import SceneWorkspace


# ── Helpers ───────────────────────────────────────────────────────────────────


def _write_file(path: Path, content: str = "data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_scene_plan(project_dir: Path, n: int = 3) -> Path:
    plan = {
        "scenes": [
            {
                "index": i + 1,
                "title": f"Scene {i + 1}",
                "narration": f"Narration for scene {i + 1}.",
                "duration_seconds": 10,
                "animation": "zoom_in",
            }
            for i in range(n)
        ]
    }
    p = project_dir / "scenes" / "scene-plan.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plan), encoding="utf-8")
    return p


# ── PipelineManifest ──────────────────────────────────────────────────────────


class TestPipelineManifest:
    def test_record_and_checksum(self, tmp_path):
        f = _write_file(tmp_path / "research" / "research.md", "content")
        manifest = PipelineManifest(tmp_path)
        manifest.record("research/research.md", "research")
        entry = manifest.get("research/research.md")
        assert entry is not None
        assert entry.stage == "research"
        assert len(entry.checksum) == 16  # first 16 hex chars of sha256

    def test_is_changed_when_content_modified(self, tmp_path):
        f = _write_file(tmp_path / "script" / "script.md", "original")
        manifest = PipelineManifest(tmp_path)
        manifest.record("script/script.md", "script")
        manifest.save()

        # Modify file
        f.write_text("modified", encoding="utf-8")
        manifest2 = PipelineManifest(tmp_path)
        assert manifest2.is_changed("script/script.md") is True

    def test_is_changed_returns_false_when_unchanged(self, tmp_path):
        _write_file(tmp_path / "script" / "script.md", "stable")
        manifest = PipelineManifest(tmp_path)
        manifest.record("script/script.md", "script")
        manifest.save()

        manifest2 = PipelineManifest(tmp_path)
        assert manifest2.is_changed("script/script.md") is False

    def test_is_missing_when_file_deleted(self, tmp_path):
        f = _write_file(tmp_path / "script" / "script.md", "data")
        manifest = PipelineManifest(tmp_path)
        manifest.record("script/script.md", "script")
        manifest.save()

        f.unlink()
        manifest2 = PipelineManifest(tmp_path)
        assert manifest2.is_missing("script/script.md") is True

    def test_get_returns_none_for_untracked(self, tmp_path):
        manifest = PipelineManifest(tmp_path)
        assert manifest.get("nope/nonexistent.md") is None

    def test_save_and_reload(self, tmp_path):
        _write_file(tmp_path / "research" / "research.md", "hello")
        manifest = PipelineManifest(tmp_path)
        manifest.record("research/research.md", "research")
        manifest.save()

        manifest2 = PipelineManifest(tmp_path)
        entry = manifest2.get("research/research.md")
        assert entry is not None
        assert entry.stage == "research"

    def test_entries_property(self, tmp_path):
        _write_file(tmp_path / "research" / "research.md")
        _write_file(tmp_path / "script" / "script.md")
        manifest = PipelineManifest(tmp_path)
        manifest.record("research/research.md", "research")
        manifest.record("script/script.md", "script")
        manifest.save()

        manifest2 = PipelineManifest(tmp_path)
        assert "research/research.md" in manifest2.entries
        assert "script/script.md" in manifest2.entries


# ── ChangeDetector ────────────────────────────────────────────────────────────


class TestChangeDetector:
    def test_new_file_detected(self, tmp_path):
        _write_file(tmp_path / "script" / "script.md", "x")
        manifest = PipelineManifest(tmp_path)
        detector = ChangeDetector(tmp_path, manifest)
        report = detector.detect()
        assert "script/script.md" in report.new
        assert "script" in report.invalidated_stages

    def test_changed_file_detected(self, tmp_path):
        f = _write_file(tmp_path / "script" / "script.md", "original")
        manifest = PipelineManifest(tmp_path)
        manifest.record("script/script.md", "script")
        manifest.save()

        f.write_text("modified", encoding="utf-8")
        manifest2 = PipelineManifest(tmp_path)
        detector = ChangeDetector(tmp_path, manifest2)
        report = detector.detect()
        assert "script/script.md" in report.changed
        assert "script" in report.invalidated_stages

    def test_unchanged_file_not_flagged(self, tmp_path):
        _write_file(tmp_path / "script" / "script.md", "stable")
        manifest = PipelineManifest(tmp_path)
        manifest.record("script/script.md", "script")
        manifest.save()

        manifest2 = PipelineManifest(tmp_path)
        detector = ChangeDetector(tmp_path, manifest2)
        report = detector.detect()
        assert "script/script.md" not in report.changed
        assert "script/script.md" not in report.new

    def test_force_stages_invalidates_stage(self, tmp_path):
        manifest = PipelineManifest(tmp_path)
        detector = ChangeDetector(tmp_path, manifest)
        report = detector.detect(force_stages={"images"})
        assert "images" in report.invalidated_stages
        # downstream of images: voice is NOT downstream but video is
        assert "video" in report.invalidated_stages

    def test_scene_filter_scopes_glob_scan(self, tmp_path):
        _write_file(tmp_path / "images" / "scene-001.png", "img1")
        _write_file(tmp_path / "images" / "scene-002.png", "img2")
        manifest = PipelineManifest(tmp_path)
        detector = ChangeDetector(tmp_path, manifest)
        report = detector.detect(scene_filter=1)
        # Only scene-001 should appear (new); scene-002 ignored
        assert any("scene-001" in p for p in report.new)
        assert not any("scene-002" in p for p in report.new)

    def test_downstream_propagation_from_script(self, tmp_path):
        _write_file(tmp_path / "script" / "script.md", "new")
        manifest = PipelineManifest(tmp_path)
        detector = ChangeDetector(tmp_path, manifest)
        report = detector.detect()
        # script is upstream of scenes, which is upstream of images/voice/captions/video/review/publish
        assert "script" in report.invalidated_stages
        assert "scenes" in report.invalidated_stages
        assert "images" in report.invalidated_stages
        assert "video" in report.invalidated_stages
        assert "publish" in report.invalidated_stages

    def test_missing_assets(self, tmp_path):
        f = _write_file(tmp_path / "script" / "script.md", "data")
        manifest = PipelineManifest(tmp_path)
        manifest.record("script/script.md", "script")
        manifest.save()
        f.unlink()

        manifest2 = PipelineManifest(tmp_path)
        detector = ChangeDetector(tmp_path, manifest2)
        missing = detector.missing_assets("script")
        assert "script/script.md" in missing

    def test_stage_is_complete_true(self, tmp_path):
        _write_file(tmp_path / "script" / "script.md")
        manifest = PipelineManifest(tmp_path)
        manifest.record("script/script.md", "script")
        manifest.save()
        manifest2 = PipelineManifest(tmp_path)
        detector = ChangeDetector(tmp_path, manifest2)
        assert detector.stage_is_complete("script") is True

    def test_stage_is_complete_false_when_missing(self, tmp_path):
        f = _write_file(tmp_path / "script" / "script.md")
        manifest = PipelineManifest(tmp_path)
        manifest.record("script/script.md", "script")
        manifest.save()
        f.unlink()
        manifest2 = PipelineManifest(tmp_path)
        detector = ChangeDetector(tmp_path, manifest2)
        assert detector.stage_is_complete("script") is False

    def test_stage_is_complete_false_when_no_entries(self, tmp_path):
        manifest = PipelineManifest(tmp_path)
        detector = ChangeDetector(tmp_path, manifest)
        assert detector.stage_is_complete("script") is False


# ── SceneWorkspace ────────────────────────────────────────────────────────────


class TestSceneWorkspace:
    def test_default_state_is_draft(self, tmp_path):
        ws = SceneWorkspace(tmp_path)
        assert ws.get_state(1) == SceneState.DRAFT

    def test_set_and_get_state(self, tmp_path):
        ws = SceneWorkspace(tmp_path)
        ws.set_state(1, SceneState.APPROVED)
        assert ws.get_state(1) == SceneState.APPROVED

    def test_persistence(self, tmp_path):
        ws = SceneWorkspace(tmp_path)
        ws.set_state(2, SceneState.NEEDS_REVIEW)
        ws2 = SceneWorkspace(tmp_path)
        assert ws2.get_state(2) == SceneState.NEEDS_REVIEW

    def test_locked_guard_prevents_needs_revision(self, tmp_path):
        ws = SceneWorkspace(tmp_path)
        ws.set_state(1, SceneState.LOCKED)
        ws.mark_needs_revision(1, notes="failed")
        assert ws.get_state(1) == SceneState.LOCKED  # still locked

    def test_is_locked(self, tmp_path):
        ws = SceneWorkspace(tmp_path)
        ws.set_state(3, SceneState.LOCKED)
        assert ws.is_locked(3) is True
        assert ws.is_locked(4) is False

    def test_mark_needs_review_advances_draft(self, tmp_path):
        ws = SceneWorkspace(tmp_path)
        ws.set_state(1, SceneState.DRAFT)
        ws.mark_needs_review(1)
        assert ws.get_state(1) == SceneState.NEEDS_REVIEW

    def test_mark_needs_review_does_not_downgrade_approved(self, tmp_path):
        ws = SceneWorkspace(tmp_path)
        ws.set_state(1, SceneState.APPROVED)
        ws.mark_needs_review(1)
        assert ws.get_state(1) == SceneState.APPROVED  # unchanged

    def test_initialize_scenes(self, tmp_path):
        ws = SceneWorkspace(tmp_path)
        ws.initialize_scenes([1, 2, 3])
        assert ws.get_state(1) == SceneState.DRAFT
        assert ws.get_state(3) == SceneState.DRAFT

    def test_initialize_scenes_does_not_overwrite_existing(self, tmp_path):
        ws = SceneWorkspace(tmp_path)
        ws.set_state(1, SceneState.APPROVED)
        ws.initialize_scenes([1, 2])
        assert ws.get_state(1) == SceneState.APPROVED  # unchanged

    def test_all_states(self, tmp_path):
        ws = SceneWorkspace(tmp_path)
        ws.set_state(1, SceneState.DRAFT)
        ws.set_state(2, SceneState.LOCKED)
        states = ws.all_states()
        assert states[1] == SceneState.DRAFT
        assert states[2] == SceneState.LOCKED

    def test_get_notes(self, tmp_path):
        ws = SceneWorkspace(tmp_path)
        ws.set_state(1, SceneState.NEEDS_REVISION, notes="bad audio")
        assert ws.get_notes(1) == "bad audio"

    def test_mark_needs_revision_stores_notes(self, tmp_path):
        ws = SceneWorkspace(tmp_path)
        ws.mark_needs_revision(5, notes="blurry image")
        assert ws.get_state(5) == SceneState.NEEDS_REVISION
        assert "blurry" in ws.get_notes(5)


# ── deps ─────────────────────────────────────────────────────────────────────


class TestDeps:
    def test_downstream_stages_from_script(self):
        result = downstream_stages({"script"})
        assert "scenes" in result
        assert "images" in result
        assert "video" in result
        assert "publish" in result
        assert "script" not in result  # not in its own downstream

    def test_downstream_stages_from_images(self):
        result = downstream_stages({"images"})
        assert "video" in result
        assert "review" in result
        assert "voice" not in result  # images is not upstream of voice

    def test_downstream_stages_from_voice(self):
        result = downstream_stages({"voice"})
        assert "captions" in result
        assert "video" in result

    def test_downstream_stages_empty(self):
        result = downstream_stages({"publish"})
        assert result == set()

    def test_stages_to_run_ordering(self):
        invalidated = {"video", "scenes", "captions"}
        ordered = stages_to_run(invalidated)
        # Must respect PIPELINE_STAGES order
        stage_indices = {s: PIPELINE_STAGES.index(s) for s in ordered}
        assert list(stage_indices.values()) == sorted(stage_indices.values())

    def test_force_flag_to_stage_mapping(self):
        assert FORCE_FLAG_TO_STAGE["images"] == "images"
        assert FORCE_FLAG_TO_STAGE["narration"] == "voice"
        assert FORCE_FLAG_TO_STAGE["subtitles"] == "captions"
        assert FORCE_FLAG_TO_STAGE["bgm"] == "video"


# ── IncrementalBuildEngine ────────────────────────────────────────────────────


class TestIncrementalBuildEngine:
    def test_needs_run_for_invalidated_stage(self, tmp_path):
        _write_file(tmp_path / "script" / "script.md", "new")
        engine = IncrementalBuildEngine(tmp_path)
        report = engine.analyze()
        # script appeared new → needs run
        assert engine.needs_run("script", report) is True

    def test_needs_run_false_for_unchanged(self, tmp_path):
        f = _write_file(tmp_path / "research" / "research.md", "done")
        engine = IncrementalBuildEngine(tmp_path)
        engine.manifest.record("research/research.md", "research")
        engine.manifest.save()

        engine2 = IncrementalBuildEngine(tmp_path)
        report = engine2.analyze()
        assert engine2.needs_run("research", report) is False

    def test_force_stage_marks_as_invalidated(self, tmp_path):
        engine = IncrementalBuildEngine(tmp_path)
        report = engine.analyze(force_stages={"images"})
        assert engine.needs_run("images", report) is True
        assert engine.needs_run("video", report) is True  # downstream

    def test_record_stage_outputs_captures_files(self, tmp_path):
        _write_file(tmp_path / "script" / "script.md", "text")
        engine = IncrementalBuildEngine(tmp_path)
        engine.record_stage_outputs("script")
        entry = engine.manifest.get("script/script.md")
        assert entry is not None
        assert entry.stage == "script"

    def test_is_locked_delegates_to_workspace(self, tmp_path):
        engine = IncrementalBuildEngine(tmp_path)
        engine.workspace.set_state(7, SceneState.LOCKED)
        assert engine.is_locked(7) is True
        assert engine.is_locked(8) is False

    def test_locked_scenes_list(self, tmp_path):
        engine = IncrementalBuildEngine(tmp_path)
        engine.workspace.set_state(3, SceneState.LOCKED)
        engine.workspace.set_state(5, SceneState.LOCKED)
        locked = engine.locked_scenes()
        assert 3 in locked
        assert 5 in locked
        assert 1 not in locked

    def test_initialize_workspace_from_scene_plan(self, tmp_path):
        _make_scene_plan(tmp_path, n=4)
        engine = IncrementalBuildEngine(tmp_path)
        engine.initialize_workspace()
        states = engine.workspace.all_states()
        assert set(states.keys()) == {1, 2, 3, 4}
        assert all(s == SceneState.DRAFT for s in states.values())

    def test_initialize_workspace_no_plan(self, tmp_path):
        engine = IncrementalBuildEngine(tmp_path)
        engine.initialize_workspace()  # should not raise
        assert engine.workspace.all_states() == {}

    def test_write_scene_review_md(self, tmp_path):
        _make_scene_plan(tmp_path, n=2)
        engine = IncrementalBuildEngine(tmp_path)
        engine.initialize_workspace()
        out = engine.write_scene_review_md()
        assert out.exists()
        content = out.read_text()
        assert "Scene 001" in content
        assert "Scene 002" in content

    def test_analyze_with_scene_filter(self, tmp_path):
        _write_file(tmp_path / "images" / "scene-001.png", "img1")
        _write_file(tmp_path / "images" / "scene-002.png", "img2")
        engine = IncrementalBuildEngine(tmp_path)
        report = engine.analyze(scene_filter=1)
        # Only scene-001 should be in new
        assert any("001" in p for p in report.new)
        assert not any("002" in p for p in report.new)


# ── IncrementalReporter ───────────────────────────────────────────────────────


class TestIncrementalReporter:
    def test_write_scene_review_md_no_plan(self, tmp_path):
        ws = SceneWorkspace(tmp_path)
        manifest = PipelineManifest(tmp_path)
        reporter = IncrementalReporter()
        out = reporter.write_scene_review_md(tmp_path, ws, manifest)
        assert out.exists()
        assert "No scene plan found" in out.read_text()

    def test_write_scene_review_md_with_plan(self, tmp_path):
        _make_scene_plan(tmp_path, n=3)
        ws = SceneWorkspace(tmp_path)
        ws.initialize_scenes([1, 2, 3])
        ws.set_state(2, SceneState.APPROVED)
        manifest = PipelineManifest(tmp_path)
        reporter = IncrementalReporter()
        out = reporter.write_scene_review_md(tmp_path, ws, manifest)
        content = out.read_text()
        assert "Scene 001" in content
        assert "Scene 002" in content
        assert "approved" in content.lower() or "Approved" in content

    def test_write_scene_review_md_shows_asset_presence(self, tmp_path):
        _make_scene_plan(tmp_path, n=1)
        _write_file(tmp_path / "images" / "scene-001.png", "img")
        _write_file(tmp_path / "audio" / "scene-001.mp3", "aud")
        ws = SceneWorkspace(tmp_path)
        ws.initialize_scenes([1])
        manifest = PipelineManifest(tmp_path)
        reporter = IncrementalReporter()
        out = reporter.write_scene_review_md(tmp_path, ws, manifest)
        content = out.read_text()
        # Image and audio present → checkmarks
        assert "✓" in content or "✗" in content  # at least one asset check

    def test_print_change_report_does_not_raise(self, tmp_path, capsys):
        reporter = IncrementalReporter()
        report = ChangeReport(
            changed=["images/scene-001.png"],
            new=[],
            missing=[],
            invalidated_stages={"images", "video"},
        )
        # Should not raise
        reporter.print_change_report(report, reused_stages={"research"}, rebuilt_stages={"images"})


# ── ChangeReport dataclass ────────────────────────────────────────────────────


class TestChangeReport:
    def test_has_changes_true_when_changed(self):
        report = ChangeReport(changed=["a.md"])
        assert report.has_changes is True

    def test_has_changes_true_when_new(self):
        report = ChangeReport(new=["b.md"])
        assert report.has_changes is True

    def test_has_changes_false_when_empty(self):
        report = ChangeReport()
        assert report.has_changes is False

    def test_invalidated_stages_default_empty(self):
        report = ChangeReport()
        assert report.invalidated_stages == set()


# ── BuildPipeline.run_incremental — script stage (MW-005) ─────────────────────


def _make_project_json(project_dir: Path, title: str = "Test Topic") -> None:
    import json
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project.json").write_text(
        json.dumps({"id": project_dir.name, "title": title, "stages": {}})
    )


class TestBuildPipelineIncrementalScript:
    """Verify run_incremental() runs/skips the script stage correctly (MW-005)."""

    def _build_pipeline_with_mocks(self, monkeypatch):
        """Return a BuildPipeline whose sub-pipelines are all mocked."""
        from unittest.mock import MagicMock, patch

        # Patch each sub-pipeline class so __init__ never touches real APIs
        patches = [
            patch("ytfactory.build.pipeline.Settings"),
            patch("ytfactory.build.pipeline.ScriptEnhancerPipeline"),
            patch("ytfactory.build.pipeline.ScenePipeline"),
            patch("ytfactory.build.pipeline.ImagePipeline"),
            patch("ytfactory.build.pipeline.VoicePipeline"),
            patch("ytfactory.build.pipeline.CaptionPipeline"),
            patch("ytfactory.build.pipeline.VideoPipeline"),
            patch("ytfactory.build.pipeline.CTAPipeline"),
            patch("ytfactory.build.pipeline.ReviewPipeline"),
            patch("ytfactory.build.pipeline.PublishPipeline"),
        ]
        for p in patches:
            p.start()

        from ytfactory.build.pipeline import BuildPipeline
        bp = BuildPipeline()

        for p in patches:
            p.stop()

        # Replace all sub-pipelines with fresh MagicMocks
        bp.script_enhancer = MagicMock()
        bp.scenes = MagicMock()
        bp.images = MagicMock()
        bp.voice = MagicMock()
        bp.captions = MagicMock()
        bp.video = MagicMock()
        bp.cta = MagicMock()
        bp.review = MagicMock()
        bp.publish = MagicMock()
        bp.review.run.return_value = MagicMock(verdict="PASS")
        return bp

    def test_script_stage_runs_when_dirty(self, tmp_path, monkeypatch):
        project_id = "proj-001"
        project_dir = tmp_path / project_id
        _make_project_json(project_dir, title="My Topic")
        (project_dir / "script").mkdir(parents=True)
        (project_dir / "script" / "script.md").write_text("# Script")
        # No manifest entry → engine sees script.md as new → stage is dirty

        monkeypatch.setattr("ytfactory.build.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr(
            "ytfactory.build.pipeline.ProjectRepository",
            lambda: type("R", (), {"load": lambda self, pid: type("P", (), {"title": "My Topic"})()})(),
        )

        bp = self._build_pipeline_with_mocks(monkeypatch)
        bp.run_incremental(project_id)

        bp.script_enhancer.run.assert_called_once_with(project_id, topic="My Topic")

    def test_script_stage_skipped_when_clean(self, tmp_path, monkeypatch):
        project_id = "proj-002"
        project_dir = tmp_path / project_id
        _make_project_json(project_dir, title="My Topic")
        (project_dir / "script").mkdir(parents=True)
        script_file = project_dir / "script" / "script.md"
        script_file.write_text("# Script")

        # Record script.md in the manifest so the engine sees it as clean
        from ytfactory.incremental.manifest import PipelineManifest
        manifest = PipelineManifest(project_dir)
        manifest.record("script/script.md", "script")
        manifest.save()

        monkeypatch.setattr("ytfactory.build.pipeline.WORKSPACE_DIR", str(tmp_path))

        bp = self._build_pipeline_with_mocks(monkeypatch)
        bp.run_incremental(project_id)

        bp.script_enhancer.run.assert_not_called()
