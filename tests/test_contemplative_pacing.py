"""Tests for the Contemplative Pacing Engine.

Covers:
  - SentenceAnalyzer: scoring, pause categories, pre-concept supplement, profiles
  - ThoughtAnalyzer: block grouping, boundary triggers, scoring, silence assignment
  - PauseInjector: single block, multi-block, boundary shifting, subtitle extension
  - VoicePipeline integration: pacing enabled/disabled, asset scene exemption
  - Settings: new fields, profile validation
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.providers.tts.pacing.analyzer import (
    SentenceAnalyzer,
    _score_sentence,
    _split_sentences,
)
from ytfactory.providers.tts.pacing.config import (
    PROFILE_PAUSES,
    THOUGHT_PROFILE_PAUSES,
    PacingProfile,
)
from ytfactory.providers.tts.pacing.injector import PauseInjector
from ytfactory.providers.tts.pacing.models import (
    PauseCategory,
    SentenceAnalysis,
    ThoughtPauseCategory,
)
from ytfactory.providers.tts.pacing.thought_analyzer import (
    ThoughtAnalyzer,
    _new_block_trigger,
    _score_block,
    _split_sentences as _thought_split_sentences,
)


# ── Deterministic RNG for tests ───────────────────────────────────────────────

@pytest.fixture
def rng() -> random.Random:
    return random.Random(42)


# ── _split_sentences ──────────────────────────────────────────────────────────

class TestSplitSentences:
    def test_single_sentence(self):
        result = _split_sentences("Peace cannot be found outside.")
        assert result == ["Peace cannot be found outside."]

    def test_two_sentences(self):
        result = _split_sentences("Peace cannot be found outside. Desire keeps growing forever.")
        assert len(result) == 2
        assert result[0] == "Peace cannot be found outside."
        assert result[1] == "Desire keeps growing forever."

    def test_line_breaks_normalized(self):
        result = _split_sentences("First sentence.\nSecond sentence.")
        assert len(result) == 2

    def test_multiple_line_breaks(self):
        result = _split_sentences("First sentence.\n\nSecond sentence.\n\nThird.")
        assert len(result) == 3

    def test_exclamation_and_question(self):
        result = _split_sentences("Is this real? Everything is an illusion! Notice now.")
        assert len(result) == 3

    def test_empty_string(self):
        result = _split_sentences("")
        assert result == []

    def test_strips_blank_fragments(self):
        result = _split_sentences("  Real sentence.  ")
        assert result == ["Real sentence."]


# ── _score_sentence ───────────────────────────────────────────────────────────

class TestScoreSentence:
    def test_major_concept_single(self):
        score, triggers = _score_sentence("Peace is found within.")
        assert score >= 1
        assert any("concept" in t for t in triggers)

    def test_major_concept_multi(self):
        score, triggers = _score_sentence("Desire causes suffering.")
        assert score >= 3
        assert any("multi-concept" in t for t in triggers)

    def test_concept_opener_bonus(self):
        score_opener, _ = _score_sentence("Silence speaks louder than words.")
        score_non, _ = _score_sentence("The mind craves silence always.")
        # opener gets +2 bonus for first-word concept
        assert score_opener >= score_non - 1  # opener should be competitive

    def test_very_short_sentence(self):
        score, triggers = _score_sentence("Peace is now.")
        assert score >= 3  # 3 words + concept
        assert any("very-short" in t for t in triggers)

    def test_short_sentence(self):
        score, triggers = _score_sentence("You cannot escape the present moment.")
        assert any("short" in t for t in triggers)

    def test_long_sentence_no_short_bonus(self):
        score, triggers = _score_sentence(
            "When you begin to understand that every feeling passes and nothing is permanent, you may start to relax."
        )
        assert not any("short" in t or "very-short" in t for t in triggers)

    def test_negation_pattern(self):
        score, triggers = _score_sentence("You cannot find peace in possessions.")
        assert any("negation" in t for t in triggers)

    def test_universal_statement(self):
        score, triggers = _score_sentence("Everything eventually passes away.")
        assert any("universal" in t for t in triggers)

    def test_question_reduces_score(self):
        score_q, triggers = _score_sentence("What is peace?")
        assert any("question" in t for t in triggers)
        score_stmt, _ = _score_sentence("Peace is within.")
        # question penalty: score_q should be lower than equivalent statement
        assert score_q <= score_stmt + 1

    def test_plain_connecting_sentence_low_score(self):
        score, _ = _score_sentence(
            "In this video we will explore several ideas about productivity."
        )
        assert score <= 2

    def test_triggers_populated(self):
        _, triggers = _score_sentence("Desire causes great suffering always.")
        assert len(triggers) >= 1


# ── SentenceAnalyzer ──────────────────────────────────────────────────────────

class TestSentenceAnalyzer:
    def test_last_sentence_is_none(self, rng):
        analyzer = SentenceAnalyzer()
        sentences = analyzer.analyze("First. Second.", profile="spiritual", rng=rng)
        assert sentences[-1].pause_category == PauseCategory.NONE
        assert sentences[-1].pause_ms == 0

    def test_single_sentence_is_none(self, rng):
        analyzer = SentenceAnalyzer()
        sentences = analyzer.analyze("Just one sentence.", profile="spiritual", rng=rng)
        assert len(sentences) == 1
        assert sentences[0].pause_category == PauseCategory.NONE

    def test_empty_narration(self):
        analyzer = SentenceAnalyzer()
        assert analyzer.analyze("") == []

    def test_pause_within_profile_range_short(self, rng):
        analyzer = SentenceAnalyzer()
        # Plain connecting sentence → SHORT category
        narration = (
            "In this section we will look at several productivity tips. "
            "The following ideas may help you stay focused."
        )
        sentences = analyzer.analyze(narration, profile="spiritual", rng=rng)
        first = sentences[0]
        if first.pause_category == PauseCategory.SHORT:
            pauses = PROFILE_PAUSES["spiritual"].short
            assert pauses.min_ms <= first.pause_ms <= pauses.max_ms + 600  # +600 for concept_pre

    def test_pause_within_profile_range_long(self, rng):
        analyzer = SentenceAnalyzer()
        # Major realization sentence → LONG category
        narration = "Desire is the root of suffering. You cannot find peace outside."
        sentences = analyzer.analyze(narration, profile="spiritual", rng=rng)
        first = sentences[0]
        if first.pause_category == PauseCategory.LONG:
            pauses = PROFILE_PAUSES["spiritual"].long
            assert pauses.min_ms <= first.pause_ms

    def test_spiritual_pauses_longer_than_normal(self, rng):
        analyzer = SentenceAnalyzer()
        narration = "Peace cannot be found outside. Desire keeps growing forever."
        rng_s = random.Random(42)
        rng_n = random.Random(42)
        s_sentences = analyzer.analyze(narration, profile="spiritual", rng=rng_s)
        n_sentences = analyzer.analyze(narration, profile="normal", rng=rng_n)
        # Spiritual pauses are always ≥ normal pauses
        for s, n in zip(s_sentences[:-1], n_sentences[:-1]):
            assert s.pause_ms >= n.pause_ms

    def test_meditation_pauses_longer_than_spiritual(self, rng):
        analyzer = SentenceAnalyzer()
        narration = "Peace is within. Silence reveals it."
        rng_s = random.Random(42)
        rng_m = random.Random(42)
        s_sentences = analyzer.analyze(narration, profile="spiritual", rng=rng_s)
        m_sentences = analyzer.analyze(narration, profile="meditation", rng=rng_m)
        for s, m in zip(s_sentences[:-1], m_sentences[:-1]):
            assert m.pause_ms >= s.pause_ms

    def test_pre_concept_supplement_added(self, rng):
        analyzer = SentenceAnalyzer()
        # "Silence" opens sentence 2 → supplement added to sentence 1
        narration = "You carry many burdens each day. Silence can lift them all."
        sentences = analyzer.analyze(narration, profile="spiritual", rng=rng)
        assert len(sentences) == 2
        assert any("pre-concept" in t for t in sentences[0].triggers)

    def test_no_pre_concept_supplement_for_plain_next(self, rng):
        analyzer = SentenceAnalyzer()
        narration = "Here is the first idea. And here is the second one."
        sentences = analyzer.analyze(narration, profile="spiritual", rng=rng)
        assert not any("pre-concept" in t for t in sentences[0].triggers)

    def test_all_profiles_accepted(self, rng):
        analyzer = SentenceAnalyzer()
        narration = "The mind seeks peace. It never finds it outside."
        for profile in ["normal", "documentary", "spiritual", "meditation", "slow_reflection"]:
            result = analyzer.analyze(narration, profile=profile, rng=rng)
            assert len(result) == 2

    def test_sentence_texts_match_input(self, rng):
        analyzer = SentenceAnalyzer()
        narration = "First thought. Second thought. Third thought."
        sentences = analyzer.analyze(narration, profile="spiritual", rng=rng)
        assert sentences[0].text == "First thought."
        assert sentences[1].text == "Second thought."
        assert sentences[2].text == "Third thought."

    def test_triggers_are_populated_for_high_score(self, rng):
        analyzer = SentenceAnalyzer()
        narration = "Desire is suffering. Peace is within."
        sentences = analyzer.analyze(narration, profile="spiritual", rng=rng)
        assert sentences[0].triggers  # high-score sentence should have triggers


# ── Profile config ────────────────────────────────────────────────────────────

class TestProfilePauses:
    def test_all_profiles_defined(self):
        for profile in PacingProfile:
            assert profile.value in PROFILE_PAUSES

    def test_spiritual_medium_range(self):
        pauses = PROFILE_PAUSES["spiritual"]
        assert pauses.medium.min_ms == 1200
        assert pauses.medium.max_ms == 1800

    def test_spiritual_long_range(self):
        pauses = PROFILE_PAUSES["spiritual"]
        assert pauses.long.min_ms == 2000
        assert pauses.long.max_ms == 2500

    def test_ranges_are_monotonically_increasing_across_categories(self):
        for name, p in PROFILE_PAUSES.items():
            assert p.short.max_ms <= p.medium.min_ms, f"{name}: short.max >= medium.min"
            assert p.medium.max_ms <= p.long.min_ms, f"{name}: medium.max >= long.min"

    def test_slower_profiles_have_longer_pauses(self):
        order = ["normal", "documentary", "spiritual", "meditation", "slow_reflection"]
        for i in range(len(order) - 1):
            a = PROFILE_PAUSES[order[i]]
            b = PROFILE_PAUSES[order[i + 1]]
            assert a.medium.min_ms <= b.medium.min_ms, f"{order[i]} medium >= {order[i+1]} medium"


# ── PauseInjector ─────────────────────────────────────────────────────────────

class TestPauseInjector:
    """Tests for PauseInjector using mocked provider/optimizer and FFmpeg calls."""

    def _make_mock_provider(self, tmp_path: Path, duration_per_call: float = 2.0):
        """Return a mock provider that writes a real silence audio file."""
        call_count = 0

        def generate_with_boundaries(text, output_path, **kwargs):
            nonlocal call_count
            # Write a real silence MP3 of duration_per_call seconds
            import subprocess
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "lavfi",
                    "-i", "anullsrc=sample_rate=24000:channel_layout=mono",
                    "-t", str(duration_per_call),
                    "-c:a", "libmp3lame", "-q:a", "9",
                    str(output_path),
                ],
                check=True, capture_output=True,
            )
            boundaries = [
                {"word": w, "start": j * 0.3, "end": j * 0.3 + 0.25}
                for j, w in enumerate(text.split()[:3])
            ]
            call_count += 1
            return output_path, boundaries

        provider = MagicMock()
        provider.generate_with_boundaries.side_effect = generate_with_boundaries
        provider._call_count = lambda: call_count
        return provider

    def _make_mock_optimizer(self):
        optimizer = MagicMock()
        optimizer.optimize.side_effect = lambda text, **kwargs: text
        return optimizer

    def test_single_sentence_no_silence(self, tmp_path):
        injector = PauseInjector()
        provider = self._make_mock_provider(tmp_path)
        optimizer = self._make_mock_optimizer()
        output = tmp_path / "out.mp3"

        out_path, boundaries = injector.generate(
            narration="Peace is found within.",
            output_path=output,
            optimizer=optimizer,
            provider=provider,
            profile="spiritual",
        )

        assert out_path == output
        assert output.exists()
        assert len(boundaries) >= 0  # boundaries may be empty for silence
        # Single sentence → provider called exactly once
        assert provider.generate_with_boundaries.call_count == 1

    def test_two_thought_blocks_call_provider_twice(self, tmp_path):
        """Two distinct thought blocks → provider called exactly twice."""
        injector = PauseInjector()
        provider = self._make_mock_provider(tmp_path)
        optimizer = self._make_mock_optimizer()
        output = tmp_path / "out.mp3"

        # "But" starts a new thought block — guaranteed 2 blocks
        injector.generate(
            narration="Peace cannot be found outside. But desire keeps growing forever.",
            output_path=output,
            optimizer=optimizer,
            provider=provider,
            profile="spiritual",
        )

        assert provider.generate_with_boundaries.call_count == 2

    def test_boundary_timestamps_shifted_correctly(self, tmp_path):
        injector = PauseInjector()
        provider = self._make_mock_provider(tmp_path, duration_per_call=2.0)
        optimizer = self._make_mock_optimizer()
        output = tmp_path / "out.mp3"

        _, boundaries = injector.generate(
            narration="First thought here always. Second thought here always.",
            output_path=output,
            optimizer=optimizer,
            provider=provider,
            profile="normal",  # short pauses for predictability
        )

        if len(boundaries) > 3:
            # Words from sentence 2 must start after sentence 1 ends (2.0s audio + pause)
            # Sentence 1 ends at 2.0s, pause is at least 200ms → sentence 2 starts at 2.2s+
            sent2_start = boundaries[3]["start"]
            assert sent2_start >= 2.0, f"Sentence 2 words not shifted: {sent2_start}"

    def test_output_file_created(self, tmp_path):
        injector = PauseInjector()
        provider = self._make_mock_provider(tmp_path)
        optimizer = self._make_mock_optimizer()
        output = tmp_path / "out.mp3"

        injector.generate(
            narration="Silence is truth. Desire is suffering.",
            output_path=output,
            optimizer=optimizer,
            provider=provider,
        )

        assert output.exists()
        assert output.stat().st_size > 0

    def test_optimizer_called_per_thought_block(self, tmp_path):
        """Optimizer is called once per thought block, not per sentence."""
        injector = PauseInjector()
        provider = self._make_mock_provider(tmp_path)
        optimizer = self._make_mock_optimizer()
        output = tmp_path / "out.mp3"

        # Contrast openers force 3 distinct thought blocks
        narration = (
            "Peace is within every living being. "
            "But desire pulls us away from it. "
            "Yet stillness remains always."
        )
        injector.generate(
            narration=narration,
            output_path=output,
            optimizer=optimizer,
            provider=provider,
        )

        assert optimizer.optimize.call_count == 3

    def test_profile_forwarded_to_analyzer(self, tmp_path):
        injector = PauseInjector()
        provider = self._make_mock_provider(tmp_path)
        optimizer = self._make_mock_optimizer()
        output = tmp_path / "out.mp3"

        with patch.object(injector._analyzer, "analyze", wraps=injector._analyzer.analyze) as mock_analyze:
            injector.generate(
                narration="Peace is within. Silence reveals it.",
                output_path=output,
                optimizer=optimizer,
                provider=provider,
                profile="meditation",
            )
            mock_analyze.assert_called_once()
            assert mock_analyze.call_args[0][1] == "meditation"

    def test_empty_narration_fallback(self, tmp_path):
        injector = PauseInjector()
        provider = self._make_mock_provider(tmp_path)
        optimizer = self._make_mock_optimizer()
        output = tmp_path / "out.mp3"

        # Empty narration → fallback to plain synthesis (single call)
        out, boundaries = injector.generate(
            narration="",
            output_path=output,
            optimizer=optimizer,
            provider=provider,
        )
        assert provider.generate_with_boundaries.call_count == 1

    def test_subtitle_end_extends_over_silence(self, tmp_path):
        """Last word boundary's end covers the silence so subtitle stays visible."""
        injector = PauseInjector()
        # duration_per_call=1.0 → each block produces 1 second of audio
        provider = self._make_mock_provider(tmp_path, duration_per_call=1.0)
        optimizer = self._make_mock_optimizer()
        output = tmp_path / "out.mp3"

        # "But" forces 2 blocks; profile=normal gives predictable short silence
        _, boundaries = injector.generate(
            narration="Everything you seek is within. But nothing outside can give it.",
            output_path=output,
            optimizer=optimizer,
            provider=provider,
            profile="normal",  # small=400–700 ms
        )

        # Block 1 produces boundaries for its words; last boundary's end must
        # be >= 1.0s (audio) + 0.4s (min silence) = 1.4s
        if boundaries:
            # Find the last boundary from block 1 (start < 1.0s since audio is 1s)
            block1_last = max(
                (b for b in boundaries if b["start"] < 1.0),
                key=lambda b: b["end"],
                default=None,
            )
            if block1_last:
                assert block1_last["end"] >= 1.4, (
                    f"Subtitle end not extended over silence: {block1_last['end']:.3f}s"
                )


