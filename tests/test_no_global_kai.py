"""Regression tests: no global Kai anchor in IMAGE_PROMPTS.md.

Verifies that:
1. No "ANCHOR CHARACTER (KAI)" global header appears in IMAGE_PROMPTS.md.
2. No broken "Appears in scenes ." (empty scene list) output is produced.
3. A scene with character_presence=["KAI"] still gets per-scene Kai spec (scene-driven).
4. A scene without Kai in character_presence does not receive Kai.
5. Generic Story Bible recurring-character support works independently of Kai.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ytfactory.agents.nodes.scene_planner import (
    KAI_COMPRESSED_SPEC,
    _assemble_export_prompt,
    _enforce_primary_kai_spec,
    _has_kai_markers,
    _write_prompts_file,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(anchor_enabled: bool = False) -> MagicMock:
    s = MagicMock()
    s.image_width = 1280
    s.image_height = 720
    s.ANCHOR_CHARACTER_ENABLED = anchor_enabled
    s.HYBRID_STYLE_ENABLED = False
    s.KAI_POSE_DISCIPLINE_ENABLED = False
    return s


def _minimal_scene(
    index: int = 1,
    character_presence: list[str] | None = None,
    anchor_role: str = "absent",
    character_staging: str | None = None,
    environment_prompt: str = "Ancient stone archway, golden afternoon light.",
) -> dict:
    return {
        "index": index,
        "title": f"Scene {index}",
        "narration": f"Narration for scene {index}.",
        "visual_prompt": "Ancient stone archway, golden afternoon light, photorealistic.",
        "duration_seconds": 8,
        "scene_type": "generated_image",
        "visual_metadata": {},
        "anchor_role": anchor_role,
        "character_presence": character_presence if character_presence is not None else [],
        "scene_analysis": {},
        "structured_prompt": {
            "shot_type": "wide",
            "camera_angle": "eye_level",
            "environment_prompt": environment_prompt,
            "character_staging": character_staging or "",
            "lighting_match": "Warm afternoon light.",
            "focal_length": "35mm",
            "color_palette_phase": "neutral",
            "continuity_ref": "",
            "compiled_prompt": "[old compiled prompt]",
        },
    }


def _run_write(tmp_path: Path, scenes: list[dict], *, anchor_enabled: bool = False) -> str:
    """Call _write_prompts_file and return the master markdown content."""
    project_id = "test-no-global-kai"
    images_dir = tmp_path / "workspace" / "jobs" / project_id / "images"
    images_dir.mkdir(parents=True)

    import ytfactory.agents.nodes.scene_planner as sp_module

    original_ws = sp_module.WORKSPACE_DIR
    sp_module.WORKSPACE_DIR = str(tmp_path / "workspace" / "jobs")
    try:
        master = _write_prompts_file(
            project_id, scenes, "documentary", _make_settings(anchor_enabled)
        )
        return master.read_text(encoding="utf-8")
    finally:
        sp_module.WORKSPACE_DIR = original_ws


# ─────────────────────────────────────────────────────────────────────────────
# 1. No global ANCHOR CHARACTER (KAI) header
# ─────────────────────────────────────────────────────────────────────────────

class TestNoGlobalKaiHeader:
    def test_no_anchor_character_kai_header_by_default(self, tmp_path: Path) -> None:
        """IMAGE_PROMPTS.md must never contain 'ANCHOR CHARACTER (KAI)' header."""
        scenes = [_minimal_scene(i) for i in range(1, 6)]
        content = _run_write(tmp_path, scenes)
        assert "ANCHOR CHARACTER (KAI)" not in content

    def test_no_anchor_character_header_even_when_setting_enabled(self, tmp_path: Path) -> None:
        """Even with ANCHOR_CHARACTER_ENABLED=True, the block is no longer emitted.

        The setting remains in SharedSettings for backward compatibility but the
        global-Kai header has been removed from _write_prompts_file.
        """
        scenes = [_minimal_scene(i) for i in range(1, 4)]
        content = _run_write(tmp_path, scenes, anchor_enabled=True)
        assert "ANCHOR CHARACTER (KAI)" not in content

    def test_no_anchor_character_header_with_all_absent_scenes(self, tmp_path: Path) -> None:
        """All-absent scene plan must not produce any Kai global block."""
        scenes = [_minimal_scene(i, anchor_role="absent") for i in range(1, 8)]
        content = _run_write(tmp_path, scenes)
        assert "ANCHOR CHARACTER" not in content

    def test_global_instructions_section_still_present(self, tmp_path: Path) -> None:
        """Removing the Kai header must not affect the 'Global Instructions' section."""
        scenes = [_minimal_scene(i) for i in range(1, 4)]
        content = _run_write(tmp_path, scenes)
        assert "## Global Instructions" in content


# ─────────────────────────────────────────────────────────────────────────────
# 2. No broken "Appears in scenes ." output
# ─────────────────────────────────────────────────────────────────────────────

class TestNoEmptyAppearsInScenes:
    def test_no_appears_in_scenes_string_at_all(self, tmp_path: Path) -> None:
        """'Appears in scenes' must not appear anywhere in IMAGE_PROMPTS.md."""
        scenes = [_minimal_scene(i) for i in range(1, 6)]
        content = _run_write(tmp_path, scenes)
        assert "Appears in scenes" not in content

    def test_no_appears_in_scenes_with_empty_primary_list(self, tmp_path: Path) -> None:
        """When no scenes have anchor_role=primary, no 'Appears in scenes .' is produced."""
        scenes = [_minimal_scene(i, anchor_role="absent") for i in range(1, 10)]
        content = _run_write(tmp_path, scenes)
        assert "Appears in scenes" not in content
        # Specifically guard against the broken empty-list form
        assert "Appears in scenes ." not in content


# ─────────────────────────────────────────────────────────────────────────────
# 3. Scene with character_presence=["KAI"] still gets per-scene Kai spec
# ─────────────────────────────────────────────────────────────────────────────

class TestKaiStillWorksWhenExplicit:
    def test_kai_character_presence_injects_spec_via_enforce(self) -> None:
        """_enforce_primary_kai_spec must inject Kai spec when KAI in character_presence."""
        scene = _minimal_scene(
            index=1,
            character_presence=["KAI"],
            anchor_role="absent",
        )
        # Override visual_prompt with character staging to trigger injection
        scene["visual_prompt"] = "Standing at the edge of the frame, looking outward."
        result = _enforce_primary_kai_spec([scene])
        assert _has_kai_markers(result[0]["visual_prompt"])

    def test_kai_in_character_presence_sets_anchor_role_primary(self) -> None:
        """Explicit KAI in character_presence must set anchor_role=primary."""
        scene = _minimal_scene(
            index=2,
            character_presence=["KAI"],
            anchor_role="absent",
        )
        scene["visual_prompt"] = "Walking slowly through a narrow alley, back to camera."
        result = _enforce_primary_kai_spec([scene])
        assert result[0]["anchor_role"] == "primary"

    def test_kai_character_ref_appears_in_assembled_prompt_when_present(self) -> None:
        """Per-scene KAI: character ref appears in assembled prompt when anchor_role=primary."""
        scene = _minimal_scene(
            index=3,
            character_presence=["KAI"],
            anchor_role="primary",
            character_staging="Lean young man, late 20s, short dark hair, simple dark shirt — walking away.",
        )
        settings = _make_settings()
        result = _assemble_export_prompt(scene, settings, story_bible=None)
        assert "KAI:" in result
        assert KAI_COMPRESSED_SPEC in result


# ─────────────────────────────────────────────────────────────────────────────
# 4. Scene without Kai does not receive Kai
# ─────────────────────────────────────────────────────────────────────────────

class TestNoKaiInjectionWithoutExplicitPresence:
    def test_empty_character_presence_no_kai(self) -> None:
        """Empty character_presence must produce no Kai in enforce step."""
        scene = _minimal_scene(index=1, character_presence=[], anchor_role="absent")
        result = _enforce_primary_kai_spec([scene])
        assert not _has_kai_markers(result[0]["visual_prompt"])

    def test_non_kai_character_presence_no_kai(self) -> None:
        """character_presence=['ANT'] must strip any stray Kai and keep anchor_role absent."""
        scene = _minimal_scene(
            index=2,
            character_presence=["ANT"],
            anchor_role="primary",
        )
        scene["visual_prompt"] = (
            f"{KAI_COMPRESSED_SPEC} — standing on a rock watching. "
            "Himalayan path winds upward."
        )
        result = _enforce_primary_kai_spec([scene])
        assert not _has_kai_markers(result[0]["visual_prompt"])
        assert result[0]["anchor_role"] == "absent"

    def test_assembled_prompt_no_kai_ref_when_absent(self) -> None:
        """Per-scene KAI: reference must NOT appear in assembled prompt when anchor_role=absent."""
        scene = _minimal_scene(
            index=4,
            anchor_role="absent",
            character_presence=[],
            character_staging=None,
        )
        settings = _make_settings()
        result = _assemble_export_prompt(scene, settings, story_bible=None)
        assert "KAI:" not in result

    def test_ant_only_scenes_produce_no_global_kai_header(self, tmp_path: Path) -> None:
        """A full ant/mountain video (all absent) produces no Kai anywhere in prompts file."""
        scenes = [
            _minimal_scene(
                i,
                character_presence=[],
                anchor_role="absent",
                environment_prompt=f"A tiny ant crawls across a massive mountain rock, scene {i}.",
            )
            for i in range(1, 8)
        ]
        content = _run_write(tmp_path, scenes)
        assert "ANCHOR CHARACTER" not in content
        assert "Appears in scenes" not in content
        assert "Kai" not in content


# ─────────────────────────────────────────────────────────────────────────────
# 5. Generic Story Bible recurring-character support still works
# ─────────────────────────────────────────────────────────────────────────────

class TestStoryBibleCharacterSupportIndependentOfKai:
    def test_non_kai_story_bible_character_ref_appears_when_allowed(self) -> None:
        """A Story Bible character (not Kai) appears in character refs when in allowed_characters."""
        from unittest.mock import MagicMock as MM

        char = MM()
        char.name = "SOCRATES"
        char.appearance = "Older man with thick grey beard, worn linen chiton"
        char.clothing = "simple sandals and a plain cloak"

        story_bible = MM()
        story_bible.characters = [char]
        story_bible.locations = []

        scene = _minimal_scene(
            index=1,
            anchor_role="absent",
            character_presence=["SOCRATES"],
            character_staging=(
                "Older man with thick grey beard stands calmly at the edge of the agora."
            ),
        )
        scene["scene_analysis"] = {"allowed_characters": ["SOCRATES"]}

        settings = _make_settings()
        result = _assemble_export_prompt(scene, settings, story_bible=story_bible)
        assert "SOCRATES:" in result
        # Kai must not appear for a Socrates-only scene
        assert "KAI:" not in result

    def test_kai_and_story_character_coexist_when_both_in_presence(self) -> None:
        """When both KAI and SOCRATES are in character_presence, both refs appear."""
        from unittest.mock import MagicMock as MM

        char = MM()
        char.name = "SOCRATES"
        char.appearance = "Older man with thick grey beard, worn linen chiton"
        char.clothing = "simple sandals"

        story_bible = MM()
        story_bible.characters = [char]
        story_bible.locations = []

        scene = _minimal_scene(
            index=2,
            anchor_role="primary",
            character_presence=["KAI", "SOCRATES"],
            character_staging=(
                "Lean young man with short dark hair — smaller in frame, "
                "watching as an older man with a grey beard speaks."
            ),
        )
        scene["scene_analysis"] = {"allowed_characters": ["KAI", "SOCRATES"]}

        settings = _make_settings()
        result = _assemble_export_prompt(scene, settings, story_bible=story_bible)
        assert "KAI:" in result
        assert "SOCRATES:" in result
