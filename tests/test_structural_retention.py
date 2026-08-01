"""Tests for StructuralRetentionPipeline (see STRUCTURAL_RETENTION_PASS_SPEC.md).

No live LLM calls (see CLAUDE.md — tests/ must not require live keys). The
eagle-script fixture test uses a mocked LLM response crafted to satisfy the
spec's 5 success criteria, verifying the PIPELINE correctly parses/persists
them — not the live model's creative quality on that script (that is a
manual break-in-period review, per spec).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.structural_retention.pipeline import (
    _MOVE_KEYS,
    StructuralRetentionPipeline,
    _drop_identical_text_flags,
    _normalize_for_identity,
    _parse_json_response,
    _parse_structural_moves,
)

EAGLE_SCRIPT_PATH = (
    Path(__file__).parent.parent
    / "base_scripts"
    / "refined script files"
    / "word-for-those-who-say-cant-do-anything.md"
)

SAMPLE_INPUT = """\
A bird once built a nest.

The chick asked, "Where is such strength in me?"

Bhagiratha was told it was impossible. He did it anyway.

This is Atma Theory. Join us on this journey. Clear mind. Meaningful life.
"""


def _make_response(text: str) -> MagicMock:
    r = MagicMock()
    r.text = text
    return r


def _moves_json(stories_cut=None, stories_reordered=None, **statuses) -> str:
    payload = {
        key: {"status": statuses.get(key, "not_needed"), "note": statuses.get(f"{key}_note", "")}
        for key in _MOVE_KEYS
    }
    payload["stories_cut"] = stories_cut or []
    payload["stories_reordered"] = stories_reordered or []
    return json.dumps(payload)


def _restructure_response(narration: str, **kwargs) -> str:
    return (
        f"{narration}\n\n---STRUCTURAL MOVES---\n{_moves_json(**kwargs)}\n---END STRUCTURAL MOVES---"
    )


def _move_status(report: dict, move_name: str) -> str:
    return next(m["status"] for m in report["moves_applied"] if m["move"] == move_name)


@pytest.fixture
def settings():
    s = MagicMock()
    s.structural_pass_enabled = True
    s.structural_pass_faithfulness_check = True
    return s


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def pipeline(settings, mock_llm):
    with patch("ytfactory.structural_retention.pipeline.get_llm_provider", return_value=mock_llm):
        return StructuralRetentionPipeline(settings)


# ── _parse_structural_moves ─────────────────────────────────────────────────


class TestParseStructuralMoves:
    def test_parses_all_five_moves_fired(self):
        text = _restructure_response(
            "Restructured narration here.",
            open_loop="fired",
            break_parallel_examples="fired",
            shadow_beat="fired",
            depth_over_coverage="fired",
            climax_breath="fired",
            stories_cut=["The watchmaker parable — redundant with Bhagiratha"],
            stories_reordered=["Chick's question: paragraph 1 -> final paragraph"],
        )
        narration, report = _parse_structural_moves(text)
        assert narration == "Restructured narration here."
        for key in _MOVE_KEYS:
            assert report["moves"][key]["status"] == "fired"
        assert report["stories_cut"] == ["The watchmaker parable — redundant with Bhagiratha"]
        assert report["stories_reordered"] == ["Chick's question: paragraph 1 -> final paragraph"]

    @pytest.mark.parametrize("move_key", _MOVE_KEYS)
    def test_each_move_individually_detectable(self, move_key):
        overrides = {move_key: "fired", f"{move_key}_note": f"{move_key} fired here"}
        text = _restructure_response("Narration.", **overrides)
        _, report = _parse_structural_moves(text)
        assert report["moves"][move_key]["status"] == "fired"
        assert report["moves"][move_key]["note"] == f"{move_key} fired here"
        for other_key in _MOVE_KEYS:
            if other_key != move_key:
                assert report["moves"][other_key]["status"] == "not_needed"

    def test_missing_block_returns_empty_report(self):
        narration, report = _parse_structural_moves("Just narration, no block.")
        assert narration == "Just narration, no block."
        assert report == {"moves": {}, "stories_cut": [], "stories_reordered": []}

    def test_malformed_json_block_falls_back_gracefully(self):
        text = "Narration.\n\n---STRUCTURAL MOVES---\nnot json\n---END STRUCTURAL MOVES---"
        narration, report = _parse_structural_moves(text)
        assert narration == "Narration."
        assert report["moves"] == {}
        assert report["stories_cut"] == []


class TestParseJsonResponse:
    def test_handles_valid_dict(self):
        assert _parse_json_response('{"key": "value"}') == {"key": "value"}

    def test_handles_markdown_fenced_json(self):
        text = '```json\n{\n  "key": "value"\n}\n```'
        assert _parse_json_response(text) == {"key": "value"}

    def test_returns_empty_on_invalid(self):
        assert _parse_json_response("Not JSON here") == {}


# ── Prompt builders ──────────────────────────────────────────────────────────


class TestPromptBuilders:
    def test_structural_pass_prompt_contains_five_moves_and_hard_rule(self):
        from ytfactory.agents.prompts.structural_retention import build_structural_pass_prompt

        prompt = build_structural_pass_prompt("Some script.", {})
        assert "OPEN LOOP" in prompt
        assert "BREAK PARALLEL EXAMPLES" in prompt
        assert "SHADOW BEAT" in prompt
        assert "DEPTH OVER COVERAGE" in prompt
        assert "CLIMAX BREATH" in prompt
        assert "Reshape structure freely. Never change meaning." in prompt
        assert "BRAND BLOCK" in prompt
        assert "No scripture spans detected" in prompt

    def test_structural_pass_prompt_is_lean_no_framework_reinjection(self):
        """The pass must not re-inject the full ATMA_THEORY framework (already ran in Pass 1)."""
        from ytfactory.agents.prompts.structural_retention import build_structural_pass_prompt

        prompt = build_structural_pass_prompt("Some script.", {})
        for framework_marker in ("MISSION", "THE GOLDEN RULE", "SCRIPT STRUCTURE", "VISUAL WRITING"):
            assert framework_marker not in prompt

    def test_structural_pass_prompt_lists_scripture_placeholders(self):
        from ytfactory.agents.prompts.structural_retention import build_structural_pass_prompt

        prompt = build_structural_pass_prompt("Script.", {"SCRIPTURE_1": "ॐ नमः शिवाय"})
        assert "SCRIPTURE_1" in prompt
        assert "ॐ नमः शिवाय" in prompt

    def test_faithfulness_prompt_contains_meaning_only_language(self):
        from ytfactory.agents.prompts.structural_retention import build_faithfulness_check_prompt

        prompt = build_faithfulness_check_prompt("orig", "restructured")
        assert "MEANING ONLY" in prompt
        assert "NOT a violation" in prompt
        assert "reordered anywhere" in prompt
        assert "cut entirely" in prompt

    def test_faithfulness_prompt_has_identical_text_rule(self):
        """v5 bug: identical input/output text got flagged as a meaning change."""
        from ytfactory.agents.prompts.structural_retention import build_faithfulness_check_prompt

        prompt = build_faithfulness_check_prompt("orig", "restructured")
        assert "unchanged text cannot have a" in prompt.lower()
        assert "do not" in prompt.lower() and "flag" in prompt.lower()

    def test_break_parallel_examples_has_concrete_detection_instruction(self):
        """v5 bug: model defined the parallel-sequence trigger away instead of declining to cut."""
        import re

        from ytfactory.agents.prompts.structural_retention import build_structural_pass_prompt

        prompt = build_structural_pass_prompt("Some script.", {})
        normalized = re.sub(r"\s+", " ", prompt)
        assert "3+ stories that" in normalized
        assert "does not make them" in normalized.lower()
        assert "you MUST keep the two" in normalized
        assert "Completeness is not a virtue here" in normalized
        assert "NAME every story you evaluated for this pattern" in normalized
        assert 'A "not_needed" with no stories named is invalid' in normalized

    def test_depth_over_coverage_has_loss_aversion_release(self):
        import re

        from ytfactory.agents.prompts.structural_retention import build_structural_pass_prompt

        prompt = build_structural_pass_prompt("Some script.", {})
        normalized = re.sub(r"\s+", " ", prompt)
        assert "Cutting a redundant story is faithful, not unfaithful" in normalized
        assert "NAME every story you evaluated for redundancy" in normalized

    def test_report_schema_reinforces_naming_requirement(self):
        from ytfactory.agents.prompts.structural_retention import build_structural_pass_prompt

        prompt = build_structural_pass_prompt("Some script.", {})
        assert "name every story you evaluated and the shape they share" in prompt.lower()
        assert "name every story you evaluated for redundancy and the truth they share" in prompt.lower()


class TestIdenticalTextFaithfulnessFilter:
    """Fix 3: an identical (or whitespace/punctuation-only-different) input/
    output pair cannot be a genuine faithfulness flag — deterministic backstop
    for when the model doesn't follow the prompt-level instruction."""

    def test_normalize_ignores_whitespace_and_punctuation(self):
        a = _normalize_for_identity('The eagle doesn\'t teach; the chick learns by watching...')
        b = _normalize_for_identity("The eagle doesnt teach the chick learns by watching")
        assert a == b

    def test_drops_flag_with_identical_meanings(self):
        flags = [
            {
                "item": "eagle teaching line",
                "input_meaning": "The eagle doesn't teach; the chick learns by watching.",
                "output_meaning": "The eagle doesn't teach; the chick learns by watching.",
                "severity": "minor",
            }
        ]
        assert _drop_identical_text_flags(flags) == []

    def test_drops_flag_differing_only_in_punctuation_and_case(self):
        flags = [
            {
                "item": "x",
                "input_meaning": "The Eagle doesn't teach, the chick learns by watching",
                "output_meaning": "the eagle doesnt teach the chick learns by watching...",
                "severity": "major",
            }
        ]
        assert _drop_identical_text_flags(flags) == []

    def test_keeps_flag_with_genuinely_different_meanings(self):
        flags = [
            {
                "item": "y",
                "input_meaning": "Attachment causes suffering.",
                "output_meaning": "Attachment guarantees happiness.",
                "severity": "major",
            }
        ]
        assert _drop_identical_text_flags(flags) == flags

    def test_mixed_list_keeps_only_the_genuine_flag(self):
        identical = {
            "item": "unchanged",
            "input_meaning": "Same text here.",
            "output_meaning": "Same text here.",
            "severity": "minor",
        }
        genuine = {
            "item": "changed",
            "input_meaning": "The teacher said suffering is real.",
            "output_meaning": "The teacher said suffering is an illusion.",
            "severity": "major",
        }
        result = _drop_identical_text_flags([identical, genuine])
        assert result == [genuine]


