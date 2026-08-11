"""Regression tests for image-prompt generation pipeline consistency.

All failure patterns originate from the Atma Theory 26-scene storyboard audit.
Tests are written against generic patterns — nothing hard-codes that specific story.

Failure classes covered:
  A. Environment-only scene cannot contain character description
  B. Character scene contains canonical character definition exactly once
  C. Global illustrated-character rule present in final prompt
  D. Photorealistic-character language is detected
  E. Positive lamp + negative lamp conflict is detected
  F. Positive human + "no human" conflict is detected
  G. Positive animal + "no animal" conflict is detected
  H. Kai is not injected unless scene has non-empty character_staging
  I. Character_staging canonical across scenes (repair not duplication)
  J. Duplicate character definitions are detected
  K. 16:9 requirement present in style block
  L. Environment remains photorealistic while characters remain illustrated
  M. Scene role is preserved (environment_only anchor_role="absent")
"""

from __future__ import annotations

import pytest

from ytfactory.images.prompt_validator import (
    _split_positive_negative,
    check_positive_negative_conflicts,
    validate_prompt_contradictions,
)
from ytfactory.agents.nodes.scene_planner import (
    _CHARACTER_ENV_CONTAMINATION_MARKERS,
    _CHAR_ENV_SEPARATOR,
    _env_has_character_contamination,
    _repair_structured_prompt_dict,
    KAI_COMPRESSED_SPEC,
    _EXPORT_STYLE_HYBRID,
    _EXPORT_STYLE_DOC,
    _EXPORT_GLOBAL_NEGATIVES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scene(
    index: int = 1,
    anchor_role: str = "absent",
    character_staging: str | None = None,
    environment_prompt: str = "A forest at night, damp soil, fallen leaves.",
    shot_type: str = "medium",
    camera_angle: str = "eye_level",
    focal_length: str = "50mm",
    lighting_match: str = "Soft diffused moonlight.",
    color_palette_phase: str = "cool blue-black",
    continuity_ref: str = "",
    compiled_prompt: str = "",
    **extra,
) -> dict:
    """Build a minimal scene dict for testing _assemble_export_prompt."""
    sp = {
        "shot_type": shot_type,
        "camera_angle": camera_angle,
        "environment_prompt": environment_prompt,
        "character_staging": character_staging,
        "lighting_match": lighting_match,
        "focal_length": focal_length,
        "color_palette_phase": color_palette_phase,
        "continuity_ref": continuity_ref,
        "compiled_prompt": compiled_prompt or environment_prompt,
    }
    return {
        "index": index,
        "anchor_role": anchor_role,
        "structured_prompt": sp,
        "scene_analysis": {},
        **extra,
    }


def _make_hybrid_settings():
    """Return a minimal settings-like object with HYBRID_STYLE_ENABLED=True."""
    from unittest.mock import MagicMock
    s = MagicMock()
    s.HYBRID_STYLE_ENABLED = True
    return s


def _make_doc_settings():
    from unittest.mock import MagicMock
    s = MagicMock()
    s.HYBRID_STYLE_ENABLED = False
    return s


def _assemble(scene: dict, hybrid: bool = True) -> str:
    from ytfactory.agents.nodes.scene_planner import _assemble_export_prompt
    settings = _make_hybrid_settings() if hybrid else _make_doc_settings()
    return _assemble_export_prompt(scene, settings, story_bible=None)


# ---------------------------------------------------------------------------
# A. Environment-only scene cannot contain character description
# ---------------------------------------------------------------------------

class TestEnvironmentOnlyNoCharacter:
    def test_absent_scene_no_character_staging_emits_env_only_action(self):
        """Absent anchor_role + no character_staging → 'no character present' action."""
        scene = _make_scene(
            anchor_role="absent",
            character_staging=None,
            environment_prompt="Ancient forest floor, roots and damp soil.",
        )
        prompt = _assemble(scene)
        assert "no character present" in prompt.lower()

    def test_absent_scene_emits_no_kai_block(self):
        """Absent scene never emits KAI: block regardless of style."""
        scene = _make_scene(anchor_role="absent", character_staging=None)
        prompt = _assemble(scene)
        assert "kai:" not in prompt.lower()

    def test_environment_only_contamination_suppresses_no_character_line(self):
        """When environment_prompt has character text, no 'no character present' emitted."""
        contaminated_env = (
            "Lean young man, late 20s, short dark hair, light stubble, "
            "simple dark shirt, plain trousers, calm expression — "
            "Ancient forest floor at night, roots and damp soil."
        )
        scene = _make_scene(
            anchor_role="primary",
            character_staging=None,  # empty — the LLM put char text in env
            environment_prompt=contaminated_env,
        )
        prompt = _assemble(scene)
        # Must NOT say "no character present" when character text exists in env
        assert "no character present" not in prompt.lower()

    def test_validate_contradictions_catches_env_only_plus_character(self):
        """validate_prompt_contradictions flags 'no character present' + character description."""
        bad_prompt = (
            "PRIMARY SUBJECT: Symbolic environment.\n"
            "PRIMARY ACTION: Environment-only/symbolic scene — no character present.\n"
            "ENVIRONMENT: Lean young man stands beside a wooden bed.\n"
            "KAI: Lean young man, late 20s, short dark hair.\n"
            "NEGATIVE: No text."
        )
        errors = validate_prompt_contradictions(bad_prompt, scene_idx=17)
        # Should detect "no character" + character description AND KAI + "no character"
        assert any("no character present" in e.lower() or "kai" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# B. Character scene — KAI block only when character_staging is non-empty
# ---------------------------------------------------------------------------

class TestCharacterSceneKaiBlock:
    def test_primary_with_character_staging_emits_kai(self):
        """Primary scene with non-empty character_staging gets KAI: block."""
        scene = _make_scene(
            anchor_role="primary",
            character_staging=(
                "Lean young man, late 20s, short dark hair, light stubble, "
                "simple dark shirt — seated on a stone, looking outward."
            ),
        )
        prompt = _assemble(scene)
        assert "KAI:" in prompt

    def test_primary_with_empty_character_staging_no_kai(self):
        """Primary scene with empty character_staging must NOT emit KAI: block."""
        scene = _make_scene(
            anchor_role="primary",
            character_staging="",  # LLM returned empty
        )
        prompt = _assemble(scene)
        assert "KAI:" not in prompt

    def test_primary_with_none_character_staging_no_kai(self):
        """Primary scene with None character_staging must NOT emit KAI: block."""
        scene = _make_scene(anchor_role="primary", character_staging=None)
        prompt = _assemble(scene)
        assert "KAI:" not in prompt

    def test_spectator_with_character_staging_emits_kai(self):
        """Spectator scene with character_staging gets KAI: block."""
        scene = _make_scene(
            anchor_role="spectator",
            character_staging="At the edge, a lean young man stands watching.",
        )
        prompt = _assemble(scene)
        assert "KAI:" in prompt

    def test_spectator_empty_character_staging_no_kai(self):
        scene = _make_scene(anchor_role="spectator", character_staging="")
        prompt = _assemble(scene)
        assert "KAI:" not in prompt


# ---------------------------------------------------------------------------
# C. Global illustrated-character rule present in final prompt
# ---------------------------------------------------------------------------

class TestGlobalCharacterStyle:
    def test_hybrid_style_block_present_in_assembled_prompt(self):
        """Every assembled prompt contains the HYBRID style line."""
        scene = _make_scene(anchor_role="absent")
        prompt = _assemble(scene, hybrid=True)
        assert "illustrated storybook characters" in prompt.lower()
        assert "photorealistic" in prompt.lower()

    def test_hybrid_style_not_photorealistic_for_characters(self):
        """The style block explicitly says characters are NOT photorealistic."""
        prompt = _EXPORT_STYLE_HYBRID
        assert "not photorealistic" in prompt.lower()

    def test_doc_style_block_when_hybrid_disabled(self):
        """Documentary mode emits photorealistic style, no illustrated characters."""
        scene = _make_scene(anchor_role="absent")
        prompt = _assemble(scene, hybrid=False)
        assert "photorealistic documentary cinema" in prompt.lower()

    def test_16_9_in_style_block(self):
        """STYLE block includes 16:9 aspect ratio."""
        assert "16:9" in _EXPORT_STYLE_HYBRID
        assert "16:9" in _EXPORT_STYLE_DOC


# ---------------------------------------------------------------------------
# D. Photorealistic character language detection
# ---------------------------------------------------------------------------

class TestPhotorealisticCharacterDetection:
    def test_photorealistic_human_flagged_in_character_context(self):
        bad_prompt = (
            "PRIMARY SUBJECT: A traveler.\n"
            "PRIMARY ACTION: Photorealistic human standing in a forest.\n"
            "NEGATIVE: No text."
        )
        errors = validate_prompt_contradictions(bad_prompt, scene_idx=5)
        assert any("photorealistic" in e.lower() for e in errors)

    def test_photorealistic_character_flagged(self):
        bad_prompt = (
            "PRIMARY ACTION: A photorealistic character walks the path.\n"
            "NEGATIVE: No text."
        )
        errors = validate_prompt_contradictions(bad_prompt, scene_idx=5)
        assert any("photorealistic character" in e.lower() for e in errors)

    def test_photorealistic_environment_not_flagged(self):
        """'photorealistic environment' should not trigger character style error."""
        ok_prompt = (
            "PRIMARY ACTION: Environment-only/symbolic scene — no character present.\n"
            "ENVIRONMENT: A photorealistic environment, forest at dawn.\n"
            "NEGATIVE: No text."
        )
        errors = validate_prompt_contradictions(ok_prompt, scene_idx=5)
        # Should not flag photorealistic environment as character style violation
        assert not any("photorealistic character" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# E. Positive lamp + negative lamp conflict
# ---------------------------------------------------------------------------

class TestLampConflictDetection:
    def test_lamp_in_positive_and_negative_flagged(self):
        prompt = (
            "PRIMARY ACTION: Traveler holds an oil lamp with visible flame.\n"
            "ENVIRONMENT: Forest path, lamp casting warm amber light.\n"
            "NEGATIVE: No text. Do not show: lamp, torch, lantern."
        )
        errors = validate_prompt_contradictions(prompt, scene_idx=8)
        assert any("lamp" in e.lower() for e in errors)

    def test_lamp_in_positive_no_negative_restriction_ok(self):
        prompt = (
            "PRIMARY ACTION: Traveler holds an oil lamp.\n"
            "NEGATIVE: No text, no watermark."
        )
        errors = validate_prompt_contradictions(prompt, scene_idx=8)
        assert not any("lamp" in e.lower() for e in errors)

    def test_check_positive_negative_conflicts_detects_lamp(self):
        """check_positive_negative_conflicts catches lamp conflict."""
        positive = "Traveler holds a lamp with visible flame."
        negative_items = ["lamp", "torch"]
        conflicts = check_positive_negative_conflicts(positive, negative_items, scene_idx=8)
        assert conflicts  # should have at least one conflict

    def test_lamp_in_positive_torch_only_in_negative_not_flagged(self):
        """lamp + torch are different objects — lamp in positive + torch in NEGATIVE is NOT a conflict."""
        prompt = (
            "PRIMARY ACTION: Traveler holds an oil lamp, flame steady.\n"
            "ENVIRONMENT: Forest path lit by the lamp.\n"
            "NEGATIVE: No text. Do not show: torch."
        )
        errors = validate_prompt_contradictions(prompt, scene_idx=3)
        assert not any("lamp_flame" in e.lower() or "lamp" in e.lower() for e in errors), (
            f"lamp+torch cross-synonym should NOT fire LAMP_FLAME_CONFLICT: {errors}"
        )

    def test_gold_light_in_positive_coin_forbidden_not_flagged(self):
        """gold (lighting) in positive + 'do not show: coin' in NEGATIVE is NOT a conflict.
        'gold' as a color/lighting term and 'coin' are different concepts."""
        prompt = (
            "PRIMARY ACTION: Sage stands in warm golden morning light.\n"
            "ENVIRONMENT: Forest edge at dawn, golden rays through the canopy.\n"
            "NEGATIVE: No text. Do not show: coin."
        )
        errors = validate_prompt_contradictions(prompt, scene_idx=18)
        assert not any("coin_gold" in e.lower() or "coin" in e.lower() for e in errors), (
            f"gold(light)+coin cross-synonym should NOT fire COIN_GOLD_CONFLICT: {errors}"
        )

    def test_forbidden_objects_lamp_filtered_from_negative_if_in_positive(self):
        """_assemble_export_prompt drops forbidden_objects items that appear in positive."""
        scene = _make_scene(
            anchor_role="absent",
            environment_prompt="An oil lamp burns on a stone surface in the forest.",
            scene_analysis={"forbidden_objects": ["lamp", "torch"]},
        )
        prompt = _assemble(scene)
        # The NEGATIVE section should NOT contain "lamp" since lamp is in the environment
        neg_section = prompt.split("NEGATIVE:")[-1] if "NEGATIVE:" in prompt else ""
        # "lamp" should have been filtered out of forbidden list
        # (it appears in positive environment)
        assert "do not show: lamp" not in neg_section.lower()


# ---------------------------------------------------------------------------
# F. Positive human + "no human" conflict
# ---------------------------------------------------------------------------

class TestHumanConflictDetection:
    def test_human_in_positive_and_no_human_in_negative_flagged(self):
        prompt = (
            "PRIMARY ACTION: A traveler walks along the path.\n"
            "ENVIRONMENT: Forest.\n"
            "NEGATIVE: No text. No human figure. No visible character."
        )
        errors = validate_prompt_contradictions(prompt, scene_idx=5)
        assert any("human" in e.lower() or "traveler" in e.lower() for e in errors)

    def test_figure_in_positive_and_no_character_in_negative_flagged(self):
        prompt = (
            "PRIMARY ACTION: A lone figure sits by the road.\n"
            "NEGATIVE: No character. No text."
        )
        errors = validate_prompt_contradictions(prompt, scene_idx=6)
        assert any("human" in e.lower() or "character" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# G. Positive animal + "no animal" conflict
# ---------------------------------------------------------------------------

class TestAnimalConflictDetection:
    def test_eagle_in_positive_no_animal_in_negative_flagged(self):
        prompt = (
            "PRIMARY ACTION: A golden eagle soars above the trees.\n"
            "NEGATIVE: No text. No animal, no bird, no eagle."
        )
        errors = validate_prompt_contradictions(prompt, scene_idx=3)
        assert any("animal" in e.lower() or "eagle" in e.lower() for e in errors)

    def test_animal_in_positive_no_conflict_when_negative_allows(self):
        prompt = (
            "PRIMARY ACTION: A golden eagle soars above the trees.\n"
            "NEGATIVE: No text, no watermark."
        )
        errors = validate_prompt_contradictions(prompt, scene_idx=3)
        assert not any("animal" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# H. Kai not injected unless scene has non-empty character_staging
# ---------------------------------------------------------------------------

class TestKaiInjectionGuard:
    def test_kai_absent_role_no_kai_spec_in_prompt(self):
        scene = _make_scene(anchor_role="absent", character_staging=None)
        prompt = _assemble(scene)
        assert "lean young man" not in prompt.lower() or "kai" not in prompt.lower()
        assert "KAI:" not in prompt

    def test_primary_empty_staging_no_kai_block(self):
        """Scene 17 pattern: primary + empty character_staging → no KAI: block."""
        scene = _make_scene(anchor_role="primary", character_staging="")
        prompt = _assemble(scene)
        assert "KAI:" not in prompt

    def test_primary_nonempty_staging_has_kai_block(self):
        scene = _make_scene(
            anchor_role="primary",
            character_staging="Lean young man — seated quietly, watching distant horizon.",
        )
        prompt = _assemble(scene)
        assert "KAI:" in prompt


# ---------------------------------------------------------------------------
# I. _repair_structured_prompt_dict — canonical character recovery
# ---------------------------------------------------------------------------

class TestRepairStructuredPromptDict:
    def test_character_in_env_prompt_extracted_to_staging(self):
        """Scene 17 pattern: character text in env_prompt → moved to character_staging."""
        sp_dict = {
            "shot_type": "medium",
            "camera_angle": "eye_level",
            "environment_prompt": (
                "Lean young man, late 20s, short dark hair, light stubble, "
                "simple dark shirt, plain trousers, calm expression — "
                "Forest floor at night, damp soil, scattered leaves."
            ),
            "character_staging": "",
            "lighting_match": "Soft moonlight.",
            "focal_length": "50mm",
            "color_palette_phase": "cool blue-black",
            "continuity_ref": "",
            "compiled_prompt": "Forest floor at night.",
        }
        repaired, errors = _repair_structured_prompt_dict(sp_dict, "primary", scene_idx=17)
        assert errors  # should have logged errors
        # Character staging should now be populated
        assert "lean young man" in (repaired.get("character_staging") or "").lower()
        # Environment should be clean
        assert "lean young man" not in (repaired.get("environment_prompt") or "").lower()

    def test_no_contamination_leaves_dict_unchanged(self):
        sp_dict = {
            "shot_type": "medium",
            "camera_angle": "eye_level",
            "environment_prompt": "Forest floor at night, damp soil, scattered leaves.",
            "character_staging": "Lean young man — seated on a root.",
            "lighting_match": "Soft moonlight.",
            "focal_length": "50mm",
            "color_palette_phase": "cool blue-black",
            "continuity_ref": "",
            "compiled_prompt": "Forest floor.",
        }
        repaired, errors = _repair_structured_prompt_dict(sp_dict, "primary", scene_idx=5)
        # No repair errors for a clean dict
        assert not any("REPAIRED" in e for e in errors)
        assert repaired["character_staging"] == "Lean young man — seated on a root."

    def test_hybrid_prefix_in_env_prompt_stripped(self):
        """HYBRID CINEMATIC STYLE prefix in environment_prompt is stripped."""
        sp_dict = {
            "shot_type": "medium",
            "camera_angle": "eye_level",
            "environment_prompt": (
                "HYBRID CINEMATIC STYLE: 100% photorealistic environment. "
                "Forest at night."
            ),
            "character_staging": "",
            "lighting_match": "Moonlight.",
            "focal_length": "50mm",
            "color_palette_phase": "",
            "continuity_ref": "",
            "compiled_prompt": "Forest.",
        }
        repaired, errors = _repair_structured_prompt_dict(sp_dict, "absent", scene_idx=3)
        env = repaired.get("environment_prompt") or ""
        assert not env.upper().startswith("HYBRID CINEMATIC STYLE")
        assert "forest at night" in env.lower()

    def test_duplicate_hybrid_in_compiled_logged_not_auto_fixed(self):
        """Duplicate HYBRID headers in compiled_prompt are logged but not auto-removed."""
        hybrid_header = "HYBRID CINEMATIC STYLE: 100% photorealistic environment."
        sp_dict = {
            "shot_type": "medium",
            "camera_angle": "eye_level",
            "environment_prompt": "Forest.",
            "character_staging": "Young man standing.",
            "lighting_match": "Moonlight.",
            "focal_length": "50mm",
            "color_palette_phase": "",
            "continuity_ref": "",
            "compiled_prompt": f"{hybrid_header} {hybrid_header} Forest.",
        }
        repaired, errors = _repair_structured_prompt_dict(sp_dict, "primary", scene_idx=20)
        assert any("duplicate" in e.lower() or "hybrid" in e.lower() for e in errors)
        # compiled_prompt should NOT be auto-modified (only logged)
        assert repaired["compiled_prompt"].count("HYBRID CINEMATIC STYLE") == 2


# ---------------------------------------------------------------------------
# J. Duplicate character definitions in same scene detected
# ---------------------------------------------------------------------------

class TestDuplicateCharacterDetection:
    def test_validate_contradictions_kai_block_plus_no_char(self):
        """KAI: block + 'no character present' = contradiction (check B)."""
        prompt = (
            "PRIMARY SUBJECT: Lean young man.\n"
            "PRIMARY ACTION: Environment-only/symbolic scene — no character present.\n"
            "KAI: Lean young man, late 20s, short dark hair, light stubble.\n"
            "NEGATIVE: No text."
        )
        errors = validate_prompt_contradictions(prompt, scene_idx=17)
        # KAI block + "no character present" is a contradiction
        assert any("kai" in e.lower() for e in errors)

    def test_single_character_spec_no_contradiction(self):
        prompt = (
            "PRIMARY SUBJECT: Lean young man.\n"
            "PRIMARY ACTION: Seated quietly on a stone, looking outward.\n"
            "KAI: Lean young man, late 20s, short dark hair, light stubble.\n"
            "NEGATIVE: No text."
        )
        errors = validate_prompt_contradictions(prompt, scene_idx=5)
        # Should not flag a clean character scene
        assert not any("kai" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# K. 16:9 requirement present
# ---------------------------------------------------------------------------

class TestAspectRatio:
    def test_16_9_in_hybrid_style_export(self):
        assert "16:9" in _EXPORT_STYLE_HYBRID

    def test_16_9_in_doc_style_export(self):
        assert "16:9" in _EXPORT_STYLE_DOC

    def test_assembled_prompt_contains_16_9(self):
        scene = _make_scene(anchor_role="absent")
        prompt = _assemble(scene, hybrid=True)
        assert "16:9" in prompt


# ---------------------------------------------------------------------------
# L. Environment photorealistic, characters illustrated
# ---------------------------------------------------------------------------

class TestHybridStyleSeparation:
    def test_hybrid_export_style_mentions_photorealistic_environment(self):
        assert "photorealistic environment" in _EXPORT_STYLE_HYBRID.lower()

    def test_hybrid_export_style_mentions_illustrated_characters(self):
        assert "illustrated storybook characters" in _EXPORT_STYLE_HYBRID.lower()

    def test_hybrid_export_style_says_not_photorealistic_for_chars(self):
        assert "not photorealistic" in _EXPORT_STYLE_HYBRID.lower()


# ---------------------------------------------------------------------------
# M. Scene role preserved — environment_only invariant with anchor_role=absent
# ---------------------------------------------------------------------------

class TestSceneRolePreservation:
    def test_absent_scene_no_character_action(self):
        """anchor_role=absent + no staging → environment-only action declared."""
        scene = _make_scene(
            anchor_role="absent",
            character_staging=None,
            environment_prompt="A secluded clearing at dawn, mist over the creek.",
        )
        prompt = _assemble(scene)
        assert "no character present" in prompt.lower()

    def test_absent_scene_contaminated_env_no_contradictory_action(self):
        """When environment has character text (bug state), no 'no character' contradiction."""
        scene = _make_scene(
            anchor_role="absent",
            character_staging=None,
            environment_prompt=(
                "Lean young man, light stubble, simple dark shirt — "
                "A secluded clearing at dawn, mist over the creek."
            ),
        )
        prompt = _assemble(scene)
        # Should NOT say "no character present" when character text exists
        assert "no character present" not in prompt.lower()


# ---------------------------------------------------------------------------
# Additional: _env_has_character_contamination helper
# ---------------------------------------------------------------------------

class TestEnvContaminationDetector:
    def test_clean_environment_not_contaminated(self):
        env = "Ancient forest floor, damp soil, roots, fallen leaves at night."
        assert not _env_has_character_contamination(env)

    def test_kai_markers_at_start_detected(self):
        env = (
            "Lean young man, late 20s, short dark hair, light stubble, "
            "simple dark shirt, plain trousers — Forest floor."
        )
        assert _env_has_character_contamination(env)

    def test_illustrated_style_text_detected(self):
        env = "Illustrated in hand-painted storybook style — Ancient forest at dawn."
        assert _env_has_character_contamination(env)

    def test_markers_after_200_chars_not_triggered(self):
        """Contamination check only covers first 200 chars."""
        long_clean_env = "A" * 250 + " lean young man, short dark hair"
        assert not _env_has_character_contamination(long_clean_env)


# ---------------------------------------------------------------------------
# validate_prompt_contradictions — utility
# ---------------------------------------------------------------------------

class TestValidatePromptContradictions:
    def test_empty_prompt_returns_no_errors(self):
        assert validate_prompt_contradictions("", scene_idx=1) == []

    def test_clean_env_only_prompt_no_errors(self):
        prompt = (
            "PRIMARY SUBJECT: Forest floor.\n"
            "PRIMARY ACTION: Environment-only/symbolic scene — no character present.\n"
            "ENVIRONMENT: Dense forest at night, damp soil and roots.\n"
            "STYLE: Hybrid cinematic — photorealistic environment; illustrated storybook "
            "characters with ink outlines and cel shading (NOT photorealistic). 16:9 aspect ratio.\n"
            "NEGATIVE: No text, no watermark, no subtitle, no logo."
        )
        assert validate_prompt_contradictions(prompt, scene_idx=1) == []

    def test_clean_character_scene_no_errors(self):
        prompt = (
            "PRIMARY SUBJECT: Lean young man.\n"
            "PRIMARY ACTION: Standing quietly at the forest edge, looking outward.\n"
            "KAI: Lean young man, late 20s, short dark hair, light stubble, simple dark shirt, plain trousers.\n"
            "STYLE: Hybrid cinematic — photorealistic environment; illustrated storybook "
            "characters with ink outlines and cel shading (NOT photorealistic). 16:9 aspect ratio.\n"
            "NEGATIVE: No text, no watermark."
        )
        assert validate_prompt_contradictions(prompt, scene_idx=5) == []


# ---------------------------------------------------------------------------
# check_positive_negative_conflicts — utility
# ---------------------------------------------------------------------------

class TestCheckPositiveNegativeConflicts:
    def test_detects_lamp_conflict(self):
        conflicts = check_positive_negative_conflicts(
            "A lamp burns beside the coins.", ["lamp", "torch"], scene_idx=8
        )
        assert conflicts

    def test_no_conflict_when_positive_clear(self):
        conflicts = check_positive_negative_conflicts(
            "Forest floor, roots, damp soil.", ["lamp", "torch"], scene_idx=8
        )
        assert not conflicts

    def test_short_words_ignored(self):
        """Words ≤3 chars don't trigger a conflict."""
        conflicts = check_positive_negative_conflicts(
            "A dim glow.", ["dim"], scene_idx=1
        )
        assert not conflicts  # "dim" has 3 chars, excluded by >3 filter

    def test_empty_negative_no_conflicts(self):
        assert check_positive_negative_conflicts("A lamp.", [], scene_idx=1) == []

    def test_empty_positive_no_conflicts(self):
        assert check_positive_negative_conflicts("", ["lamp"], scene_idx=1) == []
