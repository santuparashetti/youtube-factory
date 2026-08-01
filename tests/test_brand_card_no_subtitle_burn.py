"""Brand card scene must never get subtitle burn-in — voice-only static card.

Covers both render paths:
  - FFmpegRenderer.render() — per-scene renderer (VideoPipeline.run() and the
    agent-graph video_renderer_node() both call this)
  - FFmpegRenderer.render_continuous() — single-pass filter_complex renderer
    used by compose_continuous_video()

Phase 1 subtitle file generation (.ass/.srt) is untouched — the file is still
written to disk; these tests only assert it's never fed into the -vf chain
for brand_card scenes, and that narration audio is still included.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


class TestPerSceneRenderSkipsSubtitleForBrandCard:
    def _capture_render_cmd(self, tmp_path, scene_type):
        from ytfactory.video.ffmpeg import FFmpegRenderer

        renderer = FFmpegRenderer()
        renderer.settings = renderer.settings.model_copy(update={"subtitle_burn_enabled": True})
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

    def test_brand_card_no_subtitle_burn(self, tmp_path):
        cmd = self._capture_render_cmd(tmp_path, scene_type="brand_card")
        vf = cmd[cmd.index("-vf") + 1]
        assert "subtitles=" not in vf, f"Brand card -vf must not burn subtitles: {vf}"

    def test_brand_card_audio_input_still_present(self, tmp_path):
        cmd = self._capture_render_cmd(tmp_path, scene_type="brand_card")
        assert str(tmp_path / "audio.mp3") in cmd, (
            "Brand card render must still include the narration audio input"
        )

    def test_generated_image_scene_still_gets_subtitle_burn(self, tmp_path):
        """Regression guard: only brand_card is excluded — every other scene
        type keeps subtitle burn-in exactly as before."""
        cmd = self._capture_render_cmd(tmp_path, scene_type="generated_image")
        vf = cmd[cmd.index("-vf") + 1]
        assert "subtitles=" in vf

    def test_no_scene_type_still_gets_subtitle_burn(self, tmp_path):
        """Default (scene_type=None) must not accidentally suppress subtitles."""
        cmd = self._capture_render_cmd(tmp_path, scene_type=None)
        vf = cmd[cmd.index("-vf") + 1]
        assert "subtitles=" in vf


class TestRenderContinuousSkipsSubtitleForBrandCard:
    def _capture_filter_complex(self, tmp_path, monkeypatch, scene_type):
        from ytfactory.video.ffmpeg import FFmpegRenderer

        project_dir = tmp_path / "proj"
        for sub in ("images", "audio", "subtitles"):
            (project_dir / sub).mkdir(parents=True)

        image = project_dir / "images" / "scene-001.png"
        image.write_bytes(b"x")
        audio = project_dir / "audio" / "scene-001.mp3"
        audio.write_bytes(b"x")
        ass_sub = project_dir / "subtitles" / "scene-001.ass"
        ass_sub.write_text("dummy", encoding="utf-8")

        scene = {
            "index": 1,
            "scene_type": scene_type,
            "narration": "This is Atma Theory.",
            "motion": {"motion_type": "static"},
        }

        renderer = FFmpegRenderer()
        renderer.settings = renderer.settings.model_copy(update={"subtitle_burn_enabled": True})
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

    def test_brand_card_no_subtitle_burn(self, tmp_path, monkeypatch):
        cmd = self._capture_filter_complex(tmp_path, monkeypatch, scene_type="brand_card")
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "subtitles=" not in filter_complex

    def test_generated_image_scene_still_gets_subtitle_burn(self, tmp_path, monkeypatch):
        cmd = self._capture_filter_complex(
            tmp_path, monkeypatch, scene_type="generated_image"
        )
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "subtitles=" in filter_complex
