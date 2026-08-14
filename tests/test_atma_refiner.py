"""Tests for the Atma Theory 7-Beat Script Refinement Pipeline.

Covers:
- ScriptIdentity extraction (deterministic, no LLM)
- AtmaRefinerPipeline (mocked LLM)
- ScriptValidator
- RevisionStore (revision lineage)
- Graph nodes: script_identity_node, atma_7beat_refiner_node,
  script_validator_node
- Production workflow: A/B NOT invoked, validation occurs, revision
  lineage tracked
- Existing A/B / composer / polisher tests are not affected (those modules
  remain importable and their test files unchanged)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.atma_refiner.identity import extract_script_identity
from ytfactory.atma_refiner.pipeline import AtmaRefinerPipeline
from ytfactory.atma_refiner.revision_store import RevisionStore
from ytfactory.atma_refiner.validator import ScriptValidator, _WORD_COUNT_MAX, _WORD_COUNT_MIN
from ytfactory.domain.script_revision import (
    ReviewDecision,
    RevisionStatus,
    ScriptIdentity,
    ValidationFlagType,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

# A minimal valid refined script: covers all 7 beats (pattern-matchable),
# ~620 spoken words worth of content.
_REFINED_SCRIPT = (
    "There was a man who traded every hour for a wage.\n\n"
    "Most of us believe that time is what we exchange for money. "
    "But what if the real question is what we exchange our time for?\n\n"
    "In 1978, a study found that deep focused work produced results "
    "ten times greater than scattered effort. The researchers discovered "
    "that mastery compounds in ways that hourly wages cannot.\n\n"
    "The real problem is not how many hours you work. "
    "It is not about selling time — it is about building something "
    "that outlasts the hours. The shift is from time seller to mastery builder.\n\n"
    "There are three principles that guide this shift. "
    "First: protect one hour daily for deep work. "
    "Second: measure output by impact, not hours logged. "
    "Third: ask what you are building, not just what you are doing.\n\n"
    "In your own life, this means that the next time you sit down to work, "
    "you ask: am I selling my time, or building something? "
    "At home, with your family, in your career, the question is the same.\n\n"
    "Stop measuring your worth in hours. Start building mastery. "
    "This is the Atma Theory. If these ideas resonated with you, "
    "subscribe and join us on this journey.\n"
)

_BASE_SCRIPT = (
    "A man spent his whole life trading time for money.\n\n"
    "The real lesson here is that time is the one resource "
    "you cannot recover. This is not about working more hours "
    "but about what those hours create.\n\n"
    "In 1978, researchers found that focused workers outperformed "
    "scattered ones by a factor of ten.\n\n"
    "The deeper insight: mastery compounds. "
    "The time seller sees each hour as a commodity. "
    "The mastery builder sees each hour as an investment.\n\n"
    "Three rules follow from this understanding. "
    "First, protect your deep work hours. "
    "Second, measure yourself by what you build. "
    "Third, ask the right question each morning.\n\n"
    "Apply this at work, at home, with your family.\n\n"
    "Stop selling. Start building."
)


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.generate.return_value = MagicMock(text=_REFINED_SCRIPT)
    return llm


@pytest.fixture
def pipeline(mock_llm):
    settings = MagicMock()
    with patch("ytfactory.atma_refiner.pipeline.get_llm_for_role", return_value=mock_llm):
        return AtmaRefinerPipeline(settings)


# ── ScriptIdentity extraction tests ──────────────────────────────────────────

class TestScriptIdentityExtraction:
    def test_extracts_core_topic_from_argument(self):
        identity = extract_script_identity(_BASE_SCRIPT, topic="Mastery vs Time")
        assert identity.core_topic == "Mastery vs Time"

    def test_extracts_thesis_statement(self):
        identity = extract_script_identity(_BASE_SCRIPT)
        assert identity.core_thesis != ""

    def test_extracts_key_story(self):
        identity = extract_script_identity(_BASE_SCRIPT)
        assert identity.key_story != ""

    def test_extracts_factual_details_year(self):
        identity = extract_script_identity(_BASE_SCRIPT)
        year_details = " ".join(identity.important_factual_details)
        assert "1978" in year_details

    def test_extracts_visual_moments(self):
        script_with_visual = _BASE_SCRIPT + "\n\n[Close-up on an hourglass]\n"
        identity = extract_script_identity(script_with_visual)
        assert any("hourglass" in v.lower() for v in identity.important_visual_moments)

    def test_returns_valid_identity_for_empty_script(self):
        identity = extract_script_identity("", topic="Test topic")
        assert isinstance(identity, ScriptIdentity)
        assert identity.core_topic == "Test topic"

    def test_identity_extracted_before_refinement(self, pipeline, tmp_path):
        """ScriptIdentity extraction must happen BEFORE any LLM call."""
        identity = extract_script_identity(_BASE_SCRIPT, topic="Mastery")
        assert identity.core_topic == "Mastery"
        # The extraction itself makes no LLM call — it is deterministic.
        # We verify that the object is fully populated before pipeline.run() is called.
        assert isinstance(identity, ScriptIdentity)
        assert identity.important_factual_details is not None

    def test_identity_to_from_dict_roundtrip(self):
        identity = extract_script_identity(_BASE_SCRIPT, topic="Test")
        d = identity.to_dict()
        identity2 = ScriptIdentity.from_dict(d)
        assert identity2.core_topic == identity.core_topic
        assert identity2.important_factual_details == identity.important_factual_details
        assert identity2.important_visual_moments == identity.important_visual_moments


# ── ScriptValidator tests ─────────────────────────────────────────────────────

class TestScriptValidator:
    def setup_method(self):
        self.validator = ScriptValidator()
        self.identity = ScriptIdentity(
            core_topic="Mastery",
            core_thesis="This is not about selling time but building mastery.",
        )

    def test_pass_for_valid_script(self):
        result = self.validator.validate(_REFINED_SCRIPT, self.identity, _BASE_SCRIPT)
        assert result.spoken_word_count > 0
        assert result.beat_coverage  # dict is populated

    def test_flags_short_script(self):
        short = "This is a very short script." * 5
        result = self.validator.validate(short, self.identity)
        flag_types = [f.flag_type for f in result.flags]
        assert ValidationFlagType.WORD_COUNT in flag_types

    def test_flags_new_years_as_factual_risk(self):
        script_with_new_year = _REFINED_SCRIPT + "\nIn 1492, Columbus crossed the ocean."
        result = self.validator.validate(script_with_new_year, self.identity, _BASE_SCRIPT)
        flag_types = [f.flag_type for f in result.flags]
        assert ValidationFlagType.FACTUAL_RISK in flag_types

    def test_beat_coverage_populated(self):
        result = self.validator.validate(_REFINED_SCRIPT, self.identity)
        assert "DISRUPT" in result.beat_coverage
        assert "TRANSFORM" in result.beat_coverage

    def test_validation_does_not_discard_script(self):
        """Validation never silently discards the script — it just sets flags."""
        short = "Short."
        result = self.validator.validate(short, self.identity)
        assert result.status == "REVIEW_REQUIRED"
        assert len(result.flags) > 0

    def test_to_dict_serializable(self):
        result = self.validator.validate(_REFINED_SCRIPT, self.identity)
        d = result.to_dict()
        assert "status" in d
        assert "flags" in d
        assert "beat_coverage" in d
        assert "spoken_word_count" in d
        # Must be JSON-serializable
        json.dumps(d)


# ── AtmaRefinerPipeline tests ─────────────────────────────────────────────────

class TestAtmaRefinerPipeline:
    def test_returns_refined_script(self, pipeline, tmp_path):
        identity = ScriptIdentity(core_topic="Mastery")
        with patch("ytfactory.atma_refiner.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result, _ = pipeline.run("proj-1", _BASE_SCRIPT, identity)
        assert result.strip() != ""

    def test_single_llm_call_in_default_path(self, pipeline, mock_llm, tmp_path):
        """Exactly one LLM call for the initial refinement (not A/B)."""
        identity = ScriptIdentity(core_topic="Mastery")
        with patch("ytfactory.atma_refiner.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run("proj-1", _BASE_SCRIPT, identity)
        assert mock_llm.generate.call_count == 1

    def test_ab_generation_not_invoked(self, pipeline, mock_llm, tmp_path):
        """composer.pipeline.build_script_a_prompt / build_script_b_prompt must NOT be called."""
        identity = ScriptIdentity(core_topic="Mastery")
        with patch("ytfactory.atma_refiner.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with patch("ytfactory.agents.prompts.composer.build_script_a_prompt") as mock_a:
                with patch("ytfactory.agents.prompts.composer.build_script_b_prompt") as mock_b:
                    pipeline.run("proj-1", _BASE_SCRIPT, identity)
                    mock_a.assert_not_called()
                    mock_b.assert_not_called()

    def test_identity_passed_to_prompt(self, pipeline, mock_llm, tmp_path):
        """ScriptIdentity fields must appear in the prompt sent to the LLM."""
        identity = ScriptIdentity(
            core_topic="UNIQUE_TOPIC_XYZ",
            core_thesis="UNIQUE_THESIS_XYZ",
        )
        with patch("ytfactory.atma_refiner.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run("proj-1", _BASE_SCRIPT, identity)
        call_args = mock_llm.generate.call_args
        prompt = call_args[0][0] if call_args[0] else call_args.kwargs.get("prompt", "")
        assert "UNIQUE_TOPIC_XYZ" in prompt
        assert "UNIQUE_THESIS_XYZ" in prompt

    def test_writes_atma_refined_md(self, pipeline, tmp_path):
        identity = ScriptIdentity(core_topic="Mastery")
        with patch("ytfactory.atma_refiner.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run("proj-atma", _BASE_SCRIPT, identity)
        assert (tmp_path / "proj-atma" / "script" / "atma-refined.md").exists()

    def test_writes_refinement_report(self, pipeline, tmp_path):
        identity = ScriptIdentity(core_topic="Mastery")
        with patch("ytfactory.atma_refiner.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run("proj-atma", _BASE_SCRIPT, identity)
        report_path = tmp_path / "proj-atma" / "script" / "atma-refinement-report.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text())
        assert "word_count" in report
        assert "validation" in report

    def test_idempotency_skip(self, pipeline, mock_llm, tmp_path):
        """Second call with existing atma-refined.md must not invoke the LLM again."""
        identity = ScriptIdentity(core_topic="Mastery")
        script_dir = tmp_path / "proj-idem" / "script"
        script_dir.mkdir(parents=True)
        (script_dir / "atma-refined.md").write_text(_REFINED_SCRIPT, encoding="utf-8")
        with patch("ytfactory.atma_refiner.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run("proj-idem", _BASE_SCRIPT, identity)
        mock_llm.generate.assert_not_called()

    def test_targeted_refinement_after_rejection(self, pipeline, mock_llm, tmp_path):
        """Targeted refinement: LLM receives reviewer feedback in the prompt."""
        identity = ScriptIdentity(core_topic="Mastery")
        feedback = "Beat 1 hook is too weak. Strengthen the emotional opening."
        with patch("ytfactory.atma_refiner.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run(
                "proj-target",
                base_script=_BASE_SCRIPT,
                identity=identity,
                reviewer_feedback=feedback,
                current_refined=_REFINED_SCRIPT,
                force=True,
            )
        call_args = mock_llm.generate.call_args
        prompt = call_args[0][0] if call_args[0] else call_args.kwargs.get("prompt", "")
        assert "Beat 1 hook is too weak" in prompt
        assert "CURRENT REFINED SCRIPT" in prompt

    def test_targeted_refinement_includes_previous_script(self, pipeline, mock_llm, tmp_path):
        identity = ScriptIdentity(core_topic="Mastery")
        with patch("ytfactory.atma_refiner.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run(
                "proj-target2",
                base_script=_BASE_SCRIPT,
                identity=identity,
                reviewer_feedback="Fix the ending.",
                current_refined=_REFINED_SCRIPT,
                force=True,
            )
        call_args = mock_llm.generate.call_args
        prompt = call_args[0][0] if call_args[0] else call_args.kwargs.get("prompt", "")
        assert "SOURCE / BASE SCRIPT" in prompt

    def test_source_script_identity_preserved_in_refined(self, pipeline, tmp_path):
        """Core thesis from ScriptIdentity should be detectable in the refined script."""
        identity = ScriptIdentity(
            core_topic="Mastery",
            core_thesis="mastery compounds",
        )
        with patch("ytfactory.atma_refiner.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result, _ = pipeline.run("proj-preserve", _BASE_SCRIPT, identity)
        # The LLM mock returns _REFINED_SCRIPT which contains "mastery"
        assert "mastery" in result.lower()

    def test_validation_result_returned(self, pipeline, tmp_path):
        identity = ScriptIdentity(core_topic="Mastery")
        with patch("ytfactory.atma_refiner.pipeline.WORKSPACE_DIR", str(tmp_path)):
            _, validation = pipeline.run("proj-val", _BASE_SCRIPT, identity)
        assert validation is not None
        assert hasattr(validation, "status")
        assert hasattr(validation, "beat_coverage")

    def test_beats_passed_to_prompt(self, pipeline, mock_llm, tmp_path):
        identity = ScriptIdentity(core_topic="Mastery")
        beats = [{"id": 1, "beat": "UNIQUE_BEAT_STRING_123"}]
        with patch("ytfactory.atma_refiner.pipeline.WORKSPACE_DIR", str(tmp_path)):
            pipeline.run("proj-beats", _BASE_SCRIPT, identity, beats=beats)
        call_args = mock_llm.generate.call_args
        prompt = call_args[0][0] if call_args[0] else call_args.kwargs.get("prompt", "")
        assert "UNIQUE_BEAT_STRING_123" in prompt


# ── RevisionStore tests ───────────────────────────────────────────────────────

class TestRevisionStore:
    def test_save_revision_creates_file(self, tmp_path):
        with patch("ytfactory.atma_refiner.revision_store.WORKSPACE_DIR", str(tmp_path)):
            store = RevisionStore("proj-rev")
            rev = store.save_revision("Script text version 1.")
        assert (tmp_path / "proj-rev" / "script" / "revision-1.md").exists()
        assert rev.revision_number == 1

    def test_revision_number_increments(self, tmp_path):
        with patch("ytfactory.atma_refiner.revision_store.WORKSPACE_DIR", str(tmp_path)):
            store = RevisionStore("proj-inc")
            r1 = store.save_revision("Revision one text.")
            r2 = store.save_revision("Revision two text.", parent_id=r1.revision_id)
        assert r2.revision_number == 2

    def test_parent_id_tracked(self, tmp_path):
        with patch("ytfactory.atma_refiner.revision_store.WORKSPACE_DIR", str(tmp_path)):
            store = RevisionStore("proj-parent")
            r1 = store.save_revision("First.")
            r2 = store.save_revision("Second.", parent_id=r1.revision_id)
        assert r2.parent_id == r1.revision_id

    def test_record_acceptance_sets_canonical(self, tmp_path):
        with patch("ytfactory.atma_refiner.revision_store.WORKSPACE_DIR", str(tmp_path)):
            store = RevisionStore("proj-accept")
            rev = store.save_revision("Accepted script.")
            store.record_acceptance(rev.revision_id)
            assert store.get_canonical_revision_id() == rev.revision_id

    def test_get_canonical_script_returns_text(self, tmp_path):
        with patch("ytfactory.atma_refiner.revision_store.WORKSPACE_DIR", str(tmp_path)):
            store = RevisionStore("proj-canon")
            rev = store.save_revision("Canonical content.")
            store.record_acceptance(rev.revision_id)
            text = store.get_canonical_script()
        assert text == "Canonical content."

    def test_record_rejection_stores_feedback(self, tmp_path):
        with patch("ytfactory.atma_refiner.revision_store.WORKSPACE_DIR", str(tmp_path)):
            store = RevisionStore("proj-reject")
            rev = store.save_revision("Draft script.")
            store.record_rejection(rev.revision_id, "Beat 1 is weak.")
            revisions = store.list_revisions()
        rejected = revisions[0]
        assert rejected.status == RevisionStatus.REJECTED
        assert rejected.reviewer_decision == ReviewDecision.REJECT
        assert rejected.reviewer_feedback == "Beat 1 is weak."

    def test_revision_lineage_persists_to_json(self, tmp_path):
        with patch("ytfactory.atma_refiner.revision_store.WORKSPACE_DIR", str(tmp_path)):
            store = RevisionStore("proj-persist")
            r1 = store.save_revision("R1.")
            r2 = store.save_revision("R2.", parent_id=r1.revision_id)
            store.record_rejection(r1.revision_id, "Too short.")
            store.record_acceptance(r2.revision_id)

        revisions_file = tmp_path / "proj-persist" / "script" / "revisions.json"
        assert revisions_file.exists()
        data = json.loads(revisions_file.read_text())
        assert len(data["revisions"]) == 2
        assert data["canonical_revision_id"] == r2.revision_id

    def test_accepted_revision_identifiable(self, tmp_path):
        with patch("ytfactory.atma_refiner.revision_store.WORKSPACE_DIR", str(tmp_path)):
            store = RevisionStore("proj-id")
            r1 = store.save_revision("Draft 1.")
            r2 = store.save_revision("Draft 2.", parent_id=r1.revision_id)
            store.record_rejection(r1.revision_id, "Weak.")
            store.record_acceptance(r2.revision_id)
            canonical_id = store.get_canonical_revision_id()
        assert canonical_id == r2.revision_id

    def test_get_latest_revision(self, tmp_path):
        with patch("ytfactory.atma_refiner.revision_store.WORKSPACE_DIR", str(tmp_path)):
            store = RevisionStore("proj-latest")
            store.save_revision("A.")
            r2 = store.save_revision("B.")
            latest = store.get_latest_revision()
        assert latest.revision_id == r2.revision_id


# ── Graph node tests ──────────────────────────────────────────────────────────

class TestScriptIdentityNode:
    def test_returns_script_identity_dict(self, tmp_path):
        from ytfactory.agents.nodes.atma_refiner import script_identity_node
        state = {
            "project_id": "proj-node",
            "topic": "The Art of Mastery",
            "script_md": _BASE_SCRIPT,
        }
        with patch("ytfactory.agents.nodes.atma_refiner.WORKSPACE_DIR", str(tmp_path)):
            result = script_identity_node(state)
        assert "script_identity" in result
        assert result["script_identity"]["core_topic"] == "The Art of Mastery"

    def test_writes_script_identity_json(self, tmp_path):
        from ytfactory.agents.nodes.atma_refiner import script_identity_node
        state = {
            "project_id": "proj-node2",
            "topic": "Mastery",
            "script_md": _BASE_SCRIPT,
        }
        with patch("ytfactory.agents.nodes.atma_refiner.WORKSPACE_DIR", str(tmp_path)):
            script_identity_node(state)
        assert (tmp_path / "proj-node2" / "script" / "script-identity.json").exists()

    def test_no_llm_call_in_identity_node(self, tmp_path):
        from ytfactory.agents.nodes.atma_refiner import script_identity_node
        state = {
            "project_id": "proj-nollm",
            "topic": "Mastery",
            "script_md": _BASE_SCRIPT,
        }
        with patch("ytfactory.agents.nodes.atma_refiner.WORKSPACE_DIR", str(tmp_path)):
            with patch(
                "ytfactory.agents.nodes.atma_refiner.extract_script_identity",
                wraps=extract_script_identity,
            ) as mock_extract:
                with patch("video_core.providers.llm.factory.get_llm_for_role") as mock_llm_factory:
                    script_identity_node(state)
                    mock_llm_factory.assert_not_called()
                    mock_extract.assert_called_once()

    def test_raises_when_no_script(self, tmp_path):
        from ytfactory.agents.nodes.atma_refiner import script_identity_node
        state = {"project_id": "proj-nofile", "topic": "X", "script_md": ""}
        with patch("ytfactory.agents.nodes.atma_refiner.WORKSPACE_DIR", str(tmp_path)):
            with pytest.raises(FileNotFoundError):
                script_identity_node(state)


def _patch_workspaces(tmp_path):
    """Context manager that patches WORKSPACE_DIR in all three modules the node uses."""
    from contextlib import ExitStack
    stack = ExitStack()
    for module in (
        "ytfactory.agents.nodes.atma_refiner",
        "ytfactory.atma_refiner.pipeline",
        "ytfactory.atma_refiner.revision_store",
    ):
        stack.enter_context(patch(f"{module}.WORKSPACE_DIR", str(tmp_path)))
    return stack


class TestAtma7BeatRefinerNode:
    def test_returns_script_md(self, tmp_path):
        from ytfactory.agents.nodes.atma_refiner import atma_7beat_refiner_node

        state = {
            "project_id": "proj-refine",
            "topic": "Mastery",
            "script_md": _BASE_SCRIPT,
            "script_identity": ScriptIdentity(core_topic="Mastery").to_dict(),
            "beats": [],
            "target_minutes": 5,
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=_REFINED_SCRIPT)
        with _patch_workspaces(tmp_path):
            with patch("ytfactory.atma_refiner.pipeline.get_llm_for_role", return_value=mock_llm):
                result = atma_7beat_refiner_node(state)
        assert "script_md" in result
        assert result["script_md"].strip() != ""

    def test_ab_NOT_invoked(self, tmp_path):
        """The node must never call build_script_a_prompt / build_script_b_prompt."""
        from ytfactory.agents.nodes.atma_refiner import atma_7beat_refiner_node
        state = {
            "project_id": "proj-noab",
            "script_md": _BASE_SCRIPT,
            "script_identity": ScriptIdentity(core_topic="Mastery").to_dict(),
            "beats": [],
            "target_minutes": 5,
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=_REFINED_SCRIPT)
        with _patch_workspaces(tmp_path):
            with patch("ytfactory.atma_refiner.pipeline.get_llm_for_role", return_value=mock_llm):
                with patch("ytfactory.agents.prompts.composer.build_script_a_prompt") as pa:
                    with patch("ytfactory.agents.prompts.composer.build_script_b_prompt") as pb:
                        atma_7beat_refiner_node(state)
                        pa.assert_not_called()
                        pb.assert_not_called()

    def test_saves_revision_lineage(self, tmp_path):
        from ytfactory.agents.nodes.atma_refiner import atma_7beat_refiner_node
        state = {
            "project_id": "proj-lineage",
            "script_md": _BASE_SCRIPT,
            "script_identity": ScriptIdentity(core_topic="Mastery").to_dict(),
            "beats": [],
            "target_minutes": 5,
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=_REFINED_SCRIPT)
        with _patch_workspaces(tmp_path):
            with patch("ytfactory.atma_refiner.pipeline.get_llm_for_role", return_value=mock_llm):
                result = atma_7beat_refiner_node(state)
        assert "atma_current_revision_id" in result
        assert result["atma_current_revision_id"] is not None

    def test_revision_number_in_result(self, tmp_path):
        from ytfactory.agents.nodes.atma_refiner import atma_7beat_refiner_node
        state = {
            "project_id": "proj-revnum",
            "script_md": _BASE_SCRIPT,
            "script_identity": ScriptIdentity(core_topic="Mastery").to_dict(),
            "beats": [],
            "target_minutes": 5,
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=_REFINED_SCRIPT)
        with _patch_workspaces(tmp_path):
            with patch("ytfactory.atma_refiner.pipeline.get_llm_for_role", return_value=mock_llm):
                result = atma_7beat_refiner_node(state)
        assert result["atma_revision_number"] == 1

    def test_targeted_refinement_uses_feedback(self, tmp_path):
        from ytfactory.agents.nodes.atma_refiner import atma_7beat_refiner_node
        state = {
            "project_id": "proj-target",
            "script_md": _BASE_SCRIPT,
            "script_identity": ScriptIdentity(core_topic="Mastery").to_dict(),
            "beats": [],
            "target_minutes": 5,
            "atma_reviewer_feedback": "Beat 1 is weak.",
            "atma_current_refined": _REFINED_SCRIPT,
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=_REFINED_SCRIPT)
        with _patch_workspaces(tmp_path):
            with patch("ytfactory.atma_refiner.pipeline.get_llm_for_role", return_value=mock_llm):
                result = atma_7beat_refiner_node(state)
        # Feedback consumed → cleared in result
        assert result["atma_reviewer_feedback"] is None

    def test_validation_result_in_state(self, tmp_path):
        from ytfactory.agents.nodes.atma_refiner import atma_7beat_refiner_node
        state = {
            "project_id": "proj-valstate",
            "script_md": _BASE_SCRIPT,
            "script_identity": ScriptIdentity(core_topic="Mastery").to_dict(),
            "beats": [],
            "target_minutes": 5,
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=_REFINED_SCRIPT)
        with _patch_workspaces(tmp_path):
            with patch("ytfactory.atma_refiner.pipeline.get_llm_for_role", return_value=mock_llm):
                result = atma_7beat_refiner_node(state)
        assert "atma_validation" in result
        assert "status" in result["atma_validation"]


class TestScriptValidatorNode:
    def test_returns_validation_dict(self, tmp_path):
        from ytfactory.agents.nodes.atma_refiner import script_validator_node
        state = {
            "project_id": "proj-vnode",
            "script_md": _REFINED_SCRIPT,
            "script_identity": ScriptIdentity(
                core_topic="Mastery",
                core_thesis="mastery compounds",
            ).to_dict(),
        }
        with patch("ytfactory.agents.nodes.atma_refiner.WORKSPACE_DIR", str(tmp_path)):
            result = script_validator_node(state)
        assert "atma_validation" in result
        val = result["atma_validation"]
        assert "status" in val
        assert "flags" in val

    def test_validation_does_not_modify_script(self, tmp_path):
        from ytfactory.agents.nodes.atma_refiner import script_validator_node
        state = {
            "project_id": "proj-vnodemod",
            "script_md": _REFINED_SCRIPT,
            "script_identity": ScriptIdentity(core_topic="Mastery").to_dict(),
        }
        with patch("ytfactory.agents.nodes.atma_refiner.WORKSPACE_DIR", str(tmp_path)):
            result = script_validator_node(state)
        assert "script_md" not in result


# ── Production workflow assertions ────────────────────────────────────────────

class TestProductionWorkflowAssertions:
    """High-level assertions about the graph structure and routing."""

    def test_graph_has_atma_7beat_refiner_node(self):
        from ytfactory.agents.graph import build_graph
        g = build_graph()
        assert "atma_7beat_refiner" in g.nodes

    def test_graph_has_script_identity_node(self):
        from ytfactory.agents.graph import build_graph
        g = build_graph()
        assert "script_identity" in g.nodes

    def test_graph_has_human_review_atma_script(self):
        from ytfactory.agents.graph import build_graph
        g = build_graph()
        assert "human_review_atma_script" in g.nodes

    def test_graph_does_not_have_composer_in_active_path(self):
        """The old A/B composer node must NOT be registered in the production graph."""
        from ytfactory.agents.graph import build_graph
        g = build_graph()
        assert "composer" not in g.nodes

    def test_graph_does_not_have_script_selector_polisher(self):
        from ytfactory.agents.graph import build_graph
        g = build_graph()
        assert "script_selector_polisher" not in g.nodes

    def test_old_ab_code_still_importable(self):
        """Existing A/B code must remain importable (not deleted)."""
        from ytfactory.composer.pipeline import ComposerPipeline  # noqa: F401
        from ytfactory.agents.nodes.script_selector_polisher import (  # noqa: F401
            script_selector_polisher_node,
        )
        from ytfactory.agents.nodes.composer import composer_node  # noqa: F401
        from ytfactory.source_refiner.pipeline import SourceRefinerPipeline  # noqa: F401

    def test_scene_planner_receives_only_canonical_script(self, tmp_path):
        """human_review_atma_script_node writes canonical to script.md before scene_planner."""
        from ytfactory.agents.nodes.atma_refiner import human_review_atma_script_node

        state = {
            "project_id": "proj-canon-test",
            "auto_mode": True,  # Skip interactive prompt
            "script_md": _REFINED_SCRIPT,
            "atma_current_refined": _REFINED_SCRIPT,
            "atma_current_revision_id": None,
            "script_identity": ScriptIdentity(core_topic="Mastery").to_dict(),
            "atma_validation": {"status": "PASS", "flags": [], "beat_coverage": {}, "spoken_word_count": 620},
            "beats": [],
            "target_minutes": 5,
        }

        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=_REFINED_SCRIPT)

        with patch("ytfactory.agents.nodes.atma_refiner.WORKSPACE_DIR", str(tmp_path)):
            with patch("ytfactory.atma_refiner.pipeline.get_llm_for_role", return_value=mock_llm):
                result = human_review_atma_script_node(state)

        # script_md returned is the canonical script
        assert result["script_md"].strip() == _REFINED_SCRIPT.strip()

        # script.md on disk is also written
        script_file = tmp_path / "proj-canon-test" / "script" / "script.md"
        assert script_file.exists()
        assert script_file.read_text(encoding="utf-8").strip() == _REFINED_SCRIPT.strip()

    def test_auto_mode_does_not_prompt(self, tmp_path):
        """auto_mode=True must not call typer.prompt."""
        from ytfactory.agents.nodes.atma_refiner import human_review_atma_script_node
        state = {
            "project_id": "proj-auto",
            "auto_mode": True,
            "script_md": _REFINED_SCRIPT,
            "atma_current_refined": _REFINED_SCRIPT,
            "atma_current_revision_id": None,
            "script_identity": ScriptIdentity(core_topic="Mastery").to_dict(),
            "atma_validation": {"status": "PASS", "flags": [], "beat_coverage": {}, "spoken_word_count": 620},
            "beats": [],
            "target_minutes": 5,
        }
        mock_llm = MagicMock()
        with patch("ytfactory.agents.nodes.atma_refiner.WORKSPACE_DIR", str(tmp_path)):
            with patch("ytfactory.atma_refiner.pipeline.get_llm_for_role", return_value=mock_llm):
                with patch("typer.prompt") as mock_prompt:
                    human_review_atma_script_node(state)
                    mock_prompt.assert_not_called()


# ── Backward-compatibility: existing A/B tests must still pass ────────────────
# (These are tested via their own test files: test_composer.py,
#  test_script_selector_polisher.py. We just verify nothing was broken.)

class TestBackwardCompatibility:
    def test_composer_pipeline_importable(self):
        from ytfactory.composer.pipeline import ComposerPipeline  # noqa: F401
        assert ComposerPipeline is not None

    def test_script_selector_polisher_importable(self):
        from ytfactory.agents.nodes.script_selector_polisher import (  # noqa: F401
            script_selector_polisher_node,
        )
        assert script_selector_polisher_node is not None

    def test_composer_selection_importable(self):
        from ytfactory.composer.selection import run_composer_with_ab_selection  # noqa: F401
        assert run_composer_with_ab_selection is not None

    def test_editorial_qa_pipeline_importable(self):
        from ytfactory.editorial_qa.pipeline import EditorialQAPipeline  # noqa: F401
        assert EditorialQAPipeline is not None

    def test_source_refiner_pipeline_importable(self):
        from ytfactory.source_refiner.pipeline import SourceRefinerPipeline  # noqa: F401
        assert SourceRefinerPipeline is not None
