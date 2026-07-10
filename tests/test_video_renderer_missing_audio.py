"""Regression tests — missing narration audio during video rendering.

Root cause of the original bug:
    audio_paths.get(index, "")  →  ""  →  Path("") == Path(".")
    Path(".").exists() == True  (current directory always exists)
    FFmpeg called with "-i ." → ".: Is a directory"

These tests verify that:
  1. Path("") == Path(".") trap is blocked by is_file() checks
  2. Per-scene rendering fails cleanly without invoking FFmpeg
  3. One missing-audio scene does not halt other scenes
  4. compose_continuous_video() refuses to run when audio is absent
  5. video_concatenator_node refuses to compose when scene renders are missing
  6. Normal rendering with valid audio is unchanged
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_scene(index: int, scene_type: str = "generated_image") -> dict:
    return {
        "index": index,
        "narration": f"Scene {index} narration.",
        "visual_prompt": f"Scene {index} image.",
        "duration_seconds": 5.0,
        "scene_type": scene_type,
        "motion": None,
        "transition_in": None,
        "transition_out": None,
        "effects": None,
    }


def _scaffold_assets(
    project_dir: Path,
    n_scenes: int,
    *,
    missing_audio: set[int] | None = None,
) -> dict[str, dict[int, str]]:
    """Create scene asset files; return absolute path dicts for use in state."""
    missing_audio = missing_audio or set()
    for sub in ("audio", "images", "subtitles", "video", "scenes"):
        (project_dir / sub).mkdir(parents=True, exist_ok=True)

    image_paths: dict[int, str] = {}
    audio_paths: dict[int, str] = {}
    srt_paths: dict[int, str] = {}
    scenes: list[dict] = []

    for i in range(1, n_scenes + 1):
        img = project_dir / "images" / f"scene-{i:03d}.png"
        img.write_bytes(b"\x89PNG")
        image_paths[i] = str(img)

        srt = project_dir / "subtitles" / f"scene-{i:03d}.srt"
        srt.write_text(f"1\n00:00:00,000 --> 00:00:05,000\nScene {i}\n", encoding="utf-8")
        srt_paths[i] = str(srt)

        if i not in missing_audio:
            mp3 = project_dir / "audio" / f"scene-{i:03d}.mp3"
            mp3.write_bytes(b"ID3")
            (project_dir / "audio" / f"scene-{i:03d}.timing.json").write_text(
                json.dumps([{"word": "w", "start": 0.0, "end": 5.0}]), encoding="utf-8"
            )
            audio_paths[i] = str(mp3)

        scenes.append(_make_scene(i))

    (project_dir / "scenes" / "scene-plan.json").write_text(
        json.dumps({"scenes": scenes}), encoding="utf-8"
    )
    return {"image_paths": image_paths, "audio_paths": audio_paths, "srt_paths": srt_paths}


def _renderer_state(
    project_id: str,
    project_dir: Path,
    n_scenes: int,
    paths: dict,
) -> dict:
    scenes = [_make_scene(i) for i in range(1, n_scenes + 1)]
    return {
        "project_id": project_id,
        "scene_plan": scenes,
        "image_paths": paths["image_paths"],
        "audio_paths": paths["audio_paths"],
        "srt_paths": paths["srt_paths"],
        "render_profile": "balanced",
    }


def _call_renderer(state: dict) -> dict:
    from ytfactory.agents.nodes.video_renderer import video_renderer_node
    return video_renderer_node(state)


def _call_concatenator(state: dict) -> dict:
    from ytfactory.agents.nodes.video_concatenator import video_concatenator_node
    return video_concatenator_node(state)


# ── 1. Path("") == Path(".") invariant ───────────────────────────────────────


class TestPathEmptyEqualsCurrentDir:
    """Verify the Python invariant that caused the original bug."""

    def test_path_empty_string_equals_dot(self):
        assert Path("") == Path(".")

    def test_path_dot_exists_always(self):
        assert Path(".").exists(), "current directory always exists"

    def test_path_dot_is_not_a_file(self):
        assert not Path(".").is_file(), "is_file() correctly rejects directories"

    def test_path_empty_is_not_a_file(self):
        assert not Path("").is_file(), "Path('') is_file() also False"


# ── 2. video_renderer_node — agentic path ────────────────────────────────────


class TestVideoRendererNodeMissingAudio:
    """Tests for the agentic video_renderer_node."""

    def test_missing_audio_error_recorded(self, tmp_path, monkeypatch):
        """A scene with no audio entry in audio_paths produces a clear stage_error."""
        pid = "proj"
        project_dir = tmp_path / pid
        paths = _scaffold_assets(project_dir, n_scenes=1, missing_audio={1})
        monkeypatch.setattr(
            "ytfactory.agents.nodes.video_renderer.WORKSPACE_DIR", str(tmp_path)
        )

        # audio_paths is empty — TTS failed for scene 1
        paths["audio_paths"] = {}
        state = _renderer_state(pid, project_dir, 1, paths)

        with patch("ytfactory.agents.nodes.video_renderer.FFmpegRenderer"):
            result = _call_renderer(state)

        errors = result.get("stage_errors", [])
        assert any("Scene 1" in e for e in errors)
        assert any("audio" in e.lower() or "TTS" in e for e in errors)

    def test_ffmpeg_never_called_with_dot_path(self, tmp_path, monkeypatch):
        """FFmpegRenderer.render must never be called with audio=Path('.')."""
        pid = "proj"
        project_dir = tmp_path / pid
        paths = _scaffold_assets(project_dir, n_scenes=1, missing_audio={1})
        monkeypatch.setattr(
            "ytfactory.agents.nodes.video_renderer.WORKSPACE_DIR", str(tmp_path)
        )

        paths["audio_paths"] = {}  # no audio → would produce Path("") == Path(".")
        state = _renderer_state(pid, project_dir, 1, paths)

        with patch("ytfactory.agents.nodes.video_renderer.FFmpegRenderer") as MockFFmpeg:
            _call_renderer(state)

        mock_render = MockFFmpeg.return_value.render
        assert mock_render.call_count == 0, "FFmpeg should not be called when audio is missing"
        for c in mock_render.call_args_list:
            audio_arg = c.kwargs.get("audio")
            assert audio_arg != Path("."), "render() was called with audio=Path('.')"

    def test_ffmpeg_never_called_with_nonexistent_audio_path(self, tmp_path, monkeypatch):
        """Providing a path string that points to a missing file is also rejected."""
        pid = "proj"
        project_dir = tmp_path / pid
        paths = _scaffold_assets(project_dir, n_scenes=1, missing_audio={1})
        monkeypatch.setattr(
            "ytfactory.agents.nodes.video_renderer.WORKSPACE_DIR", str(tmp_path)
        )

        # Point to a path that doesn't exist on disk
        paths["audio_paths"] = {1: str(project_dir / "audio" / "scene-001.mp3")}
        state = _renderer_state(pid, project_dir, 1, paths)

        with patch("ytfactory.agents.nodes.video_renderer.FFmpegRenderer") as MockFFmpeg:
            _call_renderer(state)

        assert MockFFmpeg.return_value.render.call_count == 0

    def test_one_missing_audio_does_not_halt_other_scenes(self, tmp_path, monkeypatch):
        """Processing continues for valid scenes when one scene has missing audio."""
        pid = "proj"
        project_dir = tmp_path / pid
        paths = _scaffold_assets(project_dir, n_scenes=3, missing_audio={2})
        monkeypatch.setattr(
            "ytfactory.agents.nodes.video_renderer.WORKSPACE_DIR", str(tmp_path)
        )

        state = _renderer_state(pid, project_dir, 3, paths)

        with patch("ytfactory.agents.nodes.video_renderer.FFmpegRenderer") as MockFFmpeg:
            result = _call_renderer(state)

        # Scenes 1 and 3 rendered, scene 2 skipped
        assert MockFFmpeg.return_value.render.call_count == 2
        errors = result.get("stage_errors", [])
        assert any("Scene 2" in e for e in errors)

    def test_tts_failed_error_message_is_actionable(self, tmp_path, monkeypatch):
        """The error message for missing audio mentions TTS and the expected path."""
        pid = "proj"
        project_dir = tmp_path / pid
        paths = _scaffold_assets(project_dir, n_scenes=1, missing_audio={1})
        monkeypatch.setattr(
            "ytfactory.agents.nodes.video_renderer.WORKSPACE_DIR", str(tmp_path)
        )

        paths["audio_paths"] = {}
        state = _renderer_state(pid, project_dir, 1, paths)

        with patch("ytfactory.agents.nodes.video_renderer.FFmpegRenderer"):
            result = _call_renderer(state)

        error = next(e for e in result.get("stage_errors", []) if "Scene 1" in e)
        # Must mention TTS and/or expected path
        assert "TTS" in error or "scene-001.mp3" in error

    def test_valid_audio_renders_normally(self, tmp_path, monkeypatch):
        """Normal rendering path is unchanged when all assets are present."""
        pid = "proj"
        project_dir = tmp_path / pid
        paths = _scaffold_assets(project_dir, n_scenes=2)
        monkeypatch.setattr(
            "ytfactory.agents.nodes.video_renderer.WORKSPACE_DIR", str(tmp_path)
        )

        state = _renderer_state(pid, project_dir, 2, paths)

        with patch("ytfactory.agents.nodes.video_renderer.FFmpegRenderer") as MockFFmpeg:
            result = _call_renderer(state)

        assert MockFFmpeg.return_value.render.call_count == 2
        assert result.get("stage_errors", []) == []


# ── 3. compose_continuous_video ───────────────────────────────────────────────


class TestComposeContinuousVideoMissingAudio:
    def _mock_settings(self):
        from ytfactory.config.settings import Settings

        s = MagicMock(spec=Settings)
        s.render_profile = "balanced"
        s.video_width = 1280
        s.video_height = 720
        s.video_fps = 30
        s.bgm_enabled = False
        s.video_intro_enabled = False
        s.video_intro_seconds = 1.5
        return s

    def test_raises_before_ffmpeg_when_audio_missing(self, tmp_path):
        from ytfactory.video.pipeline import compose_continuous_video

        project_dir = tmp_path / "proj"
        _scaffold_assets(project_dir, n_scenes=2, missing_audio={2})
        output_dir = project_dir / "video"

        with patch("ytfactory.video.pipeline.FFmpegRenderer") as MockFFmpeg:
            with pytest.raises(RuntimeError, match="narration audio missing"):
                compose_continuous_video(project_dir, output_dir, self._mock_settings())

        MockFFmpeg.return_value.render_continuous.assert_not_called()

    def test_error_names_every_missing_scene(self, tmp_path):
        from ytfactory.video.pipeline import compose_continuous_video

        project_dir = tmp_path / "proj"
        _scaffold_assets(project_dir, n_scenes=3, missing_audio={1, 3})
        output_dir = project_dir / "video"

        with patch("ytfactory.video.pipeline.FFmpegRenderer"):
            with pytest.raises(RuntimeError) as exc_info:
                compose_continuous_video(project_dir, output_dir, self._mock_settings())

        msg = str(exc_info.value)
        assert "Scene 1" in msg
        assert "Scene 3" in msg

    def test_all_audio_present_calls_render_continuous(self, tmp_path):
        from ytfactory.video.pipeline import compose_continuous_video

        project_dir = tmp_path / "proj"
        _scaffold_assets(project_dir, n_scenes=2)
        output_dir = project_dir / "video"

        with patch("ytfactory.video.pipeline.FFmpegRenderer") as MockFFmpeg, \
             patch("ytfactory.video.pipeline._apply_bgm"):
            compose_continuous_video(project_dir, output_dir, self._mock_settings())

        MockFFmpeg.return_value.render_continuous.assert_called_once()


# ── 4. video_concatenator_node ────────────────────────────────────────────────


class TestVideoConcatenatorNodeMissingRenders:
    def _make_state(
        self,
        project_id: str,
        project_dir: Path,
        scene_plan: list,
        scene_video_paths: dict,
    ) -> dict:
        return {
            "project_id": project_id,
            "scene_plan": scene_plan,
            "scene_video_paths": scene_video_paths,
        }

    def test_blocks_compose_when_scene_render_missing(self, tmp_path, monkeypatch):
        pid = "proj"
        project_dir = tmp_path / pid
        (project_dir / "video").mkdir(parents=True)
        monkeypatch.setattr(
            "ytfactory.agents.nodes.video_concatenator.WORKSPACE_DIR", str(tmp_path)
        )

        scenes = [_make_scene(1), _make_scene(2)]
        # Scene 2 render failed
        state = self._make_state(pid, project_dir, scenes, scene_video_paths={1: "v/scene-001.mp4"})

        with patch("ytfactory.agents.nodes.video_concatenator.compose_continuous_video") as mc, \
             patch("ytfactory.agents.nodes.video_concatenator.Settings"):
            result = _call_concatenator(state)

        mc.assert_not_called()
        errors = result.get("stage_errors", [])
        assert any("Scene 2" in e for e in errors)

    def test_reports_all_missing_scenes(self, tmp_path, monkeypatch):
        pid = "proj"
        project_dir = tmp_path / pid
        (project_dir / "video").mkdir(parents=True)
        monkeypatch.setattr(
            "ytfactory.agents.nodes.video_concatenator.WORKSPACE_DIR", str(tmp_path)
        )

        scenes = [_make_scene(1), _make_scene(2), _make_scene(3)]
        state = self._make_state(pid, project_dir, scenes, scene_video_paths={})

        with patch("ytfactory.agents.nodes.video_concatenator.compose_continuous_video"), \
             patch("ytfactory.agents.nodes.video_concatenator.Settings"):
            result = _call_concatenator(state)

        combined = " ".join(result.get("stage_errors", []))
        assert "Scene 1" in combined
        assert "Scene 2" in combined
        assert "Scene 3" in combined

    def test_proceeds_when_all_scenes_rendered(self, tmp_path, monkeypatch):
        pid = "proj"
        project_dir = tmp_path / pid
        (project_dir / "video").mkdir(parents=True)
        final = project_dir / "video" / "final.mp4"
        final.write_bytes(b"fake")
        monkeypatch.setattr(
            "ytfactory.agents.nodes.video_concatenator.WORKSPACE_DIR", str(tmp_path)
        )

        scenes = [_make_scene(1), _make_scene(2)]
        scene_video_paths = {
            1: str(project_dir / "video" / "scene-001.mp4"),
            2: str(project_dir / "video" / "scene-002.mp4"),
        }
        state = self._make_state(pid, project_dir, scenes, scene_video_paths)

        with patch("ytfactory.agents.nodes.video_concatenator.compose_continuous_video") as mc, \
             patch("ytfactory.agents.nodes.video_concatenator.Settings") as MockSettings:
            MockSettings.return_value.bgm_enabled = False
            _call_concatenator(state)

        mc.assert_called_once()


# ── 5. VideoPipeline sequential path ─────────────────────────────────────────


class TestVideoPipelineSequentialMissingAudio:
    """Tests for VideoPipeline.run() collect-and-continue behavior."""

    def _mock_settings_obj(self):
        m = MagicMock()
        m.render_profile = "balanced"
        m.video_width = 1280
        m.video_height = 720
        m.video_fps = 30
        m.bgm_enabled = False
        m.video_intro_enabled = False
        m.video_intro_seconds = 1.5
        m.video_crf = 23
        m.video_preset = "medium"
        m.video_tune = ""
        m.video_keyframe_interval = 60
        m.video_audio_bitrate = "128k"
        return m

    def test_raises_summary_error_not_first_scene_abort(self, tmp_path, monkeypatch):
        """VideoPipeline.run() raises a single summary error after all scenes."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "ytfactory.video.pipeline.Settings",
            MagicMock(return_value=self._mock_settings_obj()),
        )

        project_dir = tmp_path / "workspace" / "jobs" / "proj"
        _scaffold_assets(project_dir, n_scenes=3, missing_audio={2})

        with patch("ytfactory.video.pipeline.FFmpegRenderer"):
            with pytest.raises(RuntimeError) as exc_info:
                from ytfactory.video.pipeline import VideoPipeline
                VideoPipeline().run("proj")

        msg = str(exc_info.value)
        assert "Scene 2" in msg
        assert "TTS failed" in msg or "missing" in msg.lower()

    def test_processes_other_scenes_before_raising(self, tmp_path, monkeypatch):
        """Scenes 1 and 3 are attempted; only scene 2 (no audio) is skipped."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "ytfactory.video.pipeline.Settings",
            MagicMock(return_value=self._mock_settings_obj()),
        )

        project_dir = tmp_path / "workspace" / "jobs" / "proj"
        _scaffold_assets(project_dir, n_scenes=3, missing_audio={2})

        rendered: list[str] = []

        def fake_render(**kwargs):
            rendered.append(str(kwargs.get("output", "")))

        with patch("ytfactory.video.pipeline.FFmpegRenderer") as MockFFmpeg, \
             pytest.raises(RuntimeError):
            MockFFmpeg.return_value.render.side_effect = fake_render
            from ytfactory.video.pipeline import VideoPipeline
            VideoPipeline().run("proj")

        # scene-001 and scene-003 rendered; scene-002 skipped
        assert any("scene-001" in r for r in rendered)
        assert any("scene-003" in r for r in rendered)
        assert not any("scene-002" in r for r in rendered)

    def test_no_error_when_all_audio_present(self, tmp_path, monkeypatch):
        """Normal path raises no error when all assets present."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "ytfactory.video.pipeline.Settings",
            MagicMock(return_value=self._mock_settings_obj()),
        )

        project_dir = tmp_path / "workspace" / "jobs" / "proj"
        _scaffold_assets(project_dir, n_scenes=2)

        with patch("ytfactory.video.pipeline.FFmpegRenderer") as MockFFmpeg, \
             patch("ytfactory.video.pipeline._apply_bgm"), \
             patch("ytfactory.video.pipeline._actual_audio_duration", return_value=5.0):
            MockFFmpeg.return_value.render_continuous = MagicMock()
            from ytfactory.video.pipeline import VideoPipeline
            # must not raise
            VideoPipeline().run("proj")