# ── Pipeline: disabled / config ──────────────────────────────────────────────


class TestPipelineDisabled:
    def test_disabled_pass_is_full_noop(self, mock_llm, tmp_path):
        settings = MagicMock()
        settings.structural_pass_enabled = False
        with patch("ytfactory.structural_retention.pipeline.get_llm_provider", return_value=mock_llm):
            pipeline = StructuralRetentionPipeline(settings)

        with patch("ytfactory.structural_retention.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-disabled", script_text=SAMPLE_INPUT)

        assert result == SAMPLE_INPUT
        mock_llm.generate.assert_not_called()
        assert not (tmp_path / "proj-disabled" / "script" / "structural-retention-report.json").exists()

    def test_faithfulness_check_disabled_skips_second_llm_call(self, mock_llm, tmp_path):
        settings = MagicMock()
        settings.structural_pass_enabled = True
        settings.structural_pass_faithfulness_check = False
        with patch("ytfactory.structural_retention.pipeline.get_llm_provider", return_value=mock_llm):
            pipeline = StructuralRetentionPipeline(settings)

        mock_llm.generate.side_effect = [_make_response(_restructure_response("Narration."))]

        with patch("ytfactory.structural_retention.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run("proj-nofaith", script_text=SAMPLE_INPUT)

        assert mock_llm.generate.call_count == 1
        report = json.loads(
            (tmp_path / "proj-nofaith" / "script" / "structural-retention-report.json").read_text()
        )
        assert report["faithfulness_check_enabled"] is False
        assert report["faithfulness_flags"] == []
        assert report["structural_score"] is None


# ── Pipeline: basic run + report artifact ────────────────────────────────────


class TestPipelineBasicRun:
    def test_writes_all_artifacts(self, pipeline, mock_llm, tmp_path):
        mock_llm.generate.side_effect = [
            _make_response(_restructure_response("Restructured text.")),
            _make_response(json.dumps({"faithfulness_flags": [], "structural_score": 8.0})),
        ]
        with patch("ytfactory.structural_retention.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-001", script_text=SAMPLE_INPUT)

        assert result.strip() == "Restructured text."
        script_dir = tmp_path / "proj-001" / "script"
        assert (script_dir / "script.md").read_text(encoding="utf-8").strip() == "Restructured text."
        assert (script_dir / "pre-structural-retention.md").read_text(encoding="utf-8") == SAMPLE_INPUT
        report = json.loads((script_dir / "structural-retention-report.json").read_text())
        assert report["enabled"] is True
        assert report["structural_score"] == 8.0

    def test_reads_script_from_file_when_not_provided(self, pipeline, mock_llm, tmp_path):
        project_id = "proj-002"
        script_dir = tmp_path / project_id / "script"
        script_dir.mkdir(parents=True)
        (script_dir / "script.md").write_text(SAMPLE_INPUT, encoding="utf-8")

        mock_llm.generate.side_effect = [
            _make_response(_restructure_response("From file.")),
            _make_response(json.dumps({"faithfulness_flags": [], "structural_score": 9.0})),
        ]
        with patch("ytfactory.structural_retention.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run(project_id)

        assert result.strip() == "From file."

    def test_raises_when_no_script_file(self, pipeline, tmp_path):
        with patch("ytfactory.structural_retention.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with pytest.raises(FileNotFoundError):
                pipeline.run("proj-missing")

    def test_scripture_span_survives_restructure(self, pipeline, mock_llm, tmp_path):
        # Explicit <scripture> markers give a single reliable placeholder;
        # the Indic-Unicode-range heuristic in extract_scripture_spans has a
        # pre-existing multi-span-split quirk on some phrases (also present,
        # and masked by Pass 3 fallback, in the existing enhancer test suite)
        # that is out of scope for this pass.
        scripture = "<scripture>ॐ नमः शिवाय</scripture>"
        script = f"The teacher said {scripture} and continued.\n\nThis is Atma Theory."
        mock_llm.generate.side_effect = [
            _make_response(_restructure_response("The teacher said {{SCRIPTURE_1}} at the close.")),
            _make_response(json.dumps({"faithfulness_flags": [], "structural_score": 9.0})),
        ]
        with patch("ytfactory.structural_retention.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-scripture", script_text=script)
        assert scripture in result


# ── Faithfulness check: non-blocking ─────────────────────────────────────────


class TestFaithfulnessCheckNonBlocking:
    def _run(self, pipeline, mock_llm, tmp_path, restructure_text, check_result, project_id):
        mock_llm.generate.side_effect = [
            _make_response(restructure_text),
            _make_response(json.dumps(check_result)),
        ]
        with patch("ytfactory.structural_retention.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run(project_id, script_text=SAMPLE_INPUT)
        report = json.loads(
            (tmp_path / project_id / "script" / "structural-retention-report.json").read_text()
        )
        return result, report

    def test_meaning_preserving_reorder_zero_flags(self, pipeline, mock_llm, tmp_path):
        restructure = _restructure_response(
            "Reordered narration, same meaning.", stories_reordered=["X: 1 -> 3"]
        )
        result, report = self._run(
            pipeline, mock_llm, tmp_path, restructure,
            {"faithfulness_flags": [], "structural_score": 9.0},
            "proj-faith-reorder",
        )
        assert report["faithfulness_flags"] == []
        assert "Reordered narration" in result

    def test_fabricated_teaching_flagged_but_not_blocking(self, pipeline, mock_llm, tmp_path):
        restructure = _restructure_response("Narration with a fabricated new teaching.")
        check_result = {
            "faithfulness_flags": [
                {
                    "item": "new teaching about karma cycles",
                    "input_meaning": "not present in original",
                    "output_meaning": "invented teaching",
                    "severity": "major",
                }
            ],
            "structural_score": 6.0,
        }
        result, report = self._run(
            pipeline, mock_llm, tmp_path, restructure, check_result, "proj-faith-fabricated"
        )
        assert len(report["faithfulness_flags"]) == 1
        assert report["faithfulness_flags"][0]["severity"] == "major"
        # Non-blocking: output is still returned unmodified, no auto-revert, no exception.
        assert "fabricated new teaching" in result

    def test_identical_text_flag_filtered_from_report(self, pipeline, mock_llm, tmp_path):
        """v5 bug reproduction: model flags an item whose input/output text is
        identical. The report must end up with zero flags — the genuine flag
        survives, the identical-text one is dropped before it's written."""
        restructure = _restructure_response("Narration, mostly unchanged.")
        check_result = {
            "faithfulness_flags": [
                {
                    "item": "eagle teaching line",
                    "input_meaning": "The eagle doesn't teach; the chick learns by watching.",
                    "output_meaning": "The eagle doesn't teach; the chick learns by watching.",
                    "severity": "minor",
                },
                {
                    "item": "genuine drift",
                    "input_meaning": "Suffering is real.",
                    "output_meaning": "Suffering is an illusion.",
                    "severity": "major",
                },
            ],
            "structural_score": 8.0,
        }
        result, report = self._run(
            pipeline, mock_llm, tmp_path, restructure, check_result, "proj-faith-identical"
        )
        assert len(report["faithfulness_flags"]) == 1
        assert report["faithfulness_flags"][0]["item"] == "genuine drift"

    def test_cut_story_zero_flags(self, pipeline, mock_llm, tmp_path):
        restructure = _restructure_response(
            "Narration with one story cut, meaning preserved elsewhere.",
            stories_cut=["Watchmaker parable — redundant"],
        )
        result, report = self._run(
            pipeline, mock_llm, tmp_path, restructure,
            {"faithfulness_flags": [], "structural_score": 8.5},
            "proj-faith-cut",
        )
        assert report["faithfulness_flags"] == []
        assert report["stories_cut"] == ["Watchmaker parable — redundant"]

    def test_never_aborts_even_when_stop_on_quality_gate_failure_true(
        self, mock_llm, tmp_path
    ):
        """Faithfulness flags are report-only. This pipeline doesn't even read
        stop_on_quality_gate_failure — confirm a flag never raises regardless."""
        settings = MagicMock()
        settings.structural_pass_enabled = True
        settings.structural_pass_faithfulness_check = True
        settings.stop_on_quality_gate_failure = True
        with patch("ytfactory.structural_retention.pipeline.get_llm_provider", return_value=mock_llm):
            pipeline = StructuralRetentionPipeline(settings)

        mock_llm.generate.side_effect = [
            _make_response(_restructure_response("Narration.")),
            _make_response(
                json.dumps(
                    {
                        "faithfulness_flags": [
                            {
                                "item": "x",
                                "input_meaning": "a",
                                "output_meaning": "b",
                                "severity": "major",
                            }
                        ],
                        "structural_score": 3.0,
                    }
                )
            ),
        ]
        with patch("ytfactory.structural_retention.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-never-abort", script_text=SAMPLE_INPUT)
        assert result  # returned normally, no exception raised


# ── Eagle script canonical fixture ───────────────────────────────────────────


class TestEagleScriptFixture:
    """Canonical before/after fixture per STRUCTURAL_RETENTION_PASS_SPEC.md.

    Mocked LLM response crafted to satisfy the 5 success criteria — this
    verifies the pipeline correctly parses/persists them, not the live
    model's writing quality on this script (manual break-in-period review).
    """

    @pytest.mark.skipif(
        not EAGLE_SCRIPT_PATH.exists(),
        reason="fixture script not present in this checkout",
    )
    def test_five_success_criteria(self, pipeline, mock_llm, tmp_path):
        script_text = EAGLE_SCRIPT_PATH.read_text(encoding="utf-8")

        restructured_narration = (
            "A bird once built a nest, and laid an eagle's egg.\n\n"
            'The chick asked, "Where is such strength in me?" '
            'The mother did not answer. She only said, "Try."\n\n'
            "Bhagiratha was told it was impossible. He brought the Ganga down anyway.\n\n"
            "The watchmaker was told it was impossible. With half a loaf of bread, "
            "he built an empire that fed thousands.\n\n"
            "There were days the chick came back down, wings aching, doubting it "
            "would ever fly.\n\n"
            "Then one day, after eight days of trying, it soared — and understood: "
            "the strength was never absent. It was always there, waiting to be used.\n\n"
            "Sit with that for a moment.\n\n"
            "This is Atma Theory. If these ideas resonate with you, join us on this "
            "journey. Clear mind. Meaningful life."
        )
        restructure_response = _restructure_response(
            restructured_narration,
            open_loop="fired",
            open_loop_note="Chick's question held until the final paragraph payoff.",
            break_parallel_examples="fired",
            break_parallel_examples_note=(
                "Reduced the eagle/Bhagiratha/watchmaker/Vinoba four-parable run to two."
            ),
            shadow_beat="fired",
            shadow_beat_note="Added the chick's doubt/ache line before the climax.",
            depth_over_coverage="fired",
            depth_over_coverage_note=(
                "Cut Vinoba Bhave's chapati story — same 'small things matter' truth "
                "already carried by the watchmaker."
            ),
            climax_breath="fired",
            climax_breath_note="Added a quiet line before the brand block.",
            stories_cut=[
                "Vinoba Bhave's chapati story — redundant with the "
                "mastery-of-small-things theme already present"
            ],
            stories_reordered=[
                'Chick\'s "where is such strength in me": opening -> final paragraph'
            ],
        )
        faithfulness_response = json.dumps({"faithfulness_flags": [], "structural_score": 9.0})

        mock_llm.generate.side_effect = [
            _make_response(restructure_response),
            _make_response(faithfulness_response),
        ]

        with patch("ytfactory.structural_retention.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-eagle", script_text=script_text)

        report = json.loads(
            (tmp_path / "proj-eagle" / "script" / "structural-retention-report.json").read_text()
        )

        # (a) chick's "where is such strength in me?" NOT answered immediately —
        # held open, paid off near the end.
        question_idx = result.find("Where is such strength in me")
        answer_idx = result.find("the strength was never absent")
        assert question_idx != -1 and answer_idx != -1
        assert answer_idx > question_idx
        assert answer_idx > len(result) / 2  # payoff lands in the back half

        # (b) the four same-shape parables (eagle/Bhagiratha/watchmaker/Vinoba)
        # reduced/separated — not four identical-shape stories in a row.
        assert _move_status(report, "break_parallel_examples") == "fired"
        assert "Vinoba" not in result

        # (c) a shadow beat exists before the climax.
        assert _move_status(report, "shadow_beat") == "fired"
        assert "ache" in result.lower() or "doubt" in result.lower()

        # (d) a breath line sits between the peak and "This is Atma Theory."
        assert _move_status(report, "climax_breath") == "fired"
        breath_idx = result.find("Sit with that for a moment.")
        brand_idx = result.find("This is Atma Theory.")
        assert breath_idx != -1 and brand_idx != -1
        assert breath_idx < brand_idx

        # (e) faithfulness check: no meaning-change flags (cuts/reorders are not flags)
        assert report["faithfulness_flags"] == []
        assert report["stories_cut"]  # the cut IS recorded...
        assert report["stories_reordered"]  # ...as is the reorder...
        assert report["faithfulness_flags"] == []  # ...but neither is a faithfulness flag
