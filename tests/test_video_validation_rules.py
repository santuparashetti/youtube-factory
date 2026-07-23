"""Tests for Video Validation Rules V1.

Coverage:
  - ValidationResult / ValidationReport models
  - ValidationRulesConfig / RuleConfig
  - BaseValidator helpers
  - All 8 category validators (Script, Narration, Subtitle, Image, Motion,
    Audio, Rendering, Story)
  - ValidationRunner orchestration
  - ValidationReporter persistence
  - Engine integration (ValidationRunner wired into VideoQualityReviewEngine)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ytfactory.review.validation.config import RuleConfig, ValidationRulesConfig
from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationReport, ValidationResult
from ytfactory.review.validation.reporter import ValidationReporter
from ytfactory.review.validation.rules.audio import AudioValidator
from ytfactory.review.validation.rules.image import ImageValidator
from ytfactory.review.validation.rules.motion import MotionValidator
from ytfactory.review.validation.rules.narration import NarrationValidator
from ytfactory.review.validation.rules.rendering import RenderingValidator
from ytfactory.review.validation.rules.script import ScriptValidator
from ytfactory.review.validation.rules.story import StoryValidator
from ytfactory.review.validation.rules.subtitle import SubtitleValidator
from ytfactory.review.validation.runner import ValidationRunner


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def cfg() -> ValidationRulesConfig:
    return ValidationRulesConfig()


@pytest.fixture()
def scene() -> dict:
    return {
        "index": 1,
        "title": "Introduction",
        "scene_type": "generated_image",
        "narration": "This is the opening narration with enough words to pass validation checks.",
        "visual_prompt": "Cinematic wide shot, dramatic lighting, high quality, 4k resolution",
        "shot_type": "wide_shot",
        "transition": "fade",
        "duration_seconds": 10.0,
        "motion": {"motion_type": "push_in", "drift_x": 0.0, "drift_y": 0.0},
    }


@pytest.fixture()
def scenes(scene) -> list[dict]:
    return [
        scene,
        {
            "index": 2,
            "title": "Main Content",
            "scene_type": "generated_image",
            "narration": "The second scene narration provides detailed information about the topic.",
            "visual_prompt": "Close-up portrait, natural lighting, sharp focus, photorealistic",
            "shot_type": "close_up",
            "transition": "cut",
            "duration_seconds": 15.0,
            "motion": {"motion_type": "drift", "drift_x": 0.02, "drift_y": 0.0},
        },
        {
            "index": 3,
            "title": "Conclusion",
            "scene_type": "generated_image",
            "narration": "The concluding narration wraps up the key points from this video.",
            "visual_prompt": "Aerial wide shot, cinematic, high resolution, documentary style",
            "shot_type": "aerial_shot",
            "transition": "dissolve",
            "duration_seconds": 12.0,
            "motion": {"motion_type": "pull_out", "drift_x": 0.0, "drift_y": 0.0},
        },
    ]


@pytest.fixture()
def proj(tmp_path) -> Path:
    """Minimal project directory with all required assets."""
    for d in ("script", "scenes", "images", "audio", "subtitles", "video", "review"):
        (tmp_path / d).mkdir()

    # Script — must be >= 200 words to pass SCRIPT_002
    script_body = " ".join([
        "Introduction to the topic.",
        "This script covers the historical background and context of the subject.",
        "The first section introduces the main topic with a comprehensive overview.",
        "Historical events shaped the course of development significantly.",
        "The second section provides detailed analysis of key factors involved.",
        "Economic considerations played a major role in the final outcome.",
        "Political dynamics influenced every major decision along the way.",
        "Cultural factors cannot be overlooked when examining this period.",
        "The third section concludes the discussion with a synthesis of findings.",
        "Important lessons learned from this period remain relevant today.",
        "Scholars continue to debate the long-term significance of these events.",
        "Modern perspectives offer new insights into historical developments.",
        "The impact of these changes continues to be felt in contemporary society.",
        "Future research will undoubtedly uncover additional important details.",
        "This script provides a comprehensive overview of the entire subject matter.",
        "Each scene narration was carefully crafted to match the visual content.",
        "The documentary approach ensures an engaging and educational experience.",
        "Viewers will gain a deeper appreciation of the topic after watching.",
        "The production team worked hard to verify all historical facts presented.",
        "This concludes the main body of the script for this production project.",
        "The narrative arc is designed to inform and engage the audience throughout.",
        "Thank you for watching this comprehensive historical documentary production.",
    ])
    (tmp_path / "script" / "script.md").write_text(script_body, encoding="utf-8")

    # Images
    for i in range(1, 4):
        (tmp_path / "images" / f"scene-{i:03d}.png").write_bytes(b"\x89PNG" + b"\x00" * 2000)

    # Audio
    for i in range(1, 4):
        (tmp_path / "audio" / f"scene-{i:03d}.mp3").write_bytes(b"ID3" + b"\x00" * 6000)

    # Subtitles
    srt_content = (
        "1\n00:00:00,000 --> 00:00:03,000\nThis is the opening narration\n\n"
        "2\n00:00:03,500 --> 00:00:07,000\nwith enough words to pass\n"
    )
    for i in range(1, 4):
        (tmp_path / "subtitles" / f"scene-{i:03d}.srt").write_text(srt_content, encoding="utf-8")

    # Video clips
    for i in range(1, 4):
        (tmp_path / "video" / f"scene-{i:03d}.mp4").write_bytes(b"\x00" * 15_000)

    # Final video
    (tmp_path / "video" / "final.mp4").write_bytes(b"\x00" * 200_000)

    return tmp_path


# ── TestValidationResult ──────────────────────────────────────────────────────


class TestValidationResult:
    def test_pass_result_is_not_critical(self):
        r = ValidationResult(
            rule_id="X_001",
            category="test",
            status="PASS",
            severity="low",
            description="ok",
            evidence="all good",
            confidence=1.0,
            responsible_engine="Engine",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        assert r.is_critical_failure is False
        assert r.passed is True

    def test_fail_critical_severity_is_critical(self):
        r = ValidationResult(
            rule_id="X_001",
            category="test",
            status="FAIL",
            severity="critical",
            description="bad",
            evidence="missing file",
            confidence=0.9,
            responsible_engine="Engine",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        assert r.is_critical_failure is True
        assert r.passed is False

    def test_fail_high_severity_not_critical_failure(self):
        r = ValidationResult(
            rule_id="X_001",
            category="test",
            status="FAIL",
            severity="high",
            description="bad",
            evidence="missing file",
            confidence=0.9,
            responsible_engine="Engine",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        assert r.is_critical_failure is False

    def test_skip_is_passed(self):
        r = ValidationResult(
            rule_id="X_001",
            category="test",
            status="SKIP",
            severity="low",
            description="skipped",
            evidence="not available",
            confidence=1.0,
            responsible_engine="Engine",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        assert r.passed is True

    def test_to_dict_has_required_fields(self):
        r = ValidationResult(
            rule_id="X_001",
            category="test",
            status="PASS",
            severity="low",
            description="ok",
            evidence="all good",
            confidence=1.0,
            responsible_engine="Engine",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        d = r.to_dict()
        required = {
            "rule_id", "category", "status", "severity", "description",
            "evidence", "confidence", "responsible_engine", "timestamp",
            "scene_index", "timestamp_seconds", "debug_metadata",
        }
        assert required <= set(d.keys())


# ── TestValidationReport ──────────────────────────────────────────────────────


class TestValidationReport:
    def test_empty_report_passes(self):
        r = ValidationReport(project_id="p", timestamp="t")
        assert r.verdict == "PASS"

    def test_report_with_critical_fails(self):
        fail = ValidationResult(
            rule_id="X_001", category="test", status="FAIL", severity="critical",
            description="x", evidence="x", confidence=0.9,
            responsible_engine="E", timestamp="t",
        )
        r = ValidationReport(project_id="p", timestamp="t", critical_failures=[fail])
        assert r.verdict == "FAIL"

    def test_to_dict_includes_verdict(self):
        r = ValidationReport(project_id="p", timestamp="t")
        d = r.to_dict()
        assert d["verdict"] == "PASS"
        assert "results" in d
        assert "category_scores" in d

    def test_to_dict_serializes_critical_failures(self):
        fail = ValidationResult(
            rule_id="X_001", category="test", status="FAIL", severity="critical",
            description="x", evidence="x", confidence=0.9,
            responsible_engine="E", timestamp="t",
        )
        r = ValidationReport(project_id="p", timestamp="t", critical_failures=[fail])
        d = r.to_dict()
        assert len(d["critical_failures"]) == 1
        assert d["critical_failures"][0]["rule_id"] == "X_001"


# ── TestValidationRulesConfig ─────────────────────────────────────────────────


class TestValidationRulesConfig:
    def test_defaults(self):
        c = ValidationRulesConfig()
        assert c.enabled is True
        assert c.story_min_scenes == 3
        assert c.subtitle_max_cps == 18.0

    def test_global_disable_prevents_rules(self):
        c = ValidationRulesConfig(enabled=False)
        assert c.is_enabled("SCRIPT_001") is False

    def test_per_rule_disable(self):
        c = ValidationRulesConfig(rules={"SCRIPT_001": RuleConfig(enabled=False)})
        assert c.is_enabled("SCRIPT_001") is False
        assert c.is_enabled("SCRIPT_002") is True

    def test_severity_override(self):
        c = ValidationRulesConfig(rules={"SCRIPT_001": RuleConfig(severity="low")})
        assert c.severity_for("SCRIPT_001", "critical") == "low"

    def test_severity_default_when_no_override(self):
        c = ValidationRulesConfig()
        assert c.severity_for("SCRIPT_001", "critical") == "critical"

    def test_threshold_override(self):
        c = ValidationRulesConfig(rules={"IMG_004": RuleConfig(threshold=0.9)})
        assert c.threshold_for("IMG_004", 0.5) == 0.9

    def test_threshold_default_when_no_override(self):
        c = ValidationRulesConfig()
        assert c.threshold_for("IMG_004", 0.5) == 0.5


# ── Concrete BaseValidator for testing ────────────────────────────────────────


class _AlwaysPassValidator(BaseValidator):
    category = "test"
    responsible_engine = "TestEngine"

    def validate(self, project_dir, scenes, context):
        return [self._pass("TEST_001", "always passes")]


class _AlwaysFailValidator(BaseValidator):
    category = "test"
    responsible_engine = "TestEngine"

    def validate(self, project_dir, scenes, context):
        return [self._fail("TEST_001", "always fails", "evidence", "critical")]


class _RaisesValidator(BaseValidator):
    category = "test"
    responsible_engine = "TestEngine"

    def validate(self, project_dir, scenes, context):
        raise RuntimeError("boom")


class TestBaseValidator:
    def test_pass_builder(self, tmp_path, cfg):
        v = _AlwaysPassValidator(cfg)
        results = v.validate(tmp_path, [], {})
        assert len(results) == 1
        assert results[0].status == "PASS"

    def test_fail_builder(self, tmp_path, cfg):
        v = _AlwaysFailValidator(cfg)
        results = v.validate(tmp_path, [], {})
        assert results[0].status == "FAIL"
        assert results[0].severity == "critical"

    def test_skip_builder(self, tmp_path, cfg):
        v = _AlwaysPassValidator(cfg)
        r = v._skip("TEST_001", "reason")
        assert r.status == "SKIP"
        assert r.evidence == "reason"

    def test_warn_builder(self, tmp_path, cfg):
        v = _AlwaysPassValidator(cfg)
        r = v._warn("TEST_001", "desc", "evid", "medium")
        assert r.status == "WARNING"
        assert r.severity == "medium"


# ── TestScriptValidator ───────────────────────────────────────────────────────


class TestScriptValidator:
    def test_missing_script_is_critical(self, tmp_path, cfg):
        v = ScriptValidator(cfg)
        results = v.validate(tmp_path, [], {})
        rule = next(r for r in results if r.rule_id == "SCRIPT_001")
        assert rule.status == "FAIL"
        assert rule.severity == "critical"

    def test_empty_script_is_critical(self, tmp_path, cfg):
        (tmp_path / "script").mkdir()
        (tmp_path / "script" / "script.md").write_text("", encoding="utf-8")
        v = ScriptValidator(cfg)
        results = v.validate(tmp_path, [], {})
        rule = next(r for r in results if r.rule_id == "SCRIPT_001")
        assert rule.status == "FAIL"

    def test_valid_script_passes(self, proj, cfg, scenes):
        v = ScriptValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "SCRIPT_001")
        assert rule.status == "PASS"

    def test_word_count_ok(self, proj, cfg, scenes):
        v = ScriptValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "SCRIPT_002")
        assert rule.status == "PASS"

    def test_word_count_too_short(self, tmp_path, cfg):
        (tmp_path / "script").mkdir()
        (tmp_path / "script" / "script.md").write_text(
            "Short. Script. Three sentences here.", encoding="utf-8"
        )
        v = ScriptValidator(cfg)
        results = v.validate(tmp_path, [], {})
        rule = next(r for r in results if r.rule_id == "SCRIPT_002")
        assert rule.status == "FAIL"
        assert rule.severity == "high"

    def test_word_count_too_long_is_warning(self, tmp_path, cfg):
        (tmp_path / "script").mkdir()
        long_text = ("word " * 6000).strip()
        (tmp_path / "script" / "script.md").write_text(long_text, encoding="utf-8")
        v = ScriptValidator(cfg)
        results = v.validate(tmp_path, [], {})
        rule = next(r for r in results if r.rule_id == "SCRIPT_002")
        assert rule.status == "WARNING"

    def test_no_repeated_paragraphs_passes(self, proj, cfg, scenes):
        v = ScriptValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "SCRIPT_003")
        assert rule.status == "PASS"

    def test_disabled_rule_absent_from_results(self, proj, scenes):
        cfg = ValidationRulesConfig(rules={"SCRIPT_003": RuleConfig(enabled=False)})
        v = ScriptValidator(cfg)
        results = v.validate(proj, scenes, {})
        # A disabled rule produces no output — it is silently omitted
        assert not any(r.rule_id == "SCRIPT_003" for r in results)

    def test_min_sentence_count_fails_trivial_script(self, tmp_path):
        cfg = ValidationRulesConfig(script_min_words=1, script_min_sentences=5)
        (tmp_path / "script").mkdir()
        (tmp_path / "script" / "script.md").write_text("One sentence only", encoding="utf-8")
        v = ScriptValidator(cfg)
        results = v.validate(tmp_path, [], {})
        rule = next(r for r in results if r.rule_id == "SCRIPT_004")
        assert rule.status == "FAIL"


# ── TestNarrationValidator ────────────────────────────────────────────────────


class TestNarrationValidator:
    def test_passes_with_good_scenes(self, proj, cfg, scenes):
        v = NarrationValidator(cfg)
        results = v.validate(proj, scenes, {})
        narr1 = [r for r in results if r.rule_id == "NARR_001" and r.scene_index == 1]
        assert narr1[0].status == "PASS"

    def test_missing_narration_is_critical(self, proj, cfg):
        bad_scenes = [{"index": 1, "narration": "", "title": "X", "duration_seconds": 10.0}]
        v = NarrationValidator(cfg)
        results = v.validate(proj, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "NARR_001")
        assert rule.status == "FAIL"
        assert rule.severity == "critical"

    def test_no_scenes_produces_skips(self, proj, cfg):
        v = NarrationValidator(cfg)
        results = v.validate(proj, [], {})
        assert all(r.status == "SKIP" for r in results)

    def test_word_count_too_short(self, proj):
        cfg = ValidationRulesConfig(narration_min_words=50)
        bad_scenes = [{"index": 1, "narration": "short", "title": "X", "duration_seconds": 10.0}]
        v = NarrationValidator(cfg)
        results = v.validate(proj, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "NARR_002")
        assert rule.status == "FAIL"

    def test_pacing_warning_when_avg_words_low(self, proj):
        cfg = ValidationRulesConfig(narration_min_words=1)
        bad_scenes = [
            {"index": 1, "narration": "one two", "title": "X", "duration_seconds": 5.0},
            {"index": 2, "narration": "three four", "title": "Y", "duration_seconds": 5.0},
        ]
        v = NarrationValidator(cfg)
        results = v.validate(proj, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "NARR_004")
        assert rule.status == "WARNING"

    def test_natural_pacing_passes_with_good_scenes(self, proj, cfg, scenes):
        v = NarrationValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "NARR_004")
        assert rule.status == "PASS"

    def test_single_long_block_warning(self, proj):
        cfg = ValidationRulesConfig(narration_max_single_block_words=5)
        bad_scenes = [
            {
                "index": 1,
                "narration": "one two three four five six seven eight nine ten",
                "title": "X",
                "duration_seconds": 10.0,
            }
        ]
        v = NarrationValidator(cfg)
        results = v.validate(proj, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "NARR_003")
        assert rule.status == "WARNING"


# ── TestSubtitleValidator ─────────────────────────────────────────────────────


class TestSubtitleValidator:
    def test_srt_exists_passes(self, proj, cfg, scenes):
        v = SubtitleValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "SUBT_001" and r.scene_index == 1)
        assert rule.status == "PASS"

    def test_missing_srt_is_critical(self, tmp_path, cfg):
        (tmp_path / "subtitles").mkdir()
        bad_scenes = [{"index": 1, "narration": "hello", "duration_seconds": 5.0}]
        v = SubtitleValidator(cfg)
        results = v.validate(tmp_path, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "SUBT_001")
        assert rule.status == "FAIL"
        assert rule.severity == "critical"

    def test_no_overlapping_timestamps_passes(self, proj, cfg, scenes):
        v = SubtitleValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "SUBT_002" and r.scene_index == 1)
        assert rule.status == "PASS"

    def test_overlapping_timestamps_fails(self, tmp_path, cfg):
        (tmp_path / "subtitles").mkdir()
        bad_srt = (
            "1\n00:00:00,000 --> 00:00:05,000\nFirst cue\n\n"
            "2\n00:00:03,000 --> 00:00:08,000\nSecond overlaps\n"  # overlaps first
        )
        (tmp_path / "subtitles" / "scene-001.srt").write_text(bad_srt, encoding="utf-8")
        bad_scenes = [{"index": 1, "narration": "First cue second overlaps", "duration_seconds": 8.0}]
        v = SubtitleValidator(cfg)
        results = v.validate(tmp_path, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "SUBT_002")
        assert rule.status == "FAIL"

    def test_no_empty_cues_passes(self, proj, cfg, scenes):
        v = SubtitleValidator(cfg)
        results = v.validate(proj, scenes, {})
        subt5 = [r for r in results if r.rule_id == "SUBT_005"]
        assert all(r.status == "PASS" for r in subt5)

    def test_no_scenes_produces_skips(self, proj, cfg):
        v = SubtitleValidator(cfg)
        results = v.validate(proj, [], {})
        assert all(r.status == "SKIP" for r in results)

    def test_chars_per_line_ok(self, proj, cfg, scenes):
        v = SubtitleValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "SUBT_004" and r.scene_index == 1)
        assert rule.status == "PASS"

    def test_subtitle_narration_overlap_skipped_for_short_narration(self, tmp_path, cfg):
        (tmp_path / "subtitles").mkdir()
        srt = "1\n00:00:00,000 --> 00:00:03,000\nHello world\n"
        (tmp_path / "subtitles" / "scene-001.srt").write_text(srt, encoding="utf-8")
        scenes = [{"index": 1, "narration": "hi", "duration_seconds": 3.0}]
        v = SubtitleValidator(cfg)
        results = v.validate(tmp_path, scenes, {})
        rule = next(r for r in results if r.rule_id == "SUBT_006")
        assert rule.status == "SKIP"


# ── TestImageValidator ────────────────────────────────────────────────────────


class TestImageValidator:
    def test_image_exists_passes(self, proj, cfg, scenes):
        v = ImageValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "IMG_001" and r.scene_index == 1)
        assert rule.status == "PASS"

    def test_missing_image_critical(self, tmp_path, cfg):
        (tmp_path / "images").mkdir()
        bad_scenes = [{"index": 1, "scene_type": "generated_image", "visual_prompt": "a", "duration_seconds": 5.0}]
        v = ImageValidator(cfg)
        results = v.validate(tmp_path, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "IMG_001")
        assert rule.status == "FAIL"
        assert rule.severity == "critical"

    def test_visual_prompt_present_passes(self, proj, cfg, scenes):
        v = ImageValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "IMG_003" and r.scene_index == 1)
        assert rule.status == "PASS"

    def test_missing_visual_prompt_fails(self, proj, cfg):
        bad_scenes = [
            {"index": 1, "scene_type": "generated_image", "visual_prompt": "", "duration_seconds": 5.0}
        ]
        v = ImageValidator(cfg)
        results = v.validate(proj, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "IMG_003")
        assert rule.status == "FAIL"

    def test_no_repeated_prompts_passes(self, proj, cfg, scenes):
        v = ImageValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "IMG_004")
        assert rule.status == "PASS"

    def test_repeated_prompts_warning(self, proj, cfg):
        identical_prompt = "cinematic wide shot dramatic lighting"
        dupe_scenes = [
            {"index": 1, "scene_type": "generated_image", "visual_prompt": identical_prompt, "duration_seconds": 5.0},
            {"index": 2, "scene_type": "generated_image", "visual_prompt": identical_prompt, "duration_seconds": 5.0},
        ]
        v = ImageValidator(cfg)
        results = v.validate(proj, dupe_scenes, {})
        rule = next(r for r in results if r.rule_id == "IMG_004")
        assert rule.status == "WARNING"

    def test_style_markers_detected(self, proj, cfg, scenes):
        v = ImageValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "IMG_006" and r.scene_index == 1)
        assert rule.status == "PASS"

    def test_missing_style_markers_warns(self, proj, cfg):
        bad_scenes = [
            {
                "index": 1,
                "scene_type": "generated_image",
                "visual_prompt": "a simple picture of a dog",
                "duration_seconds": 5.0,
            }
        ]
        v = ImageValidator(cfg)
        results = v.validate(proj, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "IMG_006")
        assert rule.status == "WARNING"


# ── Helpers for per-image brightness tests ─────────────────────────────────────


def _write_test_image(path: Path, brightness: int, size: tuple[int, int] = (64, 64)) -> None:
    """Write a solid-gray PNG with the given 0-255 brightness."""
    from PIL import Image
    img = Image.new("L", size, brightness)
    img.save(path)


# ── TestSceneAssetChecks ───────────────────────────────────────────────────────


class TestSceneAssetChecks:
    """IMG_007 (static-hold cap) and IMG_008 (brightness floor)."""

    def test_static_long_hold_scene_flagged(self, tmp_path, cfg):
        for d in ("script", "images"):
            (tmp_path / d).mkdir()
        (tmp_path / "script" / "script.md").write_text("word " * 200, encoding="utf-8")
        _write_test_image(tmp_path / "images" / "scene-001.png", brightness=128)
        _write_test_image(tmp_path / "images" / "scene-002.png", brightness=128)

        scenes = [
            {
                "index": 1,
                "scene_type": "generated_image",
                "visual_prompt": "Cinematic wide shot, dramatic lighting, high quality, 4k resolution",
                "duration_seconds": 12.0,
                "motion": {"motion_type": "static"},
            },
            {
                "index": 2,
                "scene_type": "generated_image",
                "visual_prompt": "Close-up portrait, natural lighting, sharp focus, photorealistic",
                "duration_seconds": 5.0,
                "motion": {"motion_type": "static"},
            },
        ]
        v = ImageValidator(cfg)
        results = v.validate(tmp_path, scenes, {})

        rule = next(r for r in results if r.rule_id == "IMG_007" and r.scene_index == 1)
        assert rule.status == "WARNING"
        assert "12.0s" in rule.description
        assert "8.0s" in rule.description

        rule2 = next(r for r in results if r.rule_id == "IMG_007" and r.scene_index == 2)
        assert rule2.status == "PASS"

    def test_dark_warmth_scene_flagged(self, tmp_path, cfg):
        for d in ("script", "images"):
            (tmp_path / d).mkdir()
        (tmp_path / "script" / "script.md").write_text("word " * 200, encoding="utf-8")
        _write_test_image(tmp_path / "images" / "scene-001.png", brightness=10)

        scenes = [
            {
                "index": 1,
                "scene_type": "generated_image",
                "visual_prompt": "Golden hour, warm light, soft shadows",
                "duration_seconds": 5.0,
                "visual_metadata": {"mood": "HOPEFUL"},
            }
        ]
        v = ImageValidator(cfg)
        results = v.validate(tmp_path, scenes, {})

        rule = next(r for r in results if r.rule_id == "IMG_008" and r.scene_index == 1)
        assert rule.status == "WARNING"
        assert "HOPEFUL" in rule.description
        assert "10." in rule.description
        assert "40." in rule.description

    def test_somber_dark_scene_not_flagged(self, tmp_path, cfg):
        for d in ("script", "images"):
            (tmp_path / d).mkdir()
        (tmp_path / "script" / "script.md").write_text("word " * 200, encoding="utf-8")
        _write_test_image(tmp_path / "images" / "scene-001.png", brightness=5)

        scenes = [
            {
                "index": 1,
                "scene_type": "generated_image",
                "visual_prompt": "Dark shadows, stormy contrast",
                "duration_seconds": 5.0,
                "visual_metadata": {"mood": "FEARFUL"},
            }
        ]
        v = ImageValidator(cfg)
        results = v.validate(tmp_path, scenes, {})

        img008_rules = [r for r in results if r.rule_id == "IMG_008"]
        assert len(img008_rules) == 1
        assert img008_rules[0].status == "SKIP"

    def test_non_static_motion_scene_skips_static_hold_check(self, tmp_path, cfg):
        for d in ("script", "images"):
            (tmp_path / d).mkdir()
        (tmp_path / "script" / "script.md").write_text("word " * 200, encoding="utf-8")
        _write_test_image(tmp_path / "images" / "scene-001.png", brightness=128)

        scenes = [
            {
                "index": 1,
                "scene_type": "generated_image",
                "visual_prompt": "Cinematic wide shot, dramatic lighting, high quality, 4k resolution",
                "duration_seconds": 20.0,
                "motion": {"motion_type": "push_in", "drift_x": 0.0, "drift_y": 0.0},
            }
        ]
        v = ImageValidator(cfg)
        results = v.validate(tmp_path, scenes, {})

        img007_rules = [r for r in results if r.rule_id == "IMG_007"]
        assert len(img007_rules) == 1
        assert img007_rules[0].status == "SKIP"
        assert "push_in" in img007_rules[0].description

    def test_normal_scene_passes_both_checks(self, tmp_path, cfg):
        for d in ("script", "images"):
            (tmp_path / d).mkdir()
        (tmp_path / "script" / "script.md").write_text("word " * 200, encoding="utf-8")
        _write_test_image(tmp_path / "images" / "scene-001.png", brightness=150)

        scenes = [
            {
                "index": 1,
                "scene_type": "generated_image",
                "visual_prompt": "Cinematic wide shot, dramatic lighting, high quality, 4k resolution",
                "duration_seconds": 6.0,
                "visual_metadata": {"mood": "HOPEFUL"},
            }
        ]
        v = ImageValidator(cfg)
        results = v.validate(tmp_path, scenes, {})

        static_rules = [r for r in results if r.rule_id == "IMG_007"]
        brightness_rules = [r for r in results if r.rule_id == "IMG_008"]
        assert all(r.status == "PASS" for r in static_rules)
        assert all(r.status == "PASS" for r in brightness_rules)

    def test_missing_mood_skips_brightness_check(self, tmp_path, cfg):
        for d in ("script", "images"):
            (tmp_path / d).mkdir()
        (tmp_path / "script" / "script.md").write_text("word " * 200, encoding="utf-8")
        _write_test_image(tmp_path / "images" / "scene-001.png", brightness=5)

        scenes = [
            {
                "index": 1,
                "scene_type": "generated_image",
                "visual_prompt": "Cinematic wide shot, dramatic lighting",
                "duration_seconds": 5.0,
            }
        ]
        v = ImageValidator(cfg)
        results = v.validate(tmp_path, scenes, {})

        img008_rules = [r for r in results if r.rule_id == "IMG_008"]
        assert len(img008_rules) == 1
        assert img008_rules[0].status == "SKIP"


# ── TestMotionValidator ───────────────────────────────────────────────────────


class TestMotionValidator:
    def test_duration_ok_passes(self, proj, cfg, scenes):
        v = MotionValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "MOT_001" and r.scene_index == 1)
        assert rule.status == "PASS"

    def test_zero_duration_critical(self, proj, cfg):
        bad_scenes = [{"index": 1, "duration_seconds": 0.0, "narration": "x"}]
        v = MotionValidator(cfg)
        results = v.validate(proj, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "MOT_002")
        assert rule.status == "FAIL"
        assert rule.severity == "critical"

    def test_negative_duration_critical(self, proj, cfg):
        bad_scenes = [{"index": 1, "duration_seconds": -5.0, "narration": "x"}]
        v = MotionValidator(cfg)
        results = v.validate(proj, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "MOT_002")
        assert rule.status == "FAIL"

    def test_duration_too_short_fails(self, proj):
        cfg = ValidationRulesConfig(motion_min_scene_duration_seconds=10.0)
        bad_scenes = [{"index": 1, "duration_seconds": 1.0, "narration": "x", "shot_type": "wide"}]
        v = MotionValidator(cfg)
        results = v.validate(proj, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "MOT_001")
        assert rule.status == "FAIL"

    def test_duration_too_long_warns(self, proj):
        cfg = ValidationRulesConfig(motion_max_scene_duration_seconds=60.0)
        long_scenes = [{"index": 1, "duration_seconds": 90.0, "narration": "x", "shot_type": "wide"}]
        v = MotionValidator(cfg)
        results = v.validate(proj, long_scenes, {})
        rule = next(r for r in results if r.rule_id == "MOT_001")
        assert rule.status == "WARNING"

    def test_shot_type_present_passes(self, proj, cfg, scenes):
        v = MotionValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "MOT_003" and r.scene_index == 1)
        assert rule.status == "PASS"

    def test_no_shot_type_warns(self, proj, cfg):
        bad_scenes = [{"index": 1, "duration_seconds": 10.0, "narration": "x"}]
        v = MotionValidator(cfg)
        results = v.validate(proj, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "MOT_003")
        assert rule.status == "WARNING"


# ── TestAudioValidator ────────────────────────────────────────────────────────


class TestAudioValidator:
    def test_audio_exists_passes(self, proj, cfg, scenes):
        v = AudioValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "AUD_001" and r.scene_index == 1)
        assert rule.status == "PASS"

    def test_missing_audio_critical(self, tmp_path, cfg):
        (tmp_path / "audio").mkdir()
        bad_scenes = [{"index": 1, "narration": "x", "duration_seconds": 5.0}]
        v = AudioValidator(cfg)
        results = v.validate(tmp_path, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "AUD_001")
        assert rule.status == "FAIL"
        assert rule.severity == "critical"

    def test_audio_size_ok(self, proj, cfg, scenes):
        v = AudioValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "AUD_002" and r.scene_index == 1)
        assert rule.status == "PASS"

    def test_too_small_audio_fails(self, tmp_path, cfg):
        (tmp_path / "audio").mkdir()
        (tmp_path / "audio" / "scene-001.mp3").write_bytes(b"\x00" * 500)  # 500 bytes
        bad_scenes = [{"index": 1, "narration": "x", "duration_seconds": 5.0}]
        v = AudioValidator(cfg)
        results = v.validate(tmp_path, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "AUD_002")
        assert rule.status == "FAIL"

    def test_short_clip_heuristic_warns(self, tmp_path):
        cfg = ValidationRulesConfig(audio_min_size_bytes=100, audio_short_clip_bytes=5_000)
        (tmp_path / "audio").mkdir()
        (tmp_path / "audio" / "scene-001.mp3").write_bytes(b"\x00" * 200)  # > min but < short_threshold
        bad_scenes = [{"index": 1, "narration": "x", "duration_seconds": 5.0}]
        v = AudioValidator(cfg)
        results = v.validate(tmp_path, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "AUD_003")
        assert rule.status == "WARNING"

    def test_voice_clarity_always_skipped(self, proj, cfg, scenes):
        v = AudioValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "AUD_004")
        assert rule.status == "SKIP"

    def test_no_scenes_produces_skips(self, proj, cfg):
        v = AudioValidator(cfg)
        results = v.validate(proj, [], {})
        assert all(r.status == "SKIP" for r in results)


# ── TestRenderingValidator ────────────────────────────────────────────────────


class TestRenderingValidator:
    def test_clip_exists_passes(self, proj, cfg, scenes):
        v = RenderingValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "REND_001" and r.scene_index == 1)
        assert rule.status == "PASS"

    def test_missing_clip_critical(self, tmp_path, cfg):
        (tmp_path / "video").mkdir()
        bad_scenes = [{"index": 1, "narration": "x", "duration_seconds": 5.0}]
        v = RenderingValidator(cfg)
        results = v.validate(tmp_path, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "REND_001")
        assert rule.status == "FAIL"
        assert rule.severity == "critical"

    def test_final_video_exists_passes(self, proj, cfg, scenes):
        v = RenderingValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "REND_003")
        assert rule.status == "PASS"

    def test_missing_final_video_critical(self, tmp_path, cfg):
        (tmp_path / "video").mkdir()
        (tmp_path / "video" / "scene-001.mp4").write_bytes(b"\x00" * 15_000)
        bad_scenes = [{"index": 1, "narration": "x", "duration_seconds": 5.0}]
        v = RenderingValidator(cfg)
        results = v.validate(tmp_path, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "REND_003")
        assert rule.status == "FAIL"
        assert rule.severity == "critical"

    def test_all_clips_present_passes(self, proj, cfg, scenes):
        v = RenderingValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "REND_005")
        assert rule.status == "PASS"

    def test_missing_clips_reported(self, tmp_path, cfg):
        (tmp_path / "video").mkdir()
        (tmp_path / "video" / "scene-001.mp4").write_bytes(b"\x00" * 15_000)
        (tmp_path / "video" / "final.mp4").write_bytes(b"\x00" * 200_000)
        # scene 2 clip is missing
        scenes = [
            {"index": 1, "narration": "x", "duration_seconds": 5.0},
            {"index": 2, "narration": "y", "duration_seconds": 5.0},
        ]
        v = RenderingValidator(cfg)
        results = v.validate(tmp_path, scenes, {})
        rule = next(r for r in results if r.rule_id == "REND_005")
        assert rule.status == "FAIL"

    def test_small_clip_fails(self, tmp_path, cfg):
        (tmp_path / "video").mkdir()
        (tmp_path / "video" / "scene-001.mp4").write_bytes(b"\x00" * 100)  # too small
        (tmp_path / "video" / "final.mp4").write_bytes(b"\x00" * 200_000)
        bad_scenes = [{"index": 1, "narration": "x", "duration_seconds": 5.0}]
        v = RenderingValidator(cfg)
        results = v.validate(tmp_path, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "REND_002")
        assert rule.status == "FAIL"

    def test_no_scenes_produces_skips(self, proj, cfg):
        v = RenderingValidator(cfg)
        results = v.validate(proj, [], {})
        assert all(r.status == "SKIP" for r in results)

    # ── REND_006: black-frame detection ──────────────────────────────────────

    def test_rend006_passes_when_no_black_frames(self, proj, cfg, scenes, monkeypatch):
        import ytfactory.review.validation.rules.rendering as rmod
        monkeypatch.setattr(rmod, "_detect_unexpected_black_frames", lambda *a, **kw: [])
        v = RenderingValidator(cfg)
        results = v.validate(proj, scenes, {})
        rend006 = [r for r in results if r.rule_id == "REND_006"]
        assert rend006, "REND_006 results should exist"
        assert all(r.status == "PASS" for r in rend006)

    def test_rend006_fails_when_black_frames_detected(self, proj, cfg, scenes, monkeypatch):
        import ytfactory.review.validation.rules.rendering as rmod
        segment = {"start": 3.0, "end": 3.5, "duration": 0.5}
        monkeypatch.setattr(
            rmod,
            "_detect_unexpected_black_frames",
            lambda *a, **kw: [segment],
        )
        v = RenderingValidator(cfg)
        results = v.validate(proj, scenes, {})
        rend006_fails = [r for r in results if r.rule_id == "REND_006" and r.status == "FAIL"]
        assert rend006_fails, "At least one REND_006 FAIL expected"
        assert rend006_fails[0].severity == "high"
        assert "1 unexpected black segment" in rend006_fails[0].description

    def test_rend006_skips_missing_clip(self, tmp_path, cfg):
        (tmp_path / "video").mkdir()
        # No scene-001.mp4 written → clip missing
        scenes = [{"index": 1, "narration": "x", "duration_seconds": 5.0}]
        v = RenderingValidator(cfg)
        results = v.validate(tmp_path, scenes, {})
        rend006 = next((r for r in results if r.rule_id == "REND_006"), None)
        assert rend006 is not None
        assert rend006.status == "SKIP"

    def test_rend006_disabled_produces_no_results(self, proj, scenes):
        cfg_off = ValidationRulesConfig(
            rules={"REND_006": RuleConfig(enabled=False)}
        )
        v = RenderingValidator(cfg_off)
        results = v.validate(proj, scenes, {})
        assert not any(r.rule_id == "REND_006" for r in results)

    def test_rend006_skips_gracefully_on_exception(self, proj, cfg, scenes, monkeypatch):
        import ytfactory.review.validation.rules.rendering as rmod
        monkeypatch.setattr(
            rmod,
            "_detect_unexpected_black_frames",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("ffmpeg not found")),
        )
        v = RenderingValidator(cfg)
        results = v.validate(proj, scenes, {})
        rend006 = [r for r in results if r.rule_id == "REND_006"]
        assert rend006, "Should still produce REND_006 results"
        assert all(r.status == "SKIP" for r in rend006)


# ── TestStoryValidator ────────────────────────────────────────────────────────


class TestStoryValidator:
    def test_sequential_indices_passes(self, proj, cfg, scenes):
        v = StoryValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "STOR_001")
        assert rule.status == "PASS"

    def test_non_sequential_indices_fails(self, proj, cfg):
        bad_scenes = [
            {"index": 1, "narration": "x", "title": "A", "duration_seconds": 5.0},
            {"index": 3, "narration": "y", "title": "B", "duration_seconds": 5.0},
        ]
        v = StoryValidator(cfg)
        results = v.validate(proj, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "STOR_001")
        assert rule.status == "FAIL"

    def test_scene_count_ok_passes(self, proj, cfg, scenes):
        v = StoryValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "STOR_002")
        assert rule.status == "PASS"

    def test_scene_count_too_few_fails(self, proj):
        cfg = ValidationRulesConfig(story_min_scenes=5)
        bad_scenes = [{"index": i, "narration": "x", "title": f"T{i}", "duration_seconds": 5.0} for i in range(1, 4)]
        v = StoryValidator(cfg)
        results = v.validate(proj, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "STOR_002")
        assert rule.status == "FAIL"

    def test_unique_titles_passes(self, proj, cfg, scenes):
        v = StoryValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "STOR_003")
        assert rule.status == "PASS"

    def test_duplicate_titles_warns(self, proj, cfg):
        bad_scenes = [
            {"index": 1, "narration": "x", "title": "Same", "duration_seconds": 5.0},
            {"index": 2, "narration": "y", "title": "Same", "duration_seconds": 5.0},
        ]
        v = StoryValidator(cfg)
        results = v.validate(proj, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "STOR_003")
        assert rule.status == "WARNING"

    def test_narration_variation_passes(self, proj, cfg, scenes):
        v = StoryValidator(cfg)
        results = v.validate(proj, scenes, {})
        rule = next(r for r in results if r.rule_id == "STOR_004")
        assert rule.status == "PASS"

    def test_identical_narrations_warns(self, proj, cfg):
        text = "All the same narration repeated multiple times"
        bad_scenes = [
            {"index": 1, "narration": text, "title": "A", "duration_seconds": 5.0},
            {"index": 2, "narration": text, "title": "B", "duration_seconds": 5.0},
        ]
        v = StoryValidator(cfg)
        results = v.validate(proj, bad_scenes, {})
        rule = next(r for r in results if r.rule_id == "STOR_004")
        assert rule.status == "WARNING"


# ── TestValidationRunner ──────────────────────────────────────────────────────


class TestValidationRunner:
    def test_returns_validation_report(self, proj, cfg, scenes):
        runner = ValidationRunner(cfg)
        report = runner.run(proj, scenes, {})
        assert isinstance(report, ValidationReport)
        assert report.project_id == proj.name

    def test_disabled_config_returns_empty_report(self, proj, scenes):
        cfg = ValidationRulesConfig(enabled=False)
        runner = ValidationRunner(cfg)
        report = runner.run(proj, scenes, {})
        assert report.total_rules_run == 0

    def test_validator_exception_doesnt_raise(self, proj, scenes):
        # Test that a crashing validator doesn't bubble up an exception
        class _BadRunner(ValidationRunner):
            def run(self, project_dir, sc, ctx):
                from ytfactory.review.validation.models import ValidationResult
                from datetime import datetime, timezone
                import time
                t0 = time.perf_counter()
                ts = datetime.now(timezone.utc).isoformat()
                result = ValidationResult(
                    rule_id="TEST_RUNNER_ERROR", category="test",
                    status="SKIP", severity="low",
                    description="crashed", evidence="boom",
                    confidence=0.0, responsible_engine="E", timestamp=ts,
                    debug_metadata={"exception": "RuntimeError"},
                )
                return ValidationReport(
                    project_id=project_dir.name, timestamp=ts,
                    total_rules_run=1, total_skipped=1,
                    results=[result],
                    processing_time_seconds=round(time.perf_counter() - t0, 3),
                )

        bad_runner = _BadRunner()
        report = bad_runner.run(proj, scenes, {})
        assert report.total_skipped >= 1

    def test_all_categories_run(self, proj, cfg, scenes):
        runner = ValidationRunner(cfg)
        report = runner.run(proj, scenes, {})
        categories = {r.category for r in report.results}
        expected = {"script", "narration", "subtitle", "image", "motion", "audio", "rendering", "story"}
        assert expected <= categories

    def test_critical_failures_aggregated(self, tmp_path, cfg):
        (tmp_path / "script").mkdir()
        (tmp_path / "scenes").mkdir()
        runner = ValidationRunner(cfg)
        report = runner.run(tmp_path, [], {})
        # Script missing → SCRIPT_001 critical failure
        assert any(f.rule_id == "SCRIPT_001" for f in report.critical_failures)

    def test_category_scores_computed(self, proj, cfg, scenes):
        runner = ValidationRunner(cfg)
        report = runner.run(proj, scenes, {})
        assert "script" in report.category_scores
        assert 0.0 <= report.category_scores["script"] <= 1.0

    def test_processing_time_is_positive(self, proj, cfg, scenes):
        runner = ValidationRunner(cfg)
        report = runner.run(proj, scenes, {})
        assert report.processing_time_seconds >= 0.0

    def test_no_scenes_still_runs(self, proj, cfg):
        runner = ValidationRunner(cfg)
        report = runner.run(proj, [], {})
        assert report.total_rules_run > 0  # script checks run even with no scenes


# ── TestValidationReporter ────────────────────────────────────────────────────


class TestValidationReporter:
    def test_writes_json_file(self, tmp_path):
        import ytfactory.review.artifacts as art

        # Patch WORKSPACE_DIR so review_directory writes under tmp_path
        original_ws = art.WORKSPACE_DIR
        art.WORKSPACE_DIR = str(tmp_path)
        try:
            fail = ValidationResult(
                rule_id="TEST_001", category="test", status="FAIL", severity="critical",
                description="x", evidence="x", confidence=0.9,
                responsible_engine="E", timestamp="2026-01-01T00:00:00+00:00",
            )
            report = ValidationReport(
                project_id="test-proj",
                timestamp="2026-01-01T00:00:00+00:00",
                total_rules_run=3,
                total_passed=2,
                total_failed=1,
                critical_failures=[fail],
            )
            reporter = ValidationReporter()
            path = reporter.write(report)
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["project_id"] == "test-proj"
            assert data["verdict"] == "FAIL"
        finally:
            art.WORKSPACE_DIR = original_ws

    def test_json_is_valid(self, tmp_path):
        import ytfactory.review.artifacts as art
        original_ws = art.WORKSPACE_DIR
        art.WORKSPACE_DIR = str(tmp_path)
        try:
            report = ValidationReport(project_id="p", timestamp="t")
            path = ValidationReporter().write(report)
            data = json.loads(path.read_text())
            assert isinstance(data["results"], list)
        finally:
            art.WORKSPACE_DIR = original_ws

    def test_category_scores_serialized(self, tmp_path):
        import ytfactory.review.artifacts as art
        original_ws = art.WORKSPACE_DIR
        art.WORKSPACE_DIR = str(tmp_path)
        try:
            report = ValidationReport(
                project_id="p", timestamp="t", category_scores={"script": 0.75}
            )
            path = ValidationReporter().write(report)
            data = json.loads(path.read_text())
            assert data["category_scores"]["script"] == 0.75
        finally:
            art.WORKSPACE_DIR = original_ws


# ── TestEngineIntegration ─────────────────────────────────────────────────────


class TestEngineIntegration:
    def test_engine_runs_validation_and_attaches_report(self, proj, scenes, monkeypatch):
        """Validation report is attached to ReviewReport."""
        import ytfactory.review.engine as eng
        import ytfactory.review.artifacts as art

        monkeypatch.setattr(eng, "WORKSPACE_DIR", str(proj.parent))
        monkeypatch.setattr(art, "WORKSPACE_DIR", str(proj.parent))

        # Write scene-plan.json for the engine to load
        scene_plan = {"scenes": scenes}
        (proj / "scenes" / "scene-plan.json").write_text(
            json.dumps(scene_plan), encoding="utf-8"
        )
        (proj / "review").mkdir(exist_ok=True)

        from ytfactory.review.engine import VideoQualityReviewEngine
        engine = VideoQualityReviewEngine()
        report = engine.review(proj.name)
        assert report.validation_report is not None
        assert "verdict" in report.validation_report

    def test_critical_validation_failure_affects_verdict(self, tmp_path, monkeypatch):
        """Missing script → SCRIPT_001 critical → review verdict FAIL."""
        import ytfactory.review.engine as eng
        import ytfactory.review.artifacts as art

        monkeypatch.setattr(eng, "WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr(art, "WORKSPACE_DIR", str(tmp_path))

        proj_dir = tmp_path / "empty-proj"
        proj_dir.mkdir()
        (proj_dir / "scenes").mkdir()
        (proj_dir / "review").mkdir()
        # No scene-plan.json, no script → critical failure expected
        scene_plan = {"scenes": [{"index": 1, "narration": "hello", "duration_seconds": 10.0}]}
        (proj_dir / "scenes" / "scene-plan.json").write_text(json.dumps(scene_plan), encoding="utf-8")

        from ytfactory.review.engine import VideoQualityReviewEngine
        engine = VideoQualityReviewEngine()
        report = engine.review(proj_dir.name)
        # SCRIPT_001 failure should be in all_errors
        assert any("SCRIPT_001" in e for e in report.all_errors)

    def test_validation_report_json_written_to_disk(self, proj, scenes, monkeypatch):
        """validation-report.json is written into the review directory."""
        import ytfactory.review.engine as eng
        import ytfactory.review.artifacts as art

        monkeypatch.setattr(eng, "WORKSPACE_DIR", str(proj.parent))
        monkeypatch.setattr(art, "WORKSPACE_DIR", str(proj.parent))

        scene_plan = {"scenes": scenes}
        (proj / "scenes" / "scene-plan.json").write_text(json.dumps(scene_plan), encoding="utf-8")
        (proj / "review").mkdir(exist_ok=True)

        from ytfactory.review.engine import VideoQualityReviewEngine
        VideoQualityReviewEngine().review(proj.name)

        val_report = proj / "review" / "validation-report.json"
        assert val_report.exists()
        data = json.loads(val_report.read_text())
        assert "verdict" in data
        assert "category_scores" in data

    def test_backward_compatible_no_validation_config(self, proj, scenes, monkeypatch):
        """Engine still works when created without validation_config arg."""
        import ytfactory.review.engine as eng
        import ytfactory.review.artifacts as art

        monkeypatch.setattr(eng, "WORKSPACE_DIR", str(proj.parent))
        monkeypatch.setattr(art, "WORKSPACE_DIR", str(proj.parent))

        scene_plan = {"scenes": scenes}
        (proj / "scenes" / "scene-plan.json").write_text(json.dumps(scene_plan), encoding="utf-8")
        (proj / "review").mkdir(exist_ok=True)

        from ytfactory.review.engine import VideoQualityReviewEngine
        engine = VideoQualityReviewEngine()  # no validation_config — default
        report = engine.review(proj.name)
        assert hasattr(report, "validation_report")

    def test_validation_disabled_produces_empty_report(self, proj, scenes, monkeypatch):
        """When validation is disabled the validation_report has zero rules run."""
        import ytfactory.review.engine as eng
        import ytfactory.review.artifacts as art

        monkeypatch.setattr(eng, "WORKSPACE_DIR", str(proj.parent))
        monkeypatch.setattr(art, "WORKSPACE_DIR", str(proj.parent))

        scene_plan = {"scenes": scenes}
        (proj / "scenes" / "scene-plan.json").write_text(json.dumps(scene_plan), encoding="utf-8")
        (proj / "review").mkdir(exist_ok=True)

        from ytfactory.review.engine import VideoQualityReviewEngine
        from ytfactory.review.validation.config import ValidationRulesConfig
        engine = VideoQualityReviewEngine(validation_config=ValidationRulesConfig(enabled=False))
        report = engine.review(proj.name)
        assert report.validation_report["total_rules_run"] == 0
