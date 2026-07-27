"""SUBTITLE_BURN_ENABLED — global toggle to skip subtitle burn-in at render
time while Phase 1 still generates .ass/.srt files for YouTube upload.

Independent of the brand_card exclusion (test_brand_card_no_subtitle_burn.py),
which always skips burn-in regardless of this setting.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ytfactory.config.settings import Settings


class TestSubtitleBurnSettingDefault:
    def test_default_is_true(self):
        assert Settings.model_fields["subtitle_burn_enabled"].default is True


class TestPerSceneRenderRespectsSubtitleBurnSetting:
    def _capture_render_cmd(self, tmp_path, subtitle_burn_enabled, scene_type="generated_image"):
        from ytfactory.video.ffmpeg import FFmpegRenderer

        renderer = FFmpegRenderer()
        renderer.settings.subtitle_burn_enabled = subtitle_burn_enabled
        captured: list[list[str]] = []

        with patch(
            "ytfactory.video.ffmpeg.subprocess.run",
            side_effect=lambda cmd, **kw: captured.append(list(cmd)),
        ):
            renderer.render(
                image=tmp_path / "img.png",
                audio=tmp_path / "audio.mp3",
                subtitle=tmp_path / "scene.ass",
                output=tmp_path / "out.mp4",
                duration_hint=10.0,
                scene_type=scene_type,
            )

        return captured[0]

    def test_disabled_skips_filter(self, tmp_path):
        cmd = self._capture_render_cmd(tmp_path, subtitle_burn_enabled=False)
        vf = cmd[cmd.index("-vf") + 1]
        assert "subtitles=" not in vf
        assert "ass=" not in vf

    def test_enabled_includes_filter(self, tmp_path):
        cmd = self._capture_render_cmd(tmp_path, subtitle_burn_enabled=True)
        vf = cmd[cmd.index("-vf") + 1]
        assert "subtitles=" in vf

    def test_disabled_still_includes_audio_input(self, tmp_path):
        cmd = self._capture_render_cmd(tmp_path, subtitle_burn_enabled=False)
        assert str(tmp_path / "audio.mp3") in cmd

    def test_disabled_does_not_override_brand_card_exclusion(self, tmp_path):
        """Brand card must stay subtitle-free even if burn is re-enabled."""
        cmd = self._capture_render_cmd(
            tmp_path, subtitle_burn_enabled=True, scene_type="brand_card"
        )
        vf = cmd[cmd.index("-vf") + 1]
        assert "subtitles=" not in vf


class TestRenderContinuousRespectsSubtitleBurnSetting:
    def _capture_filter_complex(self, tmp_path, monkeypatch, subtitle_burn_enabled, scene_type="generated_image"):
        from ytfactory.video.ffmpeg import FFmpegRenderer

        project_dir = tmp_path / "proj"
        for sub in ("images", "audio", "subtitles"):
            (project_dir / sub).mkdir(parents=True)

        (project_dir / "images" / "scene-001.png").write_bytes(b"x")
        (project_dir / "audio" / "scene-001.mp3").write_bytes(b"x")
        (project_dir / "subtitles" / "scene-001.ass").write_text("dummy", encoding="utf-8")

        scene = {
            "index": 1,
            "scene_type": scene_type,
            "narration": "Test narration.",
            "motion": {"motion_type": "static"},
        }

        renderer = FFmpegRenderer()
        renderer.settings.subtitle_burn_enabled = subtitle_burn_enabled
        captured: dict[str, list[str]] = {}

        def _fake_run(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            Path(cmd[-1]).write_bytes(b"x")

        monkeypatch.chdir(tmp_path)
        with patch("ytfactory.video.ffmpeg.subprocess.run", side_effect=_fake_run):
            renderer.render_continuous(
                scenes=[scene],
                durations=[10.0],
                project_dir=project_dir,
                output_path=project_dir / "out.mp4",
                intro_enabled=False,
                intro_seconds=0.0,
            )

        return captured["cmd"]

    def test_disabled_skips_filter(self, tmp_path, monkeypatch):
        cmd = self._capture_filter_complex(tmp_path, monkeypatch, subtitle_burn_enabled=False)
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "subtitles=" not in filter_complex

    def test_enabled_includes_filter(self, tmp_path, monkeypatch):
        cmd = self._capture_filter_complex(tmp_path, monkeypatch, subtitle_burn_enabled=True)
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "subtitles=" in filter_complex

    def test_disabled_does_not_override_brand_card_exclusion(self, tmp_path, monkeypatch):
        cmd = self._capture_filter_complex(
            tmp_path, monkeypatch, subtitle_burn_enabled=True, scene_type="brand_card"
        )
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "subtitles=" not in filter_complex


class TestSubtitleFilesStillGeneratedWhenBurnDisabled:
    """subtitle_burn_enabled only affects the render filter chain — it must
    not reach anywhere near Phase 1's SubtitleEngine/.srt writing."""

    def test_setting_not_referenced_by_subtitle_generation(self):
        import inspect

        from ytfactory.subtitles.engine import SubtitleEngine

        source = inspect.getsource(SubtitleEngine)
        assert "subtitle_burn_enabled" not in source
