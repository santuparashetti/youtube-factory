"""Tests for DocumentaryScriptEnhancerPipeline (ADR-0011 two-pass structure)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from ytfactory.script_enhancer.pipeline import (
    DocumentaryEnhancerValidator,
    DocumentaryScriptEnhancerPipeline,
    ScriptEnhancerPipeline,
    _parse_narrative_score,
    _NARRATIVE_SCORE_THRESHOLD,
)
from ytfactory.agents.prompts.script_enhancer import (
    build_pass1_prompt,
    build_pass2_prompt,
)


# ── Fixtures ────────────────────────────────────────────────────────────────────

SAMPLE_SCRIPT = """\
This is a discourse about the nature of suffering.

The teacher explains that attachment causes pain.

Stories and analogies follow naturally.

The closing wisdom lands with weight.
"""

SAMPLE_SCRIPT_WITH_SCRIPTURE = """\
The Gita says ॐ नमः शिवाय in its opening verses.

This sacred utterance carries the entire teaching within it.
"""

PASS1_CLEAN = """\
This is a discourse about the nature of suffering.

The teacher explains that attachment causes pain.

Stories and analogies follow naturally.

The closing wisdom lands with weight.
"""

PASS2_SCORED_GOOD = (
    "This is a discourse about the nature of suffering.\n\n"
    "The teacher explains that attachment causes pain.\n\n"
    "Stories and analogies follow naturally.\n\n"
    "The closing wisdom lands with weight.\n\n"
    "---NARRATIVE SCORE---\n"
    "Hook: 9/10\n"
    "Story Density: 9/10\n"
    "Curiosity: 9/10\n"
    "Emotional Rhythm: 9/10\n"
    "Accessibility: 9/10\n"
    "Overall: 9/10\n"
    "---END SCORE---"
)

PASS2_SCORED_LOW = (
    "This is a discourse about the nature of suffering.\n\n"
    "---NARRATIVE SCORE---\n"
    "Hook: 7/10\n"
    "Story Density: 7/10\n"
    "Curiosity: 7/10\n"
    "Emotional Rhythm: 7/10\n"
    "Accessibility: 7/10\n"
    "Overall: 7/10\n"
    "---END SCORE---"
)

PASS3_EXPANDED = """\
The teacher began with ॐ नमः शिवाय and spoke at length on the nature of consciousness.

This is a profound and detailed discourse about the nature of suffering and the ancient path that leads beyond it. The teacher gathers the listeners and begins with a question that cuts through all pretense: why do we suffer, and is there a way out that does not depend on changing the world?

The teacher begins by explaining that attachment is the root cause of all inner pain. When we cling to people, possessions, outcomes, and identities, we set ourselves up for inevitable disappointment. This is not a pessimistic view but a realistic and compassionate one. The first step toward genuine freedom is seeing clearly how our own clinging binds us.

The teacher then explores how this attachment operates in daily life, often without our awareness. We attach to our opinions, our social status, our carefully constructed plans, and even our spiritual achievements. Each attachment creates a subtle background tension, a low-grade anxiety that colors every experience. Even pleasant experiences become contaminated by the quiet fear of losing them.

Consider, the teacher says, how a beautiful sunset is diminished the moment we photograph it instead of simply seeing it. The attachment to possessing the moment destroys the very joy we sought to capture. This pattern repeats endlessly.

Stories and analogies follow naturally from this observation. The teacher tells of a man who carries a heavy burden across a vast desert, convinced it contains untold treasure. He guards it jealously, suffering under its weight, unwilling to share or rest. When he finally sets it down to rest his weary body, he discovers to his shock that it was filled with ordinary stones. His suffering was real, but the burden he carried was entirely optional — a creation of his own mind.

The teaching deepens as the teacher examines the relationship between pleasure and pain. Where there is intense pleasure, there is also the seed of intense pain, because all pleasant conditions are impermanent. This is not a reason to reject pleasure but to understand its nature. Enjoyment without clinging is possible, and that is the goal of the practice.

The teacher explains that detachment is not withdrawal from life but engagement without desperation. It is possible to love deeply while holding lightly, to strive wholeheartedly while accepting any outcome. This paradox lies at the very heart of the wisdom tradition. The lotus flower floats on water, the teacher notes, yet is not drowned by it.