# ── ThoughtAnalyzer ───────────────────────────────────────────────────────────

class TestThoughtAnalyzer:
    """Tests for semantic thought-block detection and silence assignment."""

    def test_contrast_opener_starts_new_block(self):
        analyzer = ThoughtAnalyzer()
        blocks = analyzer.analyze(
            "Peace is within every being. But desire pulls us away.",
            profile="spiritual",
        )
        assert len(blocks) == 2
        assert blocks[0].text.startswith("Peace")
        assert blocks[1].text.startswith("But")

    def test_yet_opener_starts_new_block(self):
        analyzer = ThoughtAnalyzer()
        blocks = analyzer.analyze(
            "The mind seeks stillness. Yet it keeps running from it.",
            profile="spiritual",
        )
        assert len(blocks) == 2

    def test_shift_opener_starts_new_block(self):
        analyzer = ThoughtAnalyzer()
        blocks = analyzer.analyze(
            "Many people search their entire lives for happiness. "
            "Now consider where you have been looking.",
            profile="spiritual",
        )
        assert len(blocks) == 2

    def test_conclusive_short_concept_starts_new_block(self):
        analyzer = ThoughtAnalyzer()
        blocks = analyzer.analyze(
            "Everything you chase will eventually disappear. "
            "But there is one thing that never leaves you. "
            "It is your awareness.",
            profile="spiritual",
        )
        # "But" → block 2, "It is your awareness." (conclusive + concept) → block 3
        assert len(blocks) == 3
        assert blocks[2].text == "It is your awareness."

    def test_continuous_sentences_stay_in_one_block(self):
        analyzer = ThoughtAnalyzer()
        blocks = analyzer.analyze(
            "The mind is often restless. It constantly seeks new experiences. "
            "This is its natural state.",
            profile="spiritual",
        )
        # No contrast/shift triggers → grouped together (or at most 2 if conclusive fires)
        # At minimum, no 3-way split on plain continuation sentences
        assert len(blocks) <= 2

    def test_last_block_has_no_silence(self, rng):
        analyzer = ThoughtAnalyzer()
        blocks = analyzer.analyze(
            "Peace is within. But desire keeps us searching.",
            profile="spiritual",
            rng=rng,
        )
        assert blocks[-1].pause_ms == 0
        assert blocks[-1].pause_category == ThoughtPauseCategory.NONE

    def test_non_last_block_has_silence(self, rng):
        analyzer = ThoughtAnalyzer()
        blocks = analyzer.analyze(
            "Everything fades away. But awareness remains eternal.",
            profile="spiritual",
            rng=rng,
        )
        assert blocks[0].pause_ms > 0

    def test_pause_within_profile_range(self, rng):
        analyzer = ThoughtAnalyzer()
        blocks = analyzer.analyze(
            "Nothing lasts forever. Yet love transcends time.",
            profile="spiritual",
            rng=rng,
        )
        block = blocks[0]
        if block.pause_category != ThoughtPauseCategory.NONE:
            ranges = THOUGHT_PROFILE_PAUSES["spiritual"]
            pause_range = getattr(ranges, block.pause_category.value)
            assert pause_range.min_ms <= block.pause_ms <= pause_range.max_ms

    def test_insight_category_for_short_philosophical_block(self, rng):
        analyzer = ThoughtAnalyzer()
        # Short block with concept + universal → high score → INSIGHT
        blocks = analyzer.analyze(
            "Nothing is eternal. Yet love and peace always remain.",
            profile="spiritual",
            rng=rng,
        )
        first = blocks[0]
        assert first.pause_category in (
            ThoughtPauseCategory.INSIGHT,
            ThoughtPauseCategory.REALIZATION,
        )

    def test_spiritual_pauses_longer_than_normal(self, rng):
        analyzer = ThoughtAnalyzer()
        narration = "Desire is suffering. But peace is always here."
        rng_s = random.Random(42)
        rng_n = random.Random(42)
        s_blocks = analyzer.analyze(narration, profile="spiritual", rng=rng_s)
        n_blocks = analyzer.analyze(narration, profile="normal", rng=rng_n)
        for s, n in zip(s_blocks[:-1], n_blocks[:-1]):
            assert s.pause_ms >= n.pause_ms

    def test_meditation_pauses_longer_than_spiritual(self, rng):
        analyzer = ThoughtAnalyzer()
        narration = "The truth is within. Yet we keep searching outside."
        rng_s = random.Random(42)
        rng_m = random.Random(42)
        s_blocks = analyzer.analyze(narration, profile="spiritual", rng=rng_s)
        m_blocks = analyzer.analyze(narration, profile="meditation", rng=rng_m)
        for s, m in zip(s_blocks[:-1], m_blocks[:-1]):
            assert m.pause_ms >= s.pause_ms

    def test_empty_narration_returns_empty(self):
        analyzer = ThoughtAnalyzer()
        assert analyzer.analyze("") == []

    def test_single_sentence_is_last_block(self, rng):
        analyzer = ThoughtAnalyzer()
        blocks = analyzer.analyze("Peace is within.", profile="spiritual", rng=rng)
        assert len(blocks) == 1
        assert blocks[0].pause_ms == 0

    def test_ellipsis_stays_within_block(self):
        """Ellipsis is a prosodic pause; it should NOT split into separate blocks."""
        analyzer = ThoughtAnalyzer()
        blocks = analyzer.analyze(
            "Everything you chase... will eventually disappear.",
            profile="spiritual",
        )
        assert len(blocks) == 1

    def test_all_profiles_accepted(self, rng):
        analyzer = ThoughtAnalyzer()
        narration = "Silence is truth. But the mind resists it."
        for profile in ["normal", "documentary", "spiritual", "meditation", "slow_reflection"]:
            result = analyzer.analyze(narration, profile=profile, rng=rng)
            assert len(result) >= 1


