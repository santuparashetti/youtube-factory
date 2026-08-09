"""Tests for IMAGE_PROMPTS.md prompt assembly, split-file generation, and semantic ordering.

Verifies that _write_prompts_file produces:
  - IMAGE_PROMPTS.md   — full file (all prompts)
  - IMAGE_PROMPTS-part-NN.md — split files, max MAX_PROMPTS_PER_SPLIT_FILE each,
    every split self-contained with header + its chunk of prompts.

Also verifies _assemble_export_prompt:
  - Scene-specific content (PRIMARY SUBJECT, PRIMARY ACTION, ENVIRONMENT) appears
    before global content (STYLE, LIGHTING, NEGATIVE).
  - No LLM calls — pure deterministic assembly from structured scene fields.
  - Character references include only characters relevant to the scene.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ytfactory.agents.nodes.scene_planner import (
    MAX_PROMPTS_PER_SPLIT_FILE,
    _assemble_export_prompt,
    _validate_prompt_split,
    _write_prompts_file,
    _write_split_prompt_files,
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_settings(anchor_enabled: bool = False) -> MagicMock:
    s = MagicMock()
    s.image_width = 1280
    s.image_height = 720
    s.ANCHOR_CHARACTER_ENABLED = anchor_enabled
    return s


def _make_scenes(n: int) -> list[dict]:
    return [
        {
            "index": i,
            "title": f"Scene {i}",
            "narration": f"Narration for scene {i}.",
            "visual_prompt": f"Photorealistic cinematic shot scene {i}, no text, no watermark.",
            "duration_seconds": 10,
            "scene_type": "generated_image",
            "visual_metadata": {},
            "anchor_role": "absent",
            "scene_analysis": {},
            "structured_prompt": {
                "shot_type": "medium",
                "camera_angle": "eye_level",
                "environment_prompt": f"Ancient forest at dusk, scene {i}. Mossy stones.",
                "character_staging": f"Lone figure standing at edge of clearing, scene {i}.",
                "lighting_match": "Warm golden hour light from left.",
                "focal_length": "50mm standard",
                "color_palette_phase": f"build phase — warm amber tones, scene {i}",
                "continuity_ref": "Distinct from prior scene." if i > 1 else "",
                "compiled_prompt": f"[OLD FORMAT] Scene {i} compiled.",
            },
        }
        for i in range(1, n + 1)
    ]


def _count_scene_headers(text: str) -> int:
    return len(re.findall(r"^## Scene \d+", text, re.MULTILINE))


def _extract_scene_indices(text: str) -> list[int]:
    return [int(m) for m in re.findall(r"^## Scene (\d+)", text, re.MULTILINE)]


def _run(tmp_path: Path, n: int, *, anchor: bool = False) -> tuple[Path, list[Path]]:
    """Run _write_prompts_file and return (master_path, sorted part_paths)."""
    project_id = "test-project"
    images_dir = tmp_path / "workspace" / "jobs" / project_id / "images"
    images_dir.mkdir(parents=True)

    import ytfactory.agents.nodes.scene_planner as sp_module

    original_ws = sp_module.WORKSPACE_DIR
    sp_module.WORKSPACE_DIR = str(tmp_path / "workspace" / "jobs")

    try:
        master = _write_prompts_file(
            project_id, _make_scenes(n), "documentary", _make_settings(anchor)
        )
    finally:
        sp_module.WORKSPACE_DIR = original_ws

    part_paths = sorted(images_dir.glob("IMAGE_PROMPTS-part-*.md"))
    return master, part_paths


# ── Part count parameterisation ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "n_scenes, expected_parts",
    [
        (1, 1),
        (8, 1),
        (9, 1),
        (10, 2),   # 9 + 1
        (18, 2),   # 9 + 9
        (19, 3),   # 9 + 9 + 1
        (25, 3),   # 9 + 9 + 7
        (100, 12),
    ],
)
def test_split_file_count(tmp_path: Path, n_scenes: int, expected_parts: int) -> None:
    _master, parts = _run(tmp_path, n_scenes)
    assert len(parts) == expected_parts, (
        f"{n_scenes} scenes → expected {expected_parts} parts, got {len(parts)}"
    )


# ── Full file is untouched ─────────────────────────────────────────────────────


def test_full_file_exists_and_contains_all_scenes(tmp_path: Path) -> None:
    master, _parts = _run(tmp_path, 25)
    assert master.exists()
    assert _count_scene_headers(master.read_text()) == 25


def test_full_file_scene_indices_sequential(tmp_path: Path) -> None:
    master, _parts = _run(tmp_path, 15)
    assert _extract_scene_indices(master.read_text()) == list(range(1, 16))


# ── Split invariants ───────────────────────────────────────────────────────────


def test_split_total_equals_master(tmp_path: Path) -> None:
    n = 25
    master, parts = _run(tmp_path, n)
    master_count = _count_scene_headers(master.read_text())
    split_total = sum(_count_scene_headers(p.read_text()) for p in parts)
    assert split_total == master_count == n


def test_no_missing_no_duplicate_scenes(tmp_path: Path) -> None:
    n = 25
    master, parts = _run(tmp_path, n)
    master_indices = _extract_scene_indices(master.read_text())
    split_indices: list[int] = []
    for p in parts:
        split_indices.extend(_extract_scene_indices(p.read_text()))
    assert split_indices == master_indices


def test_original_order_preserved(tmp_path: Path) -> None:
    n = 20
    master, parts = _run(tmp_path, n)
    master_indices = _extract_scene_indices(master.read_text())
    split_indices: list[int] = []
    for p in parts:
        split_indices.extend(_extract_scene_indices(p.read_text()))
    assert split_indices == master_indices


def test_original_numbering_preserved(tmp_path: Path) -> None:
    """Split files must use the scene's original index, not restart at 1."""
    n = 10  # two parts: 1-9 and 10
    _master, parts = _run(tmp_path, n)
    assert len(parts) == 2
    part2_indices = _extract_scene_indices(parts[1].read_text())
    assert part2_indices == [10]