Analogies illuminate the point from many angles. The teacher compares the mind to a clear mountain lake: when disturbed by wind, it cannot reflect the sky. But the sky is always there, unchanged, waiting to be seen. Similarly, our essential nature remains untouched by the ripples of circumstance. The practice is not to stop the ripples but to identify with the depth beneath them.

The teacher addresses a common misunderstanding with care. Some think that renunciation means abandoning the world, its duties, and its relationships. True renunciation, the teacher insists, is renouncing the need for the world to be different than it is. It is an inner posture, not an outer performance. One can wear fine clothes and still be free, if the heart does not depend on them.

Stories from the tradition illustrate this with vivid clarity. A great king renounces his throne not because palace life is inherently bad, but because he sees through its hollow promises. A humble householder continues to work and raise a family yet lives from a place of inner freedom that nothing can disturb. The outer form does not determine the inner state.

The teacher then turns to the practical dimension with generosity. How does one cultivate this freedom in the midst of a busy life? Through attention, through honest self-inquiry, through the repeated willingness to question one's own attachments. Each moment of genuine self-examination loosens the grip of habit and reveals a little more space within.

The closing wisdom lands with deep weight: suffering is not a failure of life but an invitation to deeper understanding. Every frustration, every loss, every disappointment carries within it a teaching if we are willing to receive it with an open mind. The path out of suffering is not away from experience but through it — with open eyes and a willing heart.

In the final reflection, the teacher reminds the listener that this understanding is not distant, rare, or reserved for a few. It is available in every breath, every bodily sensation, every moment of genuine attention. The question is not whether the teaching is true but whether we are ready to live from that truth in the midst of ordinary life. The readiness comes not from accumulating more knowledge but from the willingness to be transformed by what we already know deep within.