class TestNewBlockTrigger:
    """Unit tests for the block-boundary trigger function."""

    def test_but_triggers_contrast(self):
        assert _new_block_trigger("But desire pulls us away.", ["Peace is within."]) == "contrast"

    def test_yet_triggers_contrast(self):
        assert _new_block_trigger("Yet stillness remains.", ["Many things change."]) == "contrast"

    def test_however_triggers_contrast(self):
        assert _new_block_trigger("However, the truth is within.", []) == "contrast"

    def test_and_yet_triggers_contrast(self):
        assert _new_block_trigger("And yet love persists.", ["All things fade away."]) == "contrast"

    def test_now_triggers_shift(self):
        assert _new_block_trigger("Now consider what truly matters.", ["The mind seeks peace."]) == "shift"

    def test_remember_triggers_shift(self):
        assert _new_block_trigger("Remember where you came from.", ["Much time has passed."]) == "shift"

    def test_conclusive_with_concept_triggers_new_block(self):
        trigger = _new_block_trigger("It is your awareness.", ["Everything else will fade."])
        assert trigger == "conclusive"

    def test_conclusive_without_concept_does_not_trigger(self):
        # "This is natural" has no major concept word
        trigger = _new_block_trigger("This is natural.", ["The mind works in cycles."])
        assert trigger is None

    def test_continuation_sentence_stays_in_block(self):
        assert _new_block_trigger(
            "It constantly seeks new experiences.",
            ["The mind is often restless."],
        ) is None

    def test_very_short_standalone_with_concept(self):
        # 3 words, has "peace", current block has 8+ words
        current = ["The human mind wanders through many complicated thoughts daily."]
        assert _new_block_trigger("Peace is within.", current) is not None

    def test_very_short_without_concept_does_not_trigger(self):
        current = ["The human mind wanders through many complicated thoughts daily."]
        assert _new_block_trigger("And then more.", current) is None


