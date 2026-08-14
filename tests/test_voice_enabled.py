"""Tests for VOICE_ENABLED runtime configuration.

Verifies:
- VOICE_ENABLED=true  → existing behavior unchanged
- VOICE_ENABLED=false → no TTS provider called, no audio generated,
                         silent audio created for renderer, pipeline succeeds
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.config.settings import Settings
from ytfactory.voice.pipeline import VoicePipeline
from ytfactory.bootstrap.provider_validator import validate_providers, CheckResult, CheckStatus


# ── Helpers ────────────────────────────────────────────────────────────────────


def _scaffold_project(tmp_path: Path, n_scenes: int = 3) -> Path:
    """Create a minimal project with scene plan but no audio."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    for sub in ("scenes", "audio", "images", "subtitles", "video"):
        (project_dir / sub).mkdir(parents=True, exist_ok=True)

    scenes = [
        {
            "index": i + 1,
            "title": f"Scene {i + 1}",
            "narration": f"Narration for scene {i + 1}.",
            "visual_prompt": f"Visual for scene {i + 1}.",
            "duration_seconds": 5.0,
        }
        for i in range(n_scenes)
    ]
    (project_dir / "scenes" / "scene-plan.json").write_text(
        json.dumps({"scenes": scenes}), encoding="utf-8"
    )
    return project_dir


# ── VoicePipeline.run() ────────────────────────────────────────────────────────


class TestVoicePipelineEnabled:
    """VOICE_ENABLED=true preserves existing behavior."""

    def test_returns_early_and_logs_when_disabled(self, tmp_path: Path) -> None:
        """When voice_enabled=False, run() returns immediately with one log line."""
        from loguru import logger as _loguru

        project_dir = _scaffold_project(tmp_path, n_scenes=2)
        settings = Settings(voice_enabled=False)
        pipeline = VoicePipeline(settings)

        captured = []
        _loguru.add(captured.append, level="INFO")

        with patch("ytfactory.voice.pipeline.audio_directory", return_value=project_dir / "audio"):
            pipeline.run("proj")

        # No audio files should exist
        audio_dir = project_dir / "audio"
        assert not any(audio_dir.iterdir()), "No audio files should be generated"

        # Log message should appear
        assert any(
            "VOICE_ENABLED=false" in r and "skipping narration generation" in r
            for r in captured
        ), f"Expected log message not found. Captured: {captured}"

    def test_proceeds_normally_when_enabled(self, tmp_path: Path) -> None:
        """When voice_enabled=True (default), run() does NOT take the early-return path.

        We verify this by checking that the early-return condition is False,
        and that the TTS provider is loaded when run() is called.
        """
        settings = Settings(
            voice_enabled=True,
            ssml_enhancement_enabled=False,
            tts_validate_audio=False,
        )
        pipeline = VoicePipeline(settings)

        # The early-return check should be False
        assert pipeline._settings.voice_enabled is True
        # Provider is loaded lazily now
        assert pipeline._provider is None

        mock_provider = MagicMock()
        mock_provider.capabilities.provider_name = "mock-tts"
        mock_provider.generate_with_boundaries.return_value = (None, [{"end": 5.0}])

        project_dir = _scaffold_project(tmp_path, n_scenes=1)

        scene_file = project_dir / "scenes" / "scene-plan.json"
        scene_data = json.loads(scene_file.read_text())

        m = MagicMock()
        m.__enter__ = MagicMock(return_value=MagicMock(
            read=MagicMock(return_value=json.dumps(scene_data).encode())
        ))
        m.__exit__ = MagicMock(return_value=False)

        with patch("ytfactory.voice.pipeline.audio_directory", return_value=project_dir / "audio"):
            with patch("builtins.open", return_value=m):
                with patch("ytfactory.voice.pipeline.get_tts_provider", return_value=mock_provider):
                    pipeline.run("proj")

        assert mock_provider.generate_with_boundaries.called, (
            "TTS provider should be called when voice_enabled=True"
        )


# ── generate_scene_assets() ────────────────────────────────────────────────────


