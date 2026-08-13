"""Regression tests for the character_presence architecture.

Verifies that:
- Kai is absent when not in character_presence
- Kai is present when explicitly selected via character_presence
- YOUNG_HUSBAND does not cause Kai to appear
- Symbolic scenes do not automatically inject Kai
- Environment-only scenes contain no characters
- Previous-scene characters do not leak into subsequent scenes
- Character appearance resolves from Character Bible
- anchor_role is derived from character_presence, not the other way around
"""

from __future__ import annotations

import pytest

from ytfactory.agents.nodes.scene_planner import (
    KAI_COMPRESSED_SPEC,
    _enforce_primary_kai_spec,
    _enforce_style_footer,
    _has_kai_markers,
)
from ytfactory.scenes.models import Scene, ScenePlan


# ── helpers ──────────────────────────────────────────────────────────────────


def _scene_dict(
    index: int = 1,
    visual_prompt: str = "Ancient Greek street at dawn, stone paving, olive trees.",
    anchor_role: str = "absent",
    character_presence: list[str] | None = None,
    narration: str = "Test narration.",
    scene_type: str = "generated_image",
    structured_prompt: dict | None = None,
) -> dict:
    return {
        "index": index,
        "title": f"Scene {index}",
        "narration": narration,
        "visual_prompt": visual_prompt,
        "duration_seconds": 5.0,
        "anchor_role": anchor_role,
        "character_presence": character_presence if character_presence is not None else [],
        "scene_type": scene_type,
        "structured_prompt": structured_prompt,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Kai absent when not in character_presence
# ─────────────────────────────────────────────────────────────────────────────

class TestKaiAbsentWhenNotSelected:
    def test_kai_not_injected_when_absent_from_character_presence(self):
        """Scene with character_presence=[] must never contain Kai spec."""
        scene = _scene_dict(
            anchor_role="absent",
            character_presence=[],
        )
        result = _enforce_primary_kai_spec([scene])
        assert not _has_kai_markers(result[0]["visual_prompt"])

    def test_kai_stripped_when_anchor_primary_but_character_presence_has_others(self):
        """character_presence with only YOUNG_HUSBAND overrides anchor_role='primary'."""
        scene = _scene_dict(
            anchor_role="primary",
            character_presence=["YOUNG_HUSBAND"],
            visual_prompt=(
                f"{KAI_COMPRESSED_SPEC} — sitting, facing forward. "
                "Ancient Greek courtyard."
            ),
        )
        result = _enforce_primary_kai_spec([scene])
        assert not _has_kai_markers(result[0]["visual_prompt"])

    def test_anchor_role_overridden_to_absent_when_kai_stripped(self):
        """When Kai is stripped from a scene, anchor_role must become 'absent'."""
        scene = _scene_dict(
            anchor_role="primary",
            character_presence=["WIFE"],
            visual_prompt=(
                f"{KAI_COMPRESSED_SPEC} — walking quietly. Greek street."
            ),
        )
        result = _enforce_primary_kai_spec([scene])
        assert result[0]["anchor_role"] == "absent"

    def test_symbolic_scene_no_characters_no_kai(self):
        """Symbolic environment-only scene must produce no Kai."""
        scene = _scene_dict(
            anchor_role="absent",
            character_presence=[],
            visual_prompt="A cracked hourglass on a stone floor, soft grey light.",
        )
        result = _enforce_primary_kai_spec([scene])
        assert not _has_kai_markers(result[0]["visual_prompt"])
        assert result[0]["anchor_role"] == "absent"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Kai present when explicitly selected
# ─────────────────────────────────────────────────────────────────────────────

class TestKaiPresentWhenExplicitlySelected:
    def test_kai_injected_when_in_character_presence(self):
        """character_presence=['KAI'] triggers Kai spec injection."""
        scene = _scene_dict(
            anchor_role="absent",
            character_presence=["KAI"],
            visual_prompt="Seated on a stone bench, looking at the horizon.",
        )
        result = _enforce_primary_kai_spec([scene])
        assert _has_kai_markers(result[0]["visual_prompt"])

    def test_kai_presence_sets_anchor_role_primary(self):
        """character_presence=['KAI'] must set anchor_role='primary'."""
        scene = _scene_dict(
            anchor_role="absent",
            character_presence=["KAI"],
            visual_prompt="Walking slowly through a morning market.",
        )
        result = _enforce_primary_kai_spec([scene])
        assert result[0]["anchor_role"] == "primary"

    def test_existing_kai_markers_and_action_not_doubled(self):
        """If Kai spec is already present with action staging, don't duplicate."""
        scene = _scene_dict(
            anchor_role="primary",
            character_presence=["KAI"],
            visual_prompt=(
                f"{KAI_COMPRESSED_SPEC} — sitting on a stone bench, "
                "hands resting on knees, looking outward."
            ),
        )
        result = _enforce_primary_kai_spec([scene])
        prompt = result[0]["visual_prompt"]
        # Spec should appear exactly once (not doubled)
        assert prompt.count("short dark hair") == 1


# ─────────────────────────────────────────────────────────────────────────────
# 3. YOUNG_HUSBAND does not cause Kai to appear
# ─────────────────────────────────────────────────────────────────────────────

class TestYoungHusbandDoesNotCauseKai:
    def test_young_husband_scene_has_no_kai(self):
        """A YOUNG_HUSBAND scene must never have Kai spec injected."""
        scene = _scene_dict(
            anchor_role="absent",
            character_presence=["YOUNG_HUSBAND"],
            visual_prompt=(
                "A young man in a simple linen tunic stands at a market stall, "
                "counting coins with a worried expression."
            ),
        )
        result = _enforce_primary_kai_spec([scene])
        assert not _has_kai_markers(result[0]["visual_prompt"])

    def test_young_husband_and_wife_no_kai(self):
        """YOUNG_HUSBAND + WIFE scene must never have Kai spec."""
        scene = _scene_dict(
            anchor_role="absent",
            character_presence=["YOUNG_HUSBAND", "WIFE"],
            visual_prompt=(
                "A young couple in ancient Greek clothing sit across from each other "
                "at a wooden table, not speaking, the air heavy between them."
            ),
        )
        result = _enforce_primary_kai_spec([scene])
        assert not _has_kai_markers(result[0]["visual_prompt"])

    def test_socrates_scene_has_no_kai(self):
        """SOCRATES scene must not inject Kai."""
        scene = _scene_dict(
            anchor_role="absent",
            character_presence=["SOCRATES"],
            visual_prompt=(
                "An older man with a thick grey beard and simple tunic speaks "
                "calmly at the edge of the agora."
            ),
        )
        result = _enforce_primary_kai_spec([scene])
        assert not _has_kai_markers(result[0]["visual_prompt"])

    def test_young_husband_with_primary_anchor_still_no_kai(self):
        """anchor_role='primary' must NOT override character_presence=['YOUNG_HUSBAND']."""
        scene = _scene_dict(
            anchor_role="primary",  # old / wrong anchor role
            character_presence=["YOUNG_HUSBAND"],
            visual_prompt=(
                "A young man in a cream linen tunic stands at the threshold "
                "of a small Greek home, hesitating."
            ),
        )
        result = _enforce_primary_kai_spec([scene])
        assert not _has_kai_markers(result[0]["visual_prompt"])


# ─────────────────────────────────────────────────────────────────────────────
# 4. Symbolic scene does not automatically inject Kai
# ─────────────────────────────────────────────────────────────────────────────

class TestSymbolicSceneNoAutoKai:
    def test_symbolic_prompt_no_characters_no_kai(self):
        """Symbolic/atmospheric prompts with no character_presence never get Kai."""
        scene = _scene_dict(
            anchor_role="absent",
            character_presence=[],
            visual_prompt=(
                "A cracked clay pot on a dusty floor, a single oil lamp burning, "
                "shadow and warm amber light."
            ),
        )
        result = _enforce_primary_kai_spec([scene])
        assert not _has_kai_markers(result[0]["visual_prompt"])
        assert result[0]["anchor_role"] == "absent"

    def test_symbolic_scene_keeps_absent_role(self):
        """Symbolic scenes with no character_presence stay anchor_role='absent'."""
        scene = _scene_dict(anchor_role="absent", character_presence=[])
        result = _enforce_primary_kai_spec([scene])
        assert result[0]["anchor_role"] == "absent"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Environment-only scenes contain no characters
# ─────────────────────────────────────────────────────────────────────────────

class TestEnvironmentOnlyScenes:
    def test_empty_character_presence_no_kai(self):
        scene = _scene_dict(character_presence=[])
        result = _enforce_primary_kai_spec([scene])
        assert not _has_kai_markers(result[0]["visual_prompt"])

    def test_empty_character_presence_anchor_absent(self):
        scene = _scene_dict(character_presence=[], anchor_role="absent")
        result = _enforce_primary_kai_spec([scene])
        assert result[0]["anchor_role"] == "absent"

    def test_environment_only_style_footer_is_symbolic(self):
        """Empty character_presence → symbolic footer, not illustrated."""
        scene = _scene_dict(character_presence=[], anchor_role="absent")
        result = _enforce_style_footer([scene], hybrid=True)
        prompt = result[0]["visual_prompt"]
        # Illustrated footer would have "ink outlines" — symbolic footer should NOT
        assert "ink outlines" not in prompt.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Previous-scene characters do not leak into subsequent scenes
# ─────────────────────────────────────────────────────────────────────────────

class TestNoCharacterLeakage:
    def test_scene_11_char_does_not_appear_in_scene_12(self):
        """Characters from scene 11 must not appear in scene 12's prompt."""
        scene_11 = _scene_dict(
            index=11,
            character_presence=["YOUNG_HUSBAND", "WIFE"],
            anchor_role="absent",
            visual_prompt="Ancient Greek street. Young couple walking.",
        )
        scene_12 = _scene_dict(
            index=12,
            character_presence=[],
            anchor_role="absent",
            visual_prompt="Empty stone courtyard at night, a single oil lamp.",
        )
        result = _enforce_primary_kai_spec([scene_11, scene_12])
        # Scene 12 must not have Kai markers or reference scene 11's characters
        assert not _has_kai_markers(result[1]["visual_prompt"])
        assert result[1]["anchor_role"] == "absent"

    def test_kai_in_scene_5_does_not_appear_in_scene_6(self):
        """Kai in scene 5 must not bleed into scene 6 which has no character_presence."""
        scene_5 = _scene_dict(
            index=5,
            character_presence=["KAI"],
            anchor_role="primary",
            visual_prompt=(
                f"{KAI_COMPRESSED_SPEC} — seated on a stone, looking outward."
            ),
        )
        scene_6 = _scene_dict(
            index=6,
            character_presence=[],
            anchor_role="absent",
            visual_prompt="A river at dusk, golden light on still water.",
        )
        result = _enforce_primary_kai_spec([scene_5, scene_6])
        assert not _has_kai_markers(result[1]["visual_prompt"])
        assert result[1]["anchor_role"] == "absent"

    def test_story_characters_in_scene_13_independent_of_scene_12_empty(self):
        """Scene 13 with characters is independent of scene 12 being empty."""
        scene_12 = _scene_dict(
            index=12,
            character_presence=[],
            anchor_role="absent",
            visual_prompt="Distant mountains at sunrise.",
        )
        scene_13 = _scene_dict(
            index=13,
            character_presence=["YOUNG_HUSBAND", "WIFE", "SOCRATES"],
            anchor_role="absent",
            visual_prompt=(
                "A young couple and an older bearded man sit together in an agora."
            ),
        )
        result = _enforce_primary_kai_spec([scene_12, scene_13])
        # Scene 12 stays empty
        assert not _has_kai_markers(result[0]["visual_prompt"])
        # Scene 13 has its own characters (not Kai)
        assert not _has_kai_markers(result[1]["visual_prompt"])


# ─────────────────────────────────────────────────────────────────────────────
# 7. Character appearance from Character Bible
# ─────────────────────────────────────────────────────────────────────────────

class TestCharacterBibleLookup:
    def test_character_bible_has_kai(self):
        from ytfactory.image.character_bible import CharacterBible, CharacterSystem
        bible = CharacterBible.get_instance()
        kai = bible.get("KAI", CharacterSystem.DOCUMENTARY)
        assert kai.character_id == "KAI"
        assert kai.age == 28
        assert "dark" in (kai.hair or "").lower()

    def test_character_bible_has_young_husband(self):
        from ytfactory.image.character_bible import CharacterBible, CharacterSystem
        bible = CharacterBible.get_instance()
        yh = bible.get("YOUNG_HUSBAND", CharacterSystem.DOCUMENTARY)
        assert yh.character_id == "YOUNG_HUSBAND"
        assert yh.role == "story_subject"

    def test_character_bible_has_wife(self):
        from ytfactory.image.character_bible import CharacterBible, CharacterSystem
        bible = CharacterBible.get_instance()
        wife = bible.get("WIFE", CharacterSystem.DOCUMENTARY)
        assert wife.character_id == "WIFE"
        assert wife.role == "story_subject"

    def test_character_bible_has_socrates(self):
        from ytfactory.image.character_bible import CharacterBible, CharacterSystem
        bible = CharacterBible.get_instance()
        socrates = bible.get("SOCRATES", CharacterSystem.DOCUMENTARY)
        assert socrates.character_id == "SOCRATES"

    def test_kai_and_young_husband_are_distinct(self):
        """KAI and YOUNG_HUSBAND must have different identity_lock text — distinct characters."""
        from ytfactory.image.character_bible import CharacterBible, CharacterSystem
        bible = CharacterBible.get_instance()
        kai = bible.get("KAI", CharacterSystem.DOCUMENTARY)
        yh = bible.get("YOUNG_HUSBAND", CharacterSystem.DOCUMENTARY)
        # They are distinct characters with different roles
        assert kai.role != yh.role
        # Their clothing description is different
        kai_clothing = " ".join(kai.clothing.values()).lower()
        yh_clothing = " ".join(yh.clothing.values()).lower()
        # Kai has dark shirt/charcoal; Young Husband has linen/cream tunic
        assert "charcoal" in kai_clothing or "dark" in kai_clothing
        assert "linen" in yh_clothing or "cream" in yh_clothing or "tunic" in yh_clothing


# ─────────────────────────────────────────────────────────────────────────────
# 8. Style footer uses character_presence
# ─────────────────────────────────────────────────────────────────────────────

class TestStyleFooterUsesCharacterPresence:
    def test_kai_scene_gets_illustrated_footer(self):
        """KAI in character_presence → illustrated footer in hybrid mode."""
        scene = _scene_dict(
            character_presence=["KAI"],
            anchor_role="primary",
            visual_prompt=f"{KAI_COMPRESSED_SPEC} — standing quietly at dusk.",
        )
        result = _enforce_style_footer([scene], hybrid=True)
        assert "ink outlines" in result[0]["visual_prompt"].lower()

    def test_story_characters_get_illustrated_footer(self):
        """YOUNG_HUSBAND in character_presence → illustrated footer in hybrid mode."""
        scene = _scene_dict(
            character_presence=["YOUNG_HUSBAND", "WIFE"],
            anchor_role="absent",
            visual_prompt="Ancient Greek couple in a courtyard.",
        )
        result = _enforce_style_footer([scene], hybrid=True)
        assert "ink outlines" in result[0]["visual_prompt"].lower()

    def test_empty_character_presence_gets_symbolic_footer(self):
        """Empty character_presence → symbolic footer (no illustrated marker)."""
        scene = _scene_dict(
            character_presence=[],
            anchor_role="absent",
            visual_prompt="A cracked hourglass on a stone floor.",
        )
        result = _enforce_style_footer([scene], hybrid=True)
        assert "ink outlines" not in result[0]["visual_prompt"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# 9. Scene model accepts character_presence field
# ─────────────────────────────────────────────────────────────────────────────

class TestSceneModelCharacterPresence:
    def test_scene_model_default_character_presence_is_empty(self):
        scene = Scene(
            index=1,
            title="Test",
            narration="Test narration.",
            visual_prompt="Test prompt.",
            duration_seconds=5.0,
        )
        assert scene.character_presence == []

    def test_scene_model_accepts_character_presence_list(self):
        scene = Scene(
            index=1,
            title="Test",
            narration="Test narration.",
            visual_prompt="Test prompt.",
            duration_seconds=5.0,
            character_presence=["YOUNG_HUSBAND", "WIFE"],
        )
        assert "YOUNG_HUSBAND" in scene.character_presence
        assert "WIFE" in scene.character_presence

    def test_scene_model_serializes_character_presence(self):
        scene = Scene(
            index=1,
            title="Test",
            narration="Test narration.",
            visual_prompt="Test prompt.",
            duration_seconds=5.0,
            character_presence=["KAI"],
        )
        data = scene.model_dump()
        assert data["character_presence"] == ["KAI"]

    def test_scene_model_deserializes_character_presence(self):
        data = {
            "index": 1,
            "title": "Test",
            "narration": "Test narration.",
            "visual_prompt": "Test prompt.",
            "duration_seconds": 5.0,
            "character_presence": ["SOCRATES", "YOUNG_HUSBAND"],
            "anchor_role": "absent",
        }
        scene = Scene.model_validate(data)
        assert scene.character_presence == ["SOCRATES", "YOUNG_HUSBAND"]


# ─────────────────────────────────────────────────────────────────────────────
# 10. Aerial shot guard still applies for KAI scenes
# ─────────────────────────────────────────────────────────────────────────────

class TestAerialShotGuardWithCharacterPresence:
    def test_kai_in_aerial_shot_is_removed_from_character_presence(self):
        """Aerial shots cannot have Kai even if character_presence=['KAI']."""
        scene = _scene_dict(
            character_presence=["KAI"],
            anchor_role="primary",
            visual_prompt=(
                "Aerial drone shot looking straight down on a winding mountain path, "
                "birds eye view."
            ),
        )
        result = _enforce_primary_kai_spec([scene])
        assert result[0]["anchor_role"] == "absent"
        assert not _has_kai_markers(result[0]["visual_prompt"])
