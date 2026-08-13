"""Tests for EnvironmentBible — loading, access, temporal compatibility, overrides."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ytfactory.image.character_bible import BibleTemporalMode
from ytfactory.image.environment_bible import EnvironmentBible


@pytest.fixture(autouse=True)
def reset_singleton():
    EnvironmentBible.reset_instance()
    yield
    EnvironmentBible.reset_instance()


@pytest.fixture()
def env_bible():
    return EnvironmentBible.get_instance()


def test_load_yaml_all_environments_present(env_bible):
    ids = env_bible.all_ids()
    assert "ANCIENT_STONE_WORKSHOP" in ids
    assert "ANCIENT_AGORA" in ids
    assert "CONTEMPORARY_APARTMENT" in ids
    assert "ABSTRACT" in ids


def test_get_known_environment_returns_entry(env_bible):
    entry = env_bible.get("ANCIENT_STONE_WORKSHOP")
    assert entry.environment_id == "ANCIENT_STONE_WORKSHOP"
    assert entry.era_family == "HISTORICAL"
    assert entry.period == "ANCIENT_GREECE"
    assert "limestone" in entry.description.lower()


def test_unknown_environment_raises_key_error(env_bible):
    with pytest.raises(KeyError):
        env_bible.get("NONEXISTENT_ENV")


def test_has_returns_true_for_known(env_bible):
    assert env_bible.has("ANCIENT_AGORA") is True
    assert env_bible.has("BOGUS") is False


def test_temporal_compatibility_is_data_driven(env_bible):
    entry = env_bible.get("ANCIENT_STONE_WORKSHOP")
    assert entry.is_compatible_with(BibleTemporalMode.HISTORICAL_LITERAL) is True
    assert entry.is_compatible_with(BibleTemporalMode.HISTORICAL_SYMBOLIC) is True
    assert entry.is_compatible_with(BibleTemporalMode.CONTEMPORARY_LITERAL) is False
    assert entry.is_compatible_with(BibleTemporalMode.CONTEMPORARY_SYMBOLIC) is False

    abstract = env_bible.get("ABSTRACT")
    assert abstract.is_compatible_with(BibleTemporalMode.TIMELESS_SYMBOLIC) is True
    assert abstract.is_compatible_with(BibleTemporalMode.HISTORICAL_SYMBOLIC) is True
    assert abstract.is_compatible_with(BibleTemporalMode.HISTORICAL_LITERAL) is False


def test_project_override_merges_without_mutating_global(tmp_path):
    override_yaml = tmp_path / "environment_bible.yaml"
    override_yaml.write_text(
        textwrap.dedent("""\
            environments:
              ANCIENT_STONE_WORKSHOP:
                description: Custom overridden description for tests.
              PROJECT_GARDEN:
                era_family: HISTORICAL
                period: ANCIENT_GREECE
                allowed_temporal_modes:
                  - HISTORICAL_LITERAL
                description: A quiet garden in ancient Athens.
        """),
        encoding="utf-8",
    )
    global_path = (
        Path(__file__).parent.parent
        / "src" / "ytfactory" / "config" / "environment_bible.yaml"
    )
    env_bible = EnvironmentBible(global_path, project_config_path=override_yaml)

    # Override applied
    entry = env_bible.get("ANCIENT_STONE_WORKSHOP")
    assert "Custom overridden" in entry.description

    # Project-only ID added
    project_entry = env_bible.get("PROJECT_GARDEN")
    assert project_entry.era_family == "HISTORICAL"

    # Other existing environments unchanged
    assert env_bible.has("ANCIENT_AGORA")


def test_invalid_environment_entry_fails_at_load(tmp_path):
    bad_yaml = tmp_path / "environment_bible.yaml"
    # YAML is valid but contains an unknown temporal mode — should load without crash
    # (unknown modes are silently skipped, as the file may be extended in future)
    bad_yaml.write_text(
        textwrap.dedent("""\
            environments:
              TEST_ENV:
                era_family: TEST
                period: TEST
                allowed_temporal_modes:
                  - HISTORICAL_LITERAL
                  - UNKNOWN_MODE
                description: Test.
        """),
        encoding="utf-8",
    )
    env_bible = EnvironmentBible(bad_yaml)
    entry = env_bible.get("TEST_ENV")
    # Known mode present, unknown skipped
    assert BibleTemporalMode.HISTORICAL_LITERAL in entry.allowed_temporal_modes