class TestSceneAssetsVoiceEnabled:
    """Scene assets node skips TTS when voice is disabled."""

    def test_skips_tts_when_voice_disabled(self, tmp_path: Path) -> None:
        """TTS provider must not be instantiated or called."""
        from ytfactory.agents.nodes.scene_assets import generate_scene_assets

        project_dir = _scaffold_project(tmp_path, n_scenes=1)
        scene = {
            "index": 1,
            "title": "Scene 1",
            "narration": "Test narration.",
            "visual_prompt": "Test visual.",
            "duration_seconds": 5.0,
            "scene_type": "generated_image",
        }
        state: dict = {
            "current_scene": scene,
            "project_id": "proj",
            "language": "en",
            "style": "spiritual",
            "skip_images": False,
            "scene_plan": [scene],
        }

        settings = Settings(voice_enabled=False)

        with patch("ytfactory.agents.nodes.scene_assets.Settings", return_value=settings):
            with patch("ytfactory.agents.nodes.scene_assets.get_image_provider"):
                with patch("ytfactory.agents.nodes.scene_assets._get_tts_provider") as mock_tts:
                    result = generate_scene_assets(state)

        assert not mock_tts.called, "TTS provider must not be instantiated when voice_enabled=False"

        audio_dir = Path("workspace") / "jobs" / "proj" / "audio"
        audio_file = audio_dir / "scene-001.mp3"
        assert audio_file.exists(), "Silent audio should be generated when voice is disabled"
        assert audio_file.stat().st_size > 0, "Silent audio should not be empty"

        assert result.get("audio_paths", {}).get(1) == str(audio_file), (
            "Silent audio path should be returned when voice is disabled"
        )


# ── compose_continuous_video() ─────────────────────────────────────────────────


class TestComposeContinuousVideoVoiceDisabled:
    """Renderer generates silent audio when voice is disabled."""

    def test_generates_silent_audio_for_all_scenes(self, tmp_path: Path) -> None:
        """Missing audio files are replaced with silent MP3s when voice_enabled=False."""
        from ytfactory.video.pipeline import compose_continuous_video

        project_dir = _scaffold_project(tmp_path, n_scenes=3)
        scenes = json.loads(
            (project_dir / "scenes" / "scene-plan.json").read_text()
        )["scenes"]

        # Add minimal motion/transition/effects so the renderer doesn't fail
        for s in scenes:
            s["motion"] = {"motion_type": "drift", "start_scale": 1.0, "end_scale": 1.0}
            s["transition_in"] = {"transition_type": "hard_cut", "duration_frames": 0}
            s["transition_out"] = {"transition_type": "hard_cut", "duration_frames": 0}
            s["effects"] = {}

        settings = Settings(voice_enabled=False, render_profile="balanced")

        with patch("ytfactory.video.pipeline.FFmpegRenderer") as mock_renderer:
            mock_renderer.return_value.render_continuous.return_value = None
            with patch("ytfactory.video.pipeline._apply_overlays"), \
                 patch("ytfactory.video.pipeline._apply_bgm"):
                compose_continuous_video(
                    project_dir=project_dir,
                    output_dir=project_dir / "video",
                    settings=settings,
                )

        # All audio files should exist (silent placeholders)
        for i in range(1, 4):
            audio = project_dir / "audio" / f"scene-{i:03d}.mp3"
            assert audio.exists(), f"Silent audio should be generated for scene {i}"
            assert audio.stat().st_size > 0, f"Silent audio should not be empty for scene {i}"


# ── Provider validator ────────────────────────────────────────────────────────


class TestProviderValidatorVoiceDisabled:
    """TTS provider validation is skipped when voice is disabled."""

    def test_skips_tts_validation(self) -> None:
        with patch("ytfactory.config.settings.Settings") as mock_settings_cls:
            mock_settings_cls.return_value = Settings(voice_enabled=False)
            with patch("ytfactory.bootstrap.provider_validator._check_tts_provider") as mock_tts:
                results = validate_providers()

        tts_results = [r for r in results if r.name == "providers:tts"]
        assert len(tts_results) == 1, "TTS check should still appear (as SKIPPED)"
        assert tts_results[0].status == CheckStatus.SKIPPED
        assert not mock_tts.called, "TTS validator must not be invoked when voice_enabled=False"

    def test_includes_tts_when_enabled(self) -> None:
        with patch("ytfactory.config.settings.Settings") as mock_settings_cls:
            mock_settings_cls.return_value = Settings(voice_enabled=True)
            with patch("ytfactory.bootstrap.provider_validator._check_tts_provider") as mock_tts:
                mock_tts.return_value = [CheckResult(name="providers:tts", status=CheckStatus.OK, message="ok", detail="")]
                results = validate_providers()

        assert mock_tts.called, "TTS validator should be invoked when voice_enabled=True"
