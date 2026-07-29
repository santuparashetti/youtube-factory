"""Tests for video/splitter.py — VideoSplitter cut-point selection and wiring.

FFmpeg/ffprobe subprocess calls are mocked throughout; these tests validate the
split-point algorithm, manifest contents, and command construction in
isolation from actual video/audio files. Per-scene audio durations (read via
ffprobe on audio/scene-NNN.mp3) are the ground truth the algorithm uses —
`duration_seconds` in the scene dicts is a convenience for building the mocked
ffprobe answers, mirroring what would otherwise be TTS-rendered audio length.

Algorithm under test: num_parts = ceil(total_duration / target_seconds);
ideal cut timestamps are evenly spaced (total * i / num_parts); each cut is
the scene boundary closest to its ideal timestamp, subject to a hard ceiling
— a part may never exceed target_seconds. There is no window/floor on the
search itself, only the ceiling constraint on the result.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.video.splitter import VideoSplitter


def _scenes(count: int, duration_each: float) -> list[dict]:
    return [{"index": i + 1, "duration_seconds": duration_each} for i in range(count)]


def _fake_run(durations: dict[str, float]):
    """subprocess.run replacement: answers ffprobe duration queries from
    `durations` (keyed by file basename) and no-ops ffmpeg segment calls."""

    def _run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        if cmd[0] == "ffprobe":
            basename = Path(cmd[-1]).name
            result.stdout = str(durations.get(basename, 0.0))
        return result

    return _run


def _run_split(
    tmp_path: Path,
    scenes: list[dict],
    target_minutes: float = 4.0,
    max_parts: int = 3,
    final_duration: float | None = None,
):
    """Run VideoSplitter.split() with ffprobe answering per-scene audio
    durations straight from `scene["duration_seconds"]`, and final.mp4's
    ffprobe'd duration defaulting to their sum (no drift) unless overridden.

    Returns (parts, mock_run).
    """
    audio_durations = {
        f"scene-{s['index']:03d}.mp3": s["duration_seconds"] for s in scenes
    }
    if final_duration is None:
        final_duration = sum(audio_durations.values())

    durations = dict(audio_durations)
    durations["final.mp4"] = final_duration

    with patch(
        "ytfactory.video.splitter.subprocess.run", side_effect=_fake_run(durations)
    ) as mock_run:
        parts = VideoSplitter().split(
            input_path=tmp_path / "final.mp4",
            scenes=scenes,
            output_dir=tmp_path,
            audio_dir=tmp_path / "audio",
            target_minutes=target_minutes,
            max_parts=max_parts,
        )
    return parts, mock_run


class TestSplitPointArithmetic:
    def test_534s_video_splits_into_three_parts_near_ideal_timestamps(self, tmp_path):
        # 534s total, target 4min (240s) -> num_parts = ceil(534/240) = 3.
        # Ideal timestamps: 534*1/3=178.0, 534*2/3=356.0. 6 scenes of 89s each
        # put exact scene boundaries at those ideals (2*89=178, 4*89=356).
        scenes = _scenes(6, 89.0)
        parts, _ = _run_split(tmp_path, scenes, target_minutes=4.0)

        assert len(parts) == 3
        manifest = json.loads((tmp_path / "split_manifest.json").read_text())
        ends = [p["end_seconds"] for p in manifest["parts"]]
        assert ends[0] == pytest.approx(178.0)
        assert ends[1] == pytest.approx(356.0)
        assert ends[2] == pytest.approx(534.0)
        durations = [e - s for s, e in zip([0.0] + ends[:-1], ends)]
        assert all(d <= 240.0 for d in durations)

    def test_444s_video_splits_into_two_parts_near_ideal_timestamp(self, tmp_path):
        # 444s total, target 4min -> num_parts = ceil(444/240) = 2.
        # Ideal timestamp: 444/2=222.0. 12 scenes of 37s each put an exact
        # scene boundary there (6*37=222).
        scenes = _scenes(12, 37.0)
        parts, _ = _run_split(tmp_path, scenes, target_minutes=4.0)

        assert len(parts) == 2
        manifest = json.loads((tmp_path / "split_manifest.json").read_text())
        assert manifest["parts"][0]["end_seconds"] == pytest.approx(222.0)
        assert manifest["parts"][1]["end_seconds"] == pytest.approx(444.0)
        durations = [p["end_seconds"] - p["start_seconds"] for p in manifest["parts"]]
        assert all(d <= 240.0 for d in durations)

    def test_400s_video_splits_into_two_parts_near_ideal_timestamp(self, tmp_path):
        # 400s total, target 4min -> num_parts = ceil(400/240) = 2.
        # Ideal timestamp: 400/2=200.0. 10 scenes of 40s each put an exact
        # scene boundary there (5*40=200).
        scenes = _scenes(10, 40.0)
        parts, _ = _run_split(tmp_path, scenes, target_minutes=4.0)

        assert len(parts) == 2
        manifest = json.loads((tmp_path / "split_manifest.json").read_text())
        assert manifest["parts"][0]["end_seconds"] == pytest.approx(200.0)
        assert manifest["parts"][1]["end_seconds"] == pytest.approx(400.0)
        durations = [p["end_seconds"] - p["start_seconds"] for p in manifest["parts"]]
        assert all(d <= 240.0 for d in durations)

    def test_hard_ceiling_forces_earlier_boundary_when_closest_would_exceed_target(
        self, tmp_path
    ):
        # 650s total, target 4min (240s) -> num_parts = ceil(650/240) = 3.
        # Ideals: 216.67 and 433.33. Scene boundaries: 198, 410, 450.
        # For the 2nd cut, the boundary naively closest to ideal (433.33) is
        # 450 (diff 16.67) -- but 450 is 252s after the first cut (198),
        # which would exceed the 240s ceiling. The algorithm must walk back
        # to 410 (diff 23.33, still eligible: 410-198=212s <= 240s) instead.
        scenes = _scenes(1, 198.0) + [
            {"index": 2, "duration_seconds": 212.0},  # boundary 410 (correct pick)
            {"index": 3, "duration_seconds": 40.0},  # boundary 450 (naive/decoy pick)
            {"index": 4, "duration_seconds": 200.0},  # total 650
        ]
        parts, _ = _run_split(tmp_path, scenes, target_minutes=4.0)

        assert len(parts) == 3
        manifest = json.loads((tmp_path / "split_manifest.json").read_text())
        ends = [p["end_seconds"] for p in manifest["parts"]]
        assert ends[0] == pytest.approx(198.0)
        # 410, not the naively-closer-but-invalid 450.
        assert ends[1] == pytest.approx(410.0)
        assert ends[2] == pytest.approx(650.0)
        durations = [e - s for s, e in zip([0.0] + ends[:-1], ends)]
        assert all(d <= 240.0 for d in durations)

    def test_no_split_when_total_duration_fits_single_part(self, tmp_path):
        # 200s total <= 240s target -> num_parts = ceil(200/240) = 1, no split.
        scenes = _scenes(8, 25.0)  # 200s total
        parts, _ = _run_split(tmp_path, scenes, target_minutes=4.0)

        assert parts == []
        assert not (tmp_path / "split_manifest.json").exists()
        assert not (tmp_path / "final_part1.mp4").exists()

    def test_micro_tail_absorption_that_would_violate_ceiling_is_refused(self, tmp_path):
        # 250s total, target 4min -> num_parts=2, ideal=125. Only one interior
        # scene boundary (200s) exists, so it's picked regardless of distance
        # from ideal. Remaining tail (250-200=50s) is < 60s, so absorption
        # merges it into the previous part — but that merge (200+50=250s)
        # exceeds the 240s ceiling, so the hard invariant correctly refuses
        # the split rather than silently keeping an over-long part.
        #
        # This isn't a corner case: since num_parts is the *minimum* count
        # satisfying total <= num_parts * target, absorbing the final split
        # always pushes the merged tail past target_seconds (total is always
        # > (num_parts-1)*target, which is exactly the merged tail's lower
        # bound). Tail absorption can only ever succeed under this algorithm
        # when it doesn't get triggered in the first place.
        scenes = [
            {"index": 1, "duration_seconds": 200.0},
            {"index": 2, "duration_seconds": 50.0},
        ]
        with patch("ytfactory.video.splitter.logger") as mock_logger:
            parts, _ = _run_split(tmp_path, scenes, target_minutes=4.0)

        assert parts == []
        assert not (tmp_path / "split_manifest.json").exists()
        assert mock_logger.error.called

    def test_max_parts_exceeded_refuses_to_split(self, tmp_path):
        # 800s total, target 4min -> num_parts = ceil(800/240) = 4, which
        # exceeds the default max_parts=3 -> refuse rather than force fewer,
        # over-long parts.
        scenes = _scenes(20, 40.0)  # 800s total
        with patch("ytfactory.video.splitter.logger") as mock_logger:
            parts, _ = _run_split(tmp_path, scenes, target_minutes=4.0, max_parts=3)

        assert parts == []
        assert not (tmp_path / "split_manifest.json").exists()
        assert mock_logger.error.called


class TestFFmpegCommand:
    def test_ffmpeg_flags_present(self, tmp_path):
        scenes = _scenes(10, 40.0)
        _, mock_run = _run_split(tmp_path, scenes, target_minutes=4.0)

        ffmpeg_calls = [
            call.args[0] for call in mock_run.call_args_list if call.args[0][0] == "ffmpeg"
        ]
        assert ffmpeg_calls
        cmd = ffmpeg_calls[0]
        assert "-ss" in cmd
        assert "-t" in cmd
        assert "-c" in cmd and "copy" in cmd
        assert "-avoid_negative_ts" in cmd and "make_zero" in cmd


class TestSplitManifest:
    def test_manifest_fields(self, tmp_path):
        scenes = _scenes(10, 40.0)
        _run_split(tmp_path, scenes, target_minutes=4.0)

        manifest = json.loads((tmp_path / "split_manifest.json").read_text())
        assert "parts" in manifest
        for i, part in enumerate(manifest["parts"], start=1):
            assert part["part"] == i
            assert part["path"] == f"final_part{i}.mp4"
            assert "start_seconds" in part
            assert "end_seconds" in part
            assert "scene_count" in part

        total_scene_count = sum(p["scene_count"] for p in manifest["parts"])
        assert total_scene_count == len(scenes)


class TestSettingsWiring:
    def test_video_split_disabled_by_default(self):
        # Check the Field default directly rather than instantiating
        # SharedSettings(), which would load the real local .env and could
        # pick up a developer's opt-in override.
        from video_core.config.shared_settings import SharedSettings

        assert SharedSettings.model_fields["video_split_enabled"].default is False
        assert SharedSettings.model_fields["video_split_length_minutes"].default == 4.0

    def test_splitter_never_instantiated_when_disabled(self):
        from ytfactory.build.pipeline import BuildPipeline

        pipeline = BuildPipeline.__new__(BuildPipeline)
        pipeline.settings = type(
            "S", (), {"video_split_enabled": False, "video_split_length_minutes": 4.0}
        )()

        with patch("ytfactory.video.splitter.VideoSplitter") as mock_splitter_cls:
            pipeline._maybe_split_video("nonexistent-project")

        mock_splitter_cls.assert_not_called()


class TestNoSplitLogging:
    def test_info_logged_when_total_duration_fits_single_part(self, tmp_path):
        scenes = _scenes(8, 25.0)  # 200s total <= 240s target -> no split
        with patch("ytfactory.video.splitter.logger") as mock_logger:
            _run_split(tmp_path, scenes, target_minutes=4.0)
            assert mock_logger.info.called


class TestDurationDriftGuard:
    def test_drift_above_five_percent_refuses_to_split(self, tmp_path):
        # Per-scene actual audio sums to 400s, but final.mp4's real ffprobe'd
        # duration is 460s (15% higher) — mirrors the real bug where
        # scene-plan.json's stale planning estimate would have overstated
        # the real timeline. Any drift beyond 5% must refuse to split rather
        # than emit cut points that don't correspond to the real file.
        scenes = _scenes(10, 40.0)  # sums to 400s
        with patch("ytfactory.video.splitter.logger") as mock_logger:
            parts, _ = _run_split(
                tmp_path, scenes, target_minutes=4.0, final_duration=460.0
            )

        assert parts == []
        assert not (tmp_path / "split_manifest.json").exists()
        assert mock_logger.error.called

    def test_drift_within_five_percent_still_splits(self, tmp_path):
        # 400s of scene audio vs a 410s final.mp4 (2.5% drift) is within
        # tolerance — the existing split behaviour should proceed normally.
        scenes = _scenes(10, 40.0)  # sums to 400s
        parts, _ = _run_split(tmp_path, scenes, target_minutes=4.0, final_duration=410.0)

        assert len(parts) >= 1
        manifest = json.loads((tmp_path / "split_manifest.json").read_text())
        # Last boundary is pinned to the real final.mp4 duration, not the
        # per-scene sum, so no part is truncated short of true EOF.
        assert manifest["parts"][-1]["end_seconds"] == pytest.approx(410.0)
