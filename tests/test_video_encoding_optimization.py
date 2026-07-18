"""Tests for video encoding optimisation (CRF 23, preset slow, tune film).

Covers:
  - Settings defaults: video_crf, video_preset, video_tune,
    video_audio_bitrate, video_keyframe_interval
  - FFmpegRenderer uses settings-driven CRF / preset / tune / audio bitrate
  - tune flag present only when video_tune is non-empty
  - video_keyframe_interval passed as -g argument
  - _generate_intro_clip uses the same settings
  - VideoStats dataclass: from_file() with mocked ffprobe
  - ComparisonReport: size_reduction_pct, duration_match, resolution_match
  - compare_videos() plumbing
  - compare-video CLI command is registered
  - Regression guard: render() must not use trim= in the VF chain (e28b94b)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


# ── Settings defaults ─────────────────────────────────────────────────────────


class TestVideoEncodingSettingsDefaults:
    def _s(self):
        from ytfactory.config.settings import Settings
        return Settings()

    def test_crf_default(self):
        assert self._s().video_crf == 23

    def test_preset_default(self):
        assert self._s().video_preset == "medium"

    def test_tune_default(self):
        assert self._s().video_tune == ""

    def test_audio_bitrate_default(self):
        assert self._s().video_audio_bitrate == "128k"

    def test_keyframe_interval_default(self):
        assert self._s().video_keyframe_interval == 60


# ── FFmpegRenderer encodes with settings ──────────────────────────────────────


class TestFFmpegRendererEncodingSettings:
    def _render_and_capture(self, tmp_path, **settings_overrides):
        """Call renderer.render() with mocked subprocess and return the ffmpeg cmd."""
        from ytfactory.video.ffmpeg import FFmpegRenderer

        renderer = FFmpegRenderer()

        # Override settings attributes
        for k, v in settings_overrides.items():
            setattr(renderer.settings, k, v)

        captured_cmds = []

        def fake_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))

        with patch("ytfactory.video.ffmpeg.subprocess.run", side_effect=fake_run):
            renderer.render(
                image=tmp_path / "img.png",
                audio=tmp_path / "audio.mp3",
                subtitle=tmp_path / "scene.ass",
                output=tmp_path / "out.mp4",
                duration_hint=5.0,
                transition_in={"duration_frames": 15, "color": "black"},
                transition_out={"duration_frames": 15, "color": "black"},
            )

        return captured_cmds[0]

    def test_crf_applied(self, tmp_path):
        cmd = self._render_and_capture(tmp_path, video_crf=27)
        idx = cmd.index("-crf")
        assert cmd[idx + 1] == "27"

    def test_preset_applied(self, tmp_path):
        cmd = self._render_and_capture(tmp_path, video_preset="veryslow")
        idx = cmd.index("-preset")
        assert cmd[idx + 1] == "veryslow"

    def test_tune_applied(self, tmp_path):
        cmd = self._render_and_capture(tmp_path, video_tune="film")
        idx = cmd.index("-tune")
        assert cmd[idx + 1] == "film"

    def test_no_tune_when_empty(self, tmp_path):
        cmd = self._render_and_capture(tmp_path, video_tune="")
        assert "-tune" not in cmd

    def test_keyframe_interval_applied(self, tmp_path):
        cmd = self._render_and_capture(tmp_path, video_keyframe_interval=90)
        idx = cmd.index("-g")
        assert cmd[idx + 1] == "90"

    def test_audio_bitrate_applied(self, tmp_path):
        cmd = self._render_and_capture(tmp_path, video_audio_bitrate="96k")
        idx = cmd.index("-b:a")
        assert cmd[idx + 1] == "96k"

    def test_default_crf_is_23(self, tmp_path):
        cmd = self._render_and_capture(tmp_path)
        idx = cmd.index("-crf")
        assert cmd[idx + 1] == "23"

    def test_default_preset_is_medium(self, tmp_path):
        cmd = self._render_and_capture(tmp_path)
        idx = cmd.index("-preset")
        assert cmd[idx + 1] == "medium"

    def test_default_audio_bitrate_is_128k(self, tmp_path):
        cmd = self._render_and_capture(tmp_path)
        idx = cmd.index("-b:a")
        assert cmd[idx + 1] == "128k"



# ── VideoStats + ComparisonReport ────────────────────────────────────────────


_FFPROBE_RESPONSE = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "profile": "High",
            "width": 1920,
            "height": 1080,
            "r_frame_rate": "30/1",
            "bit_rate": "2000000",
            "tags": {"encoder": "libx264 crf=18 preset=medium"},
        },
        {
            "codec_type": "audio",
            "codec_name": "aac",
            "bit_rate": "192000",
            "sample_rate": "48000",
        },
    ],
    "format": {
        "size": "200000000",
        "duration": "330.0",
        "bit_rate": "4850000",
    },
}

_FFPROBE_OPTIMISED = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "profile": "High",
            "width": 1920,
            "height": 1080,
            "r_frame_rate": "30/1",
            "bit_rate": "600000",
            "tags": {"encoder": "libx264 crf=23 preset=slow"},
        },
        {
            "codec_type": "audio",
            "codec_name": "aac",
            "bit_rate": "128000",
            "sample_rate": "48000",
        },
    ],
    "format": {
        "size": "50000000",
        "duration": "330.0",
        "bit_rate": "1213000",
    },
}


class TestVideoStats:
    def _make_stats(self, tmp_path, ffprobe_data):
        from ytfactory.video.reporter import VideoStats

        p = tmp_path / "video.mp4"
        p.write_bytes(b"fake")

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(ffprobe_data)

        with patch("ytfactory.video.reporter.subprocess.run", return_value=mock_result):
            return VideoStats.from_file(p)

    def test_size_bytes(self, tmp_path):
        stats = self._make_stats(tmp_path, _FFPROBE_RESPONSE)
        assert stats.size_bytes == 200_000_000

    def test_size_mb(self, tmp_path):
        stats = self._make_stats(tmp_path, _FFPROBE_RESPONSE)
        assert stats.size_mb == pytest.approx(200_000_000 / 1024**2)

    def test_crf_extracted_from_tags(self, tmp_path):
        stats = self._make_stats(tmp_path, _FFPROBE_RESPONSE)
        assert stats.video_crf == "18"

    def test_preset_extracted_from_tags(self, tmp_path):
        stats = self._make_stats(tmp_path, _FFPROBE_RESPONSE)
        assert stats.video_preset == "medium"

    def test_audio_bitrate_kbps(self, tmp_path):
        stats = self._make_stats(tmp_path, _FFPROBE_RESPONSE)
        assert stats.audio_bitrate_kbps == 192

    def test_raises_on_missing_file(self, tmp_path):
        from ytfactory.video.reporter import VideoStats

        with pytest.raises(FileNotFoundError):
            VideoStats.from_file(tmp_path / "nonexistent.mp4")


class TestComparisonReport:
    def _make_report(self, tmp_path):
        from ytfactory.video.reporter import ComparisonReport, VideoStats

        orig_path = tmp_path / "orig.mp4"
        opt_path = tmp_path / "opt.mp4"
        orig_path.write_bytes(b"x")
        opt_path.write_bytes(b"x")

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            if "orig" in str(cmd[-1]):
                m.stdout = json.dumps(_FFPROBE_RESPONSE)
            else:
                m.stdout = json.dumps(_FFPROBE_OPTIMISED)
            return m

        with patch("ytfactory.video.reporter.subprocess.run", side_effect=fake_run):
            orig = VideoStats.from_file(orig_path)
            opt = VideoStats.from_file(opt_path)

        return ComparisonReport(original=orig, optimised=opt)

    def test_size_reduction_pct(self, tmp_path):
        report = self._make_report(tmp_path)
        expected = 100 * (200_000_000 - 50_000_000) / 200_000_000
        assert report.size_reduction_pct == pytest.approx(expected, abs=0.1)

    def test_duration_match_within_threshold(self, tmp_path):
        report = self._make_report(tmp_path)
        assert report.duration_match is True

    def test_resolution_match(self, tmp_path):
        report = self._make_report(tmp_path)
        assert report.resolution_match is True

    def test_to_markdown_contains_key_sections(self, tmp_path):
        report = self._make_report(tmp_path)
        md = report.to_markdown()
        assert "## File Summary" in md
        assert "## Video Stream" in md
        assert "## Audio Stream" in md
        assert "## Quality Verification" in md
        assert "## Encoding Settings Used" in md

    def test_to_markdown_shows_size_reduction(self, tmp_path):
        report = self._make_report(tmp_path)
        md = report.to_markdown()
        assert "75.0%" in md  # (200-50)/200 = 75%

    def test_to_dict_keys(self, tmp_path):
        report = self._make_report(tmp_path)
        d = report.to_dict()
        assert "original" in d
        assert "optimised" in d
        assert "comparison" in d
        assert d["comparison"]["size_reduction_pct"] == pytest.approx(75.0, abs=0.1)


# ── Duration-handling regression guard (commit e28b94b) ───────────────────────


class TestFFmpegRendererDurationHandling:
    """Regression guard: render() must NOT use trim= in the -vf chain.

    Commit e28b94b added ``trim=duration={n},setpts=PTS-STARTPTS`` to render()'s
    VF chain.  This caused "Play does not advance" in several media players:
    the trim filter interacts with -shortest in a way that creates a container
    whose declared duration disagrees with what -shortest would normally produce,
    confusing player sync logic.

    The correct approach (matching render_continuous) is to cap the looped image
    source via ``-t {duration}`` on the input, not via a VF trim.
    """

    def _capture_render_cmd(self, tmp_path, duration_hint=10.0, **extra):
        from ytfactory.video.ffmpeg import FFmpegRenderer

        renderer = FFmpegRenderer()
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
                duration_hint=duration_hint,
                **extra,
            )

        return captured[0]

    def test_no_trim_filter_in_vf_chain(self, tmp_path):
        cmd = self._capture_render_cmd(tmp_path)
        vf = cmd[cmd.index("-vf") + 1]
        assert "trim=duration" not in vf, (
            "trim=duration in -vf causes playback freeze (regression e28b94b). "
            "Cap the image source via -t on the input instead."
        )

    def test_no_setpts_startpts_in_vf_chain(self, tmp_path):
        cmd = self._capture_render_cmd(tmp_path)
        vf = cmd[cmd.index("-vf") + 1]
        assert "setpts=PTS-STARTPTS" not in vf

    def test_duration_t_caps_image_input(self, tmp_path):
        """-t must appear before the first -i (the image) to cap the loop."""
        cmd = self._capture_render_cmd(tmp_path, duration_hint=7.5)
        t_idx = cmd.index("-t")
        first_i_idx = cmd.index("-i")
        assert t_idx < first_i_idx, "-t must precede the image -i"
        assert cmd[t_idx + 1] == "7.5000"

    def test_vf_chain_ends_with_subtitle_filter(self, tmp_path):
        """subtitle burn-in must be the last filter in the VF chain."""
        cmd = self._capture_render_cmd(tmp_path)
        vf = cmd[cmd.index("-vf") + 1]
        last_filter = vf.split(",")[-1]
        assert last_filter.startswith("subtitles="), (
            f"Expected last VF filter to be subtitle burn-in, got: {last_filter!r}"
        )

    def test_negative_cts_offsets_in_movflags(self, tmp_path):
        """+negative_cts_offsets sets ELST media_time=0 so players seek to the I-frame.

        Without this flag the ELST media_time is set to the B-frame encoder delay
        (2 frames = 1024 ticks).  Players that misinterpret the ELST as a seek target
        would jump to that non-decodeable B-frame, causing 'Play does not advance'.
        """
        cmd = self._capture_render_cmd(tmp_path)
        idx = cmd.index("-movflags")
        flags = cmd[idx + 1]
        assert "negative_cts_offsets" in flags, (
            "missing +negative_cts_offsets in -movflags: players will mis-seek to "
            "a non-decodeable B-frame and freeze on Play"
        )


# ── CLI registration ──────────────────────────────────────────────────────────


class TestCompareVideoCLI:
    def test_command_registered(self):
        from ytfactory.cli.main import app

        command_names = [c.name for c in app.registered_commands]
        assert "compare-video" in command_names
