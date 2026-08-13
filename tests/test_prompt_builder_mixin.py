"""Tests for BiblePromptBuilderMixin and ImagePromptEngineV4.build_prompt()."""

from __future__ import annotations

import pytest

from ytfactory.image.character_bible import CharacterBible
from ytfactory.image.environment_bible import EnvironmentBible
from ytfactory.image.prompt_builder_mixin import PromptValidationError
from ytfactory.images.prompt_engine import ImagePromptEngineV4


@pytest.fixture(autouse=True)
def reset_singletons():
    CharacterBible.reset_instance()
    EnvironmentBible.reset_instance()
    yield
    CharacterBible.reset_instance()
    EnvironmentBible.reset_instance()


@pytest.fixture()
def engine():
    return ImagePromptEngineV4()


def _legacy_scene() -> dict:
    return {"index": 1, "visual_prompt": "Ancient temple at dawn, photorealistic."}


def _bible_scene(**overrides) -> dict:
    base = {
        "index": 9,
        "scene_id": "scene-009",
        "visual_prompt": "informational legacy fallback",
        "bible_ext": {
            "temporal_mode": "HISTORICAL_LITERAL",
            "character_presence": "PRIMARY",
            "animal_presence": "NONE",
            "anonymous_humans_allowed": False,
            "anonymous_human_description": None,
            "allowed_character_ids": ["SOCRATES", "YOUNG_HUSBAND"],
            "forbidden_character_ids": ["KAI", "WIFE"],
            "environment_id": "ANCIENT_STONE_WORKSHOP",
            "characters": [
                {
                    "character_id": "SOCRATES",
                    "presence": "PRIMARY",
                    "action": "listens calmly, seated on stone",
                    "emotion": "patient",
                    "pose_override": None,
                },
                {
                    "character_id": "YOUNG_HUSBAND",
                    "presence": "PRIMARY",
                    "action": "stands opposite and speaks with grief",
                    "emotion": "distressed",
                    "pose_override": None,
                },
            ],
        },
    }
    base.update(overrides)
    return base


def test_legacy_scene_returns_none_from_try_bible_build(engine):
    result = engine.try_bible_build(_legacy_scene())
    assert result is None


def test_legacy_build_prompt_returns_visual_prompt(engine):
    scene = _legacy_scene()
    result = engine.build_prompt(scene)
    assert result == scene["visual_prompt"]


def test_bible_scene_returns_string_from_try_bible_build(engine):
    result = engine.try_bible_build(_bible_scene())
    assert isinstance(result, str)
    assert len(result) > 0


def test_prompt_contains_identity_from_bible_only(engine):
    prompt = engine.build_prompt(_bible_scene())
    # Character identity must come from Bible, not from action
    assert "CHARACTER — SOCRATES" in prompt
    assert "CHARACTER — YOUNG_HUSBAND" in prompt
    # Actions must be in prompt
    assert "listens calmly" in prompt
    assert "speaks with grief" in prompt


def test_action_appearance_validation_blocks_prompt(engine):
    scene = _bible_scene()
    scene["bible_ext"]["characters"][0]["action"] = "adjusts his long gray beard and sits"
    with pytest.raises(PromptValidationError) as exc_info:
        engine.build_prompt(scene)
    assert "appearance prose" in str(exc_info.value)


def test_forbidden_characters_appear_in_negative_block(engine):
    prompt = engine.build_prompt(_bible_scene())
    # KAI and WIFE are in forbidden_character_ids
    assert "No KAI" in prompt or "FORBIDDEN" in prompt


def test_animal_presence_is_independent(engine):
    scene = _bible_scene()
    scene["bible_ext"]["animal_presence"] = "PRIMARY"
    scene["bible_ext"]["character_presence"] = "NONE"
    scene["bible_ext"]["allowed_character_ids"] = []
    scene["bible_ext"]["characters"] = []
    prompt = engine.build_prompt(scene)
    assert "ANIMAL_PRESENCE: PRIMARY" in prompt


def test_anonymous_human_control_is_emitted(engine):
    # Anonymous humans require character_presence != NONE
    scene = _bible_scene()
    scene["bible_ext"]["anonymous_humans_allowed"] = True
    scene["bible_ext"]["anonymous_human_description"] = "silent background scribes"
    prompt = engine.build_prompt(scene)
    assert "ANONYMOUS" in prompt
    assert "scribes" in prompt


def test_environment_description_comes_from_environment_bible(engine):
    prompt = engine.build_prompt(_bible_scene())
    # EnvironmentBible description for ANCIENT_STONE_WORKSHOP contains "limestone"
    assert "limestone" in prompt.lower() or "workshop" in prompt.lower()


def test_block_order_matches_canonical_order(engine):
    prompt = engine.build_prompt(_bible_scene())
    global_pos = prompt.find("GLOBAL STYLE")
    temporal_pos = prompt.find("TEMPORAL_MODE")
    presence_pos = prompt.find("CHARACTER_PRESENCE")
    char_pos = prompt.find("CHARACTER — ")
    negative_pos = prompt.find("NEGATIVE:")

    assert global_pos < temporal_pos
    assert temporal_pos < presence_pos
    assert presence_pos < char_pos
    assert char_pos < negative_pos


def test_invalid_bible_ext_raises_prompt_validation_error(engine):
    scene = {
        "index": 3,
        "visual_prompt": "fallback",
        "bible_ext": {
            "temporal_mode": "INVALID_MODE",
            "character_presence": "PRIMARY",
            "animal_presence": "NONE",
            "environment_id": "X",
        },
    }
    with pytest.raises(PromptValidationError):
        engine.build_prompt(scene)


def test_validation_error_contains_scene_id(engine):
    scene = _bible_scene()
    # Empty characters list with PRIMARY presence → validation error
    scene["bible_ext"]["characters"] = []
    with pytest.raises(PromptValidationError) as exc_info:
        engine.build_prompt(scene)
    # scene_id is derived from scene["scene_id"] which is "scene-009"
    assert exc_info.value.scene_id == "scene-009"
