"""Tests for ComposerPipeline (see ATMA_THEORY_COMPOSER.md).

No live LLM calls. No mode selection, coverage floor, or reorder ban to test
here by design — those belonged to the retired transform enhancer. Scripture
protection is carried over and tested.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.composer.pipeline import ComposerPipeline, TARGET_MAX_MINUTES, TARGET_MIN_MINUTES

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
        composed = "A bird once built a nest. " * 200 + (
            'If these ideas resonate with you, join us on this journey.\n\n'
            "Clear mind. Meaningful life."
        )
        mock_llm.generate.return_value = _make_response(composed)

        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-1", script_text="Base script content.")

        assert result.strip() == composed.strip()
        script_dir = tmp_path / "proj-1" / "script"
        assert (script_dir / "script.md").read_text(encoding="utf-8").strip() == composed.strip()
        assert (script_dir / "script_pre_composer.md").read_text(
            encoding="utf-8"
        ) == "Base script content."

    def test_single_llm_call_only(self, pipeline, mock_llm, tmp_path):
        mock_llm.generate.return_value = _make_response("Composed narration.")
        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run("proj-2", script_text="Base script.")
        assert mock_llm.generate.call_count == 1

    def test_reads_script_from_file_when_not_provided(self, pipeline, mock_llm, tmp_path):
        project_id = "proj-3"
        script_dir = tmp_path / project_id / "script"
        script_dir.mkdir(parents=True)
        (script_dir / "script.md").write_text("File-based base script.", encoding="utf-8")
        mock_llm.generate.return_value = _make_response("Composed from file.")

        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run(project_id)

        assert result == "Composed from file."

    def test_raises_when_no_script_file(self, pipeline, tmp_path):
        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with pytest.raises(FileNotFoundError):
                pipeline.run("proj-missing")

    def test_scripture_span_survives_compose(self, pipeline, mock_llm, tmp_path):
        scripture = "<scripture>ॐ नमः शिवाय</scripture>"
        script = f"The teacher said {scripture} and continued."
        mock_llm.generate.return_value = _make_response(
            "The teacher opened with {{SCRIPTURE_1}} and the story began."
        )
        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-scripture", script_text=script)
        assert scripture in result

    def test_system_prompt_uses_composer_framework(self, pipeline, mock_llm, tmp_path):
        mock_llm.generate.return_value = _make_response("Composed.")
        with patch("ytfactory.composer.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run("proj-4", script_text="Base script.")
        kwargs = mock_llm.generate.call_args.kwargs
        assert "COMPOSE WHOLE" in kwargs["system_prompt"]
        assert "FAITHFULNESS" in kwargs["system_prompt"]

    def test_user_prompt_carries_base_script(self, pipeline, mock_llm, tmp_path):
        mock_llm.generate.return_value = _make_response("Composed.")
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
