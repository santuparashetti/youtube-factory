"""Tests for SceneBibleExtension — parsing, legacy detection, strict rejection."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ytfactory.image.scene_bible_extension import SceneBibleExtension, parse_bible_ext


def _valid_raw() -> dict:
    return {
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
                "action": "listens calmly, seated on a stone bench",
                "emotion": "patient",
                "pose_override": None,
            },
        ],
    }


def test_missing_bible_ext_is_legacy():
    result = parse_bible_ext(None)
    assert result is None

    # All-default SceneBibleExtension is also legacy
    ext = SceneBibleExtension()
    assert ext.is_legacy() is True


def test_valid_full_extension_parses():
    ext = parse_bible_ext(_valid_raw())
    assert ext is not None
    assert not ext.is_legacy()
    assert ext.environment_id == "ANCIENT_STONE_WORKSHOP"
    assert len(ext.characters) == 1
    assert ext.characters[0].character_id == "SOCRATES"


def test_invalid_temporal_mode_fails_at_parse():
    raw = _valid_raw()
    raw["temporal_mode"] = "HISTORICAL_LITERA"  # typo
    with pytest.raises(ValidationError):
        parse_bible_ext(raw)


def test_invalid_character_presence_fails_at_parse():
    raw = _valid_raw()
    raw["character_presence"] = "FOREGROUND"  # not a valid CharacterPresence
    with pytest.raises(ValidationError):
        parse_bible_ext(raw)


def test_invalid_animal_presence_fails_at_parse():
    raw = _valid_raw()
    raw["animal_presence"] = "MAYBE"
    with pytest.raises(ValidationError):
        parse_bible_ext(raw)


def test_wrong_primitive_type_fails_at_parse():
    raw = _valid_raw()
    raw["anonymous_humans_allowed"] = "yes"  # string instead of bool
    with pytest.raises(ValidationError):
        parse_bible_ext(raw)


def test_unknown_fields_fail_at_parse():
    raw = _valid_raw()
    raw["completely_unknown_key"] = "some_value"
    with pytest.raises(ValidationError):
        parse_bible_ext(raw)


def test_old_scene_plan_loads_unchanged():
    # A scene dict without bible_ext should return None — legacy path
    scene = {
        "index": 1,
        "scene_id": "scene-001",
        "narration": "In the beginning...",
        "visual_prompt": "Ancient temple at dawn.",
    }
    result = parse_bible_ext(scene.get("bible_ext"))
    assert result is None
