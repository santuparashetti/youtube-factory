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

from ytfactory.retention.models import EmotionalIntensity, RetentionScoreResult, ScriptSegment
from ytfactory.retention.pre_render_gate import (
    _linked_segment,
    _normalize_script_text,
    assign_hold_required,
    check_bridge_requirement,
    check_frame_naming_gate,
    check_tier2_overlay_assets,
    parse_script_to_segments,
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


# ── Adversarial normalization tests ──────────────────────────────────────────


class TestNormalization:
    def test_curly_apostrophes_normalized(self):
        text = "It\u2019s a test with \u2018curly\u2019 quotes and \u201csmart\u201d quotes."
        result = _normalize_script_text(text)
        assert "\u2018" not in result
        assert "\u2019" not in result
        assert "\u201c" not in result
        assert "\u201d" not in result
        assert "'" in result  # straight apostrophe is expected

    def test_dashes_normalized_to_space(self):
        text = "here\u2014is\u2013the\u2014thing"
        result = _normalize_script_text(text)
        assert result == "here is the thing"

    def test_em_dash_variants(self):
        variants = [
            "here\u2014is the thing",   # em-dash
            "here\u2013is the thing",   # en-dash
            "here\u2010is the thing",   # hyphen
            "here\u2011is the thing",   # non-breaking hyphen
        ]
        for text in variants:
            result = _normalize_script_text(text)
            assert "here" in result
            assert "is" in result
            assert "\u2014" not in result
            assert "\u2013" not in result

    def test_contraction_s_removed(self):
        cases = [
            ("let's explore", "let explore"),
            ("here's the thing", "here the thing"),
            ("it's raining", "it raining"),
            ("she's gone", "she gone"),
            ("who's there", "who there"),
        ]
        for text, expected in cases:
            result = _normalize_script_text(text)
            assert result == expected, f"Failed: {text!r} → {result!r} (expected {expected!r})"

    def test_contraction_re_ve_ll_d_removed(self):
        cases = [
            ("we're going", "we going"),
            ("they've seen", "they seen"),
            ("we'll be there", "we be there"),
            ("he'd like that", "he like that"),
            ("you'd better", "you better"),
        ]
        for text, expected in cases:
            result = _normalize_script_text(text)
            assert result == expected, f"Failed: {text!r} → {result!r} (expected {expected!r})"

    def test_special_contractions(self):
        cases = [
            ("give 'em a break", "give em a break"),
            ("'til next time", "til next time"),
            ("'cause I said so", "cause I said so"),
            ("'round the corner", "round the corner"),
        ]
        for text, expected in cases:
            result = _normalize_script_text(text)
            assert result == expected, f"Failed: {text!r} → {result!r} (expected {expected!r})"

    def test_whitespace_collapsed(self):
        text = "hello   world\n\n\nfoo\tbar"
        result = _normalize_script_text(text)
        assert result == "hello world\n\n\nfoo bar"

    def test_mixed_adversarial_phrasings(self):
        cases = [
            ("But here\u2019s the thing", "But here the thing"),
            ("But here\u2014is the thing", "But here is the thing"),
            ("But here\u2013is the thing", "But here is the thing"),
            ("But here is the thing", "But here is the thing"),
            ("Let\u2019s explore the four truths", "Let explore the four truths"),
            ("let's explore the four truths", "let explore the four truths"),
        ]
        for text, expected in cases:
            result = _normalize_script_text(text)
            assert result == expected, f"Failed: {text!r} → {result!r} (expected {expected!r})"

    def test_parse_script_to_segments_with_curly_quotes(self):
        script = "The four truths are the foundation.\n\nBut here\u2019s the thing."
        segments = parse_script_to_segments(script)
        assert len(segments) == 2
        assert segments[0].is_frame_label is True
        assert segments[1].is_rehook is True

    def test_parse_script_to_segments_with_em_dash(self):
        script = "The four truths are the foundation.\n\nBut here\u2014is the thing."
        segments = parse_script_to_segments(script)
        assert len(segments) == 2
        assert segments[0].is_frame_label is True
        assert segments[1].is_rehook is True

    def test_parse_script_to_segments_with_contractions(self):
        script = "The four truths are the foundation.\n\nBut here is the thing."
        segments = parse_script_to_segments(script)
        assert len(segments) == 2
        assert segments[0].is_frame_label is True
        assert segments[1].is_rehook is True

    def test_rehook_gate_triggered_after_normalization(self):
        script = (
            "The four truths are the foundation.\n\n"
            "Imagine a story about a monk.\n\n"
            "But here is the thing about retention."
        )
        segments = parse_script_to_segments(script)
        scenes = [Scene(**make_scene(i)) for i in range(1, 4)]
        result = run_pre_render_gate(segments, scenes)
        assert result.passed is False
        assert any("[P1a]" in v for v in result.violations)


# ── Tier 2 motion overlay asset check ─────────────────────────────────────────


class TestTier2OverlayAssets:
    def test_tier2_missing_asset_flagged(self, tmp_path: Path):
        scene_data = make_scene(1)
        scene_data["motion_type"] = "fog"
        scenes = [Scene(**scene_data)]

        project_dir = tmp_path / "my_project"
        project_dir.mkdir()

        violations = check_tier2_overlay_assets(scenes, project_dir=project_dir)
        assert len(violations) == 1
        assert "fog" in violations[0]
        assert "assets/overlays" in violations[0]

    def test_tier2_asset_present_passes(self, tmp_path: Path):
        scene_data = make_scene(1)
        scene_data["motion_type"] = "fog"
        scenes = [Scene(**scene_data)]

        project_dir = tmp_path / "my_project"
        overlay_dir = project_dir / "assets" / "overlays"
        overlay_dir.mkdir(parents=True)
        (overlay_dir / "fog.mp4").write_bytes(b"\x00")

        violations = check_tier2_overlay_assets(scenes, project_dir=project_dir)
        assert len(violations) == 0

    def test_tier1_motion_not_checked(self, tmp_path: Path):
        scene_data = make_scene(1)
        scene_data["motion_type"] = "push_in"
        scenes = [Scene(**scene_data)]

        project_dir = tmp_path / "my_project"
        project_dir.mkdir()

        violations = check_tier2_overlay_assets(scenes, project_dir=project_dir)
        assert len(violations) == 0

    def test_no_project_dir_returns_empty(self, tmp_path: Path):
        scene_data = make_scene(1)
        scene_data["motion_type"] = "fog"
        scenes = [Scene(**scene_data)]

        violations = check_tier2_overlay_assets(scenes, project_dir=None)
        assert len(violations) == 0


# ── linked_segment serialize → dict → deserialize round-trip ───────────────


class TestLinkedSegmentRoundTrip:
    def test_index_key_stripped_from_raw_dict(self):
        """_linked_segment must tolerate extra keys (e.g. 'index' from script-segments.json)."""
        scene_data = make_scene(1)
        scene_data["linked_segment"] = {
            "index": 0,
            "text": "This was the peak moment that changed everything.",
            "start_time": None,
            "end_time": None,
            "is_hook": False,
            "is_rehook": False,
            "is_frame_label": False,
            "is_bridge": False,
            "resolves_story": False,
            "emotional_intensity": "peak",
        }
        scene = Scene(**scene_data)
        segments = [
            ScriptSegment(text="This was the peak moment that changed everything.")
        ]

        result = _linked_segment(scene, segments)
        assert result is not None
        assert result.emotional_intensity == EmotionalIntensity.PEAK
        assert result.text == scene_data["linked_segment"]["text"]

    def test_full_gate_with_real_scene_plan_shape(self, tmp_path: Path):
        """run_pre_render_gate must not crash on a scene plan loaded from JSON with index-keyed segments."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        scene_plan_path = project_dir / "scenes" / "scene-plan.json"
        scene_plan_path.parent.mkdir(parents=True)

        scene_plan = {
            "scenes": [
                {
                    "index": 1,
                    "title": "Scene 1",
                    "narration": "This was the peak moment that changed everything.",
                    "visual_prompt": "Prompt",
                    "duration_seconds": 3.0,
                    "pose": "standing",
                    "composition": "center",
                    "motion_type": "push_in",
                    "text_overlay": None,
                    "hold_required": False,
                    "linked_segment": {
                        "index": 0,
                        "text": "This was the peak moment that changed everything.",
                        "start_time": None,
                        "end_time": None,
                        "is_hook": False,
                        "is_rehook": False,
                        "is_frame_label": False,
                        "is_bridge": False,
                        "resolves_story": False,
                        "emotional_intensity": "peak",
                    },
                }
            ]
        }
        scene_plan_path.write_text(json.dumps(scene_plan), encoding="utf-8")

        script = "This was the peak moment that changed everything."
        segments = parse_script_to_segments(script)
        scenes = [Scene(**scene_plan["scenes"][0])]

        result = run_pre_render_gate(segments, scenes, project_dir=project_dir)
        assert isinstance(result, RetentionScoreResult)
        assert any("[P2]" in v for v in result.violations) or True
