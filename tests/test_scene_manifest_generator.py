"""Tests for SceneManifestGenerator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ytfactory.publish.generators.scene_manifest import SceneManifestGenerator, _real_duration


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_scenes() -> list[dict]:
    return [
        {
            "index": 1,
            "title": "Opening",
            "narration": "The story begins here.",
            "duration_seconds": 8.0,
            "visual_prompt": "sunrise over mountains",
        },
        {
            "index": 2,
            "title": "The Journey",
            "narration": "And so the journey starts.",
            "duration_seconds": 12.0,
            "visual_prompt": "traveler on a road",
        },
    ]


def _write_project(tmp_path: Path, project_id: str) -> Path:
    proj_dir = tmp_path / project_id
    (proj_dir / "scenes").mkdir(parents=True)
    (proj_dir / "audio").mkdir(parents=True)
    (proj_dir / "images").mkdir(parents=True)
    (proj_dir / "publish").mkdir(parents=True)

    scene_plan = {"scenes": _make_scenes()}
    (proj_dir / "scenes" / "scene-plan.json").write_text(
        json.dumps(scene_plan), encoding="utf-8"
    )
    return proj_dir


# ── _real_duration ─────────────────────────────────────────────────────────────


class TestRealDuration:
    def test_returns_timing_last_end(self, tmp_path):
        proj_dir = tmp_path / "proj"
        (proj_dir / "audio").mkdir(parents=True)
        timing = [
            {"word": "hello", "start": 0.0, "end": 3.5},
            {"word": "world", "start": 3.5, "end": 7.2},
        ]
        (proj_dir / "audio" / "scene-001.timing.json").write_text(
            json.dumps(timing), encoding="utf-8"
        )
        scene = {"index": 1, "duration_seconds": 10.0}
        assert _real_duration(proj_dir, scene) == pytest.approx(7.2)

    def test_falls_back_when_timing_missing(self, tmp_path):
        proj_dir = tmp_path / "proj"
        (proj_dir / "audio").mkdir(parents=True)
        scene = {"index": 1, "duration_seconds": 15.0}
        assert _real_duration(proj_dir, scene) == pytest.approx(15.0)

    def test_falls_back_when_timing_empty(self, tmp_path):
        proj_dir = tmp_path / "proj"
        (proj_dir / "audio").mkdir(parents=True)
        (proj_dir / "audio" / "scene-002.timing.json").write_text("[]", encoding="utf-8")
        scene = {"index": 2, "duration_seconds": 9.0}
        assert _real_duration(proj_dir, scene) == pytest.approx(9.0)

    def test_falls_back_on_bad_json(self, tmp_path):
        proj_dir = tmp_path / "proj"
        (proj_dir / "audio").mkdir(parents=True)
        (proj_dir / "audio" / "scene-001.timing.json").write_text(
            "not json", encoding="utf-8"
        )
        scene = {"index": 1, "duration_seconds": 5.0}
        assert _real_duration(proj_dir, scene) == pytest.approx(5.0)


# ── SceneManifestGenerator ────────────────────────────────────────────────────


class TestSceneManifestGenerator:
    def test_writes_manifest_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ytfactory.publish.generators.scene_manifest.WORKSPACE_DIR", str(tmp_path)
        )
        monkeypatch.setattr(
            "ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path)
        )
        project_id = "test-proj"
        _write_project(tmp_path, project_id)

        SceneManifestGenerator().generate(project_id)

        out = tmp_path / project_id / "publish" / "scene-manifest.json"
        assert out.exists()

    def test_manifest_has_correct_fields(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ytfactory.publish.generators.scene_manifest.WORKSPACE_DIR", str(tmp_path)
        )
        monkeypatch.setattr(
            "ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path)
        )
        project_id = "test-proj"
        _write_project(tmp_path, project_id)

        entries = SceneManifestGenerator().generate(project_id)

        assert len(entries) == 2
        for e in entries:
            assert set(e.keys()) == {"image_path", "audio_path", "narration_text", "duration_seconds"}

    def test_narration_and_duration_correct(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ytfactory.publish.generators.scene_manifest.WORKSPACE_DIR", str(tmp_path)
        )
        monkeypatch.setattr(
            "ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path)
        )
        project_id = "test-proj"
        _write_project(tmp_path, project_id)

        entries = SceneManifestGenerator().generate(project_id)

        assert entries[0]["narration_text"] == "The story begins here."
        assert entries[0]["duration_seconds"] == pytest.approx(8.0)
        assert entries[1]["narration_text"] == "And so the journey starts."
        assert entries[1]["duration_seconds"] == pytest.approx(12.0)

    def test_paths_are_absolute(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ytfactory.publish.generators.scene_manifest.WORKSPACE_DIR", str(tmp_path)
        )
        monkeypatch.setattr(
            "ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path)
        )
        project_id = "test-proj"
        _write_project(tmp_path, project_id)

        entries = SceneManifestGenerator().generate(project_id)

        for e in entries:
            assert Path(e["image_path"]).is_absolute()
            assert Path(e["audio_path"]).is_absolute()

    def test_path_naming_matches_index(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ytfactory.publish.generators.scene_manifest.WORKSPACE_DIR", str(tmp_path)
        )
        monkeypatch.setattr(
            "ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path)
        )
        project_id = "test-proj"
        _write_project(tmp_path, project_id)

        entries = SceneManifestGenerator().generate(project_id)

        assert entries[0]["image_path"].endswith("scene-001.png")
        assert entries[0]["audio_path"].endswith("scene-001.mp3")
        assert entries[1]["image_path"].endswith("scene-002.png")
        assert entries[1]["audio_path"].endswith("scene-002.mp3")

    def test_uses_timing_duration_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ytfactory.publish.generators.scene_manifest.WORKSPACE_DIR", str(tmp_path)
        )
        monkeypatch.setattr(
            "ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path)
        )
        project_id = "test-proj"
        proj_dir = _write_project(tmp_path, project_id)
        timing = [{"word": "hello", "start": 0.0, "end": 11.3}]
        (proj_dir / "audio" / "scene-001.timing.json").write_text(
            json.dumps(timing), encoding="utf-8"
        )

        entries = SceneManifestGenerator().generate(project_id)

        # scene 1: real duration from timing; scene 2: declared (no timing file)
        assert entries[0]["duration_seconds"] == pytest.approx(11.3)
        assert entries[1]["duration_seconds"] == pytest.approx(12.0)

    def test_written_json_is_valid(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ytfactory.publish.generators.scene_manifest.WORKSPACE_DIR", str(tmp_path)
        )
        monkeypatch.setattr(
            "ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path)
        )
        project_id = "test-proj"
        _write_project(tmp_path, project_id)

        SceneManifestGenerator().generate(project_id)

        out = tmp_path / project_id / "publish" / "scene-manifest.json"
        parsed = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    def test_empty_scenes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ytfactory.publish.generators.scene_manifest.WORKSPACE_DIR", str(tmp_path)
        )
        monkeypatch.setattr(
            "ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path)
        )
        project_id = "empty-proj"
        proj_dir = tmp_path / project_id
        (proj_dir / "scenes").mkdir(parents=True)
        (proj_dir / "publish").mkdir(parents=True)
        (proj_dir / "scenes" / "scene-plan.json").write_text(
            json.dumps({"scenes": []}), encoding="utf-8"
        )

        entries = SceneManifestGenerator().generate(project_id)

        assert entries == []
        out = tmp_path / project_id / "publish" / "scene-manifest.json"
        assert json.loads(out.read_text()) == []
