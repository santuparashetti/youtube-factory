"""Tests for SceneBibleValidator — hard constraint enforcement."""

from __future__ import annotations

from pathlib import Path

import pytest

from ytfactory.image.character_bible import (
    AnimalPresence,
    BibleSceneCharacter,
    BibleTemporalMode,
    CharacterBible,
    CharacterPresence,
)
from ytfactory.image.environment_bible import EnvironmentBible
from ytfactory.image.scene_bible_extension import SceneBibleExtension
from ytfactory.image.scene_validator import SceneBibleValidator


@pytest.fixture(autouse=True)
def reset_singletons():
    CharacterBible.reset_instance()
    EnvironmentBible.reset_instance()
    yield
    CharacterBible.reset_instance()
    EnvironmentBible.reset_instance()


@pytest.fixture()
def bible():
    return CharacterBible.get_instance()


@pytest.fixture()
def env_bible():
    return EnvironmentBible.get_instance()


@pytest.fixture()
def validator(bible, env_bible):
    return SceneBibleValidator(bible, env_bible)


def _make_ext(**kwargs) -> SceneBibleExtension:
    defaults = {
        "temporal_mode": BibleTemporalMode.HISTORICAL_LITERAL,
        "character_presence": CharacterPresence.NONE,
        "animal_presence": AnimalPresence.NONE,
        "environment_id": "ANCIENT_STONE_WORKSHOP",
        "allowed_character_ids": [],
        "forbidden_character_ids": [],
        "characters": [],
        "anonymous_humans_allowed": False,
        "anonymous_human_description": None,
    }
    defaults.update(kwargs)
    return SceneBibleExtension(**defaults)


def _char(character_id: str, action: str = "walks calmly forward", emotion: str = "calm") -> BibleSceneCharacter:
    return BibleSceneCharacter(
        character_id=character_id,
        presence=CharacterPresence.PRIMARY,
        action=action,
        emotion=emotion,
    )


def test_valid_historical_scene_passes(validator):
    ext = _make_ext(
        character_presence=CharacterPresence.PRIMARY,
        allowed_character_ids=["SOCRATES"],
        characters=[_char("SOCRATES")],
    )
    result = validator.validate("scene-001", ext)
    assert result.passed


def test_valid_none_presence_passes(validator):
    ext = _make_ext()
    result = validator.validate("scene-001", ext)
    assert result.passed


def test_none_presence_with_characters_fails(validator):
    ext = _make_ext(
        character_presence=CharacterPresence.NONE,
        allowed_character_ids=["KAI"],
        characters=[_char("KAI")],
    )
    result = validator.validate("scene-001", ext)
    assert not result.passed
    assert any("NONE requires characters=[]" in e for e in result.errors)


def test_primary_presence_without_characters_fails(validator):
    ext = _make_ext(
        character_presence=CharacterPresence.PRIMARY,
        allowed_character_ids=["SOCRATES"],
        characters=[],
    )
    result = validator.validate("scene-001", ext)
    assert not result.passed
    assert any("requires at least one characters[]" in e for e in result.errors)


def test_background_presence_without_characters_fails(validator):
    ext = _make_ext(
        character_presence=CharacterPresence.BACKGROUND,
        allowed_character_ids=["KAI"],
        characters=[],
    )
    result = validator.validate("scene-001", ext)
    assert not result.passed


def test_symbolic_presence_without_characters_fails(validator):
    ext = _make_ext(
        character_presence=CharacterPresence.SYMBOLIC,
        allowed_character_ids=["KAI"],
        characters=[],
    )
    result = validator.validate("scene-001", ext)
    assert not result.passed


def test_unknown_character_id_fails(validator):
    ext = _make_ext(
        character_presence=CharacterPresence.PRIMARY,
        allowed_character_ids=["NONEXISTENT"],
        characters=[_char("NONEXISTENT")],
    )
    result = validator.validate("scene-001", ext)
    assert not result.passed
    assert any("Unknown character ID" in e for e in result.errors)


def test_character_not_in_allowed_fails(validator):
    ext = _make_ext(
        character_presence=CharacterPresence.PRIMARY,
        allowed_character_ids=["SOCRATES"],
        characters=[_char("KAI")],  # KAI not in allowed_character_ids
    )
    result = validator.validate("scene-001", ext)
    assert not result.passed
    assert any("not in allowed_character_ids" in e for e in result.errors)


def test_allowed_and_forbidden_overlap_fails(validator):
    ext = _make_ext(
        character_presence=CharacterPresence.PRIMARY,
        allowed_character_ids=["SOCRATES"],
        forbidden_character_ids=["SOCRATES"],  # overlap!
        characters=[_char("SOCRATES")],
    )
    result = validator.validate("scene-001", ext)
    assert not result.passed
    assert any("both allowed and forbidden" in e for e in result.errors)


def test_anonymous_humans_require_description(validator):
    ext = _make_ext(
        anonymous_humans_allowed=True,
        anonymous_human_description=None,  # missing
    )
    result = validator.validate("scene-001", ext)
    assert not result.passed
    assert any("requires anonymous_human_description" in e for e in result.errors)


def test_named_none_with_animals_is_valid(validator):
    # Animal presence is independent of named-character presence
    ext = _make_ext(
        character_presence=CharacterPresence.NONE,
        animal_presence=AnimalPresence.PRIMARY,
    )
    result = validator.validate("scene-001", ext)
    assert result.passed


def test_named_none_with_anonymous_humans_fails(validator):
    ext = _make_ext(
        character_presence=CharacterPresence.NONE,
        anonymous_humans_allowed=True,
        anonymous_human_description="background crowd",
    )
    result = validator.validate("scene-001", ext)
    assert not result.passed
    assert any("NONE cannot allow anonymous humans" in e for e in result.errors)


def test_temporal_environment_incompatibility_fails(validator):
    ext = _make_ext(
        temporal_mode=BibleTemporalMode.CONTEMPORARY_LITERAL,  # incompatible
        environment_id="ANCIENT_STONE_WORKSHOP",  # only allows HISTORICAL modes
    )
    result = validator.validate("scene-001", ext)
    assert not result.passed
    assert any("incompatible with environment_id" in e for e in result.errors)


def test_action_with_hair_fails(validator):
    ext = _make_ext(
        character_presence=CharacterPresence.PRIMARY,
        allowed_character_ids=["SOCRATES"],
        characters=[_char("SOCRATES", action="strokes his long gray hair thoughtfully")],
    )
    result = validator.validate("scene-001", ext)
    assert not result.passed
    assert any("appearance prose" in e for e in result.errors)


def test_action_with_clothing_fails(validator):
    ext = _make_ext(
        character_presence=CharacterPresence.PRIMARY,
        allowed_character_ids=["SOCRATES"],
        characters=[_char("SOCRATES", action="adjusts his clothing before speaking")],
    )
    result = validator.validate("scene-001", ext)
    assert not result.passed
    assert any("appearance prose" in e for e in result.errors)


def test_action_with_body_type_fails(validator):
    ext = _make_ext(
        character_presence=CharacterPresence.PRIMARY,
        allowed_character_ids=["KAI"],
        characters=[_char("KAI", action="the lean figure moves forward")],
    )
    result = validator.validate("scene-001", ext)
    assert not result.passed
    assert any("appearance prose" in e for e in result.errors)


def test_anonymous_description_cannot_reference_named_ids(validator):
    ext = _make_ext(
        anonymous_humans_allowed=True,
        anonymous_human_description="background people, not Socrates",
    )
    result = validator.validate("scene-001", ext)
    assert not result.passed
    assert any("named character identities" in e for e in result.errors)
