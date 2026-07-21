"""Acceptance tests for retention QA system.

Uses synthetic fixtures because no reviewed video exists in-repo.
Each test maps to a spec §4 acceptance case.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from ytfactory.retention.models import EmotionalIntensity, ScriptSegment
from ytfactory.retention.pre_render_gate import (
    assign_hold_required,
    check_bridge_requirement,
    check_frame_naming_gate,
    run_pre_render_gate,
)
from ytfactory.review.validation.config import ValidationRulesConfig
from ytfactory.review.validation.rules.motion import MotionValidator, _analyze_static_runs
from ytfactory.review.validation.rules.story import StoryValidator
from ytfactory.scenes.models import Scene

_DEFAULT_CONFIG = ValidationRulesConfig()


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_segments(texts: list[str]) -> list[ScriptSegment]:
    return [
        ScriptSegment(
            text=t,
            is_frame_label="truth" in t.lower() or "lesson" in t.lower(),
            is_rehook="wait" in t.lower() or "but" in t.lower(),
            is_bridge="bridge" in t.lower(),
            resolves_story="end" in t.lower() or "moral" in t.lower(),
            emotional_intensity=EmotionalIntensity.PEAK if "peak" in t.lower() else EmotionalIntensity.NORMAL,
        )
        for t in texts
    ]


def make_scene(index: int, narration: str = "", duration: float = 3.0) -> dict:
    return {
        "index": index,
        "title": f"Scene {index}",
        "narration": narration,
        "visual_prompt": f"Prompt for scene {index}",
        "duration_seconds": duration,
        "pose": "standing",
        "composition": "center" if index % 3 == 0 else "rule_of_thirds",
        "motion_type": "push_in" if index % 2 == 0 else "pull_out",
        "motion": {
            "motion_type": "push_in" if index % 2 == 0 else "pull_out",
            "drift_x": 0.0,
        },
        "text_overlay": None,
        "hold_required": False,
        "linked_segment": None,
    }


# ── P1a: Frame naming gate ────────────────────────────────────────────────────


class TestFrameNamingGate:
    def test_frame_label_before_rehook_flagged(self):
        segments = make_segments([
            "The four truths are the foundation.",
            "Imagine a story about a monk.",
            "But here is the thing about suffering.",
        ])
        violations = check_frame_naming_gate(segments)
        assert len(violations) == 1
        assert "P1a" not in violations[0]  # raw violations, no tag

    def test_frame_label_after_rehook_passes(self):
        segments = make_segments([
            "Imagine a story about a monk.",
            "But here is the thing about suffering.",
            "The four truths are the foundation.",
        ])
        violations = check_frame_naming_gate(segments)
        assert len(violations) == 0

    def test_no_rehook_returns_violation(self):
        segments = make_segments([
            "The four truths are the foundation.",
            "Another statement without a hook.",
        ])
        violations = check_frame_naming_gate(segments)
        assert len(violations) == 1


# ── P4: Bridge requirement ────────────────────────────────────────────────────


class TestBridgeRequirement:
    def test_missing_bridge_flagged(self):
        segments = make_segments([
            "And so the story ended with a moral.",
            "The four truths are the foundation.",
        ])
        violations = check_bridge_requirement(segments)
        assert len(violations) == 1

    def test_bridge_present_passes(self):
        segments = make_segments([
            "And so the story ended with a moral.",
            "This is the key insight before we continue.",
            "The four truths are the foundation.",
        ])
        violations = check_bridge_requirement(segments)
        assert len(violations) == 0


# ── P5: Missing holds ─────────────────────────────────────────────────────────


class TestMissingHolds:
    def test_peak_segment_triggers_hold(self):
        scenes = [make_scene(1, "A normal moment.", 3.0)]
        segments = make_segments([
            "This was the peak moment that changed everything.",
        ])
        scenes[0]["linked_segment"] = {
            "text": segments[0].text,
            "emotional_intensity": segments[0].emotional_intensity.value,
        }

        scene_objs = [Scene(**scenes[0])]
        assign_hold_required(scene_objs, segments)
        assert scene_objs[0].hold_required is True
        assert scene_objs[0].duration_seconds == pytest.approx(4.75, abs=0.01)


# ── P7/P17: Static shot detection — unit tests (no ffmpeg/cv2 needed) ─────────


class TestStaticShotAnalysis:
    def test_motion_frames_not_flagged(self):
        deltas = [10.0, 12.0, 8.0, 15.0, 9.0]
        violations = _analyze_static_runs(deltas, threshold=2.0, frame_duration=0.5, threshold_seconds=4.0)
        assert violations == []

    def test_static_run_exceeding_threshold_flagged(self):
        deltas = [0.5, 0.3, 0.4, 0.2, 0.1, 0.3, 0.4, 0.2, 0.1, 10.0, 12.0]
        violations = _analyze_static_runs(deltas, threshold=2.0, frame_duration=0.5, threshold_seconds=4.0)
        assert len(violations) == 1
        start, end = violations[0]
        assert pytest.approx(start, abs=0.01) == 0.0
        assert pytest.approx(end, abs=0.01) == 4.5

    def test_static_run_below_threshold_not_flagged(self):
        deltas = [0.5, 0.3, 0.4, 10.0]
        violations = _analyze_static_runs(deltas, threshold=2.0, frame_duration=0.5, threshold_seconds=4.0)
        assert violations == []

    def test_trailing_static_run_flagged(self):
        deltas = [10.0, 12.0, 0.3, 0.4, 0.5, 0.1, 0.3, 0.4, 0.2, 0.1, 0.3]
        violations = _analyze_static_runs(deltas, threshold=2.0, frame_duration=0.5, threshold_seconds=4.0)
        assert len(violations) == 1
        start, end = violations[0]
        assert pytest.approx(start, abs=0.01) == 1.0
        assert pytest.approx(end, abs=0.01) == 5.5


# ── P7/P17: Static shot detection — integration test (requires ffmpeg + cv2) ────


def _create_static_shot_video(path: Path) -> None:
    """Create a 10s video: 2s color bars (motion), 7s static, 1s motion."""
    # 2s: animated gradient (motion)
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30",
            "-t", "2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(path),
        ],
        capture_output=True,
    )
    # 7s: static color (no motion) — concatenated
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=blue:size=1280x720:rate=30,duration=7",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-f", "mov", "-i", str(path),
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
            "-shortest",
            str(path),
        ],
        capture_output=True,
    )


@pytest.mark.skipif(
    os.system("command -v ffmpeg > /dev/null 2>&1") != 0,
    reason="ffmpeg required for static shot fixture",
)
class TestStaticShots:
    @pytest.fixture(scope="class")
    def static_video(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        video_path = tmp_path_factory.mktemp("motion") / "static_shot.mp4"
        _create_static_shot_video(video_path)
        return video_path

    def test_static_shot_detected(self, static_video: Path):
        try:
            import cv2  # type: ignore[import-not-found]
        except ImportError:
            pytest.skip("cv2 not installed")

        validator = MotionValidator(_DEFAULT_CONFIG)
        scenes = [make_scene(1, "Static moment.", 10.0)]
        context = {"final_video_path": str(static_video)}
        results = validator.validate(static_video.parent, scenes, context)
        static_results = [r for r in results if r.rule_id == "MOT_005" and r.status == "FAIL"]
        assert len(static_results) >= 1


# ── P11/P20: Text overlay duration ───────────────────────────────────────────


class TestTextOverlayDuration:
    def test_overlay_exceeding_5s_flagged(self):
        validator = StoryValidator(_DEFAULT_CONFIG)
        context = {
            "cta_timing_path": "tests/fixtures/cta_timing_overlong.json",
        }
        # Write a temporary cta-timing.json with >5s overlay
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "success": True,
                    "enabled": True,
                    "timing_metadata": {
                        "timestamp": 10.0,
                        "duration": 10.0,
                        "cta_end": 20.0,
                        "variant": "full",
                    },
                    "review": {"passed": True},
                },
                f,
            )
            cta_path = f.name

        try:
            context["cta_timing_path"] = cta_path
            results = validator.validate(Path("/tmp"), [make_scene(1)], context)
            overlay_results = [r for r in results if r.rule_id == "STOR_010"]
            assert len(overlay_results) == 1
            assert overlay_results[0].status == "WARNING"
        finally:
            os.unlink(cta_path)

    def test_no_overlay_passes(self):
        validator = StoryValidator(_DEFAULT_CONFIG)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "success": True,
                    "enabled": True,
                    "timing_metadata": {
                        "timestamp": 10.0,
                        "duration": 3.0,
                        "cta_end": 13.0,
                        "variant": "full",
                    },
                    "review": {"passed": True},
                },
                f,
            )
            cta_path = f.name

        try:
            context = {"cta_timing_path": cta_path}
            results = validator.validate(Path("/tmp"), [make_scene(1)], context)
            overlay_results = [r for r in results if r.rule_id == "STOR_010"]
            assert len(overlay_results) == 1
            assert overlay_results[0].status == "PASS"
        finally:
            os.unlink(cta_path)


# ── Integration: pre-render gate end-to-end ───────────────────────────────────


class TestPreRenderGateIntegration:
    def test_hard_reject_on_frame_naming(self):
        segments = make_segments([
            "The four truths are the foundation.",
            "Imagine a story about a monk.",
        ])
        scenes = [Scene(**make_scene(i)) for i in range(1, 3)]
        result = run_pre_render_gate(segments, scenes)
        assert result.passed is False
        assert any("[P1a]" in v for v in result.violations)

    def test_score_deduction_on_bridge(self):
        segments = make_segments([
            "Imagine a story about a monk.",
            "And so the story ended with a moral.",
            "The four truths are the foundation.",
        ])
        scenes = [Scene(**make_scene(i)) for i in range(1, 4)]
        result = run_pre_render_gate(segments, scenes)
        assert any("[P4]" in v for v in result.violations)
        assert result.breakdown["story_flow"] < 100.0
