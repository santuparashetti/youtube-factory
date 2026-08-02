"""Tests for src/ytfactory/two_phase/ — Phase 1 (prep) and Phase 2 (resume).

Coverage:
  - TwoPhasePipeline._write_image_prompts_manifest
  - TwoPhasePipeline._write_phase1_report
  - TwoPhasePipeline._validate_images
  - BuildPipeline.run_prep_only delegates correctly
  - BuildPipeline.run_resume delegates correctly
  - agents/runner.run_pipeline with pipeline_mode="prep_only"
  - agents/runner.run_pipeline with pipeline_mode="resume"
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_project_dir(tmp_path: Path, project_id: str) -> Path:
    """Create a minimal project directory with project.json and scenes."""
    project_dir = tmp_path / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project.json").write_text(
        json.dumps({"id": project_id, "title": "Test Topic"}), encoding="utf-8"
    )
    (project_dir / "scenes").mkdir(parents=True, exist_ok=True)
    (project_dir / "images").mkdir(parents=True, exist_ok=True)
    (project_dir / "audio").mkdir(parents=True, exist_ok=True)
    (project_dir / "subtitles").mkdir(parents=True, exist_ok=True)
    return project_dir


def _make_scene_plan(project_dir: Path, n: int = 3) -> Path:
    plan = {
        "scenes": [
            {
                "index": i + 1,
                "title": f"Scene {i + 1}",
                "narration": f"Narration for scene {i + 1}.",
                "duration_seconds": 10,
                "visual_prompt": f"A cinematic scene about scene {i + 1}.",
                "shot_type": "medium_shot",
                "motion_type": "zoom_in" if i % 2 == 0 else "pan_left",
                "scene_type": "generated_image",
            }
            for i in range(n)
        ]
    }
    p = project_dir / "scenes" / "scene-plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    return p


# ── TwoPhasePipeline unit tests ───────────────────────────────────────────────


class TestTwoPhasePipeline:
    def test_write_manifest(self, tmp_path, monkeypatch):
        from ytfactory.two_phase.pipeline import TwoPhasePipeline

        monkeypatch.setattr("ytfactory.two_phase.pipeline.WORKSPACE_DIR", str(tmp_path))

        project_id = "test-proj"
        project_dir = _make_project_dir(tmp_path, project_id)
        _make_scene_plan(project_dir, n=3)

        tp = TwoPhasePipeline()
        manifest_path = tp._write_image_prompts_manifest(project_id)

        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["project_id"] == project_id
        assert len(data["scenes"]) == 3
        assert data["scenes"][0]["expected_filename"] == "scene-001.png"
        assert data["scenes"][0]["shot_type"] == "medium_shot"
        assert data["scenes"][0]["motion_type"] == "zoom_in"

    def test_write_manifest_missing_scene_plan(self, tmp_path, monkeypatch):
        from ytfactory.two_phase.pipeline import TwoPhasePipeline

        monkeypatch.setattr("ytfactory.two_phase.pipeline.WORKSPACE_DIR", str(tmp_path))

        project_id = "test-proj"
        _make_project_dir(tmp_path, project_id)

        tp = TwoPhasePipeline()
        with pytest.raises(FileNotFoundError):
            tp._write_image_prompts_manifest(project_id)

    def test_write_phase1_report(self, tmp_path, monkeypatch):
        from ytfactory.two_phase.pipeline import TwoPhasePipeline

        monkeypatch.setattr("ytfactory.two_phase.pipeline.WORKSPACE_DIR", str(tmp_path))

        project_id = "test-proj"
        project_dir = _make_project_dir(tmp_path, project_id)
        _make_scene_plan(project_dir, n=3)
        (project_dir / "audio").mkdir(parents=True, exist_ok=True)
        (project_dir / "audio" / "scene-001.mp3").write_text("audio", encoding="utf-8")
        (project_dir / "audio" / "scene-002.mp3").write_text("audio", encoding="utf-8")
        (project_dir / "audio" / "scene-003.mp3").write_text("audio", encoding="utf-8")
        (project_dir / "subtitles").mkdir(parents=True, exist_ok=True)
        for i in range(1, 4):
            (project_dir / "subtitles" / f"scene-{i:03d}.srt").write_text(
                "subtitle", encoding="utf-8"
            )

        tp = TwoPhasePipeline()
        manifest_path = project_dir / "image_prompts_manifest.json"
        manifest_path.write_text("{}", encoding="utf-8")
        report_path = tp._write_phase1_report(project_id, manifest_path)

        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        assert "Phase 1 Report" in content
        assert project_id in content
        assert "3" in content  # scene count

    def test_validate_images_all_present(self, tmp_path, monkeypatch):
        from ytfactory.two_phase.pipeline import TwoPhasePipeline

        monkeypatch.setattr("ytfactory.two_phase.pipeline.WORKSPACE_DIR", str(tmp_path))

        project_id = "test-proj"
        project_dir = _make_project_dir(tmp_path, project_id)
        _make_scene_plan(project_dir, n=3)

        # Write manifest
        tp = TwoPhasePipeline()
        tp._write_image_prompts_manifest(project_id)

        # Place all expected images
        for i in range(1, 4):
            (project_dir / "images" / f"scene-{i:03d}.png").write_text(
                "png", encoding="utf-8"
            )

        missing = tp._validate_images(project_id)
        assert missing == []

    def test_validate_images_missing(self, tmp_path, monkeypatch):
        from ytfactory.two_phase.pipeline import TwoPhasePipeline

        monkeypatch.setattr("ytfactory.two_phase.pipeline.WORKSPACE_DIR", str(tmp_path))

        project_id = "test-proj"
        project_dir = _make_project_dir(tmp_path, project_id)
        _make_scene_plan(project_dir, n=3)

        tp = TwoPhasePipeline()
        tp._write_image_prompts_manifest(project_id)

        # Only place 2 of 3 images
        (project_dir / "images" / "scene-001.png").write_text("png", encoding="utf-8")
        (project_dir / "images" / "scene-002.png").write_text("png", encoding="utf-8")

        missing = tp._validate_images(project_id)
        assert len(missing) == 1
        assert missing[0] == (3, "scene-003.png")

    def test_validate_images_missing_manifest(self, tmp_path, monkeypatch):
        from ytfactory.two_phase.pipeline import TwoPhasePipeline

        monkeypatch.setattr("ytfactory.two_phase.pipeline.WORKSPACE_DIR", str(tmp_path))

        project_id = "test-proj"
        _make_project_dir(tmp_path, project_id)

        tp = TwoPhasePipeline()
        with pytest.raises(FileNotFoundError, match="image_prompts_manifest.json"):
            tp._validate_images(project_id)


# ── BuildPipeline two-phase delegation tests ──────────────────────────────────


class TestBuildPipelineTwoPhase:
    def _mock_build_pipeline(self, monkeypatch):
        patches = [
            patch("ytfactory.build.pipeline.Settings"),
            patch("ytfactory.build.pipeline.LightNormalizationPipeline"),
            patch("ytfactory.build.pipeline.DocumentaryScriptEnhancerPipeline"),
            patch("ytfactory.build.pipeline.ScriptEnhancerPipeline"),
            patch("ytfactory.build.pipeline.StructuralRetentionPipeline"),
            patch("ytfactory.build.pipeline.EditorialQAPipeline"),
            patch("ytfactory.build.pipeline.ComposerPipeline"),
            patch("ytfactory.build.pipeline.ScenePipeline"),
            patch("ytfactory.build.pipeline.ImagePipeline"),
            patch("ytfactory.build.pipeline.VoicePipeline"),
            patch("ytfactory.build.pipeline.CaptionPipeline"),
            patch("ytfactory.build.pipeline.VideoPipeline"),
            patch("ytfactory.build.pipeline.CTAPipeline"),
            patch("ytfactory.build.pipeline.ReviewPipeline"),
            patch("ytfactory.build.pipeline.PublishPipeline"),
            patch("ytfactory.build.pipeline.TwoPhasePipeline"),
        ]
        for p in patches:
            p.start()

        from ytfactory.build.pipeline import BuildPipeline
        bp = BuildPipeline()

        for p in patches:
            p.stop()

        bp.light_normalization = MagicMock()
        bp.documentary_script_enhancer = MagicMock()
        bp.script_enhancer = bp.documentary_script_enhancer
        bp.structural_retention = MagicMock()
        bp.editorial_qa = MagicMock()
        bp.composer = MagicMock()
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

    def test_run_prep_only_delegates(self, tmp_path, monkeypatch):
        project_id = "proj-001"
        project_dir = _make_project_dir(tmp_path, project_id)
        _make_scene_plan(project_dir, n=2)
        monkeypatch.setattr("ytfactory.build.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr(
            "ytfactory.build.pipeline.ProjectRepository",
            lambda: type("R", (), {"load": lambda self, pid: type("P", (), {"title": "T"})()})(),
        )

        bp = self._mock_build_pipeline(monkeypatch)
        two_phase_mock = MagicMock()
        monkeypatch.setattr(
            "ytfactory.build.pipeline.TwoPhasePipeline", lambda: two_phase_mock
        )

        bp.run_prep_only(project_id, style="spiritual", target_minutes=8)

        two_phase_mock.run_prep_only.assert_called_once_with(
            project_id=project_id, style="spiritual", target_minutes=8, auto=False
        )

    def test_run_resume_delegates(self, tmp_path, monkeypatch):
        project_id = "proj-001"
        project_dir = _make_project_dir(tmp_path, project_id)
        _make_scene_plan(project_dir, n=2)
        monkeypatch.setattr("ytfactory.build.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr(
            "ytfactory.build.pipeline.ProjectRepository",
            lambda: type("R", (), {"load": lambda self, pid: type("P", (), {"title": "T"})()})(),
        )

        bp = self._mock_build_pipeline(monkeypatch)
        two_phase_mock = MagicMock()
        monkeypatch.setattr(
            "ytfactory.build.pipeline.TwoPhasePipeline", lambda: two_phase_mock
        )

        bp.run_resume(project_id)

        two_phase_mock.run_resume.assert_called_once_with(project_id=project_id, overlay=True)


# ── agents/runner pipeline_mode tests ─────────────────────────────────────────


class TestRunnerPipelineMode:
    def test_resume_requires_project_id(self):
        from ytfactory.agents.runner import run_pipeline

        with pytest.raises(ValueError, match="--phase=resume requires"):
            run_pipeline("Topic", pipeline_mode="resume")

    @patch("ytfactory.two_phase.pipeline.TwoPhasePipeline")
    @patch("ytfactory.agents.runner.graph")
    @patch("ytfactory.agents.runner.CreatePipeline")
    @patch("ytfactory.storage.project_repository.ProjectRepository")
    def test_prep_only_sets_skip_images(
        self, mock_repo_cls, mock_create_cls, mock_graph, mock_two_phase_cls, tmp_path, monkeypatch
    ):
        from ytfactory.agents.runner import run_pipeline

        project_id = "proj-001"
        project_dir = tmp_path / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "project.json").write_text(
            json.dumps({"id": project_id, "title": "Topic"}), encoding="utf-8"
        )
        (project_dir / "script").mkdir(parents=True, exist_ok=True)
        (project_dir / "script" / "script.md").write_text("Test script.", encoding="utf-8")
        monkeypatch.setattr("ytfactory.agents.runner.WORKSPACE_DIR", str(tmp_path))

        mock_project = MagicMock()
        mock_project.id = project_id
        mock_create_cls.return_value.run.return_value = mock_project
        mock_repo_cls.return_value.load.return_value = mock_project

        mock_graph.invoke.return_value = {
            "project_id": project_id,
            "scene_plan": [],
            "stage_errors": [],
        }
        mock_two_phase = MagicMock()
        mock_two_phase_cls.return_value = mock_two_phase

        run_pipeline(
            "Topic",
            project_id=project_id,
            pipeline_mode="prep_only",
        )

        call_args = mock_graph.invoke.call_args
        state = call_args[0][0]
        assert state["skip_images"] is True
        assert state["skip_thumbnail"] is False
        mock_two_phase._write_image_prompts_manifest.assert_called_once_with(project_id)
        mock_two_phase._write_phase1_report.assert_called_once()

    @patch("ytfactory.two_phase.pipeline.TwoPhasePipeline")
    @patch("ytfactory.agents.runner.graph")
    @patch("ytfactory.agents.runner.CreatePipeline")
    @patch("ytfactory.storage.project_repository.ProjectRepository")
    def test_resume_sets_skip_thumbnail(
        self, mock_repo_cls, mock_create_cls, mock_graph, mock_two_phase_cls, tmp_path, monkeypatch
    ):
        from ytfactory.agents.runner import run_pipeline

        project_id = "proj-001"
        project_dir = tmp_path / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "project.json").write_text(
            json.dumps({"id": project_id, "title": "Topic"}), encoding="utf-8"
        )
        (project_dir / "script").mkdir(parents=True, exist_ok=True)
        (project_dir / "script" / "script.md").write_text("Test script.", encoding="utf-8")
        (project_dir / "images").mkdir(parents=True, exist_ok=True)
        (project_dir / "image_prompts_manifest.json").write_text(
            json.dumps({
                "project_id": project_id,
                "scenes": [
                    {"scene_id": 1, "expected_filename": "scene-001.png"},
                ],
            }),
            encoding="utf-8",
        )
        (project_dir / "images" / "scene-001.png").write_text("png", encoding="utf-8")
        monkeypatch.setattr("ytfactory.agents.runner.WORKSPACE_DIR", str(tmp_path))

        mock_project = MagicMock()
        mock_project.id = project_id
        mock_repo_cls.return_value.load.return_value = mock_project

        mock_graph.invoke.return_value = {
            "project_id": project_id,
            "scene_plan": [],
            "stage_errors": [],
        }
        mock_two_phase = MagicMock()
        mock_two_phase._validate_images.return_value = []
        mock_two_phase_cls.return_value = mock_two_phase

        run_pipeline(
            "Topic",
            project_id=project_id,
            pipeline_mode="resume",
        )

        call_args = mock_graph.invoke.call_args
        state = call_args[0][0]
        assert state["skip_images"] is False
        assert state["skip_thumbnail"] is True
        mock_two_phase._validate_images.assert_called_once_with(project_id)

    @patch("ytfactory.agents.runner.graph")
    @patch("ytfactory.agents.runner.CreatePipeline")
    @patch("ytfactory.storage.project_repository.ProjectRepository")
    def test_resume_fails_on_missing_image(
        self, mock_repo_cls, mock_create_cls, mock_graph, tmp_path, monkeypatch
    ):
        from ytfactory.agents.runner import run_pipeline

        project_id = "proj-001"
        project_dir = tmp_path / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "project.json").write_text(
            json.dumps({"id": project_id, "title": "Topic"}), encoding="utf-8"
        )
        (project_dir / "script").mkdir(parents=True, exist_ok=True)
        (project_dir / "script" / "script.md").write_text("Test script.", encoding="utf-8")
        (project_dir / "images").mkdir(parents=True, exist_ok=True)
        (project_dir / "image_prompts_manifest.json").write_text(
            json.dumps({
                "project_id": project_id,
                "scenes": [
                    {"scene_id": 1, "expected_filename": "scene-001.png"},
                ],
            }),
            encoding="utf-8",
        )
        # No image file placed
        monkeypatch.setattr("ytfactory.agents.runner.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.two_phase.pipeline.WORKSPACE_DIR", str(tmp_path))

        mock_project = MagicMock()
        mock_project.id = project_id
        mock_repo_cls.return_value.load.return_value = mock_project

        with pytest.raises(RuntimeError, match="missing images"):
            run_pipeline(
                "Topic",
                project_id=project_id,
                pipeline_mode="resume",
            )

        mock_graph.invoke.assert_not_called()


# ── Phase 1 resume-skip: existing script.md skips regeneration ──────────────


class TestPhase1ResumeSkip:
    """If a finalized script.md already exists, TwoPhasePipeline.run_prep_only
    skips composer / QA regeneration and resumes straight at the review
    checkpoint (which itself hash-guards for hand-edits)."""

    def _run(self, tmp_path, monkeypatch, script_exists: bool):
        from ytfactory.two_phase.pipeline import TwoPhasePipeline

        project_id = "proj-resume"
        project_dir = _make_project_dir(tmp_path, project_id)
        _make_scene_plan(project_dir, n=2)
        (project_dir / "script").mkdir(parents=True, exist_ok=True)
        if script_exists:
            (project_dir / "script" / "script.md").write_text(
                "Existing finalized script.", encoding="utf-8"
            )

        monkeypatch.setattr("ytfactory.two_phase.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr(
            "ytfactory.two_phase.pipeline.ProjectRepository",
            lambda: type("R", (), {"load": lambda self, pid: type("P", (), {"title": "T"})()})(),
        )

        mock_bp = MagicMock()

        def _fake_compose(*args, **kwargs):
            (project_dir / "script" / "script.md").write_text(
                "Freshly generated script.", encoding="utf-8"
            )

        mock_bp.composer.run.side_effect = _fake_compose
        monkeypatch.setattr("ytfactory.build.pipeline.BuildPipeline", lambda: mock_bp)
        # Stub the A/B selection wrapper so tests stay non-interactive and
        # composer.run() is called exactly once (matching pre-A/B assertions).
        monkeypatch.setattr(
            "ytfactory.two_phase.pipeline.run_composer_with_ab_selection",
            lambda composer, project_id: composer.run(project_id),
        )

        mock_gate = MagicMock()
        mock_gate.run.side_effect = lambda pid, text, auto_mode=False: text
        monkeypatch.setattr(
            "ytfactory.editorial_qa.review_gate.FinalScriptReviewGate",
            lambda settings: mock_gate,
        )

        tp = TwoPhasePipeline()
        tp.run_prep_only(project_id, auto=True)
        return mock_bp, mock_gate

    def test_existing_script_skips_regeneration(self, tmp_path, monkeypatch):
        mock_bp, mock_gate = self._run(tmp_path, monkeypatch, script_exists=True)
        mock_bp.light_normalization.run.assert_not_called()
        mock_bp.composer.run.assert_not_called()
        mock_bp.editorial_qa.run.assert_not_called()
        mock_gate.run.assert_called_once()
        assert mock_gate.run.call_args.args[1] == "Existing finalized script."

    def test_missing_script_runs_full_generation(self, tmp_path, monkeypatch):
        mock_bp, mock_gate = self._run(tmp_path, monkeypatch, script_exists=False)
        mock_bp.light_normalization.run.assert_called_once()
        mock_bp.composer.run.assert_called_once()
        mock_bp.editorial_qa.run.assert_called_once()
        mock_gate.run.assert_called_once()
        assert mock_gate.run.call_args.args[1] == "Freshly generated script."
