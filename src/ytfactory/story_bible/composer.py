"""Compose per-scene prompt context from the Story Bible.

Instead of re-typing character/location descriptions per scene,
this module pulls locked descriptions from the bible and builds
a context block that `_build_structured_prompt()` injects.
"""

from __future__ import annotations

from ytfactory.story_bible.models import StoryBible


def compose_scene_context(
    bible: StoryBible,
    scene_characters: list[str],
    scene_environment: str,
    arc_phase: str,
) -> str:
    """Build a prompt context block for one scene from the story bible.

    Returns a multi-line string ready to inject into the V2 system prompt.
    Empty string if the bible has no relevant entries for this scene.
    """
    blocks: list[str] = []

    # ── World rules ──────────────────────────────────────────────────────
    if bible.world.era or bible.world.cultural_context:
        world_block = "STORY BIBLE — WORLD:\n"
        if bible.world.era:
            world_block += f"  Era: {bible.world.era}\n"
        if bible.world.cultural_context:
            world_block += f"  Culture: {bible.world.cultural_context}\n"
        if bible.world.architectural_style:
            world_block += f"  Architecture: {bible.world.architectural_style}\n"
        if bible.world.time_period_note:
            world_block += f"  Constraint: {bible.world.time_period_note}\n"
        blocks.append(world_block)

    # ── Recurring symbols ──────────────────────────────────────────────
    if bible.world.recurring_symbols:
        sym_lines = [f"  • {s}" for s in bible.world.recurring_symbols]
        blocks.append(
            "RECURRING SYMBOLS (include when narratively present — keep visually consistent):\n"
            + "\n".join(sym_lines)
        )

    # ── Key objects (locked descriptions) ────────────────────────────────
    if bible.world.key_objects:
        obj_lines = [f"  {name}: {desc}" for name, desc in bible.world.key_objects.items()]
        blocks.append("LOCKED OBJECTS (use these exact descriptions):\n" + "\n".join(obj_lines))

    # ── Characters in this scene ─────────────────────────────────────────
    matched_chars = _match_characters(bible, scene_characters)
    if matched_chars:
        char_lines = []
        for ch in matched_chars:
            char_lines.append(
                f"  {ch.name}: {ch.appearance}. Clothing: {ch.clothing}."
            )
        blocks.append(
            "LOCKED CHARACTERS (do not re-invent — use these exact descriptions):\n"
            + "\n".join(char_lines)
        )

    # ── Location for this scene ──────────────────────────────────────────
    matched_loc = _match_location(bible, scene_environment)
    if matched_loc:
        details = ", ".join(matched_loc.key_details) if matched_loc.key_details else ""
        loc_block = (
            f"LOCKED LOCATION — {matched_loc.name}:\n"
            f"  {matched_loc.description}\n"
        )
        if matched_loc.lighting_default:
            loc_block += f"  Default lighting: {matched_loc.lighting_default}\n"
        if details:
            loc_block += f"  Must include: {details}\n"
        blocks.append(loc_block)

    # ── Color palette for this arc phase ─────────────────────────────────
    palette = bible.style.color_progression.get(arc_phase, "")
    if palette:
        blocks.append(f"COLOR PALETTE ({arc_phase} phase): {palette}")

    # ── Do-not-change rules ──────────────────────────────────────────────
    if bible.do_not_change:
        dnc_lines = [f"  • {rule}" for rule in bible.do_not_change]
        blocks.append("DO NOT CHANGE (locked across all scenes):\n" + "\n".join(dnc_lines))

    return "\n\n".join(blocks)


def compose_global_style(bible: StoryBible) -> str:
    """Return the global style block — injected once at the top of the system prompt."""
    parts = []
    if bible.style.rendering_prefix:
        parts.append(bible.style.rendering_prefix)
    if bible.style.camera_defaults:
        parts.append(f"Camera: {bible.style.camera_defaults}")
    if bible.style.grain_and_dof:
        parts.append(f"Rendering: {bible.style.grain_and_dof}")
    return "\n".join(parts)


def get_negative_prompt(bible: StoryBible) -> str:
    """Return the standardized negative prompt from the bible."""
    return bible.style.negative_prompt


def _match_characters(
    bible: StoryBible,
    scene_characters: list[str],
) -> list:
    """Find bible entries matching scene characters by fuzzy name match."""
    if not scene_characters or not bible.characters:
        return []
    scene_lower = {c.lower().strip() for c in scene_characters}
    matched = []
    for entry in bible.characters:
        name_lower = entry.name.lower().strip()
        if name_lower in scene_lower:
            matched.append(entry)
            continue
        for sc in scene_lower:
            if name_lower in sc or sc in name_lower:
                matched.append(entry)
                break
    return matched


def _match_location(
    bible: StoryBible,
    scene_environment: str,
) -> object | None:
    """Find the best-matching location entry for a scene environment string."""
    if not scene_environment or not bible.locations:
        return None
    env_lower = scene_environment.lower()
    best = None
    best_score = 0
    for loc in bible.locations:
        name_words = loc.name.lower().split()
        score = sum(1 for w in name_words if w in env_lower)
        if loc.slug.replace("-", " ") in env_lower:
            score += 2
        if score > best_score:
            best_score = score
            best = loc
    return best if best_score >= 1 else None