def test_every_split_has_at_most_max_prompts(tmp_path: Path) -> None:
    n = 25
    _master, parts = _run(tmp_path, n)
    for p in parts:
        count = _count_scene_headers(p.read_text())
        assert count <= MAX_PROMPTS_PER_SPLIT_FILE, (
            f"{p.name} has {count} prompts, max is {MAX_PROMPTS_PER_SPLIT_FILE}"
        )


# ── Header/footer presence ────────────────────────────────────────────────────


def test_each_split_contains_global_instructions_header(tmp_path: Path) -> None:
    _master, parts = _run(tmp_path, 20)
    for p in parts:
        content = p.read_text()
        assert "## Global Instructions" in content, (
            f"{p.name} is missing '## Global Instructions'"
        )


def test_each_split_contains_how_to_use(tmp_path: Path) -> None:
    _master, parts = _run(tmp_path, 20)
    for p in parts:
        assert "## How to Use" in p.read_text(), f"{p.name} missing '## How to Use'"


def test_each_split_contains_title_header(tmp_path: Path) -> None:
    _master, parts = _run(tmp_path, 10)
    for p in parts:
        assert "# Image Prompts" in p.read_text(), f"{p.name} missing title header"


# ── Prompt content integrity ───────────────────────────────────────────────────


def test_prompt_text_unchanged_in_splits(tmp_path: Path) -> None:
    """Each scene block in the split must match the master verbatim."""
    n = 12
    master, parts = _run(tmp_path, n)
    master_text = master.read_text()

    for part in parts:
        part_indices = _extract_scene_indices(part.read_text())
        part_text = part.read_text()
        for idx in part_indices:
            # Find the scene block in master
            pattern = rf"(## Scene {idx} —.*?)(?=\n## Scene |\Z)"
            m_block = re.search(pattern, master_text, re.DOTALL)
            p_block = re.search(pattern, part_text, re.DOTALL)
            assert m_block and p_block, f"Scene {idx} block not found"
            assert m_block.group(1) == p_block.group(1), (
                f"Scene {idx} content differs between master and {part.name}"
            )


# ── Stale file cleanup ────────────────────────────────────────────────────────


def test_stale_split_files_removed_on_rerun(tmp_path: Path) -> None:
    """Old run produced 4 parts; new run with fewer scenes should remove extras."""
    project_id = "stale-test"
    images_dir = tmp_path / "workspace" / "jobs" / project_id / "images"
    images_dir.mkdir(parents=True)

    import ytfactory.agents.nodes.scene_planner as sp_module

    original_ws = sp_module.WORKSPACE_DIR
    sp_module.WORKSPACE_DIR = str(tmp_path / "workspace" / "jobs")

    try:
        # First run: 28 scenes → 4 parts
        _write_prompts_file(
            project_id, _make_scenes(28), "documentary", _make_settings()
        )
        parts_after_first = sorted(images_dir.glob("IMAGE_PROMPTS-part-*.md"))
        assert len(parts_after_first) == 4

        # Second run: 10 scenes → 2 parts
        _write_prompts_file(
            project_id, _make_scenes(10), "documentary", _make_settings()
        )
        parts_after_second = sorted(images_dir.glob("IMAGE_PROMPTS-part-*.md"))
        assert len(parts_after_second) == 2

        # Part 03 and 04 must be gone
        stale = [p for p in parts_after_first if "part-03" in p.name or "part-04" in p.name]
        for p in stale:
            assert not p.exists(), f"Stale file was not removed: {p.name}"
    finally:
        sp_module.WORKSPACE_DIR = original_ws


