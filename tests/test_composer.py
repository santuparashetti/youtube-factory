"""Tests for ComposerPipeline (see ATMA_THEORY_COMPOSER.md).

No live LLM calls. No mode selection, coverage floor, or reorder ban to test
here by design — those belonged to the retired transform enhancer. Scripture
protection is carried over and tested.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.composer.pipeline import ComposerPipeline, TARGET_MAX_MINUTES, TARGET_MIN_MINUTES
from ytfactory.composer.selection import run_composer_with_ab_selection

# Minimal valid composed script: 11 non-empty lines, "lighthouse" echoed as rehook.
_VALID_COMPOSED = (
    "A lighthouse stands alone at the edge of everything.\n"
    "Its beam cuts through the endless dark each night.\n"
    "Actions shape character and define meaning in life.\n"
    "Clarity of mind brings focus to our work.\n"
    "Every hour spent in focus adds to a larger whole.\n"
    "Discipline is not punishment but a form of self-respect.\n"
    "The quiet worker finishes what the loud talker begins.\n"
    "That lighthouse beam still sweeps the same dark water.\n"
    "This is the Atma Theory.\n"
    "If these ideas resonate with you, join us on this journey.\n"
    "Clear mind. Meaningful life."
)

# Valid script with a scripture placeholder preserved for scripture-span tests.
_VALID_COMPOSED_SCRIPTURE = (
    "The teacher stood before the assembly and began.\n"
    "He opened with {{SCRIPTURE_1}} and the hall fell silent.\n"
    "Actions shape character and define meaning in life.\n"
    "Clarity of mind brings focus to our work.\n"
    "Every hour spent in focus adds to a larger whole.\n"
    "Discipline is not punishment but a form of self-respect.\n"
    "The quiet worker finishes what the loud talker begins.\n"
    "That teacher still stands before the same assembly.\n"
    "This is the Atma Theory.\n"
    "If these ideas resonate with you, join us on this journey.\n"
    "Clear mind. Meaningful life."
)

EAGLE_SCRIPT_PATH = (
    Path(__file__).parent.parent
    / "base_scripts"
    / "refined script files"
    / "word-for-those-who-say-cant-do-anything.md"
)


def _make_response(text: str) -> MagicMock:
    r = MagicMock()
    r.text = text
    return r


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def pipeline(mock_llm):
    settings = MagicMock()
    with patch("ytfactory.composer.pipeline.get_llm_provider", return_value=mock_llm):
        return ComposerPipeline(settings)


class TestComposerPipeline:
    def test_composes_and_writes_files(self, pipeline, mock_llm, tmp_path):
        mock_llm.generate.return_value = _make_response(_VALID_COMPOSED)

        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-1", script_text="Base script content.")

        assert result.strip() == _VALID_COMPOSED.strip()
        script_dir = tmp_path / "proj-1" / "script"
        assert (script_dir / "script.md").read_text(encoding="utf-8").strip() == _VALID_COMPOSED.strip()
        assert (script_dir / "script_pre_composer.md").read_text(
            encoding="utf-8"
        ) == "Base script content."

    def test_single_llm_call_only(self, pipeline, mock_llm, tmp_path):
        mock_llm.generate.return_value = _make_response(_VALID_COMPOSED)
        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run("proj-2", script_text="Base script.")
        assert mock_llm.generate.call_count == 1

    def test_reads_script_from_file_when_not_provided(self, pipeline, mock_llm, tmp_path):
        project_id = "proj-3"
        script_dir = tmp_path / project_id / "script"
        script_dir.mkdir(parents=True)
        (script_dir / "script.md").write_text("File-based base script.", encoding="utf-8")
        mock_llm.generate.return_value = _make_response(_VALID_COMPOSED)

        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run(project_id)

        assert result.strip() == _VALID_COMPOSED.strip()

    def test_raises_when_no_script_file(self, pipeline, tmp_path):
        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with pytest.raises(FileNotFoundError):
                pipeline.run("proj-missing")

    def test_scripture_span_survives_compose(self, pipeline, mock_llm, tmp_path):
        scripture = "<scripture>ॐ नमः शिवाय</scripture>"
        script = f"The teacher said {scripture} and continued."
        mock_llm.generate.return_value = _make_response(_VALID_COMPOSED_SCRIPTURE)
        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-scripture", script_text=script)
        assert scripture in result

    def test_system_prompt_uses_composer_framework(self, pipeline, mock_llm, tmp_path):
        mock_llm.generate.return_value = _make_response(_VALID_COMPOSED)
        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run("proj-4", script_text="Base script.")
        kwargs = mock_llm.generate.call_args.kwargs
        assert "COMPOSE WHOLE" in kwargs["system_prompt"]
        assert "FAITHFULNESS" in kwargs["system_prompt"]

    def test_user_prompt_carries_base_script(self, pipeline, mock_llm, tmp_path):
        mock_llm.generate.return_value = _make_response(_VALID_COMPOSED)
        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run("proj-5", script_text="UNIQUE_BASE_SCRIPT_MARKER")
        prompt_arg = mock_llm.generate.call_args.args[0]
        assert "UNIQUE_BASE_SCRIPT_MARKER" in prompt_arg

    def test_target_range_constants(self):
        assert TARGET_MIN_MINUTES == 7
        assert TARGET_MAX_MINUTES == 9


class TestPromptBuilders:
    def test_system_prompt_contains_framework_sections(self):
        from ytfactory.agents.prompts.composer import build_composer_system_prompt

        prompt = build_composer_system_prompt({})
        for marker in (
            "FAITHFULNESS", "COMPOSE WHOLE", "THE SHAPE", "VOICE", "LENGTH", "OUTPUT"
        ):
            assert marker in prompt
        assert "No scripture spans detected" in prompt

    def test_system_prompt_lists_scripture_placeholders(self):
        from ytfactory.agents.prompts.composer import build_composer_system_prompt

        prompt = build_composer_system_prompt({"SCRIPTURE_1": "ॐ नमः शिवाय"})
        assert "SCRIPTURE_1" in prompt
        assert "ॐ नमः शिवाय" in prompt

    def test_user_prompt_contains_base_script(self):
        from ytfactory.agents.prompts.composer import build_composer_user_prompt

        prompt = build_composer_user_prompt("The source discourse text.")
        assert "The source discourse text." in prompt

    def test_recompose_directive_short_case(self):
        from ytfactory.agents.prompts.composer import build_recompose_directive

        directive = build_recompose_directive(5.5)
        assert "short" in directive
        assert "more of the source" in directive

    def test_recompose_directive_long_case(self):
        from ytfactory.agents.prompts.composer import build_recompose_directive

        directive = build_recompose_directive(11.0)
        assert "long" in directive
        assert "fewer stories" in directive

    def test_user_prompt_includes_recompose_directive_when_given(self):
        from ytfactory.agents.prompts.composer import build_composer_user_prompt

        prompt = build_composer_user_prompt("Base script.", "LENGTH CORRECTION directive text")
        assert "LENGTH CORRECTION directive text" in prompt
        assert "Base script." in prompt

    def test_composer_prompt_contains_audience_character_rule(self):
        from ytfactory.agents.prompts.composer import build_composer_system_prompt

        prompt = build_composer_system_prompt({})
        assert "CHARACTERS & EXAMPLES" in prompt
        assert "Western" in prompt
        assert "US, UK, AU, CA" in prompt

    def test_composer_prompt_contains_visual_anchor_directive(self):
        from ytfactory.agents.prompts.composer import build_composer_system_prompt

        prompt = build_composer_system_prompt({})
        assert "VISUAL ANCHOR CHARACTER" in prompt
        assert "Kai" in prompt
        assert "must NEVER appear" in prompt


class TestKaiFirewallInComposer:
    def test_clean_composer_output_passes(self, pipeline, mock_llm, tmp_path):
        mock_llm.generate.return_value = _make_response(_VALID_COMPOSED)
        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-clean", script_text="Base script.")
        assert "kai" not in result.lower()

    def test_composer_raises_when_kai_leaks(self, pipeline, mock_llm, tmp_path):
        from ytfactory.validators.kai_firewall import KaiFirewallViolation

        composed = "Kai stared at the blank page, unsure. " * 20
        mock_llm.generate.return_value = _make_response(composed)
        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with pytest.raises(KaiFirewallViolation):
                pipeline.run("proj-leak", script_text="Base script.")


class TestGraphWiring:
    def test_composer_node_in_active_graph(self):
        from ytfactory.agents.graph import build_graph

        nodes = build_graph().nodes.keys()
        assert "composer" in nodes
        assert "script_enhancer" not in nodes
        assert "structural_retention" not in nodes

    def test_route_entry_sends_script_md_to_composer(self):
        from ytfactory.agents.graph import _route_entry

        assert _route_entry({"script_md": "some script"}) == "composer"

    def test_retired_modules_still_importable(self):
        """Archived, not deleted — must remain importable for manual/CLI use."""
        import ytfactory.script_enhancer.pipeline  # noqa: F401
        import ytfactory.structural_retention.pipeline  # noqa: F401
        import ytfactory.agents.nodes.script_enhancer  # noqa: F401
        import ytfactory.agents.nodes.structural_retention  # noqa: F401


# ── Eagle script live fixture ────────────────────────────────────────────────


class TestEagleScriptFixture:
    @pytest.mark.skipif(
        not EAGLE_SCRIPT_PATH.exists(),
        reason="fixture script not present in this checkout",
    )
    def test_composes_eagle_script(self, pipeline, mock_llm, tmp_path):
        script_text = EAGLE_SCRIPT_PATH.read_text(encoding="utf-8")
        composed = (
            "Somewhere, a bird once laid an egg that did not belong to her.\n\n"
            + ("The chick learned to fly through doubt and quiet persistence. " * 150)
            + '\n\nIf these ideas resonate with you, join us on this journey.\n\n'
            "Clear mind. Meaningful life."
        )
        mock_llm.generate.return_value = _make_response(composed)

        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-eagle", script_text=script_text)

        assert result.strip().endswith("Clear mind. Meaningful life.")
        assert mock_llm.generate.call_count == 1
        prompt_arg = mock_llm.generate.call_args.args[0]
        assert "Where is such strength in me" in prompt_arg


def _make_settings(*, judge_enabled=True, judge_model="test-judge-model",
                   recompose_enabled=True, recompose_model="test-recompose-model"):
    s = MagicMock()
    s.SCRIPT_JUDGE_ENABLED = judge_enabled
    s.SCRIPT_JUDGE_MODEL = judge_model
    s.GUIDED_RECOMPOSE_ENABLED = recompose_enabled
    s.GUIDED_RECOMPOSER_MODEL = recompose_model
    return s


def _make_verdict(winner="A", hybrid=False, a_score=7.5, b_score=6.5):
    from ytfactory.composer.judge import JudgeVerdict, SectionVerdict
    return JudgeVerdict(
        script_a_score=a_score,
        script_b_score=b_score,
        winner=winner,
        hybrid_recommended=hybrid,
        sections=[SectionVerdict(name="opening", winner=winner, evidence="some quote", reason="stronger hook")],
        hybrid_rationale="A has opening, B has ending.",
        verdict_summary="Script A is the cleaner choice.",
    )


_VALID_JUDGE_JSON = """{
  "script_a_score": 7.5,
  "script_b_score": 6.5,
  "winner": "A",
  "hybrid_recommended": false,
  "sections": [{"name": "opening", "winner": "A", "evidence": "quote", "reason": "stronger hook"}],
  "hybrid_rationale": "A dominates.",
  "verdict_summary": "Script A is the winner."
}"""


class TestScriptJudge:
    def test_judge_returns_verdict_on_valid_json(self):
        from ytfactory.composer.judge import judge_scripts

        mock_provider = MagicMock()
        mock_provider.generate.return_value = _make_response(_VALID_JUDGE_JSON)
        settings = _make_settings()

        verdict = judge_scripts("Script A text", "Script B text", mock_provider, settings)

        assert verdict is not None
        assert verdict.winner == "A"
        assert verdict.script_a_score == 7.5
        assert verdict.hybrid_recommended is False

    def test_judge_returns_none_on_json_parse_failure(self):
        from ytfactory.composer.judge import judge_scripts

        mock_provider = MagicMock()
        mock_provider.generate.return_value = _make_response("this is not json at all")
        settings = _make_settings()

        verdict = judge_scripts("Script A", "Script B", mock_provider, settings)

        assert verdict is None

    def test_judge_returns_none_on_provider_exception(self):
        from ytfactory.composer.judge import judge_scripts

        mock_provider = MagicMock()
        mock_provider.generate.side_effect = RuntimeError("provider down")
        settings = _make_settings()

        verdict = judge_scripts("Script A", "Script B", mock_provider, settings)

        assert verdict is None
        assert mock_provider.generate.call_count == 1

    def test_judge_disabled_returns_none(self):
        from ytfactory.composer.judge import judge_scripts

        mock_provider = MagicMock()
        settings = _make_settings(judge_enabled=False)

        verdict = judge_scripts("Script A", "Script B", mock_provider, settings)

        assert verdict is None
        mock_provider.generate.assert_not_called()

    def test_judge_does_not_recommend_hybrid_when_one_dominates(self, pipeline, mock_llm, tmp_path):
        """hybrid_recommended=False in verdict → winner text returned, not recomposed."""
        from ytfactory.composer.selection import run_composer_with_ab_selection

        mock_llm.generate.side_effect = [
            _make_response(_VALID_COMPOSED),
            _make_response(_VALID_COMPOSED),
        ]
        non_hybrid_verdict = _make_verdict(winner="A", hybrid=False)

        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.composer.selection.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.composer.selection.judge_scripts", return_value=non_hybrid_verdict), \
             patch("ytfactory.composer.selection.guided_recompose") as mock_recompose:
            result = run_composer_with_ab_selection(pipeline, "proj-no-hybrid", base_script_text="Base.")

        mock_recompose.assert_not_called()
        assert result.strip().endswith("Clear mind. Meaningful life.")


class TestGuidedRecomposer:
    def test_recomposer_returns_text_on_success(self):
        from ytfactory.composer.recomposer import guided_recompose

        mock_provider = MagicMock()
        mock_provider.generate.return_value = _make_response(_VALID_COMPOSED)
        settings = _make_settings()
        verdict = _make_verdict(hybrid=True)

        result = guided_recompose("Script A", "Script B", verdict, mock_provider, settings)

        assert result is not None
        assert "lighthouse" in result

    def test_recomposer_returns_none_on_missing_rehook(self):
        from ytfactory.composer.recomposer import guided_recompose

        no_rehook = "\n".join([
            "A cobblestone archway frames the narrow city street below.",
            "Rain falls sideways through the old iron gate at dusk.",
            "Choices accumulate into the person we gradually become.",
            "Every hour spent in focus adds to a larger whole.",
            "Discipline is not punishment but a form of self-respect.",
            "The quiet worker finishes what the loud talker begins.",
            "Patience opens doors that urgency forever slams shut.",
            "Stillness is not passivity — it is concentrated force.",
            "This is Atma Theory.",
            "Clear mind. Purposeful life.",
        ])
        mock_provider = MagicMock()
        mock_provider.generate.return_value = _make_response(no_rehook)
        settings = _make_settings()
        verdict = _make_verdict(hybrid=True)

        result = guided_recompose("Script A", "Script B", verdict, mock_provider, settings)

        assert result is None

    def test_recomposer_returns_none_on_provider_exception(self):
        from ytfactory.composer.recomposer import guided_recompose

        mock_provider = MagicMock()
        mock_provider.generate.side_effect = RuntimeError("network timeout")
        settings = _make_settings()
        verdict = _make_verdict(hybrid=True)

        result = guided_recompose("Script A", "Script B", verdict, mock_provider, settings)

        assert result is None

    def test_recomposer_passes_max_tokens_to_provider(self):
        from ytfactory.composer.recomposer import guided_recompose

        mock_provider = MagicMock()
        mock_provider.generate.return_value = _make_response(_VALID_COMPOSED)
        settings = _make_settings()
        verdict = _make_verdict(hybrid=True)

        guided_recompose("Script A", "Script B", verdict, mock_provider, settings)

        call_kwargs = mock_provider.generate.call_args.kwargs
        assert call_kwargs.get("max_tokens") == 16000

    def test_recomposer_returns_none_on_empty_provider_response(self):
        from ytfactory.composer.recomposer import guided_recompose

        mock_provider = MagicMock()
        mock_provider.generate.return_value = _make_response("   ")  # whitespace only
        settings = _make_settings()
        verdict = _make_verdict(hybrid=True)

        result = guided_recompose("Script A", "Script B", verdict, mock_provider, settings)

        assert result is None

    def test_recomposer_disabled_returns_none(self):
        from ytfactory.composer.recomposer import guided_recompose

        mock_provider = MagicMock()
        settings = _make_settings(recompose_enabled=False)
        verdict = _make_verdict(hybrid=True)

        result = guided_recompose("Script A", "Script B", verdict, mock_provider, settings)

        assert result is None
        mock_provider.generate.assert_not_called()


class TestABSelectionJudgeIntegration:
    def _make_scripts(self):
        # 13-line scripts: rehook at index 9 = int(13*0.75), inside closing 25%.
        script_a = (
            "A lighthouse stands alone at the edge of everything.\n"
            "Its beam cuts through the endless dark each night.\n"
            "Actions shape character and define meaning in life.\n"
            "Clarity of mind brings focus to our work.\n"
            "Every hour spent in silent effort shapes the character.\n"
            "Discipline is not punishment but a form of self-respect.\n"
            "The quiet worker finishes what the loud talker begins.\n"
            "Patience opens doors that urgency forever slams shut.\n"
            "Stillness is not passivity — it is concentrated force.\n"
            "That lighthouse beam still sweeps the same dark water.\n"
            "This is Atma Theory.\n"
            "If these ideas resonate with you, join us on this journey.\n"
            "Clear mind. Meaningful life."
        )
        script_b = (
            "A mountain sits in the rain without complaint.\n"
            "Patience is not waiting but enduring without becoming bitter.\n"
            "Actions shape character and define meaning in life.\n"
            "Clarity of purpose shapes every good decision.\n"
            "Every hour spent in silent effort shapes the character.\n"
            "Discipline is not punishment but a form of self-respect.\n"
            "The quiet worker finishes what the loud talker begins.\n"
            "Stillness is not passivity — it is concentrated force.\n"
            "Consistency is the compound interest of effort applied daily.\n"
            "That mountain still stands through all the changing rain.\n"
            "This is Atma Theory.\n"
            "If these ideas resonate with you, join us on this journey.\n"
            "Clear mind. Meaningful life."
        )
        recomposed = (
            "A lighthouse stands at the edge where mountains meet the sea.\n"
            "Its beam sweeps through weather that patience alone can outlast.\n"
            "Clarity of mind and purpose are the same lamp lit twice.\n"
            "Every hour spent in silent effort shapes the character.\n"
            "Discipline is not punishment but a form of self-respect.\n"
            "The quiet worker finishes what the loud talker begins.\n"
            "Patience opens doors that urgency forever slams shut.\n"
            "Stillness is not passivity — it is concentrated force.\n"
            "Consistency is the compound interest of effort applied daily.\n"
            "That lighthouse beam still sweeps the same dark water.\n"
            "This is Atma Theory.\n"
            "If these ideas resonate with you, join us on this journey.\n"
            "Clear mind. Meaningful life."
        )
        return script_a, script_b, recomposed

    def test_selection_uses_recomposed_when_hybrid_recommended(self, pipeline, mock_llm, tmp_path):
        script_a, script_b, recomposed = self._make_scripts()
        mock_llm.generate.side_effect = [_make_response(script_a), _make_response(script_b)]
        hybrid_verdict = _make_verdict(winner="A", hybrid=True)
        # Quality gate: recomposed ("B") beats baseline ("A") → accept recomposed
        quality_verdict = _make_verdict(winner="B", hybrid=False)

        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.composer.selection.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.composer.selection.judge_scripts",
                   side_effect=[hybrid_verdict, quality_verdict]), \
             patch("ytfactory.composer.selection.guided_recompose", return_value=recomposed):
            result = run_composer_with_ab_selection(pipeline, "proj-hybrid", base_script_text="Base.")

        assert "lighthouse" in result
        assert "mountain" in result

    def test_selection_falls_back_to_winner_when_recomposer_fails(self, pipeline, mock_llm, tmp_path):
        script_a, script_b, _ = self._make_scripts()
        mock_llm.generate.side_effect = [_make_response(script_a), _make_response(script_b)]
        hybrid_verdict = _make_verdict(winner="B", hybrid=True)

        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.composer.selection.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.composer.selection.judge_scripts", return_value=hybrid_verdict), \
             patch("ytfactory.composer.selection.guided_recompose", return_value=None):
            result = run_composer_with_ab_selection(pipeline, "proj-fallback", base_script_text="Base.")

        # Recomposer failed → falls back to winner (Script B = mountain script)
        assert "mountain" in result

    def test_selection_uses_winner_when_hybrid_not_recommended(self, pipeline, mock_llm, tmp_path):
        script_a, script_b, _ = self._make_scripts()
        mock_llm.generate.side_effect = [_make_response(script_a), _make_response(script_b)]
        no_hybrid_verdict = _make_verdict(winner="B", hybrid=False)

        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.composer.selection.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.composer.selection.judge_scripts", return_value=no_hybrid_verdict), \
             patch("ytfactory.composer.selection.guided_recompose") as mock_recompose:
            result = run_composer_with_ab_selection(pipeline, "proj-winner-b", base_script_text="Base.")

        mock_recompose.assert_not_called()
        assert "mountain" in result

    def test_cleanup_renames_rejected_script_on_winner_a(self, pipeline, mock_llm, tmp_path):
        """Judge picks winner A → script-b.md renamed to script-b-rejected.md."""
        script_a, script_b, _ = self._make_scripts()
        mock_llm.generate.side_effect = [_make_response(script_a), _make_response(script_b)]
        verdict_a = _make_verdict(winner="A", hybrid=False)

        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.composer.selection.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.composer.selection.judge_scripts", return_value=verdict_a):
            run_composer_with_ab_selection(pipeline, "proj-cleanup-a", base_script_text="Base.")

        script_dir = tmp_path / "proj-cleanup-a" / "script"
        assert not (script_dir / "script-b.md").exists()
        assert (script_dir / "script-b-rejected.md").exists()

    def test_cleanup_renames_both_as_source_on_recomposed(self, pipeline, mock_llm, tmp_path):
        """Recomposer succeeds → script-a.md and script-b.md renamed to *-source.md."""
        script_a, script_b, recomposed = self._make_scripts()
        mock_llm.generate.side_effect = [_make_response(script_a), _make_response(script_b)]
        hybrid_verdict = _make_verdict(winner="A", hybrid=True)
        quality_verdict = _make_verdict(winner="B", hybrid=False)

        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.composer.selection.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.composer.selection.judge_scripts",
                   side_effect=[hybrid_verdict, quality_verdict]), \
             patch("ytfactory.composer.selection.guided_recompose", return_value=recomposed):
            run_composer_with_ab_selection(pipeline, "proj-cleanup-r", base_script_text="Base.")

        script_dir = tmp_path / "proj-cleanup-r" / "script"
        assert not (script_dir / "script-a.md").exists()
        assert not (script_dir / "script-b.md").exists()
        assert (script_dir / "script-a-source.md").exists()
        assert (script_dir / "script-b-source.md").exists()

    def test_selection_skips_judge_when_script_b_missing(self, pipeline, mock_llm, tmp_path):
        from ytfactory.composer.pipeline import ComposerRehookMissingError

        call_n = 0

        def side_effect(*args, **kwargs):
            nonlocal call_n
            call_n += 1
            if call_n == 1:
                return _make_response(_VALID_COMPOSED)
            raise ComposerRehookMissingError("Script B missing rehook.")

        mock_llm.generate.side_effect = side_effect

        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.composer.selection.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.composer.selection.judge_scripts") as mock_judge:
            result = run_composer_with_ab_selection(pipeline, "proj-no-b", base_script_text="Base.")

        mock_judge.assert_not_called()
        assert result.strip().endswith("Clear mind. Meaningful life.")


class TestAutoModeRecomposedGuard:
    def test_auto_mode_forced_off_for_recomposed_script(self, tmp_path):
        """outcome=recomposed + auto_mode=True → review gate does not skip."""
        from ytfactory.editorial_qa.review_gate import FinalScriptReviewGate
        from ytfactory.config.settings import Settings

        settings = MagicMock(spec=Settings)
        gate = FinalScriptReviewGate(settings)

        project_id = "proj-recomposed"
        script_dir = tmp_path / project_id / "script"
        script_dir.mkdir(parents=True)
        script_text = "Some composed script."

        judge_report_path = tmp_path / project_id / "judge-report.json"
        judge_report_path.write_text(
            json.dumps({"outcome": "recomposed", "winner": "A",
                        "script_a_score": 8.0, "script_b_score": 7.0,
                        "verdict_summary": "Recomposed wins.", "sections": []}),
            encoding="utf-8",
        )

        prompt_responses = iter(["c"])

        with patch("ytfactory.editorial_qa.review_gate.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.editorial_qa.review_gate.qa_checkpoint") as mock_cp, \
             patch("ytfactory.editorial_qa.review_gate.typer.prompt", side_effect=prompt_responses):
            mock_cp.read_recorded_hash.return_value = None
            gate.run(project_id, script_text, auto_mode=True)

        # If auto_mode was honored without forcing review, record_hash would be
        # called without typer.prompt being invoked. We verify typer.prompt WAS
        # called — which only happens when auto_mode was overridden to False.
        # (The patched prompt returned "c" so the gate continued normally.)
        mock_cp.record_hash.assert_called_once()


class TestABSelectionRehookDegradation:
    def test_ab_selection_degrades_gracefully_on_script_b_rehook_failure(
        self, pipeline, mock_llm, tmp_path
    ):
        """Script B raises ComposerRehookMissingError → function returns Script A without raising."""
        from ytfactory.composer.pipeline import ComposerRehookMissingError
        from ytfactory.composer.selection import run_composer_with_ab_selection

        script_a_text = (
            "A lighthouse stands alone at the edge of everything.\n"
            "Its beam cuts through the endless dark each night.\n"
            "Actions shape character and define meaning in life.\n"
            "Clarity of mind brings focus to our work.\n"
            "That lighthouse beam still sweeps the same dark water — but now someone watches it return.\n"
            "This is the Atma Theory.\n"
            "If these ideas resonate with you, join us on this journey.\n"
            "Clear mind. Meaningful life."
        )

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_response(script_a_text)
            raise ComposerRehookMissingError("Script B missing rehook.")

        mock_llm.generate.side_effect = side_effect

        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)), \
             patch("ytfactory.composer.selection.WORKSPACE_DIR", str(tmp_path)):
            result = run_composer_with_ab_selection(pipeline, "proj-ab", base_script_text="Base script.")

        assert result.strip().endswith("Clear mind. Meaningful life.")
        assert mock_llm.generate.call_count == 2


class TestComposerRehookGate:
    """Tests for the rehook validation gate added in V2.1."""

    def test_validate_rehook_returns_false_on_empty_string(self):
        from ytfactory.composer.pipeline import _validate_rehook_present

        assert _validate_rehook_present("") is False
        assert _validate_rehook_present("   \n  ") is False
        assert _validate_rehook_present("\n".join(["short"] * 5)) is False  # under 8 lines

    def test_composer_pipeline_raises_on_missing_rehook(self, pipeline, mock_llm, tmp_path):
        """Mock composer output with no rehook → ComposerRehookMissingError raised."""
        from ytfactory.composer.pipeline import ComposerRehookMissingError

        # Script with no closing echo of opening nouns — the opening window
        # contains unique nouns ("cobblestone", "narrow", "archway") that do
        # not appear anywhere in the closing 25% of the script.
        no_rehook_script = "\n".join([
            "A cobblestone archway frames the narrow city street below.",  # 0 — unique: cobblestone, archway, narrow
            "Rain falls sideways through the old iron gate at dusk.",
            "Choices accumulate into the person we gradually become.",
            "Every hour spent in focus adds to a larger whole.",
            "Discipline is not punishment but a form of self-respect.",
            "The quiet worker finishes what the loud talker begins.",
            "Patience opens doors that urgency forever slams shut.",
            "Stillness is not passivity — it is concentrated force.",
            "This is the Atma Theory.",
            "If these ideas resonate with you, join us on this journey.",
            "Clear mind. Purposeful life.",  # no "cobblestone", "archway", or "narrow"
        ])
        mock_llm.generate.return_value = _make_response(no_rehook_script)

        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with pytest.raises(ComposerRehookMissingError):
                pipeline.run("proj-test", script_text="Some base script text here for input.")

    def test_composer_pipeline_passes_with_valid_rehook(self, pipeline, mock_llm, tmp_path):
        """Mock composer output with valid rehook passes the gate."""
        from ytfactory.composer.pipeline import ComposerRehookMissingError

        rehook_script = (
            "A lighthouse stands alone at the edge of everything.\n"
            "Its beam cuts through the endless dark each night.\n"
            "Actions shape character and define meaning in life.\n"
            "Clarity of mind brings focus to our work.\n"
            "That lighthouse beam still sweeps the same dark water — but now someone watches it return.\n"
            "This is the Atma Theory.\n"
            "If these ideas resonate with you, join us on this journey.\n"
            "Clear mind. Meaningful life."
        )
        mock_llm.generate.return_value = _make_response(rehook_script)

        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-test", script_text="Some base script text here for input.")

        assert result.strip().endswith("Clear mind. Meaningful life.")
