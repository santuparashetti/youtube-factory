"""Tests for scene planner entity grounding."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from ytfactory.agents.nodes.scene_planner import (
    SceneEntities,
    _build_entity_block,
    _build_entity_constraints_section,
    _extract_scene_entities,
    _parse_json_response,
    _validate_prompt_faithfulness,
)
from ytfactory.images.validators import HumanClassification

# ── SceneEntities ──────────────────────────────────────────────────────────────


class TestSceneEntities:
    def test_default_values(self):
        entities = SceneEntities()
        assert entities.characters == []
        assert entities.has_human is False
        assert entities.scene_category == "abstract"

    def test_animal_only(self):
        entities = SceneEntities(
            characters=["eagle", "eaglet"],
            scene_category="animal_only",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert entities.scene_category == "animal_only"
        assert entities.has_human is False

    def test_human_named(self):
        entities = SceneEntities(
            characters=["Bhagiratha"],
            human_classification=HumanClassification.NAMED_PERSON_REQUIRED,
            human_names=["Bhagiratha"],
            scene_category="human_named",
        )
        assert entities.has_human is True
        assert "Bhagiratha" in entities.human_names


# ── _parse_json_response ──────────────────────────────────────────────────────


class TestParseJsonResponse:
    def test_clean_json(self):
        result = _parse_json_response('{"pass": true, "severity": "none"}')
        assert result == {"pass": True, "severity": "none"}

    def test_json_in_code_fence(self):
        text = '```json\n{"pass": false, "violation": "man"}\n```'
        result = _parse_json_response(text)
        assert result == {"pass": False, "violation": "man"}

    def test_malformed_returns_none(self):
        result = _parse_json_response("not json at all")
        assert result is None

    def test_empty_string_returns_none(self):
        result = _parse_json_response("")
        assert result is None


# ── _build_entity_block ───────────────────────────────────────────────────────


class TestBuildEntityBlock:
    def test_animal_only_block(self):
        entities = SceneEntities(
            characters=["eagle", "eaglet"],
            environment=["cliff", "open sky"],
            objects=["nest"],
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="animal_only",
        )
        block = _build_entity_block(entities)
        assert "scene_category: animal_only" in block
        assert "human_classification: no_human_allowed" in block
        assert "characters_present: eagle, eaglet" in block
        assert "environment: cliff, open sky" in block

    def test_human_named_block(self):
        entities = SceneEntities(
            characters=["Bhagiratha"],
            human_classification=HumanClassification.NAMED_PERSON_REQUIRED,
            human_names=["Bhagiratha"],
            scene_category="human_named",
        )
        block = _build_entity_block(entities)
        assert "scene_category: human_named" in block
        assert "named_humans: Bhagiratha" in block

    def test_abstract_block(self):
        entities = SceneEntities(
            scene_category="abstract",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        block = _build_entity_block(entities)
        assert "scene_category: abstract" in block
        assert "human_classification: no_human_allowed" in block
        assert "characters_present:" not in block


# ── _build_entity_constraints_section ────────────────────────────────────────


class TestBuildEntityConstraintsSection:
    def test_empty_map_returns_empty(self):
        result = _build_entity_constraints_section([], {})
        assert result == ""

    def test_multiple_scenes(self):
        scenes = [
            {"index": 1, "narration": "The chick rose."},
            {"index": 2, "narration": "Bhagiratha walked."},
        ]
        entity_map = {
            1: SceneEntities(characters=["eaglet"], human_classification=HumanClassification.NO_HUMAN_ALLOWED, scene_category="animal_only"),
            2: SceneEntities(characters=["Bhagiratha"], human_classification=HumanClassification.NAMED_PERSON_REQUIRED, human_names=["Bhagiratha"], scene_category="human_named"),
        }
        result = _build_entity_constraints_section(scenes, entity_map)
        assert "Scene 1:" in result
        assert "category=animal_only" in result
        assert "Scene 2:" in result
        assert "category=human_named" in result


# ── _extract_scene_entities ───────────────────────────────────────────────────


class TestExtractSceneEntities:
    def _make_llm(self, response_json: dict) -> MagicMock:
        llm = MagicMock()
        llm.generate.return_value = MagicMock(
            text=json.dumps(response_json),
            model="test-model",
        )
        return llm

    def test_eagle_segment(self):
        llm = self._make_llm({
            "characters": ["eaglet", "eagle"],
            "environment": ["cliff", "sky"],
            "objects": [],
            "human_classification": "no_human_allowed",
            "human_names": [],
            "human_description": "",
            "scene_category": "animal_only",
        })
        narration = "The chick rose a little. Came down. Tried again."
        entities = _extract_scene_entities(narration, llm)
        assert entities.scene_category == "animal_only"
        assert entities.has_human is False
        assert "eaglet" in entities.characters

    def test_viewer_address(self):
        llm = self._make_llm({
            "characters": [],
            "environment": [],
            "objects": [],
            "human_classification": "no_human_allowed",
            "human_names": [],
            "human_description": "",
            "scene_category": "abstract",
        })
        narration = "You feel it within. One day, I too should soar up high."
        entities = _extract_scene_entities(narration, llm)
        assert entities.has_human is False
        assert entities.scene_category == "abstract"

    def test_named_human(self):
        llm = self._make_llm({
            "characters": ["Bhagiratha"],
            "environment": ["Himalayan peaks"],
            "objects": [],
            "human_classification": "named_person_required",
            "human_names": ["Bhagiratha"],
            "human_description": "an elderly Indian sage",
            "scene_category": "human_named",
        })
        narration = "Bhagiratha went to the Himalayan peaks. He blocked mountains."
        entities = _extract_scene_entities(narration, llm)
        assert entities.has_human is True
        assert "Bhagiratha" in entities.human_names
        assert entities.scene_category == "human_named"

    def test_invalid_json_falls_back_to_abstract(self):
        llm = MagicMock()
        llm.generate.return_value = MagicMock(text="not json", model="test")
        entities = _extract_scene_entities("some narration", llm)
        assert entities.scene_category == "abstract"
        assert entities.has_human is False


# ── _validate_prompt_faithfulness ─────────────────────────────────────────────


class TestValidatePromptFaithfulness:
    def _make_llm(self, pass_val: bool, violation: str = "", severity: str = "none") -> MagicMock:
        llm = MagicMock()
        llm.generate.return_value = MagicMock(
            text=json.dumps({"pass": pass_val, "violation": violation, "severity": severity}),
            model="test-model",
        )
        return llm

    def test_passes_clean_prompt(self):
        llm = self._make_llm(True)
        entities = SceneEntities(
            characters=["eaglet"],
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="animal_only",
        )
        prompt = "A young eaglet tests its wings on a cliff edge, golden hour light."
        passed, _violation = _validate_prompt_faithfulness(
            "The chick rose a little.", entities, prompt, llm
        )
        assert passed is True

    def test_fails_on_human_in_animal_scene(self):
        llm = self._make_llm(False, "man", "critical")
        entities = SceneEntities(
            characters=["eaglet"],
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="animal_only",
        )
        prompt = "A lean man stands at the edge of a cliff, watching the sky..."
        passed, violation = _validate_prompt_faithfulness(
            "The chick rose a little.", entities, prompt, llm
        )
        assert passed is False
        assert "man" in violation.lower()

    def test_minor_failure_returns_empty_violation(self):
        llm = self._make_llm(False, "minor detail wrong", "minor")
        entities = SceneEntities(
            characters=["Bhagiratha"],
            human_classification=HumanClassification.NAMED_PERSON_REQUIRED,
            human_names=["Bhagiratha"],
            scene_category="human_named",
        )
        prompt = "Bhagiratha in ancient India."
        passed, violation = _validate_prompt_faithfulness(
            "Bhagiratha went to the Himalayan peaks.", entities, prompt, llm
        )
        assert passed is False
        assert violation == ""

    def test_invalid_json_returns_pass(self):
        llm = MagicMock()
        llm.generate.return_value = MagicMock(text="not json", model="test")
        entities = SceneEntities(
            characters=["eaglet"],
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
            scene_category="animal_only",
        )
        passed, violation = _validate_prompt_faithfulness(
            "The chick rose a little.", entities, "some prompt", llm
        )
        assert passed is True
        assert violation == ""


class TestAudienceVisualDirective:
    def test_visual_prompts_template_contains_audience_rule(self):
        from ytfactory.agents.prompts.scene_planner import build_visual_prompts_prompt

        prompt = build_visual_prompts_prompt(
            scenes=[{"index": 1, "narration": "A man walks forward.", "shot_type": "wide shot"}]
        )
        assert "SYMBOLIC / ABSTRACT" in prompt
        assert "WESTERN / ENGLISH-SPEAKING" in prompt
        assert "US, UK, AU, CA" in prompt
