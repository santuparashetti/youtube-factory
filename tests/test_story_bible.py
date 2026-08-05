"""Tests for the Story Bible system."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ytfactory.story_bible.composer import (
    compose_global_style,
    compose_scene_context,
    get_negative_prompt,
)
from ytfactory.story_bible.generator import generate_story_bible, load_or_generate_story_bible
from ytfactory.story_bible.models import (
    CharacterEntry,
    GlobalStyle,
    LocationEntry,
    StoryBible,
    WorldRules,
)
from ytfactory.story_bible.writer import write_story_bible


@pytest.fixture
def sample_bible() -> StoryBible:
    return StoryBible(
        world=WorldRules(
            era="HISTORICAL",
            cultural_context="Ancient Indian river kingdom",
            key_objects={
                "coins": "Small tarnished copper coins, dull green patina, irregular edges",
                "crown": "Heavy gold crown with rough-cut rubies, tarnished at the base",
            },
            recurring_symbols=["gold coin", "river", "wooden stake", "oil lamp", "empty chair"],
            architectural_style="Stone palace with weathered sandstone walls",
            time_period_note="Pre-industrial. No modern objects.",
        ),
        characters=[
            CharacterEntry(
                name="old man",
                slug="old-man",
                appearance="Elderly, gaunt frame, deep wrinkles, white stubble, sun-darkened skin",
                clothing="Faded white dhoti, frayed at the hem, bare feet",
                role="protagonist",
                scenes=[1, 3, 5, 8],
            ),
            CharacterEntry(
                name="king",
                slug="king",
                appearance="Middle-aged, broad-shouldered, stern expression, dark beard",
                clothing="Maroon silk robe with gold thread borders, heavy gold crown",
                role="antagonist",
                scenes=[4, 6, 7],
            ),
        ],
        locations=[
            LocationEntry(
                name="river dock",
                slug="river-dock",
                description="Crumbling stone dock jutting into a slow brown river",
                lighting_default="Pre-dawn blue shifting to amber",
                key_details=[
                    "Cracked wooden stakes at the edge",
                    "Moss on the lower stones",
                    "Single rope tied to a rusted iron ring",
                ],
                scenes=[1, 3, 8],
            ),
            LocationEntry(
                name="palace throne room",
                slug="palace-throne-room",
                description="High-ceilinged stone hall with sandstone pillars",
                lighting_default="Torchlit amber with sharp shadows",
                key_details=[
                    "Worn stone floor with geometric patterns",
                    "Elevated throne platform with three steps",
                ],
                scenes=[4, 6],
            ),
        ],
        style=GlobalStyle(),
        do_not_change=[
            "The old man always wears a faded white dhoti",
            "The river is brown and slow-moving, never blue or clear",
            "Coins are small, tarnished copper — never gold or silver",
        ],
    )


class TestComposer:
    def test_compose_includes_matched_character(self, sample_bible: StoryBible):
        ctx = compose_scene_context(
            sample_bible,
            scene_characters=["old man"],
            scene_environment="river dock",
            arc_phase="opening",
        )
        assert "Elderly, gaunt frame" in ctx
        assert "Faded white dhoti" in ctx

    def test_compose_includes_matched_location(self, sample_bible: StoryBible):
        ctx = compose_scene_context(
            sample_bible,
            scene_characters=[],
            scene_environment="river dock area",
            arc_phase="opening",
        )
        assert "Crumbling stone dock" in ctx
        assert "Cracked wooden stakes" in ctx

    def test_compose_includes_world_rules(self, sample_bible: StoryBible):
        ctx = compose_scene_context(
            sample_bible,
            scene_characters=[],
            scene_environment="",
            arc_phase="opening",
        )
        assert "HISTORICAL" in ctx
        assert "Ancient Indian" in ctx

    def test_compose_includes_recurring_symbols(self, sample_bible: StoryBible):
        ctx = compose_scene_context(
            sample_bible,
            scene_characters=[],
            scene_environment="",
            arc_phase="opening",
        )
        assert "RECURRING SYMBOLS" in ctx
        assert "gold coin" in ctx
        assert "oil lamp" in ctx

    def test_compose_includes_locked_objects(self, sample_bible: StoryBible):
        ctx = compose_scene_context(
            sample_bible,
            scene_characters=[],
            scene_environment="",
            arc_phase="opening",
        )
        assert "tarnished copper" in ctx

    def test_compose_includes_do_not_change(self, sample_bible: StoryBible):
        ctx = compose_scene_context(
            sample_bible,
            scene_characters=[],
            scene_environment="",
            arc_phase="opening",
        )
        assert "never gold or silver" in ctx

    def test_compose_includes_color_palette_for_phase(self, sample_bible: StoryBible):
        ctx = compose_scene_context(
            sample_bible,
            scene_characters=[],
            scene_environment="",
            arc_phase="climax",
        )
        assert "climax" in ctx.lower()

    def test_compose_empty_bible_has_no_character_or_location_blocks(self):
        ctx = compose_scene_context(
            StoryBible(),
            scene_characters=["someone"],
            scene_environment="somewhere",
            arc_phase="opening",
        )
        assert "LOCKED CHARACTERS" not in ctx
        assert "LOCKED LOCATION" not in ctx

    def test_global_style_returns_rendering_prefix(self, sample_bible: StoryBible):
        style = compose_global_style(sample_bible)
        assert "HYBRID CINEMATIC" in style

    def test_negative_prompt_returns_standard(self, sample_bible: StoryBible):
        neg = get_negative_prompt(sample_bible)
        assert "No text" in neg
        assert "no watermark" in neg


class TestGenerator:
    def _make_llm(self, response_data: dict) -> MagicMock:
        llm = MagicMock()
        llm.generate.return_value = MagicMock(text=json.dumps(response_data))
        return llm

    def test_generate_parses_valid_response(self):
        llm = self._make_llm({
            "world": {
                "era": "MODERN",
                "cultural_context": "Urban Western",
                "key_objects": {"briefcase": "Black leather, scuffed corners"},
                "architectural_style": "Glass office towers",
                "time_period_note": "Contemporary",
            },
            "characters": [
                {
                    "name": "CEO",
                    "slug": "ceo",
                    "appearance": "50s, silver hair, sharp features",
                    "clothing": "Charcoal suit, white shirt",
                    "role": "antagonist",
                }
            ],
            "locations": [
                {
                    "name": "boardroom",
                    "slug": "boardroom",
                    "description": "Corner office, floor-to-ceiling windows",
                    "lighting_default": "Harsh fluorescent",
                    "key_details": ["Long mahogany table", "City skyline view"],
                }
            ],
            "do_not_change": ["CEO always wears charcoal suit"],
        })
        bible = generate_story_bible(["Scene 1 narration", "Scene 2 narration"], llm)
        assert bible.world.era == "MODERN"
        assert len(bible.characters) == 1
        assert bible.characters[0].name == "CEO"
        assert len(bible.locations) == 1
        assert len(bible.do_not_change) == 1

    def test_generate_handles_failure_gracefully(self):
        llm = MagicMock()
        llm.generate.side_effect = RuntimeError("LLM down")
        bible = generate_story_bible(["narration"], llm)
        assert isinstance(bible, StoryBible)
        assert len(bible.characters) == 0

    def test_load_or_generate_caches(self, tmp_path: Path):
        llm = self._make_llm({
            "world": {"era": "MODERN", "cultural_context": "Urban"},
            "characters": [],
            "locations": [],
            "do_not_change": [],
        })
        project_id = "test-project"
        ws = str(tmp_path)
        (tmp_path / project_id).mkdir()

        bible1 = load_or_generate_story_bible(project_id, ws, ["n1"], llm)
        assert llm.generate.call_count == 1

        bible2 = load_or_generate_story_bible(project_id, ws, ["n1"], llm)
        assert llm.generate.call_count == 1  # not called again
        assert bible2.world.era == "MODERN"


class TestWriter:
    def test_writes_all_files(self, tmp_path: Path, sample_bible: StoryBible):
        base = write_story_bible(sample_bible, "test", str(tmp_path))
        assert (base / "world.md").exists()
        assert (base / "characters" / "old-man.md").exists()
        assert (base / "characters" / "king.md").exists()
        assert (base / "locations" / "river-dock.md").exists()
        assert (base / "locations" / "palace-throne-room.md").exists()
        assert (base / "style" / "global.md").exists()
        assert (base / "style" / "negative.md").exists()
        assert (base / "style" / "color-progression.md").exists()
        assert (base / "do-not-change.md").exists()

    def test_character_file_contains_locked_description(self, tmp_path: Path, sample_bible: StoryBible):
        write_story_bible(sample_bible, "test", str(tmp_path))
        content = (tmp_path / "test" / "story-bible" / "characters" / "old-man.md").read_text()
        assert "Elderly, gaunt frame" in content
        assert "Faded white dhoti" in content

    def test_location_file_contains_key_details(self, tmp_path: Path, sample_bible: StoryBible):
        write_story_bible(sample_bible, "test", str(tmp_path))
        content = (tmp_path / "test" / "story-bible" / "locations" / "river-dock.md").read_text()
        assert "Cracked wooden stakes" in content

    def test_writes_scene_files_with_frontmatter(self, tmp_path: Path, sample_bible: StoryBible):
        scenes = [
            {
                "index": 1,
                "title": "The River",
                "narration": "The old man stood by the river.",
                "visual_prompt": "Wide shot of river dock at dawn.",
                "anchor_role": "primary",
                "scene_analysis": {
                    "environment": "river dock",
                    "allowed_characters": ["old man"],
                    "story_time": "dawn",
                },
                "structured_prompt": {
                    "shot_type": "establishing_wide",
                    "camera_angle": "eye_level",
                    "focal_length": "24mm wide-angle",
                    "lighting_match": "Pre-dawn blue",
                },
                "visual_metadata": {},
            }
        ]
        write_story_bible(sample_bible, "test", str(tmp_path), scenes)
        scene_file = tmp_path / "test" / "story-bible" / "scenes" / "scene-01.md"
        assert scene_file.exists()
        content = scene_file.read_text()
        assert "establishing_wide" in content
        assert "24mm" in content
        assert "The old man stood" in content