# ── _validate_prompt_split ────────────────────────────────────────────────────


def test_validate_passes_for_valid_output(tmp_path: Path) -> None:
    master, parts = _run(tmp_path, 25)
    images_dir = master.parent
    errors = _validate_prompt_split(master, images_dir)
    assert errors == [], f"Validation failed: {errors}"


@pytest.mark.parametrize("n", [1, 8, 9, 10, 18, 19, 25, 100])
def test_validate_passes_for_all_boundary_counts(tmp_path: Path, n: int) -> None:
    master, _parts = _run(tmp_path, n)
    errors = _validate_prompt_split(master, master.parent)
    assert errors == [], f"n={n}: {errors}"


def test_validate_detects_missing_scene(tmp_path: Path) -> None:
    master, parts = _run(tmp_path, 10)
    images_dir = master.parent

    # Corrupt part-02 by removing scene 10
    p2 = parts[1]
    content = p2.read_text()
    corrupted = re.sub(r"\n## Scene 10.*", "", content, flags=re.DOTALL)
    p2.write_text(corrupted)

    errors = _validate_prompt_split(master, images_dir)
    assert any("Split total" in e or "Missing" in e for e in errors), errors


def test_validate_detects_missing_header(tmp_path: Path) -> None:
    master, parts = _run(tmp_path, 10)

    # Remove the Global Instructions header from part-01
    p1 = parts[0]
    content = p1.read_text().replace("## Global Instructions", "## REMOVED")
    p1.write_text(content)

    errors = _validate_prompt_split(master, master.parent)
    assert any("Global Instructions" in e for e in errors), errors


# ── _write_split_prompt_files directly ────────────────────────────────────────


def test_write_split_no_empty_parts(tmp_path: Path) -> None:
    """Every written part file must contain at least one scene block."""
    header = ["# Title", "", "## Global Instructions", ""]
    scene_groups = [[f"## Scene {i}", "", "---", ""] for i in range(1, 20)]

    _write_split_prompt_files(tmp_path, header, scene_groups)

    for part in sorted(tmp_path.glob("IMAGE_PROMPTS-part-*.md")):
        assert _count_scene_headers(part.read_text()) > 0, (
            f"{part.name} is empty"
        )


def test_constant_max_prompts_is_nine() -> None:
    assert MAX_PROMPTS_PER_SPLIT_FILE == 9


# ── _assemble_export_prompt: semantic ordering ────────────────────────────────


def _scene_with_structured(
    idx: int,
    character_staging: str | None = "Lone figure at forest edge, standing still, arms at sides.",
    environment_prompt: str = "Dense ancient forest at golden hour. Moss-covered stones. Mist rising.",
    shot_type: str = "medium",
    camera_angle: str = "eye_level",
    focal_length: str = "85mm portrait",
    lighting_match: str = "Warm directional light from upper right.",
    color_palette_phase: str = "build phase — warm amber.",
    continuity_ref: str = "Different location from previous scene.",
    anchor_role: str = "absent",
    scene_analysis: dict | None = None,
) -> dict:
    return {
        "index": idx,
        "narration": f"Narration {idx}.",
        "visual_prompt": "old format prompt",
        "anchor_role": anchor_role,
        "scene_analysis": scene_analysis or {},
        "structured_prompt": {
            "shot_type": shot_type,
            "camera_angle": camera_angle,
            "environment_prompt": environment_prompt,
            "character_staging": character_staging,
            "lighting_match": lighting_match,
            "focal_length": focal_length,
            "color_palette_phase": color_palette_phase,
            "continuity_ref": continuity_ref,
            "compiled_prompt": "old compiled prompt",
        },
    }


def _assemble(scene: dict, hybrid: bool = True) -> str:
    settings = MagicMock()
    settings.HYBRID_STYLE_ENABLED = hybrid
    return _assemble_export_prompt(scene, settings)


def test_primary_subject_appears_first() -> None:
    scene = _scene_with_structured(1, character_staging="Mother Eagle carrying Young Eagle on high branch.")
    result = _assemble(scene)
    lines = result.splitlines()
    assert lines[0].startswith("PRIMARY SUBJECT:"), f"First line: {lines[0]!r}"


def test_primary_action_appears_before_style() -> None:
    scene = _scene_with_structured(1, character_staging="Eagle spreading wings wide against open sky.")
    result = _assemble(scene)
    lines = result.splitlines()
    action_pos = next((i for i, ln in enumerate(lines) if ln.startswith("PRIMARY ACTION:")), -1)
    style_pos = next((i for i, ln in enumerate(lines) if ln.startswith("STYLE:")), -1)
    assert action_pos != -1, "PRIMARY ACTION not found"
    assert style_pos != -1, "STYLE not found"
    assert action_pos < style_pos, (
        f"PRIMARY ACTION (line {action_pos}) should precede STYLE (line {style_pos})"
    )


