"""Tests for SubtitleEditingEngine (SUBTITLE_INTELLIGENCE_ENGINE_V2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ytfactory.subtitles.editor.engine import SubtitleEditingEngine, _words
from ytfactory.subtitles.editor.provider import CueInput, CueOutput, EditResult, SubtitleEditorProvider
from ytfactory.subtitles.editor.providers.mock import MockSubtitleEditor
from ytfactory.subtitles.editor.providers.llm_provider import LLMSubtitleEditor
from ytfactory.subtitles.models import SubtitleCue


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_cue(index: int, text: str, start: float = 0.0, end: float = 3.0) -> SubtitleCue:
    return SubtitleCue(index=index, start=start, end=end, lines=text.split("\n"))


def make_cues(*texts: str) -> list[SubtitleCue]:
    cues = []
    t = 0.0
    for i, text in enumerate(texts, start=1):
        end = t + 3.0
        cues.append(SubtitleCue(index=i, start=t, end=end, lines=text.split("\n")))
        t = end
    return cues


# ── Mock providers for testing control flow ────────────────────────────────────


class _PunctuationMock(SubtitleEditorProvider):
    """Returns cues with a period added at the end of each — same words."""

    def edit_cues(self, inputs, *, pass_number=1, retry_error=None, previous_score=0,
                  previous_failed_axes=None):
        outputs = []
        for inp in inputs:
            text = inp.original_text.rstrip(".") + "."
            outputs.append(CueOutput(cue_id=inp.cue_id, text=text))
        return EditResult(outputs=outputs, quality_score=100, pass_number=pass_number)


class _WordChangeMock(SubtitleEditorProvider):
    """Returns cues with a word swapped — word validation must revert these."""

    def edit_cues(self, inputs, *, pass_number=1, retry_error=None, previous_score=0,
                  previous_failed_axes=None):
        outputs = []
        for inp in inputs:
            # Replace first word with "CHANGED" — word mismatch
            words = inp.original_text.split()
            if words:
                words[0] = "CHANGED"
            text = " ".join(words)
            outputs.append(CueOutput(cue_id=inp.cue_id, text=text))
        return EditResult(outputs=outputs, quality_score=90, pass_number=pass_number)


class _WrongIdsMock(SubtitleEditorProvider):
    """Returns cue_ids shifted by 100 — triggers cue_id mismatch retry."""

    def __init__(self, succeed_after: int = 2):
        self._calls = 0
        self._succeed_after = succeed_after

    def edit_cues(self, inputs, *, pass_number=1, retry_error=None, previous_score=0,
                  previous_failed_axes=None):
        self._calls += 1
        if self._calls <= self._succeed_after:
            # Wrong IDs — engine must reject and retry
            outputs = [CueOutput(cue_id=inp.cue_id + 100, text=inp.original_text) for inp in inputs]
            return EditResult(outputs=outputs, quality_score=90, pass_number=pass_number)
        # Correct on final attempt
        outputs = [CueOutput(cue_id=inp.cue_id, text=inp.original_text) for inp in inputs]
        return EditResult(outputs=outputs, quality_score=100, pass_number=pass_number)


class _LowScoreMock(SubtitleEditorProvider):
    """Always returns score=50 — engine must use best-effort fallback."""

    def edit_cues(self, inputs, *, pass_number=1, retry_error=None, previous_score=0,
                  previous_failed_axes=None):
        outputs = [CueOutput(cue_id=inp.cue_id, text=inp.original_text) for inp in inputs]
        return EditResult(outputs=outputs, quality_score=50, failed_axes=["line_balance"],
                          pass_number=pass_number)


class _AlwaysRaiseMock(SubtitleEditorProvider):
    """Always raises — engine must exhaust retries and return None."""

    def edit_cues(self, inputs, **kwargs):
        raise RuntimeError("Simulated LLM failure")


# ── _words() helper ────────────────────────────────────────────────────────────


class TestWords:
    def test_same_words_different_punct(self):
        assert _words("Hello, world.") == _words("Hello world")

    def test_detects_word_removal(self):
        assert _words("one two three") != _words("one three")

    def test_detects_word_addition(self):
        assert _words("one two") != _words("one extra two")

    def test_case_insensitive(self):
        assert _words("From childhood") == _words("from childhood")

    def test_contraction_preserved(self):
        assert _words("don't stop") == _words("don't stop")

    def test_contraction_expansion_detected(self):
        assert _words("don't stop") != _words("do not stop")

    def test_multiline(self):
        assert _words("From childhood\nwe learn.") == _words("from childhood we learn")


# ── SubtitleEditingEngine — control flow ──────────────────────────────────────


class TestSubtitleEditingEngineControlFlow:
    def _engine(self, provider, *, max_passes=3, pass_threshold=95.0, max_retries=3, debug=False):
        return SubtitleEditingEngine(
            provider=provider,
            max_passes=max_passes,
            pass_threshold=pass_threshold,
            max_retries=max_retries,
            debug=debug,
        )

    def test_empty_cues_returned_unchanged(self):
        engine = self._engine(MockSubtitleEditor())
        result = engine.edit([], scene_id="scene-001", project_id="proj")
        assert result == []

    def test_mock_returns_cues_unchanged(self):
        cues = make_cues("Hello world", "This is a test")
        engine = self._engine(MockSubtitleEditor())
        result = engine.edit(cues, scene_id="scene-001", project_id="proj")
        assert len(result) == 2
        assert result[0].lines == ["Hello world"]
        assert result[1].lines == ["This is a test"]

    def test_punctuation_change_is_applied(self):
        cues = make_cues("Hello world", "another line")
        engine = self._engine(_PunctuationMock())
        result = engine.edit(cues, scene_id="scene-001", project_id="proj")
        # Trailing period added by mock — same words, valid change
        assert result[0].lines[0].endswith(".")
        assert result[1].lines[0].endswith(".")

    def test_word_change_is_reverted(self):
        cues = make_cues("From childhood we learn")
        engine = self._engine(_WordChangeMock())
        result = engine.edit(cues, scene_id="scene-001", project_id="proj")
        # Word was changed → word validator reverts to original text
        assert "CHANGED" not in result[0].lines[0]
        assert "From childhood we learn" in result[0].lines[0]

    def test_retries_on_cue_id_mismatch_then_succeeds(self):
        mock = _WrongIdsMock(succeed_after=2)
        engine = self._engine(mock, max_retries=3)
        cues = make_cues("One cue")
        result = engine.edit(cues, scene_id="scene-001", project_id="proj")
        # Should eventually succeed after retry
        assert result[0].index == 1
        assert mock._calls == 3  # 2 failures + 1 success

    def test_exhausted_retries_returns_original(self):
        engine = self._engine(_AlwaysRaiseMock(), max_retries=2)
        cues = make_cues("Original text")
        result = engine.edit(cues, scene_id="scene-001", project_id="proj")
        # No valid edit → original returned
        assert result[0].lines == ["Original text"]

    def test_stops_early_at_pass_threshold(self):
        """Score=100 on pass 1 → no further passes needed."""
        call_count = {"n": 0}

        class _CountingMock(SubtitleEditorProvider):
            def edit_cues(self, inputs, **kwargs):
                call_count["n"] += 1
                outputs = [CueOutput(cue_id=inp.cue_id, text=inp.original_text) for inp in inputs]
                return EditResult(outputs=outputs, quality_score=100)

        engine = self._engine(_CountingMock(), max_passes=3)
        engine.edit(make_cues("Text"), scene_id="s1", project_id="p")
        assert call_count["n"] == 1  # stopped after first PASS

    def test_max_passes_reached_uses_best_effort(self):
        engine = self._engine(_LowScoreMock(), max_passes=3, pass_threshold=95.0)
        cues = make_cues("Some text")
        result = engine.edit(cues, scene_id="scene-001", project_id="proj")
        # Score never reached 95 → best-effort: original is returned (score=50 same text)
        assert result[0].lines == ["Some text"]

    def test_multi_cue_scene(self):
        cues = make_cues("Cue one", "Cue two", "Cue three")
        engine = self._engine(MockSubtitleEditor())
        result = engine.edit(cues, scene_id="scene-002", project_id="proj")
        assert len(result) == 3
        assert [c.index for c in result] == [1, 2, 3]

    def test_timing_preserved(self):
        cues = [SubtitleCue(index=1, start=1.5, end=4.2, lines=["Hello"])]
        engine = self._engine(_PunctuationMock())
        result = engine.edit(cues, scene_id="s", project_id="p")
        assert result[0].start == 1.5
        assert result[0].end == 4.2

    def test_multiline_cue_preserved(self):
        cues = [SubtitleCue(index=1, start=0.0, end=4.0, lines=["From childhood", "we learn"])]
        engine = self._engine(MockSubtitleEditor())
        result = engine.edit(cues, scene_id="s", project_id="p")
        assert result[0].lines == ["From childhood", "we learn"]

    def test_provider_passes_improve_over_runs(self):
        """Later passes receive the best-so-far text as input."""
        received_texts: list[str] = []

        class _TrackingMock(SubtitleEditorProvider):
            call_num = 0

            def edit_cues(self, inputs, *, pass_number=1, **kwargs):
                received_texts.append(inputs[0].original_text)
                # Each pass "improves" by appending a comma
                text = inputs[0].original_text + ","
                self.call_num += 1
                # Score < 95 so engine does all 3 passes
                return EditResult(
                    outputs=[CueOutput(cue_id=inputs[0].cue_id, text=text)],
                    quality_score=50,
                    pass_number=pass_number,
                )

        engine = self._engine(_TrackingMock(), max_passes=3, pass_threshold=95.0)
        engine.edit(make_cues("Hello"), scene_id="s", project_id="p")
        # Pass 2 should see the output of pass 1, pass 3 sees output of pass 2
        assert received_texts[0] == "Hello"
        assert received_texts[1] == "Hello,"
        assert received_texts[2] == "Hello,,"


# ── Debug file generation ──────────────────────────────────────────────────────


class TestDebugFiles:
    def test_debug_writes_three_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "workspace" / "jobs" / "proj" / "subtitle-debug" / "editor").mkdir(
            parents=True, exist_ok=True
        )

        cues = make_cues("Hello world")
        engine = SubtitleEditingEngine(
            MockSubtitleEditor(), debug=True, max_passes=1
        )
        engine.edit(cues, scene_id="scene-001", project_id="proj")

        debug_dir = tmp_path / "workspace" / "jobs" / "proj" / "subtitle-debug" / "editor"
        assert (debug_dir / "scene-001-original.srt").exists()
        assert (debug_dir / "scene-001-edited.srt").exists()
        assert (debug_dir / "scene-001-diff.md").exists()

    def test_debug_not_written_when_disabled(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        cues = make_cues("Hello world")
        engine = SubtitleEditingEngine(MockSubtitleEditor(), debug=False, max_passes=1)
        engine.edit(cues, scene_id="scene-001", project_id="proj")

        debug_dir = tmp_path / "workspace" / "jobs" / "proj" / "subtitle-debug" / "editor"
        assert not debug_dir.exists()

    def test_diff_md_records_changed_cues(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "workspace" / "jobs" / "proj" / "subtitle-debug" / "editor").mkdir(
            parents=True, exist_ok=True
        )

        cues = make_cues("Hello world")
        engine = SubtitleEditingEngine(
            _PunctuationMock(), debug=True, max_passes=1
        )
        engine.edit(cues, scene_id="scene-001", project_id="proj")

        diff = (
            tmp_path / "workspace" / "jobs" / "proj" / "subtitle-debug" / "editor" / "scene-001-diff.md"
        ).read_text()
        # The mock adds a period → diff should note a change
        assert "Cue 1" in diff
        assert "Changed cues: 1/1" in diff

    def test_diff_md_reports_zero_changes_for_mock(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "workspace" / "jobs" / "proj" / "subtitle-debug" / "editor").mkdir(
            parents=True, exist_ok=True
        )

        cues = make_cues("Unchanged text")
        engine = SubtitleEditingEngine(MockSubtitleEditor(), debug=True, max_passes=1)
        engine.edit(cues, scene_id="scene-001", project_id="proj")

        diff = (
            tmp_path / "workspace" / "jobs" / "proj" / "subtitle-debug" / "editor" / "scene-001-diff.md"
        ).read_text()
        assert "Changed cues: 0/1" in diff


# ── MockSubtitleEditor ────────────────────────────────────────────────────────


class TestMockSubtitleEditor:
    def test_returns_same_cue_ids(self):
        mock = MockSubtitleEditor()
        inputs = [
            CueInput(cue_id=1, start_time="00:00:00,000", end_time="00:00:03,000",
                     duration_secs=3.0, cps=5.0, original_text="Hello"),
            CueInput(cue_id=2, start_time="00:00:03,000", end_time="00:00:06,000",
                     duration_secs=3.0, cps=5.0, original_text="World"),
        ]
        result = mock.edit_cues(inputs)
        assert [o.cue_id for o in result.outputs] == [1, 2]

    def test_returns_perfect_score(self):
        mock = MockSubtitleEditor()
        inputs = [CueInput(1, "00:00:00,000", "00:00:03,000", 3.0, 5.0, "Text")]
        result = mock.edit_cues(inputs)
        assert result.quality_score == 100

    def test_returns_text_unchanged(self):
        mock = MockSubtitleEditor()
        inputs = [CueInput(1, "00:00:00,000", "00:00:03,000", 3.0, 5.0, "Hello world")]
        result = mock.edit_cues(inputs)
        assert result.outputs[0].text == "Hello world"

    def test_empty_failed_axes(self):
        mock = MockSubtitleEditor()
        inputs = [CueInput(1, "00:00:00,000", "00:00:03,000", 3.0, 5.0, "Text")]
        result = mock.edit_cues(inputs)
        assert result.failed_axes == []


# ── LLMSubtitleEditor prompt building ────────────────────────────────────────


class TestLLMSubtitleEditorPrompt:
    def _editor(self):
        class _FakeLLM:
            def generate(self, prompt, *, system_prompt=None, temperature=0.2):
                class R:
                    text = json.dumps({
                        "edited_cues": [{"cue_id": 1, "text": "Hello."}],
                        "quality_score": 98,
                        "failed_axes": [],
                        "notes": "",
                    })
                    total_tokens = 100
                return R()
        return LLMSubtitleEditor(_FakeLLM())

    def test_prompt_includes_cue_data(self):
        editor = self._editor()
        inputs = [CueInput(1, "00:00:00,000", "00:00:03,000", 3.0, 5.0, "Hello world")]
        prompt = editor._build_user_prompt(inputs, pass_number=1, retry_error=None,
                                           previous_score=0, previous_failed_axes=[])
        assert '"cue_id": 1' in prompt
        assert '"original_text": "Hello world"' in prompt

    def test_prompt_includes_pass_number(self):
        editor = self._editor()
        inputs = [CueInput(1, "00:00:00,000", "00:00:03,000", 3.0, 5.0, "Text")]
        prompt = editor._build_user_prompt(inputs, pass_number=2, retry_error=None,
                                           previous_score=80, previous_failed_axes=["line_balance"])
        assert "pass 2/3" in prompt.lower() or "Editorial pass 2/3" in prompt
        assert "80/100" in prompt
        assert "line_balance" in prompt

    def test_prompt_includes_retry_error(self):
        editor = self._editor()
        inputs = [CueInput(1, "00:00:00,000", "00:00:03,000", 3.0, 5.0, "Text")]
        prompt = editor._build_user_prompt(inputs, pass_number=1,
                                           retry_error="cue_id mismatch",
                                           previous_score=0, previous_failed_axes=[])
        assert "cue_id mismatch" in prompt
        assert "VALIDATION ERROR" in prompt

    def test_parse_valid_json(self):
        raw = json.dumps({
            "edited_cues": [{"cue_id": 3, "text": "Edited text."}],
            "quality_score": 97,
            "failed_axes": [],
            "notes": "minor punct fix",
        })
        result = LLMSubtitleEditor._parse_response(raw, pass_number=1)
        assert result.outputs[0].cue_id == 3
        assert result.outputs[0].text == "Edited text."
        assert result.quality_score == 97
        assert result.notes == "minor punct fix"

    def test_parse_strips_markdown_fence(self):
        raw = "```json\n" + json.dumps({
            "edited_cues": [{"cue_id": 1, "text": "Hello."}],
            "quality_score": 95,
            "failed_axes": [],
            "notes": "",
        }) + "\n```"
        result = LLMSubtitleEditor._parse_response(raw, pass_number=1)
        assert result.quality_score == 95

    def test_edit_cues_calls_llm_and_parses(self):
        editor = self._editor()
        inputs = [CueInput(1, "00:00:00,000", "00:00:03,000", 3.0, 5.0, "Hello")]
        result = editor.edit_cues(inputs)
        assert result.outputs[0].cue_id == 1
        assert result.outputs[0].text == "Hello."
        assert result.quality_score == 98

    def test_system_prompt_used(self):
        captured_system = {}

        class _CaptureLLM:
            def generate(self, prompt, *, system_prompt=None, temperature=0.2):
                captured_system["sp"] = system_prompt

                class R:
                    text = json.dumps({
                        "edited_cues": [{"cue_id": 1, "text": "Text."}],
                        "quality_score": 100, "failed_axes": [], "notes": "",
                    })
                    total_tokens = 0
                return R()

        from ytfactory.subtitles.editor.prompt import EDITORIAL_SYSTEM_PROMPT
        editor = LLMSubtitleEditor(_CaptureLLM())
        inputs = [CueInput(1, "00:00:00,000", "00:00:03,000", 3.0, 5.0, "Text")]
        editor.edit_cues(inputs)
        assert captured_system["sp"] == EDITORIAL_SYSTEM_PROMPT


# ── Editorial prompt content ───────────────────────────────────────────────────


class TestEditorialPromptContent:
    def test_prompt_does_not_include_appendix(self):
        from ytfactory.subtitles.editor.prompt import EDITORIAL_SYSTEM_PROMPT
        assert "APPENDIX" not in EDITORIAL_SYSTEM_PROMPT
        assert "Provider Abstraction" not in EDITORIAL_SYSTEM_PROMPT

    def test_prompt_includes_golden_rule(self):
        from ytfactory.subtitles.editor.prompt import EDITORIAL_SYSTEM_PROMPT
        assert "Golden Rule" in EDITORIAL_SYSTEM_PROMPT
        assert "human subtitle editor" in EDITORIAL_SYSTEM_PROMPT

    def test_prompt_includes_absolute_rules(self):
        from ytfactory.subtitles.editor.prompt import EDITORIAL_SYSTEM_PROMPT
        assert "Never reorder words" in EDITORIAL_SYSTEM_PROMPT
        assert "Never paraphrase" in EDITORIAL_SYSTEM_PROMPT

    def test_prompt_includes_document_first(self):
        from ytfactory.subtitles.editor.prompt import EDITORIAL_SYSTEM_PROMPT
        assert "Document-First" in EDITORIAL_SYSTEM_PROMPT

    def test_prompt_includes_quality_score(self):
        from ytfactory.subtitles.editor.prompt import EDITORIAL_SYSTEM_PROMPT
        assert "Quality Score" in EDITORIAL_SYSTEM_PROMPT
        assert "95" in EDITORIAL_SYSTEM_PROMPT


# ── Settings ──────────────────────────────────────────────────────────────────


class TestSubtitleEditorSettings:
    def test_editor_disabled_by_default(self):
        from pydantic.fields import FieldInfo
        from ytfactory.config.settings import Settings
        default = Settings.model_fields["subtitle_editor_enabled"].default
        assert default is False

    def test_default_provider_is_llm(self):
        from ytfactory.config.settings import Settings
        default = Settings.model_fields["subtitle_editor_provider"].default
        assert default == "llm"

    def test_default_max_passes(self):
        from ytfactory.config.settings import Settings
        assert Settings.model_fields["subtitle_editor_max_passes"].default == 3

    def test_default_pass_threshold(self):
        from ytfactory.config.settings import Settings
        assert Settings.model_fields["subtitle_editor_pass_threshold"].default == 95.0

    def test_default_max_retries(self):
        from ytfactory.config.settings import Settings
        assert Settings.model_fields["subtitle_editor_max_retries"].default == 3
