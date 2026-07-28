"""Tests for the Final Script Review Gate: checkpoint hash-guard + the
FinalScriptReviewGate that runs between Editorial QA and scene planning.

No live LLM calls — EditorialQAPipeline (invoked on a hash mismatch) is
mocked at its get_llm_provider seam.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer

from ytfactory.editorial_qa import checkpoint as qa_checkpoint
from ytfactory.editorial_qa.review_gate import FinalScriptReviewGate


# ── checkpoint.py ─────────────────────────────────────────────────────────────


class TestCheckpoint:
    def test_no_recorded_hash_initially(self, tmp_path):
        with patch("ytfactory.editorial_qa.checkpoint.WORKSPACE_DIR", str(tmp_path)):
            assert qa_checkpoint.read_recorded_hash("proj-1") is None

    def test_record_then_read_roundtrip(self, tmp_path):
        with patch("ytfactory.editorial_qa.checkpoint.WORKSPACE_DIR", str(tmp_path)):
            qa_checkpoint.record_hash("proj-1", "Some script text.")
            recorded = qa_checkpoint.read_recorded_hash("proj-1")
        assert recorded == qa_checkpoint.script_hash("Some script text.")

    def test_different_text_gives_different_hash(self):
        assert qa_checkpoint.script_hash("A") != qa_checkpoint.script_hash("B")

    def test_same_text_gives_same_hash(self):
        assert qa_checkpoint.script_hash("Same text.") == qa_checkpoint.script_hash("Same text.")

    def test_clear_removes_recorded_hash(self, tmp_path):
        with patch("ytfactory.editorial_qa.checkpoint.WORKSPACE_DIR", str(tmp_path)):
            qa_checkpoint.record_hash("proj-1", "text")
            qa_checkpoint.clear("proj-1")
            assert qa_checkpoint.read_recorded_hash("proj-1") is None


# ── FinalScriptReviewGate ─────────────────────────────────────────────────────


@pytest.fixture
def settings():
    return MagicMock()


class TestFinalScriptReviewGate:
    def test_first_time_review_prompts_and_records_hash(self, settings, tmp_path):
        gate = FinalScriptReviewGate(settings)
        with patch("ytfactory.editorial_qa.checkpoint.WORKSPACE_DIR", str(tmp_path)):
            with patch("ytfactory.editorial_qa.review_gate.typer.prompt", return_value="c") as mock_prompt:
                with patch("ytfactory.editorial_qa.pipeline.get_llm_provider") as mock_get_llm:
                    result = gate.run("proj-1", "The final script.", auto_mode=False)
            recorded = qa_checkpoint.read_recorded_hash("proj-1")
        assert result == "The final script."
        mock_prompt.assert_called_once()
        mock_get_llm.assert_not_called()  # no recorded hash yet -> no QA re-run
        assert recorded == qa_checkpoint.script_hash("The final script.")

    def test_unchanged_hash_skips_straight_through_no_prompt(self, settings, tmp_path):
        gate = FinalScriptReviewGate(settings)
        script = "The final script."
        with patch("ytfactory.editorial_qa.checkpoint.WORKSPACE_DIR", str(tmp_path)):
            qa_checkpoint.record_hash("proj-2", script)
            with patch("ytfactory.editorial_qa.review_gate.typer.prompt") as mock_prompt:
                with patch("ytfactory.editorial_qa.pipeline.get_llm_provider") as mock_get_llm:
                    result = gate.run("proj-2", script, auto_mode=False)
        assert result == script
        mock_prompt.assert_not_called()  # skipped straight through
        mock_get_llm.assert_not_called()  # QA not re-run — unchanged

    def test_changed_hash_triggers_qa_rerun_then_prompts(self, settings, tmp_path):
        gate = FinalScriptReviewGate(settings)
        with patch("ytfactory.editorial_qa.checkpoint.WORKSPACE_DIR", str(tmp_path)):
            qa_checkpoint.record_hash("proj-3", "Original script.")
            with patch("ytfactory.editorial_qa.review_gate.typer.prompt", return_value="c") as mock_prompt:
                with patch("ytfactory.editorial_qa.review_gate.EditorialQAPipeline") as mock_qa_cls:
                    result = gate.run("proj-3", "Hand-edited script.", auto_mode=False)
        mock_qa_cls.return_value.run.assert_called_once_with(
            "proj-3", script_text="Hand-edited script."
        )
        mock_prompt.assert_called_once()  # still shown after the re-run
        assert result == "Hand-edited script."

    def test_stop_action_aborts(self, settings, tmp_path):
        gate = FinalScriptReviewGate(settings)
        with patch("ytfactory.editorial_qa.checkpoint.WORKSPACE_DIR", str(tmp_path)):
            with patch("ytfactory.editorial_qa.review_gate.typer.prompt", return_value="s"):
                with pytest.raises(typer.Abort):
                    gate.run("proj-4", "Some script.", auto_mode=False)

    def test_regenerate_clears_checkpoint_and_aborts(self, settings, tmp_path):
        gate = FinalScriptReviewGate(settings)
        with patch("ytfactory.editorial_qa.checkpoint.WORKSPACE_DIR", str(tmp_path)):
            # First-time review (no prior recorded hash) reaching the prompt directly —
            # a prior hash matching this same text would hit the skip-straight-through
            # path before ever showing the prompt.
            with patch("ytfactory.editorial_qa.review_gate.typer.prompt", return_value="r"):
                with pytest.raises(typer.Abort):
                    gate.run("proj-5", "Some script.", auto_mode=False)
            assert qa_checkpoint.read_recorded_hash("proj-5") is None

    def test_auto_mode_first_review_records_hash_without_prompting(self, settings, tmp_path):
        gate = FinalScriptReviewGate(settings)
        with patch("ytfactory.editorial_qa.checkpoint.WORKSPACE_DIR", str(tmp_path)):
            with patch("ytfactory.editorial_qa.review_gate.typer.prompt") as mock_prompt:
                result = gate.run("proj-6", "Auto script.", auto_mode=True)
            assert qa_checkpoint.read_recorded_hash("proj-6") == qa_checkpoint.script_hash(
                "Auto script."
            )
        mock_prompt.assert_not_called()
        assert result == "Auto script."

    def test_auto_mode_after_hand_edit_still_reruns_qa(self, settings, tmp_path):
        """auto_mode skips the interactive prompt, but not the hash-guard's
        re-QA on a genuine hand-edit — a hand-edit always gets scrutiny."""
        gate = FinalScriptReviewGate(settings)
        with patch("ytfactory.editorial_qa.checkpoint.WORKSPACE_DIR", str(tmp_path)):
            qa_checkpoint.record_hash("proj-7", "Original.")
            with patch("ytfactory.editorial_qa.review_gate.EditorialQAPipeline") as mock_qa_cls:
                with patch("ytfactory.editorial_qa.review_gate.typer.prompt") as mock_prompt:
                    result = gate.run("proj-7", "Edited.", auto_mode=True)
        mock_qa_cls.return_value.run.assert_called_once_with("proj-7", script_text="Edited.")
        mock_prompt.assert_not_called()
        assert result == "Edited."