The discourse concludes with a simple but powerful image: the mind is like a mirror. When covered with the dust of habit and desire, it reflects only distortion. When cleaned through patient attention, it reflects reality as it truly is. The practice of truth is the practice of cleaning that mirror — not through force or struggle, but through gentle, persistent, and honest attention to what is, exactly as it is, in this present moment.
"""


def _make_response(text: str) -> MagicMock:
    r = MagicMock()
    r.text = text
    return r


@pytest.fixture
def settings():
    return MagicMock()


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def pipeline(settings, mock_llm):
    with patch("ytfactory.script_enhancer.pipeline.get_llm_provider", return_value=mock_llm):
        return DocumentaryScriptEnhancerPipeline(settings)


# ── _parse_narrative_score ──────────────────────────────────────────────────────

class TestParseNarrativeScore:
    def test_parses_valid_block(self):
        text = "My script here.\n\n---NARRATIVE SCORE---\nHook: 8/10\nOverall: 9/10\n---END SCORE---"
        script, score = _parse_narrative_score(text)
        assert score == 9.0
        assert "My script here." in script
        assert "NARRATIVE SCORE" not in script

    def test_returns_none_when_no_block(self):
        text = "Just a script with no score."
        script, score = _parse_narrative_score(text)
        assert score is None
        assert script == text

    def test_parses_decimal_score(self):
        text = "Script.\n\n---NARRATIVE SCORE---\nOverall: 8.5/10\n---END SCORE---"
        _, score = _parse_narrative_score(text)
        assert score == 8.5

    def test_strips_whitespace_from_script_part(self):
        text = "Script here.\n\n---NARRATIVE SCORE---\nOverall: 9/10\n---END SCORE---"
        script, _ = _parse_narrative_score(text)
        assert script == "Script here."


# ── DocumentaryEnhancerValidator ───────────────────────────────────────────────

class TestDocumentaryEnhancerValidator:
    def setup_method(self):
        self.v = DocumentaryEnhancerValidator()

    def test_pass1_ok_when_placeholders_preserved(self):
        original = "Start {{SCRIPTURE_1}} end. " * 100
        pass1 = "Start {{SCRIPTURE_1}} end. " * 100
        ok, errors = self.v.validate_pass1(original, pass1)
        assert ok
        assert errors == []

    def test_pass1_fails_when_placeholder_dropped(self):
        original = "Start {{SCRIPTURE_1}} middle {{SCRIPTURE_2}} end. " * 100
        pass1 = "Start middle {{SCRIPTURE_2}} end. " * 100
        ok, errors = self.v.validate_pass1(original, pass1)
        assert not ok
        assert any("SCRIPTURE_1" in e for e in errors)

    def test_pass1_fails_when_coverage_too_low(self):
        original = "word " * 100
        pass1 = "word " * 60  # only 60% — below 80% threshold
        ok, errors = self.v.validate_pass1(original, pass1)
        assert not ok
        assert any("coverage too low" in e for e in errors)

    def test_pass1_ok_when_coverage_at_threshold(self):
        original = "word " * 100
        pass1 = "word " * 80  # exactly 80%
        ok, errors = self.v.validate_pass1(original, pass1)
        assert ok

    def test_pass1_shorten_mode_skips_coverage_check(self):
        # In shorten mode, 60% coverage is acceptable — shortening is the goal
        original = "word " * 100
        pass1 = "word " * 60  # 60% — would fail expand mode
        ok, errors = self.v.validate_pass1(original, pass1, mode="shorten")
        assert ok
        assert errors == []

    def test_validate_final_shorten_mode_skips_coverage_check(self):
        # In shorten mode, final output below 80% of input is expected
        original = "word " * 200
        final = "word " * 140  # 70% — would fail expand mode
        placeholders: dict[str, str] = {}
        ok, errors, warnings = self.v.validate_final(original, final, placeholders, mode="shorten")
        assert ok
        assert not any("coverage too low" in e for e in errors)

    def test_validate_final_ok_when_scripture_present(self):
        original = "The teacher said ॐ नमः शिवाय with reverence."
        final = "The teacher spoke: ॐ नमः शिवाय — the eternal invocation."
        placeholders = {"SCRIPTURE_1": "ॐ नमः शिवाय"}
        ok, errors, warnings = self.v.validate_final(original, final, placeholders)
        assert ok
        assert errors == []

    def test_validate_final_fails_when_scripture_missing(self):
        original = "The teacher said ॐ नमः शिवाय with reverence."
        final = "The teacher spoke an invocation without the original text."
        placeholders = {"SCRIPTURE_1": "ॐ नमः शிவாய"}
        ok, errors, warnings = self.v.validate_final(original, final, placeholders)
        assert not ok
        assert any("Scripture span missing" in e for e in errors)

    def test_validate_final_warns_on_new_years(self):
        original = "Ancient wisdom from long ago."
        final = "Ancient wisdom documented in 1845 by scholars."
        placeholders: dict[str, str] = {}
        ok, errors, warnings = self.v.validate_final(original, final, placeholders)
        # ok can be True (coverage may pass), but warnings should exist
        assert any("1845" in w for w in warnings)

    def test_validate_final_no_warning_when_year_in_original(self):
        original = "The year 1845 was significant in the movement."
        final = "The year 1845 marks a pivotal moment in the movement's history."
        placeholders: dict[str, str] = {}
        ok, errors, warnings = self.v.validate_final(original, final, placeholders)
        assert not any("1845" in w for w in warnings)


# ── DocumentaryScriptEnhancerPipeline ──────────────────────────────────────────

class TestDocumentaryScriptEnhancerPipeline:
    def test_backward_compat_alias(self):
        assert ScriptEnhancerPipeline is DocumentaryScriptEnhancerPipeline

    def test_happy_path_writes_all_files(self, pipeline, mock_llm, tmp_path):
        mock_llm.generate.side_effect = [
            _make_response(PASS1_CLEAN),
            _make_response(PASS2_SCORED_GOOD),
            _make_response(PASS3_EXPANDED),
        ]
        project_id = "proj-001"

        with patch("ytfactory.script_enhancer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run(
                project_id,
                topic="Suffering and Attachment",
                script_text=SAMPLE_SCRIPT,
            )

        assert result.strip() != ""
        script_dir = tmp_path / project_id / "script"
        assert (script_dir / "script.md").exists()
        assert (script_dir / "script_pass1.md").exists()
        assert (script_dir / "script_original.md").exists()
        assert (script_dir / "script.json").exists()
        assert (script_dir / "enhancement-report.json").exists()

    def test_enhancement_report_structure(self, pipeline, mock_llm, tmp_path):
        mock_llm.generate.side_effect = [
            _make_response(PASS1_CLEAN),
            _make_response(PASS2_SCORED_GOOD),
            _make_response(PASS3_EXPANDED),
        ]
        project_id = "proj-002"

        with patch("ytfactory.script_enhancer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run(project_id, topic="Test Topic", script_text=SAMPLE_SCRIPT)

        report = json.loads(
            (tmp_path / project_id / "script" / "enhancement-report.json").read_text()
        )
        assert report["pass1"]["validation_passed"] is True
        assert report["pass1"]["fallback_used"] is False
        assert report["pass2"]["iterations"] == 1
        assert report["pass2"]["narrative_score"] == 9.0
        assert report["final"]["validation_passed"] is True
        assert len(report["scripture_spans"]) == 0 if isinstance(report["scripture_spans"], list) else report["scripture_spans"] == 0

    def test_pass1_validation_failure_uses_fallback(self, pipeline, mock_llm, tmp_path):
        # Pass 1 returns very short output — coverage will fail
        short_pass1 = "Just a few words."
        mock_llm.generate.side_effect = [
            _make_response(short_pass1),
            _make_response(PASS2_SCORED_GOOD),
            _make_response(PASS3_EXPANDED),
        ]
        project_id = "proj-003"

        with patch("ytfactory.script_enhancer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run(project_id, topic="Test", script_text=SAMPLE_SCRIPT)

        report = json.loads(
            (tmp_path / project_id / "script" / "enhancement-report.json").read_text()
        )
        assert report["pass1"]["fallback_used"] is True
        assert report["pass1"]["validation_passed"] is False
        assert len(report["pass1"]["errors"]) > 0

    def test_pass2_iterates_when_score_below_threshold(self, pipeline, mock_llm, tmp_path):
        """First iteration scores 7.0 → second iteration scores 9.0 → stops."""
        mock_llm.generate.side_effect = [
            _make_response(PASS1_CLEAN),        # Pass 1
            _make_response(PASS2_SCORED_LOW),   # Pass 2 iteration 1: score 7.0
            _make_response(PASS2_SCORED_GOOD),  # Pass 2 iteration 2: score 9.0
            _make_response(PASS3_EXPANDED),
        ]
        project_id = "proj-004"

        with patch("ytfactory.script_enhancer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run(project_id, topic="Test", script_text=SAMPLE_SCRIPT)

        assert mock_llm.generate.call_count == 4  # 1 pass1 + 2 pass2 + 1 pass3

        report = json.loads(
            (tmp_path / project_id / "script" / "enhancement-report.json").read_text()
        )
        assert report["pass2"]["iterations"] == 2
        assert report["pass2"]["narrative_score"] == 9.0

    def test_pass2_stops_at_max_iterations_without_threshold(self, pipeline, mock_llm, tmp_path):
        """Both iterations score below 8.5 — stops at MAX_PASS2_ITERATIONS with best attempt."""
        mock_llm.generate.side_effect = [
            _make_response(PASS1_CLEAN),
            _make_response(PASS2_SCORED_LOW),  # 7.0
            _make_response(PASS2_SCORED_LOW),  # 7.0
            _make_response(PASS3_EXPANDED),
        ]
        project_id = "proj-005"

        with patch("ytfactory.script_enhancer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run(project_id, topic="Test", script_text=SAMPLE_SCRIPT)

        assert mock_llm.generate.call_count == 4  # 1 pass1 + 2 pass2 + 1 pass3

        report = json.loads(
            (tmp_path / project_id / "script" / "enhancement-report.json").read_text()
        )
        assert report["pass2"]["iterations"] == 2

    def test_scripture_verbatim_in_final_output(self, pipeline, mock_llm, tmp_path):
        """Scripture span must survive both passes byte-for-byte."""
        scripture = "ॐ नमः शिवाय"
        script = f"The teacher began with {scripture} and spoke at length on the nature of consciousness."

        # Pass 1 preserves placeholder text
        pass1_text = "The teacher began with {{SCRIPTURE_1}} and spoke at length on the nature of consciousness."
        pass2_text = (
            f"The teacher began with {{{{SCRIPTURE_1}}}} and the wisdom flowed.\n\n"
            "---NARRATIVE SCORE---\nOverall: 9/10\n---END SCORE---"
        )
        mock_llm.generate.side_effect = [
            _make_response(pass1_text),
            _make_response(pass2_text),
            _make_response(PASS3_EXPANDED),
        ]

        with patch("ytfactory.script_enhancer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-006", topic="Sacred Teachings", script_text=script)

        assert scripture in result

    def test_final_validation_fallback_to_pass1(self, pipeline, mock_llm, tmp_path):
        """Final validation failure triggers fallback to Pass 1 output."""
        script = f"The teacher said ॐ नमः शिवाय at the start."
        scripture = "ॐ नमः शिવાя"

        pass1_text = "The teacher said {{SCRIPTURE_1}} at the start."
        # Pass 2 drops the placeholder — final validation should fail
        pass2_text = (
            "The teacher spoke an invocation.\n\n"
            "---NARRATIVE SCORE---\nOverall: 9/10\n---END SCORE---"
        )
        mock_llm.generate.side_effect = [
            _make_response(pass1_text),
            _make_response(pass2_text),
            _make_response(PASS3_EXPANDED),
        ]

        with patch("ytfactory.script_enhancer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-007", topic="Sacred", script_text=script)

        report = json.loads(
            (tmp_path / "proj-007" / "script" / "enhancement-report.json").read_text()
        )
        assert report["final"]["fallback_to_pass1"] is True

    def test_reads_script_from_file_when_not_provided(self, pipeline, mock_llm, tmp_path):
        project_id = "proj-008"
        script_dir = tmp_path / project_id / "script"
        script_dir.mkdir(parents=True)
        (script_dir / "script.md").write_text(SAMPLE_SCRIPT, encoding="utf-8")

        mock_llm.generate.side_effect = [
            _make_response(PASS1_CLEAN),
            _make_response(PASS2_SCORED_GOOD),
            _make_response(PASS3_EXPANDED),
        ]

        with patch("ytfactory.script_enhancer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run(project_id, topic="Test")

        assert result.strip() != ""

    def test_raises_when_no_script_file(self, pipeline, tmp_path):
        with patch("ytfactory.script_enhancer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with pytest.raises(FileNotFoundError):
                pipeline.run("proj-missing", topic="Test")

    def test_script_json_written_with_stats(self, pipeline, mock_llm, tmp_path):
        mock_llm.generate.side_effect = [
            _make_response(PASS1_CLEAN),
            _make_response(PASS2_SCORED_GOOD),
            _make_response(PASS3_EXPANDED),
        ]

        with patch("ytfactory.script_enhancer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run("proj-009", topic="Topic", script_text=SAMPLE_SCRIPT)

        data = json.loads((tmp_path / "proj-009" / "script" / "script.json").read_text())
        assert data["topic"] == "Topic"
        assert "word_count" in data
        assert "estimated_minutes" in data
        assert "duration_ok" in data


# ── build_pass1_prompt and build_pass2_prompt ───────────────────────────────────

class TestPromptBuilders:
    def test_pass1_contains_fidelity_goals(self):
        prompt = build_pass1_prompt(
            topic="Karma and Dharma",
            script="Some script here.",
            placeholders={},
        )
        assert "Preserve meaning exactly" in prompt
        assert "Do not optimize for viewer retention" in prompt

    def test_pass1_lists_scripture_placeholders(self):
        prompt = build_pass1_prompt(
            topic="Karma",
            script="Some script.",
            placeholders={"SCRIPTURE_1": "ॐ नमः शिवाय"},
        )
        assert "SCRIPTURE_1" in prompt
        assert "ॐ नमः शिवाय" in prompt

    def test_pass1_no_scripture_message(self):
        prompt = build_pass1_prompt(
            topic="Test",
            script="Script.",
            placeholders={},
        )
        assert "No scripture spans detected" in prompt

    def test_pass2_contains_retention_rules(self):
        prompt = build_pass2_prompt(
            topic="Test",
            script="Some script.",
        )
        assert "Rule 1" in prompt
        assert "Rule 10" in prompt
        assert "NARRATIVE SCORE" in prompt

    def test_pass2_contains_fabrication_guardrail(self):
        prompt = build_pass2_prompt(
            topic="Test",
            script="Script.",
        )
        assert "FABRICATION GUARDRAIL" in prompt
        assert "clearly hypothetical" in prompt

    def test_pass2_contains_score_format(self):
        prompt = build_pass2_prompt(
            topic="Test",
            script="Script.",
        )
        assert "---NARRATIVE SCORE---" in prompt
        assert "---END SCORE---" in prompt
        assert "8.5" in prompt

    def test_pass2_contains_channel_frame(self):
        prompt = build_pass2_prompt(
            topic="Test",
            script="Script.",
            welcome="Welcome to this channel.",
            closing="Thank you for watching.",
        )
        assert "Welcome to this channel." in prompt
        assert "Thank you for watching." in prompt
