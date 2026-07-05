"""Tests for the three production-quality fixes.

Fix 1 — Audio soft-attack (voice/pipeline.py):
  - _normalize_audio_attack() calls ffmpeg dynaudnorm and replaces file in-place
  - On ffmpeg failure the original file is preserved and no exception is raised

Fix 2 — Speech emphasis (optimizer.py):
  - _extract_topic_words() returns lowercased content words from a title string
  - _apply_keyword_emphasis() capitalises single-word emphasis-vocab phrases
  - _apply_keyword_emphasis() capitalises single-word topic-word phrases
  - Multi-word phrases are never modified
  - optimize() with keywords= results in CAPS for matching single-word phrases
  - optimize() without keywords= still works (backward-compatible)

Fix 3 — Last subtitle tail extension (subtitles/timing.py + engine.py + ffmpeg.py):
  - TimingEngine.repair() with tail_extension_seconds extends the last cue's end
  - TimingEngine.repair() with default (0.0) leaves last cue unchanged
  - SubtitleEngine passes tail_extension_seconds to repair()
  - Settings: subtitle_tail_extension_seconds default = 1.0
  - FFmpegRenderer filter order: fade filters precede subtitle filter
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from ytfactory.providers.tts.optimizer import (
    SpeechOptimizer,
    _EMPHASIS_VOCAB,
    _apply_keyword_emphasis,
    _extract_topic_words,
)
from ytfactory.subtitles.models import SubtitleCue
from ytfactory.subtitles.timing import TimingEngine


# ── Fix 1: Audio soft-attack normalization ────────────────────────────────────


class TestNormalizeAudioAttack:
    def test_replaces_file_in_place_on_success(self, tmp_path):
        from ytfactory.voice.pipeline import _normalize_audio_attack

        audio = tmp_path / "scene-001.mp3"
        audio.write_bytes(b"original")

        norm_out = tmp_path / "scene-001.norm.mp3"

        def fake_run(cmd, **kwargs):
            # Write normalised content to the .norm.mp3 path
            norm_path = Path(cmd[-1])
            norm_path.write_bytes(b"normalised")
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("ytfactory.voice.pipeline.subprocess.run", side_effect=fake_run):
            _normalize_audio_attack(audio)

        assert audio.read_bytes() == b"normalised"
        assert not norm_out.exists()

    def test_preserves_original_on_ffmpeg_failure(self, tmp_path):
        from ytfactory.voice.pipeline import _normalize_audio_attack

        audio = tmp_path / "scene-001.mp3"
        audio.write_bytes(b"original")

        with patch(
            "ytfactory.voice.pipeline.subprocess.run",
            side_effect=Exception("ffmpeg not found"),
        ):
            _normalize_audio_attack(audio)  # must not raise

        assert audio.read_bytes() == b"original"

    def test_dynaudnorm_in_ffmpeg_command(self, tmp_path):
        from ytfactory.voice.pipeline import _normalize_audio_attack

        audio = tmp_path / "scene-001.mp3"
        audio.write_bytes(b"x")

        calls_made = []

        def capturing_run(cmd, **kwargs):
            calls_made.append(cmd)
            Path(cmd[-1]).write_bytes(b"normed")
            return MagicMock(returncode=0)

        with patch("ytfactory.voice.pipeline.subprocess.run", side_effect=capturing_run):
            _normalize_audio_attack(audio)

        assert calls_made, "subprocess.run should have been called"
        cmd = calls_made[0]
        joined = " ".join(str(c) for c in cmd)
        assert "dynaudnorm" in joined
        assert "libmp3lame" in joined


# ── Fix 2: Speech emphasis ────────────────────────────────────────────────────


class TestExtractTopicWords:
    def test_returns_empty_for_none(self):
        assert _extract_topic_words(None) == frozenset()

    def test_returns_empty_for_empty_list(self):
        assert _extract_topic_words([]) == frozenset()

    def test_extracts_lowercase_words(self):
        words = _extract_topic_words(["The Rise of Empire"])
        assert "rise" in words
        assert "empire" in words

    def test_skips_short_words(self):
        words = _extract_topic_words(["The Fall"])
        # "The" (3 chars) and "Fall" (4 chars)
        assert "the" not in words
        assert "fall" in words

    def test_strips_punctuation(self):
        words = _extract_topic_words(["Truth, Power!"])
        assert "truth" in words
        assert "power" in words


class TestApplyKeywordEmphasis:
    def test_capitalises_single_word_emphasis_vocab(self):
        result = _apply_keyword_emphasis(["desire."], frozenset())
        assert result == ["DESIRE."]

    def test_capitalises_single_word_topic(self):
        result = _apply_keyword_emphasis(["shivaji"], frozenset({"shivaji"}))
        assert result == ["SHIVAJI"]

    def test_does_not_modify_multi_word_phrases(self):
        phrase = "A never-ending hunger."
        result = _apply_keyword_emphasis([phrase], frozenset())
        assert result == [phrase]

    def test_leaves_unknown_single_words_unchanged(self):
        result = _apply_keyword_emphasis(["mundane"], frozenset())
        assert result == ["mundane"]

    def test_preserves_trailing_punctuation(self):
        result = _apply_keyword_emphasis(["truth?"], frozenset())
        assert result == ["TRUTH?"]

    def test_emphasis_vocab_contains_expected_terms(self):
        for term in ("desire", "truth", "love", "freedom", "empire"):
            assert term in _EMPHASIS_VOCAB


class TestSpeechOptimizerKeywords:
    def _optimizer(self):
        return SpeechOptimizer()

    def test_optimize_backward_compatible_no_keywords(self):
        opt = self._optimizer()
        result = opt.optimize("Desire. A never-ending hunger for more.")
        assert result  # must return something

    def test_optimize_with_keywords_capitalises_match(self):
        opt = self._optimizer()
        # "desire" is a single-word sentence and in _EMPHASIS_VOCAB
        result = opt.optimize("Desire.", keywords=["The Eternal Desire"])
        assert "DESIRE" in result

    def test_optimize_with_none_keywords_no_error(self):
        opt = self._optimizer()
        result = opt.optimize("The truth is eternal.", keywords=None)
        assert result

    def test_multi_word_phrases_not_all_caps(self):
        opt = self._optimizer()
        result = opt.optimize(
            "He chose power over peace.",
            keywords=["Power and Peace"],
        )
        # "power" and "peace" each appear within multi-word phrases,
        # so they should NOT be ALL-CAPS (only isolated single words get that)
        lines = [p.strip() for p in result.split("\n\n") if p.strip()]
        # Verify no multi-word phrase is fully uppercased
        for line in lines:
            if len(line.split()) > 1:
                assert line != line.upper(), f"Multi-word phrase should not be ALL CAPS: {line!r}"


# ── Fix 3: Last subtitle tail extension ──────────────────────────────────────


class TestTimingEngineTailExtension:
    def _make_cue(self, index: int, start: float, end: float) -> SubtitleCue:
        return SubtitleCue(index=index, start=start, end=end, lines=["text"])

    def test_extends_last_cue_by_given_seconds(self):
        engine = TimingEngine()
        cues = [
            self._make_cue(1, 0.0, 2.0),
            self._make_cue(2, 2.5, 5.0),
        ]
        repaired, _ = engine.repair(cues, tail_extension_seconds=1.0)
        assert repaired[-1].end == pytest.approx(6.0)
        # First cue unchanged
        assert repaired[0].end == pytest.approx(2.0)

    def test_default_tail_extension_is_zero(self):
        engine = TimingEngine()
        cues = [self._make_cue(1, 0.0, 3.0)]
        repaired, _ = engine.repair(cues)
        assert repaired[-1].end == pytest.approx(3.0)

    def test_zero_extension_leaves_last_cue_unchanged(self):
        engine = TimingEngine()
        cues = [self._make_cue(1, 0.0, 4.0)]
        repaired, _ = engine.repair(cues, tail_extension_seconds=0.0)
        assert repaired[-1].end == pytest.approx(4.0)

    def test_empty_cues_returns_empty(self):
        engine = TimingEngine()
        repaired, _ = engine.repair([], tail_extension_seconds=1.0)
        assert repaired == []

    def test_extension_applied_after_other_repairs(self):
        engine = TimingEngine()
        # Overlap: cue 1 ends at 5.5 but cue 2 starts at 5.0
        cues = [
            self._make_cue(1, 0.0, 5.5),
            self._make_cue(2, 5.0, 8.0),
        ]
        repaired, _ = engine.repair(cues, tail_extension_seconds=0.5)
        # Cue 2's end should be extended by 0.5
        assert repaired[-1].end == pytest.approx(8.5)


class TestSubtitleEngineTailExtension:
    def test_constructor_stores_tail_extension(self):
        from ytfactory.subtitles.engine import SubtitleEngine

        engine = SubtitleEngine(tail_extension_seconds=2.0)
        assert engine._tail_extension == pytest.approx(2.0)

    def test_default_tail_extension_is_one_second(self):
        from ytfactory.subtitles.engine import SubtitleEngine

        engine = SubtitleEngine()
        assert engine._tail_extension == pytest.approx(1.0)

    def test_tail_extension_passed_to_repair(self):
        """Engine's _process() should call repair() with tail_extension_seconds."""
        from ytfactory.subtitles.engine import SubtitleEngine
        from ytfactory.subtitles.models import SubtitleCue

        engine = SubtitleEngine(tail_extension_seconds=1.5, validate=False)

        captured: list = []
        original_repair = engine._timing.repair

        def spy_repair(cues, tail_extension_seconds=0.0):
            captured.append(tail_extension_seconds)
            return original_repair(cues, tail_extension_seconds=tail_extension_seconds)

        engine._timing.repair = spy_repair

        boundaries = [
            {"word": "Hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.6, "end": 1.2},
        ]
        engine.build(
            boundaries=boundaries,
            narration="Hello world",
            scene_index=1,
            project_id="test",
        )
        assert captured and captured[0] == pytest.approx(1.5)


class TestSettingsTailExtension:
    def test_subtitle_tail_extension_default(self):
        from ytfactory.config.settings import Settings

        s = Settings()
        assert s.subtitle_tail_extension_seconds == pytest.approx(1.0)


class TestFFmpegFilterOrder:
    """Verify subtitle filter comes AFTER fade filters in the vf chain."""

    def test_subtitle_after_fade_in_filter_chain(self, tmp_path):
        from ytfactory.video.ffmpeg import FFmpegRenderer

        renderer = FFmpegRenderer()

        run_calls: list[list] = []

        def capture_run(cmd, **kwargs):
            run_calls.append(list(cmd))

        out = tmp_path / "output.mp4"
        with patch("ytfactory.video.ffmpeg.subprocess.run", side_effect=capture_run):
            renderer.render(
                image=tmp_path / "image.png",
                audio=tmp_path / "audio.mp3",
                subtitle=tmp_path / "scene.ass",
                output=out,
                duration_hint=10.0,
                transition_in={"duration_frames": 15, "color": "black"},
                transition_out={"duration_frames": 15, "color": "black"},
            )

        assert run_calls, "ffmpeg should have been called"
        cmd = run_calls[0]
        vf_idx = cmd.index("-vf")
        vf = cmd[vf_idx + 1]

        subtitle_pos = vf.find("subtitles=")
        fade_in_pos = vf.find("fade=t=in")
        fade_out_pos = vf.find("fade=t=out")

        assert subtitle_pos > fade_in_pos, (
            f"subtitle filter ({subtitle_pos}) should come after fade=in ({fade_in_pos})"
        )
        assert subtitle_pos > fade_out_pos, (
            f"subtitle filter ({subtitle_pos}) should come after fade=out ({fade_out_pos})"
        )

    def test_no_fades_still_has_subtitle(self, tmp_path):
        """When no transitions are set, the subtitle filter is still present."""
        from ytfactory.video.ffmpeg import FFmpegRenderer

        renderer = FFmpegRenderer()
        run_calls: list[list] = []

        with patch("ytfactory.video.ffmpeg.subprocess.run", side_effect=lambda cmd, **kw: run_calls.append(list(cmd))):
            renderer.render(
                image=tmp_path / "image.png",
                audio=tmp_path / "audio.mp3",
                subtitle=tmp_path / "scene.ass",
                output=tmp_path / "output.mp4",
                duration_hint=5.0,
            )

        cmd = run_calls[0]
        vf = cmd[cmd.index("-vf") + 1]
        assert "subtitles=" in vf
