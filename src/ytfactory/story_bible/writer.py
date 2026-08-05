"""Write Story Bible to structured markdown files in workspace."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from ytfactory.story_bible.models import StoryBible


def write_story_bible(
    bible: StoryBible,
    project_id: str,
    workspace_dir: str,
    scenes: list[dict] | None = None,
) -> Path:
    """Write the story bible as structured markdown files.

    Layout::

        workspace/jobs/<project-id>/story-bible/
        ├── world.md
        ├── characters/
        │   ├── <slug>.md
        │   └── ...
        ├── locations/
        │   ├── <slug>.md
        │   └── ...
        ├── style/
        │   ├── global.md
        │   ├── negative.md
        │   └── color-progression.md
        └── do-not-change.md
    """
    base = Path(workspace_dir) / project_id / "story-bible"
    base.mkdir(parents=True, exist_ok=True)

    _write_world(base, bible)
    _write_characters(base, bible)
    _write_locations(base, bible)
    _write_style(base, bible)
    _write_do_not_change(base, bible)
    if scenes:
        _write_scene_files(base, bible, scenes)

    logger.info("Story Bible written to {}", base)
    return base


def _write_world(base: Path, bible: StoryBible) -> None:
    w = bible.world
    lines = [
        "---",
        f"era: {w.era}",
        f"cultural_context: {w.cultural_context}",
        f"architectural_style: {w.architectural_style}",
        "---",
        "",
        "# World Bible",
        "",
    ]
    if w.time_period_note:
        lines += [f"**Time period:** {w.time_period_note}", ""]
    if w.recurring_symbols:
        lines += ["## Recurring Symbols", ""]
        for sym in w.recurring_symbols:
            lines.append(f"- {sym}")
        lines.append("")
    if w.key_objects:
        lines += ["## Key Objects", ""]
        for name, desc in w.key_objects.items():
            lines.append(f"- **{name}:** {desc}")
        lines.append("")
    (base / "world.md").write_text("\n".join(lines), encoding="utf-8")


def _write_characters(base: Path, bible: StoryBible) -> None:
    char_dir = base / "characters"
    char_dir.mkdir(exist_ok=True)
    for ch in bible.characters:
        lines = [
            "---",
            f"name: {ch.name}",
            f"role: {ch.role}",
            f"scenes: {ch.scenes}",
            "---",
            "",
            f"# {ch.name}",
            "",
            f"**Appearance:** {ch.appearance}",
            "",
            f"**Clothing:** {ch.clothing}",
            "",
            f"**Role:** {ch.role}",
            "",
        ]
        (char_dir / f"{ch.slug}.md").write_text("\n".join(lines), encoding="utf-8")


def _write_locations(base: Path, bible: StoryBible) -> None:
    loc_dir = base / "locations"
    loc_dir.mkdir(exist_ok=True)
    for loc in bible.locations:
        lines = [
            "---",
            f"name: {loc.name}",
            f"lighting_default: {loc.lighting_default}",
            f"scenes: {loc.scenes}",
            "---",
            "",
            f"# {loc.name}",
            "",
            f"{loc.description}",
            "",
        ]
        if loc.key_details:
            lines += ["## Must include", ""]
            for d in loc.key_details:
                lines.append(f"- {d}")
            lines.append("")
        (loc_dir / f"{loc.slug}.md").write_text("\n".join(lines), encoding="utf-8")


def _write_style(base: Path, bible: StoryBible) -> None:
    style_dir = base / "style"
    style_dir.mkdir(exist_ok=True)

    (style_dir / "global.md").write_text(
        f"# Global Style\n\n"
        f"**Rendering:** {bible.style.rendering_prefix}\n\n"
        f"**Camera:** {bible.style.camera_defaults}\n\n"
        f"**Grain & DOF:** {bible.style.grain_and_dof}\n\n"
        f"**Aspect ratio:** {bible.style.aspect_ratio}\n",
        encoding="utf-8",
    )

    (style_dir / "negative.md").write_text(
        f"# Negative Prompt\n\n"
        f"Append to every image prompt:\n\n"
        f"```\n{bible.style.negative_prompt}\n```\n",
        encoding="utf-8",
    )

    palette_lines = ["# Color Progression\n"]
    for phase, palette in bible.style.color_progression.items():
        palette_lines.append(f"- **{phase}:** {palette}")
    (style_dir / "color-progression.md").write_text(
        "\n".join(palette_lines) + "\n", encoding="utf-8",
    )


def _write_do_not_change(base: Path, bible: StoryBible) -> None:
    if not bible.do_not_change:
        return
    lines = ["# Do Not Change\n", "Locked visual elements across all scenes:\n"]
    for rule in bible.do_not_change:
        lines.append(f"- {rule}")
    (base / "do-not-change.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_scene_files(base: Path, bible: StoryBible, scenes: list[dict]) -> None:
    """Write individual scene files with YAML frontmatter."""
    scene_dir = base / "scenes"
    scene_dir.mkdir(exist_ok=True)
    for scene in scenes:
        idx = scene.get("index", 0)
        sa = scene.get("scene_analysis") or {}
        if isinstance(sa, dict):
            env = sa.get("environment", "")
            chars = sa.get("allowed_characters", []) or []
        else:
            env = getattr(sa, "environment", "")
            chars = getattr(sa, "allowed_characters", []) or []

        sp = scene.get("structured_prompt") or {}
        shot = sp.get("shot_type", "") if isinstance(sp, dict) else getattr(sp, "shot_type", "")
        lens = sp.get("focal_length", "") if isinstance(sp, dict) else getattr(sp, "focal_length", "")
        cam = sp.get("camera_angle", "") if isinstance(sp, dict) else getattr(sp, "camera_angle", "")
        lighting = sp.get("lighting_match", "") if isinstance(sp, dict) else getattr(sp, "lighting_match", "")

        time_of_day = ""
        if isinstance(sa, dict):
            time_of_day = sa.get("story_time", "")

        char_slugs = []
        for c in chars:
            for entry in bible.characters:
                if entry.name.lower() == c.lower():
                    char_slugs.append(entry.slug)
                    break

        lines = [
            "---",
            f"index: {idx}",
            f"title: \"{scene.get('title', '')}\"",
            f"location: {env}",
            f"characters: {char_slugs}",
            f"camera: {shot}",
            f"angle: {cam}",
            f"lens: {lens}",
            f"lighting: {lighting}",
            f"time_of_day: {time_of_day}",
            f"anchor_role: {scene.get('anchor_role', 'absent')}",
            "---",
            "",
            "## Narration",
            "",
            scene.get("narration", ""),
            "",
            "## Image Prompt",
            "",
            scene.get("visual_prompt", ""),
            "",
        ]
        (scene_dir / f"scene-{idx:02d}.md").write_text(
            "\n".join(lines), encoding="utf-8",
        )