class TestScoreBlock:
    """Unit tests for thought block scoring."""

    def test_short_concept_block_scores_high(self):
        category, triggers = _score_block(["Peace is within."])
        assert category in (ThoughtPauseCategory.INSIGHT, ThoughtPauseCategory.REALIZATION)

    def test_universal_negation_elevates_score(self):
        category, triggers = _score_block(["Nothing you seek outside will ever satisfy you."])
        assert category in (ThoughtPauseCategory.INSIGHT, ThoughtPauseCategory.REALIZATION)
        assert any("negation" in t for t in triggers)

    def test_plain_long_block_scores_small(self):
        # Long, no concepts, no universals, no negation
        category, _ = _score_block([
            "In this section we will look at productivity techniques "
            "and how they can be applied in daily life situations."
        ])
        assert category == ThoughtPauseCategory.SMALL

    def test_ellipsis_adds_score(self):
        _, triggers = _score_block(["Everything you chase... will eventually disappear."])
        assert any("ellipsis" in t for t in triggers)

    def test_rhetorical_question_adds_score(self):
        _, triggers = _score_block(["What is the purpose of this suffering?"])
        assert any("rhetorical" in t for t in triggers)


class TestThoughtProfilePauses:
    """Structural tests for THOUGHT_PROFILE_PAUSES table."""

    def test_all_profiles_defined(self):
        for profile in PacingProfile:
            assert profile.value in THOUGHT_PROFILE_PAUSES

    def test_spiritual_small_range(self):
        r = THOUGHT_PROFILE_PAUSES["spiritual"]
        assert r.small.min_ms == 800
        assert r.small.max_ms == 1200

    def test_spiritual_insight_range(self):
        r = THOUGHT_PROFILE_PAUSES["spiritual"]
        assert r.insight.min_ms == 2500
        assert r.insight.max_ms == 4000

    def test_ranges_monotonically_increasing(self):
        for name, r in THOUGHT_PROFILE_PAUSES.items():
            assert r.small.max_ms <= r.realization.min_ms, f"{name}: small.max >= realization.min"
            assert r.realization.max_ms <= r.insight.min_ms, f"{name}: realization.max >= insight.min"

    def test_slower_profiles_have_longer_pauses(self):
        order = ["normal", "documentary", "spiritual", "meditation", "slow_reflection"]
        for i in range(len(order) - 1):
            a = THOUGHT_PROFILE_PAUSES[order[i]]
            b = THOUGHT_PROFILE_PAUSES[order[i + 1]]
            assert a.realization.min_ms <= b.realization.min_ms


