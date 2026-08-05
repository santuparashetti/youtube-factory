"""Tests for docs/script/task-2.2-retry-engine-reliability.md.

Covers: parse_retry_response (Phase 4), the HUMAN_SYMBOLIC / symbolic body-part
validator exceptions (Phase 5), the faithfulness pre-render gate (Phase 6), and
confirms the old two-system batch-retry phase is gone (Phase 2).
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import MagicMock

from ytfactory.agents.nodes import scene_planner as scene_planner_module
from ytfactory.agents.nodes.scene_planner import SceneEntities, _extract_scene_entities
from ytfactory.images.faithfulness_gate import evaluate_faithfulness_gate
from ytfactory.images.validators import (
    HumanClassification,
    StoryFidelityValidator,
    parse_retry_response,
)
from ytfactory.scenes.models import FaithfulnessStatus

VALID_PROMPT = "A" * 60  # >= 50 chars, satisfies visual_prompt minLength


def _valid_payload(scene_id: int = 1) -> dict:
    return {
        "scene_id": scene_id,
        "visual_prompt": VALID_PROMPT,
        "changes_made": ["removed generic man"],
        "violation_addressed": "removed unsupported human figure",
    }


# ── parse_retry_response ──────────────────────────────────────────────────────


class TestParseRetryResponse:
    def test_raw_json(self):
        raw = json.dumps(_valid_payload(1))
        result = parse_retry_response(raw, 1)
        assert result is not None
        assert result["scene_id"] == 1
        assert result["visual_prompt"] == VALID_PROMPT

    def test_fenced_json(self):
        raw = f"```json\n{json.dumps(_valid_payload(2))}\n```"
        result = parse_retry_response(raw, 2)
        assert result is not None
        assert result["scene_id"] == 2

    def test_prose_with_embedded_json(self):
        raw = f"Sure, here is the corrected scene:\n{json.dumps(_valid_payload(3))}\nHope that helps!"
        result = parse_retry_response(raw, 3)
        assert result is not None
        assert result["scene_id"] == 3

    def test_invalid_json_returns_none(self):
        result = parse_retry_response("{not valid json", 1)
        assert result is None

    def test_no_json_object_returns_none(self):
        result = parse_retry_response("I cannot help with that.", 1)
        assert result is None

    def test_empty_response_returns_none(self):
        assert parse_retry_response("", 1) is None
        assert parse_retry_response("   ", 1) is None

    def test_schema_mismatch_missing_field(self):
        payload = _valid_payload(1)
        del payload["changes_made"]
        result = parse_retry_response(json.dumps(payload), 1)
        assert result is None

    def test_scene_id_mismatch_rejected(self):
        raw = json.dumps(_valid_payload(1))
        result = parse_retry_response(raw, 2)
        assert result is None

    def test_empty_visual_prompt_rejected(self):
        payload = _valid_payload(1)
        payload["visual_prompt"] = "too short"
        result = parse_retry_response(json.dumps(payload), 1)
        assert result is None

    def test_changes_made_not_list_rejected(self):
        payload = _valid_payload(1)
        payload["changes_made"] = "not a list"
        result = parse_retry_response(json.dumps(payload), 1)
        assert result is None

    def test_changes_made_empty_list_rejected(self):
        payload = _valid_payload(1)
        payload["changes_made"] = []
        result = parse_retry_response(json.dumps(payload), 1)
        assert result is None


# ── HUMAN_SYMBOLIC / symbolic body-part exception ─────────────────────────────


class TestHumanSymbolicValidation:
    def test_symbolic_body_part_not_flagged_as_human_violation(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": []},
            prompt="Weathered hands knead dough on a worn wooden table, close-up, golden light.",
            narration="Your hands shape the dough, just as your choices shape your life.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert not any(e.code == "HUMAN_CLASSIFICATION_VIOLATED" for e in result.errors)

    def test_full_human_figure_still_flagged_under_no_human_allowed(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": []},
            prompt="A man stands at the edge of a cliff, wide cinematic.",
            narration="The eaglet tests its wings.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert any(e.code == "HUMAN_CLASSIFICATION_VIOLATED" for e in result.errors)

    def test_human_symbolic_passes_with_symbolic_indicator(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": []},
            prompt="An elderly sage's weathered hands rest on an ancient text, close-up, wide cinematic.",
            narration="Ancient teachers remind us that wisdom is earned slowly.",
            human_classification=HumanClassification.HUMAN_SYMBOLIC,
        )
        assert not any(e.code == "HUMAN_CLASSIFICATION_VIOLATED" for e in result.errors)

    def test_human_symbolic_fails_without_any_symbolic_indicator(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": []},
            prompt="A quiet mountain valley at dawn, wide cinematic, golden light.",
            narration="Ancient teachers remind us that wisdom is earned slowly.",
            human_classification=HumanClassification.HUMAN_SYMBOLIC,
        )
        assert any(e.code == "HUMAN_CLASSIFICATION_VIOLATED" for e in result.errors)


# ── Entity extractor: human_symbolic categorization ───────────────────────────


class TestEntityExtractorHumanSymbolic:
    def _make_llm(self, response_json: dict) -> MagicMock:
        llm = MagicMock()
        llm.generate.return_value = MagicMock(text=json.dumps(response_json), model="test-model")
        return llm

    def test_philosophical_sage_narration_classifies_as_human_symbolic(self):
        llm = self._make_llm(
            {
                "characters": [],
                "environment": ["ashram"],
                "objects": [],
                "human_classification": "human_symbolic",
                "human_names": [],
                "human_description": "an elderly sage, archetypal",
                "scene_category": "human_symbolic",
            }
        )
        narration = "Ancient teachers remind us that your hands shape your destiny."
        entities = _extract_scene_entities(narration, llm)
        assert entities.scene_category == "human_symbolic"
        assert entities.human_classification == HumanClassification.HUMAN_SYMBOLIC

    def test_scene_entities_accepts_human_symbolic_category(self):
        entities = SceneEntities(scene_category="human_symbolic")
        assert entities.scene_category == "human_symbolic"

    def test_incidental_animal_mention_classifies_as_abstract_not_animal_only(self):
        """'Birds sing in the Sharad season' — the season is the subject, not the birds."""
        llm = self._make_llm(
            {
                "characters": [],
                "environment": ["forest at dawn"],
                "objects": [],
                "human_classification": "no_human_allowed",
                "human_names": [],
                "human_description": "",
                "scene_category": "abstract",
            }
        )
        narration = "Birds sing and dance in the Sharad season, celebrating the turning of the year."
        entities = _extract_scene_entities(narration, llm)
        assert entities.scene_category == "abstract"

    def test_unambiguous_animal_subject_classifies_as_animal_only(self):
        llm = self._make_llm(
            {
                "characters": ["eaglet", "mother eagle"],
                "environment": ["cliff"],
                "objects": [],
                "human_classification": "no_human_allowed",
                "human_names": [],
                "human_description": "",
                "scene_category": "animal_only",
            }
        )
        narration = "The eaglet tests its wings, wobbling on the cliff edge before its mother."
        entities = _extract_scene_entities(narration, llm)
        assert entities.scene_category == "animal_only"


# ── Faithfulness pre-render gate ──────────────────────────────────────────────


class TestFaithfulnessGate:
    def _scene(self, index: int, status: str, scene_type: str = "generated_image") -> dict:
        return {
            "index": index,
            "title": f"Scene {index}",
            "scene_type": scene_type,
            "faithfulness_qa": {"status": status, "violation": "", "attempts": 1, "critical_errors": []},
        }

    def test_passes_when_all_scenes_pass(self):
        scenes = [self._scene(1, "pass"), self._scene(2, "pass")]
        result = evaluate_faithfulness_gate(scenes)
        assert result.passed is True
        assert result.passed_count == 2
        assert result.failed_count == 0

    def test_reports_failed_scenes(self):
        scenes = [
            self._scene(1, "pass"),
            self._scene(2, "failed"),
            self._scene(3, "skipped", scene_type="brand_card"),
        ]
        result = evaluate_faithfulness_gate(scenes)
        assert result.passed is False
        assert result.failed_count == 1
        assert result.passed_count == 1
        assert result.skipped_count == 1
        assert result.failed_scenes[0]["index"] == 2

    def test_gate_never_raises_regardless_of_failures(self):
        scenes = [self._scene(i, "failed") for i in range(1, 6)]
        result = evaluate_faithfulness_gate(scenes)
        assert result.passed is False
        assert result.failed_count == 5


# ── FaithfulnessStatus enum ────────────────────────────────────────────────────


class TestFaithfulnessStatusEnum:
    def test_enum_values(self):
        assert FaithfulnessStatus.PASS.value == "pass"
        assert FaithfulnessStatus.FAILED.value == "failed"
        assert FaithfulnessStatus.SKIPPED.value == "skipped"


# ── No batch retry phase (Phase 2 — two-system conflict removed) ─────────────


class TestNoBatchRetryPhase:
    def test_batch_retry_log_line_absent_from_source(self):
        source = inspect.getsource(scene_planner_module)
        assert "Retrying {} failed prompt" not in source
        assert "deterministic_retries" not in source

    def test_plain_text_retry_extraction_used(self):
        # Retries return plain text (no JSON parsing) — the response is
        # extracted via _strip_fences(retry_resp.text) to clean any
        # markdown fences the LLM wraps around the corrected prompt.
        source = inspect.getsource(scene_planner_module)
        assert "_strip_fences(retry_resp.text)" in source
        assert "parse_retry_response(" not in source
