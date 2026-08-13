"""Tests for CharacterBible — loading, access, rendering, singleton, overrides."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from ytfactory.image.character_bible import CharacterBible, CharacterSystem


@pytest.fixture(autouse=True)
def reset_singleton():
    CharacterBible.reset_instance()
    yield
    CharacterBible.reset_instance()


@pytest.fixture()
def bible():
    return CharacterBible.get_instance()


def test_load_yaml_all_characters_present(bible):
    ids = bible.all_ids(CharacterSystem.DOCUMENTARY)
    assert "KAI" in ids
    assert "SOCRATES" in ids
    assert "YOUNG_HUSBAND" in ids
    assert "WIFE" in ids


def test_get_known_character_returns_entry(bible):
    entry = bible.get("KAI")
    assert entry.character_id == "KAI"
    assert entry.role == "viewer_proxy"
    assert entry.age == 28


def test_get_unknown_character_raises_key_error(bible):
    with pytest.raises(KeyError):
        bible.get("NONEXISTENT")


def test_render_identity_block_contains_no_action_prose(bible):
    block = bible.get("KAI").render_identity_block()
    # Identity block must contain the character ID
    assert "CHARACTER — KAI" in block
    # Must contain identity lock text
    assert "SAME CHARACTER" in block
    # Must NOT contain action verbs describing what the character does in a scene
    action_verbs = ["walks", "runs", "listens", "speaks", "faces"]
    for verb in action_verbs:
        assert verb not in block.lower(), f"Action verb '{verb}' found in identity block"


def test_render_forbidden_block_format(bible):
    block = bible.get("KAI").render_forbidden_block()
    assert block == "No KAI."


def test_singleton_returns_same_instance():
    b1 = CharacterBible.get_instance()
    b2 = CharacterBible.get_instance()
    assert b1 is b2


def test_project_override_merges_without_mutating_global(tmp_path):
    override_yaml = tmp_path / "character_bible.yaml"
    override_yaml.write_text(
        textwrap.dedent("""\
            documentary:
              SOCRATES:
                clothing:
                  outer: dark brown wool cloak
        """),
        encoding="utf-8",
    )
    global_path = (
        Path(__file__).parent.parent
        / "src" / "ytfactory" / "config" / "character_bible.yaml"
    )
    bible = CharacterBible(global_path, project_config_path=override_yaml)

    # Project override applied
    entry = bible.get("SOCRATES")
    assert entry.clothing.get("outer") == "dark brown wool cloak"

    # Other fields unchanged
    assert entry.age == 60

    # Other characters still present
    kai = bible.get("KAI")
    assert kai.character_id == "KAI"

    # Global config file not modified
    global_data = yaml.safe_load(global_path.read_text())
    assert global_data["documentary"]["SOCRATES"]["clothing"]["outer"] == "weathered muted-brown wool cloak"


def test_thumbnail_characters_in_correct_system():
    bible = CharacterBible.get_instance()
    thumbnail_ids = bible.all_ids(CharacterSystem.THUMBNAIL)
    assert "ATMA_BOY" in thumbnail_ids

    # ATMA_BOY not in documentary namespace
    doc_ids = bible.all_ids(CharacterSystem.DOCUMENTARY)
    assert "ATMA_BOY" not in doc_ids