def test_environment_appears_before_style() -> None:
    scene = _scene_with_structured(1)
    result = _assemble(scene)
    lines = result.splitlines()
    env_pos = next((i for i, ln in enumerate(lines) if ln.startswith("ENVIRONMENT:")), -1)
    style_pos = next((i for i, ln in enumerate(lines) if ln.startswith("STYLE:")), -1)
    assert env_pos < style_pos, "ENVIRONMENT should precede STYLE"


def test_negative_appears_last() -> None:
    scene = _scene_with_structured(1)
    result = _assemble(scene)
    lines = [ln for ln in result.splitlines() if ln.strip()]
    assert lines[-1].startswith("NEGATIVE:"), f"Last line: {lines[-1]!r}"


def test_no_old_compiled_prompt_leaks_through() -> None:
    """The old LLM-generated compiled_prompt must not appear in the output."""
    scene = _scene_with_structured(1)
    result = _assemble(scene)
    assert "old compiled prompt" not in result
    assert "[OLD FORMAT]" not in result


def test_no_character_when_absent_role() -> None:
    """KAI reference must not appear when anchor_role is absent."""
    scene = _scene_with_structured(1, anchor_role="absent")
    result = _assemble(scene)
    assert "KAI:" not in result


def test_kai_reference_when_primary_role() -> None:
    """KAI: line must appear when anchor_role is primary."""
    scene = _scene_with_structured(1, anchor_role="primary")
    result = _assemble(scene)
    assert "KAI:" in result


def test_environment_only_scene_no_primary_action_character() -> None:
    """Atmospheric scene (no character_staging) falls back to environment description."""
    scene = _scene_with_structured(1, character_staging=None)
    result = _assemble(scene)
    assert "Environment-only" in result
    assert "PRIMARY ACTION: Environment-only" in result


def test_continuity_omitted_when_empty() -> None:
    scene = _scene_with_structured(1, continuity_ref="")
    result = _assemble(scene)
    assert "CONTINUITY:" not in result


def test_continuity_present_when_set() -> None:
    scene = _scene_with_structured(1, continuity_ref="Same forest as scene 3, different angle.")
    result = _assemble(scene)
    assert "CONTINUITY:" in result


def test_scene_specific_content_precedes_global_content() -> None:
    """The first 5 lines must all be scene-specific (PRIMARY/ENVIRONMENT/COMPOSITION/CAMERA)."""
    scene = _scene_with_structured(1)
    result = _assemble(scene)
    lines = [ln for ln in result.splitlines() if ln.strip()]
    scene_specific_prefixes = ("PRIMARY SUBJECT:", "PRIMARY ACTION:", "ENVIRONMENT:", "COMPOSITION:", "CAMERA:")
    for line in lines[:5]:
        assert any(line.startswith(p) for p in scene_specific_prefixes), (
            f"Non-scene-specific line in first 5: {line!r}"
        )


def test_assembly_uses_structured_prompt_fields_not_compiled_prompt() -> None:
    """The compiled_prompt field value (old format) must not appear; structured fields must."""
    scene = _scene_with_structured(
        1,
        character_staging="Young adult at cottage doorway, looking toward vast sky.",
        environment_prompt="Rustic stone cottage at dawn. Open doorway. Vast open sky beyond.",
    )
    result = _assemble(scene)
    assert "old compiled prompt" not in result
    assert "Young adult at cottage doorway" in result or "cottage doorway" in result
    assert "vast sky" in result.lower() or "Vast open sky" in result


def test_fallback_to_visual_prompt_when_no_structured_prompt() -> None:
    """Scenes without structured_prompt fall back to visual_prompt."""
    scene = {
        "index": 1,
        "narration": "Narration.",
        "visual_prompt": "Raw visual prompt fallback text. Photorealistic.",
        "anchor_role": "absent",
        "scene_analysis": {},
    }
    settings = MagicMock()
    settings.HYBRID_STYLE_ENABLED = True
    result = _assemble_export_prompt(scene, settings)
    assert "Raw visual prompt fallback text" in result


def test_scene_specific_negative_constraints_included() -> None:
    """Scene-specific forbidden_objects must appear in the NEGATIVE section."""
    scene = _scene_with_structured(
        1,
        scene_analysis={"forbidden_objects": ["sword", "shield", "crown"]},
    )
    result = _assemble(scene)
    neg_line = next((ln for ln in result.splitlines() if ln.startswith("NEGATIVE:")), "")
    assert "sword" in neg_line
    assert "shield" in neg_line
