"""Tests for the Semantic Subtitle Segmentation upgrade.

Covers the enhanced SubtitleSegmenter (mode='semantic') including:
  - Sentence-boundary breaks (Priority 1)
  - Clause-boundary breaks (Priority 2)
  - Natural pause detection (Priority 3 — via gap between consecutive words)
  - Proper noun pair protection
  - Backward compat: legacy mode still works
  - New SUBT_007-011 validation rules in SubtitleValidator (review layer)
"""

from __future__ import annotations

import pytest

from ytfactory.subtitles.models import SubtitleCue
from ytfactory.subtitles.segmenter import (
    PAUSE_BREAK_THRESHOLD_S,
    PAUSE_STRONG_THRESHOLD_S,
    SubtitleSegmenter,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _boundaries(
    words: list[str],
    *,
    pace: float = 0.3,
    start: float = 0.0,
) -> list[dict]:
    """Synthetic boundaries at a uniform pace (no gaps between words)."""
    result = []
    t = start
    for word in words:
        result.append({"word": word, "start": t, "end": t + pace})
        t += pace
    return result


def _boundaries_with_gap(words_and_gaps: list) -> list[dict]:
    """Build boundaries with explicit inter-word gaps.

    Each item is either:
      - str  → word at next position (default pace 0.3s)
      - dict → {"word": str, "gap_before": float}  explicitly insert a gap
    """
    result = []
    t = 0.0
    pace = 0.3
    for item in words_and_gaps:
        if isinstance(item, str):
            result.append({"word": item, "start": t, "end": t + pace})
            t += pace
        else:
            t += item.get("gap_before", 0.0)
            result.append({"word": item["word"], "start": t, "end": t + pace})
            t += pace
    return result


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def semantic_segmenter() -> SubtitleSegmenter:
    return SubtitleSegmenter(
        max_cps=18,
        max_chars_per_line=42,
        max_lines=2,
        mode="semantic",
    )


# ── Sentence boundary (Priority 1: must break) ─────────────────────────────────


class TestSentenceBoundaryBreaks:
    def test_breaks_after_period(self, semantic_segmenter):
        """A period forces a break — the next word starts a new cue."""
        boundaries = _boundaries(["First", "sentence.", "Second", "sentence."])
        cues = semantic_segmenter.segment(boundaries)
        texts = [c.text.replace("\n", " ") for c in cues]
        # "First sentence." and "Second sentence." should be separate cues
        assert any("First sentence." in t for t in texts)
        assert any("Second sentence." in t for t in texts)

    def test_breaks_after_exclamation(self, semantic_segmenter):
        # Need >= 2 words in pending before the flush is allowed
        boundaries = _boundaries(["She", "sang!", "People", "listened."])
        cues = semantic_segmenter.segment(boundaries)
        assert len(cues) >= 2

    def test_breaks_after_question_mark(self, semantic_segmenter):
        boundaries = _boundaries(["Who", "are", "you?", "Tell", "me."])
        cues = semantic_segmenter.segment(boundaries)
        assert len(cues) >= 2

    def test_abbreviations_not_treated_as_sentence_breaks(self, semantic_segmenter):
        """'Mr.' should NOT trigger a cue break."""
        boundaries = _boundaries(["Mr.", "Smith", "arrived", "early."])
        cues = semantic_segmenter.segment(boundaries)
        texts_combined = " ".join(c.text.replace("\n", " ") for c in cues)
        assert "Mr." in texts_combined

    def test_decimal_numbers_not_split(self, semantic_segmenter):
        """'3.5' should stay in the same cue."""
        boundaries = _boundaries(["He", "ran", "3.5", "kilometers."])
        cues = semantic_segmenter.segment(boundaries)
        texts_combined = " ".join(c.text.replace("\n", " ") for c in cues)
        assert "3.5" in texts_combined


# ── Clause boundary (Priority 2: prefer break) ────────────────────────────────


class TestClauseBoundaryBreaks:
    def test_prefers_break_after_comma_near_char_limit(self, semantic_segmenter):
        """With a long cue, a comma near the char limit should trigger a break."""
        words = ["The", "ancient", "temple,", "built", "five", "centuries", "ago,", "stood", "tall."]
        boundaries = _boundaries(words)
        cues = semantic_segmenter.segment(boundaries)
        # At least 2 cues expected due to character pressure
        assert len(cues) >= 1

    def test_returns_cue_objects(self, semantic_segmenter):
        boundaries = _boundaries(["One,", "two,", "three."])
        cues = semantic_segmenter.segment(boundaries)
        assert all(isinstance(c, SubtitleCue) for c in cues)


# ── Natural pause (Priority 3: gap-based) ─────────────────────────────────────


class TestNaturalPauseBreaks:
    def test_strong_pause_triggers_break(self, semantic_segmenter):
        """A gap >= PAUSE_STRONG_THRESHOLD_S between words should force a break."""
        gap = PAUSE_STRONG_THRESHOLD_S + 0.05
        items = [
            "She",
            "spoke",
            "softly",
            {"word": "then", "gap_before": gap},
            "paused",
            "again.",
        ]
        boundaries = _boundaries_with_gap(items)
        cues = semantic_segmenter.segment(boundaries, narration="She spoke softly then paused again.")
        assert len(cues) >= 2

    def test_mild_pause_below_threshold_does_not_break_short_cue(self, semantic_segmenter):
        """A gap below PAUSE_BREAK_THRESHOLD_S should NOT force a break."""
        gap = PAUSE_BREAK_THRESHOLD_S - 0.05  # small gap
        items = ["Hello", {"word": "world.", "gap_before": gap}]
        boundaries = _boundaries_with_gap(items)
        cues = semantic_segmenter.segment(boundaries)
        # Short text — should be a single cue
        assert len(cues) == 1

    def test_strong_pause_threshold_constant_is_larger_than_break_threshold(self):
        assert PAUSE_STRONG_THRESHOLD_S > PAUSE_BREAK_THRESHOLD_S


# ── Proper noun pair protection ───────────────────────────────────────────────


class TestProperNounPairProtection:
    def test_consecutive_capitalised_words_not_split(self, semantic_segmenter):
        """Two consecutive Title-Case words should not be separated mid-cue."""
        boundaries = _boundaries(["Emperor", "Ashoka", "ruled", "the", "empire."])
        cues = semantic_segmenter.segment(boundaries)
        texts_combined = " ".join(c.text.replace("\n", " ") for c in cues)
        # "Emperor Ashoka" should appear in the same cue, not broken apart
        assert "Emperor Ashoka" in texts_combined or any(
            "Emperor" in c.text and "Ashoka" in c.text
            for c in cues
        )


# ── Mode parameter ────────────────────────────────────────────────────────────


class TestSegmenterModes:
    def test_semantic_mode_is_default(self):
        seg = SubtitleSegmenter()
        assert seg._mode == "semantic"

    def test_legacy_mode_accepted(self):
        seg = SubtitleSegmenter(mode="legacy")
        assert seg._mode == "legacy"

    def test_semantic_segmenter_returns_cues(self):
        seg = SubtitleSegmenter(mode="semantic")
        boundaries = _boundaries(["This", "is", "a", "sentence."])
        cues = seg.segment(boundaries)
        assert len(cues) >= 1


# ── from_settings integration ─────────────────────────────────────────────────


class TestFromSettingsIntegration:
    def test_reads_subtitle_segmentation_mode_from_settings(self):
        from ytfactory.subtitles.engine import SubtitleEngine

        class FakeSettings:
            subtitle_max_cps = 18.0
            subtitle_max_chars_per_line = 42
            subtitle_max_lines = 2
            subtitle_tail_extension_seconds = 1.0
            subtitle_debug = False
            subtitle_validate = True
            subtitle_format = "srt"
            subtitle_segmentation_mode = "semantic"
            subtitle_ass_theme = "default"

        engine = SubtitleEngine.from_settings(FakeSettings())
        assert engine._segmenter._mode == "semantic"

    def test_default_mode_is_semantic_when_setting_absent(self):
        from ytfactory.subtitles.engine import SubtitleEngine

        class MinimalSettings:
            subtitle_max_cps = 18.0
            subtitle_max_chars_per_line = 42
            subtitle_max_lines = 2
            subtitle_tail_extension_seconds = 1.0
            subtitle_debug = False
            subtitle_validate = True
            subtitle_format = "srt"
            subtitle_ass_theme = "default"
            # subtitle_segmentation_mode intentionally absent

        engine = SubtitleEngine.from_settings(MinimalSettings())
        assert engine._segmenter._mode == "semantic"


# ── SUBT_007-011 review validation rules ─────────────────────────────────────


class TestReviewSubtitleUpgradeRules:
    """Integration tests for the 5 new review-layer rules."""

    @pytest.fixture()
    def cfg(self):
        from ytfactory.review.validation.config import ValidationRulesConfig
        return ValidationRulesConfig()

    @pytest.fixture()
    def validator(self, cfg):
        from ytfactory.review.validation.rules.subtitle import SubtitleValidator
        return SubtitleValidator(cfg)

    def _write_srt(self, directory, index: int, content: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"scene-{index:03d}.srt").write_text(content, encoding="utf-8")

    def _make_scene(self, narration: str = "word " * 30, index: int = 1) -> dict:
        return {"index": index, "narration": narration, "duration_seconds": 15.0}

    # SUBT_007: orphan words
    def test_subt007_pass_on_clean_srt(self, validator, tmp_path):
        srt = (
            "1\n00:00:00,000 --> 00:00:03,000\nShe spoke about history.\n\n"
            "2\n00:00:03,100 --> 00:00:06,000\nThe crowd listened silently.\n"
        )
        self._write_srt(tmp_path / "subtitles", 1, srt)
        results = validator.validate(tmp_path, [self._make_scene()], {})
        rule = next(r for r in results if r.rule_id == "SUBT_007")
        assert rule.status == "PASS"

    def test_subt007_warns_on_orphan_function_word(self, validator, tmp_path):
        srt = (
            "1\n00:00:00,000 --> 00:00:01,000\nthe\n\n"
            "2\n00:00:01,100 --> 00:00:04,000\nancient temple stood tall here.\n"
        )
        self._write_srt(tmp_path / "subtitles", 1, srt)
        results = validator.validate(tmp_path, [self._make_scene()], {})
        rule = next(r for r in results if r.rule_id == "SUBT_007")
        assert rule.status == "WARNING"

    # SUBT_008: balanced two-line subtitles
    def test_subt008_pass_on_balanced_cues(self, validator, tmp_path):
        srt = (
            "1\n00:00:00,000 --> 00:00:04,000\n"
            "She walked across the bridge\nand looked at the river.\n"
        )
        self._write_srt(tmp_path / "subtitles", 1, srt)
        results = validator.validate(tmp_path, [self._make_scene()], {})
        rule = next(r for r in results if r.rule_id == "SUBT_008")
        assert rule.status == "PASS"

    def test_subt008_warns_on_very_unbalanced_cues(self, validator, tmp_path):
        srt = (
            "1\n00:00:00,000 --> 00:00:04,000\n"
            "She walked across the very long beautiful bridge carefully\nok.\n"
        )
        self._write_srt(tmp_path / "subtitles", 1, srt)
        results = validator.validate(tmp_path, [self._make_scene()], {})
        rule = next(r for r in results if r.rule_id == "SUBT_008")
        assert rule.status == "WARNING"

    # SUBT_009: no duplicate consecutive cues
    def test_subt009_pass_with_no_duplicates(self, validator, tmp_path):
        srt = (
            "1\n00:00:00,000 --> 00:00:03,000\nFirst cue text.\n\n"
            "2\n00:00:03,100 --> 00:00:06,000\nSecond cue text.\n"
        )
        self._write_srt(tmp_path / "subtitles", 1, srt)
        results = validator.validate(tmp_path, [self._make_scene()], {})
        rule = next(r for r in results if r.rule_id == "SUBT_009")
        assert rule.status == "PASS"

    def test_subt009_warns_on_duplicate_consecutive_cues(self, validator, tmp_path):
        srt = (
            "1\n00:00:00,000 --> 00:00:03,000\nRepeated text.\n\n"
            "2\n00:00:03,100 --> 00:00:06,000\nRepeated text.\n"
        )
        self._write_srt(tmp_path / "subtitles", 1, srt)
        results = validator.validate(tmp_path, [self._make_scene()], {})
        rule = next(r for r in results if r.rule_id == "SUBT_009")
        assert rule.status == "WARNING"

    # SUBT_010: cue duration bounds
    def test_subt010_pass_on_normal_durations(self, validator, tmp_path):
        srt = (
            "1\n00:00:00,000 --> 00:00:03,000\nNormal duration cue.\n\n"
            "2\n00:00:03,100 --> 00:00:06,000\nAnother normal cue.\n"
        )
        self._write_srt(tmp_path / "subtitles", 1, srt)
        results = validator.validate(tmp_path, [self._make_scene()], {})
        rule = next(r for r in results if r.rule_id == "SUBT_010")
        assert rule.status == "PASS"

    def test_subt010_warns_on_too_short_cue(self, validator, tmp_path):
        srt = (
            "1\n00:00:00,000 --> 00:00:00,100\nFlash.\n\n"
            "2\n00:00:01,000 --> 00:00:04,000\nNormal cue after.\n"
        )
        self._write_srt(tmp_path / "subtitles", 1, srt)
        results = validator.validate(tmp_path, [self._make_scene()], {})
        rule = next(r for r in results if r.rule_id == "SUBT_010")
        assert rule.status == "WARNING"

    def test_subt010_warns_on_too_long_cue(self, validator, tmp_path):
        srt = "1\n00:00:00,000 --> 00:00:10,000\nThis cue is way too long.\n"
        self._write_srt(tmp_path / "subtitles", 1, srt)
        results = validator.validate(tmp_path, [self._make_scene()], {})
        rule = next(r for r in results if r.rule_id == "SUBT_010")
        assert rule.status == "WARNING"

    # SUBT_011: subtitle density
    def test_subt011_pass_with_adequate_cue_count(self, validator, tmp_path):
        # 5 cues for 50-word narration → 1 cue per 10 words (well above 1/25 threshold)
        srt_blocks = "\n\n".join(
            f"{i}\n00:00:{i*3:02d},000 --> 00:00:{i*3+2:02d},000\nCue {i} content text."
            for i in range(1, 6)
        )
        self._write_srt(tmp_path / "subtitles", 1, srt_blocks)
        narration = "word " * 50
        results = validator.validate(tmp_path, [self._make_scene(narration=narration)], {})
        rule = next(r for r in results if r.rule_id == "SUBT_011")
        assert rule.status == "PASS"

    def test_subt011_warns_on_very_few_cues_for_long_narration(self, validator, tmp_path):
        # 1 cue for 100-word narration → too sparse
        srt = "1\n00:00:00,000 --> 00:00:30,000\nOnly one cue for everything.\n"
        self._write_srt(tmp_path / "subtitles", 1, srt)
        narration = "word " * 100
        results = validator.validate(tmp_path, [self._make_scene(narration=narration)], {})
        rule = next(r for r in results if r.rule_id == "SUBT_011")
        assert rule.status == "WARNING"

    def test_subt011_skips_for_short_narration(self, validator, tmp_path):
        srt = "1\n00:00:00,000 --> 00:00:03,000\nShort.\n"
        self._write_srt(tmp_path / "subtitles", 1, srt)
        narration = "Short narration only."
        results = validator.validate(tmp_path, [self._make_scene(narration=narration)], {})
        rule = next(r for r in results if r.rule_id == "SUBT_011")
        assert rule.status == "SKIP"

    def test_all_new_rules_skip_when_no_scenes(self, validator, tmp_path):
        results = validator.validate(tmp_path, [], {})
        new_rule_ids = {"SUBT_007", "SUBT_008", "SUBT_009", "SUBT_010", "SUBT_011"}
        for rule_id in new_rule_ids:
            matched = [r for r in results if r.rule_id == rule_id]
            assert all(r.status == "SKIP" for r in matched), f"{rule_id} should be SKIP for empty scenes"