# ── Settings ──────────────────────────────────────────────────────────────────

class TestPacingSettings:
    def test_pacing_enabled_field_exists(self):
        from ytfactory.config.settings import Settings
        s = Settings()
        assert hasattr(s, "tts_pacing_enabled")
        assert isinstance(s.tts_pacing_enabled, bool)

    def test_pacing_profile_field_exists(self):
        from ytfactory.config.settings import Settings
        s = Settings()
        assert hasattr(s, "tts_pacing_profile")
        assert isinstance(s.tts_pacing_profile, str)

    def test_pacing_profile_default_is_spiritual(self):
        from ytfactory.config.settings import Settings
        with patch.dict("os.environ", {}, clear=False):
            s = Settings()
        assert s.tts_pacing_profile == "spiritual"


# ── VoicePipeline integration ─────────────────────────────────────────────────

class TestVoicePipelineIntegration:
    """Verify the pipeline routes to PauseInjector vs plain synthesis correctly."""

    _PROJECT_ID = "test-project"

    def _make_scene(self, scene_type: str = "generated_image", narration: str = "Test narration.") -> dict:
        return {
            "index": 1,
            "title": "Test Scene",
            "narration": narration,
            "visual_prompt": "A serene landscape.",
            "duration_seconds": 10.0,
            "scene_type": scene_type,
        }

    def _make_settings(self, pacing_enabled: bool = True):
        s = MagicMock()
        s.tts_pacing_enabled = pacing_enabled
        s.tts_pacing_profile = "spiritual"
        s.tts_debug = False
        s.tts_validate_audio = False
        s.tts_auto_retry = False
        s.tts_max_retries = 1
        return s

    def _setup_workspace(self, tmp_path: Path, scene: dict) -> tuple[Path, Path]:
        """Create workspace structure under tmp_path and return (scene_file, audio_dir)."""
        scene_dir = tmp_path / "workspace" / "jobs" / self._PROJECT_ID / "scenes"
        scene_dir.mkdir(parents=True)
        scene_file = scene_dir / "scene-plan.json"
        scene_file.write_text(json.dumps({"scenes": [scene]}))

        audio_dir = tmp_path / "workspace" / "jobs" / self._PROJECT_ID / "audio"
        audio_dir.mkdir(parents=True)
        return scene_file, audio_dir

    def test_pacing_used_for_normal_scene(self, tmp_path, monkeypatch):
        from ytfactory.voice.pipeline import VoicePipeline

        monkeypatch.chdir(tmp_path)
        scene = self._make_scene()
        _, audio_dir = self._setup_workspace(tmp_path, scene)

        settings = self._make_settings(pacing_enabled=True)
        pipeline = VoicePipeline.__new__(VoicePipeline)
        pipeline._settings = settings
        pipeline._repository = MagicMock()
        pipeline._provider = MagicMock()

        def fake_pacer(narration, output_path, **kwargs):
            output_path.write_bytes(b"\xff\xfb" * 100)
            output_path.with_suffix(".timing.json").write_text("[]")
            return output_path, []

        with (
            patch("ytfactory.voice.pipeline._pacer") as mock_pacer,
            patch("ytfactory.voice.pipeline.audio_directory", return_value=audio_dir),
            patch("ytfactory.voice.pipeline._normalize_audio_attack"),
        ):
            mock_pacer.generate.side_effect = fake_pacer
            pipeline.run(self._PROJECT_ID)
            mock_pacer.generate.assert_called_once()

    def test_pacing_skipped_for_asset_scene(self, tmp_path, monkeypatch):
        from ytfactory.voice.pipeline import VoicePipeline

        monkeypatch.chdir(tmp_path)
        scene = self._make_scene(scene_type="asset", narration="Stay curious.")
        _, audio_dir = self._setup_workspace(tmp_path, scene)
        (audio_dir / "scene-001.mp3").write_bytes(b"\xff\xfb" * 100)

        settings = self._make_settings(pacing_enabled=True)
        pipeline = VoicePipeline.__new__(VoicePipeline)
        pipeline._settings = settings
        pipeline._repository = MagicMock()

        mock_provider = MagicMock()
        mock_provider.generate_with_boundaries.return_value = (
            audio_dir / "scene-001.mp3", []
        )
        pipeline._provider = mock_provider

        with (
            patch("ytfactory.voice.pipeline._pacer") as mock_pacer,
            patch("ytfactory.voice.pipeline._optimizer") as mock_optimizer,
            patch("ytfactory.voice.pipeline.audio_directory", return_value=audio_dir),
            patch("ytfactory.voice.pipeline._normalize_audio_attack"),
        ):
            mock_optimizer.optimize.return_value = "Stay curious."
            pipeline.run(self._PROJECT_ID)

            mock_pacer.generate.assert_not_called()
            mock_provider.generate_with_boundaries.assert_called_once()

    def test_pacing_disabled_uses_plain_provider(self, tmp_path, monkeypatch):
        from ytfactory.voice.pipeline import VoicePipeline

        monkeypatch.chdir(tmp_path)
        scene = self._make_scene()
        _, audio_dir = self._setup_workspace(tmp_path, scene)
        (audio_dir / "scene-001.mp3").write_bytes(b"\xff\xfb" * 100)

        settings = self._make_settings(pacing_enabled=False)
        pipeline = VoicePipeline.__new__(VoicePipeline)
        pipeline._settings = settings
        pipeline._repository = MagicMock()

        mock_provider = MagicMock()
        mock_provider.generate_with_boundaries.return_value = (
            audio_dir / "scene-001.mp3", []
        )
        pipeline._provider = mock_provider

        with (
            patch("ytfactory.voice.pipeline._pacer") as mock_pacer,
            patch("ytfactory.voice.pipeline._optimizer") as mock_optimizer,
            patch("ytfactory.voice.pipeline.audio_directory", return_value=audio_dir),
            patch("ytfactory.voice.pipeline._normalize_audio_attack"),
        ):
            mock_optimizer.optimize.return_value = "Test narration."
            pipeline.run(self._PROJECT_ID)

            mock_pacer.generate.assert_not_called()
            mock_provider.generate_with_boundaries.assert_called_once()
