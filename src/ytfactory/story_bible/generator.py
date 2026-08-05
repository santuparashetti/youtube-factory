"""Generate a StoryBible from the script and scene analysis via a single LLM call."""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from video_core.providers.llm.base import LLMProvider
from ytfactory.story_bible.models import (
    CharacterEntry,
    GlobalStyle,
    LocationEntry,
    StoryBible,
    WorldRules,
)

_STORY_BIBLE_PROMPT = """\
You are a script analyst preparing a **Story Bible** for consistent AI image generation.
Read ALL narrations below.  Extract every recurring character, location, and world detail
so that image prompts can reference locked descriptions instead of re-inventing them.

{audience_directive}

NARRATIONS (one per scene):
{narrations}

Return ONLY valid JSON matching this schema — no markdown fences, no prose:
{{
  "world": {{
    "era": "ANCIENT|HISTORICAL|MODERN|SYMBOLIC",
    "cultural_context": "which culture, geography, and time this story inhabits",
    "key_objects": {{"object name": "locked visual description — materials, colors, condition"}},
    "recurring_symbols": ["objects that recur across scenes and carry narrative weight — e.g. gold coin, oil lamp, empty chair, river, wooden stake"],
    "architectural_style": "description of typical buildings, structures, interiors",
    "time_period_note": "constraints on what can/cannot appear"
  }},
  "characters": [
    {{
      "name": "character name exactly as used in narration",
      "slug": "kebab-case-filename-slug",
      "appearance": "locked physical description: age, build, skin, hair, features",
      "clothing": "locked clothing: garments, colors, materials, condition",
      "role": "narrative role (protagonist, mentor, antagonist, observer, etc.)"
    }}
  ],
  "locations": [
    {{
      "name": "location name",
      "slug": "kebab-case-filename-slug",
      "description": "locked visual description: architecture, materials, scale, atmosphere",
      "lighting_default": "typical lighting for this location (e.g. pre-dawn blue, torch-lit amber)",
      "key_details": ["3-5 specific physical details that must appear every time this location is shown"]
    }}
  ],
  "do_not_change": [
    "Short imperative: e.g. 'The old man always wears a faded white dhoti'",
    "e.g. 'The river has a stone dock with cracked wooden stakes'",
    "e.g. 'Coins are small, tarnished copper — never gold or silver'"
  ]
}}

RULES:
- Only include characters that appear in more than one scene or have a named identity.
- For characters: describe appearance as a casting director would — specific enough to reproduce.
- For locations: describe as a production designer would — materials, colors, scale, wear.
- key_objects: only objects that recur or are narratively significant. Lock their appearance.
- recurring_symbols: objects that appear in multiple scenes and carry thematic meaning. Include ALL visually recurring props — even if they seem minor (a specific chair, a window, a garden path).
- do_not_change: 5-15 rules that prevent the most common drift errors across scenes.
- Do NOT invent details not supported by the narrations. Infer cultural context from the story.
"""

_WESTERN_ENGLISH_BIBLE_DIRECTIVE = """\
AUDIENCE & CHARACTER DIRECTIVE (MANDATORY — apply to ALL character and location descriptions):
Target viewer: English-speaking (US, UK, AU, CA). The story may originate from any
culture, but the VISUAL PRESENTATION must feel internationally relevant.

CHARACTER RULES:
- Default all characters to Western/European appearance: light to medium complexion,
  Western clothing (tunics, cloaks, linen shirts, leather boots, simple trousers).
- Indian/South Asian ethnic markers are FORBIDDEN as defaults: no dhoti, no kurta,
  no saree, no bindi, no tilak, no charpai, no Sanskrit scrolls.
- For kings/rulers: use medieval European royal garb (cloak, crown, embroidered tunic)
  — not Indian royal attire.
- For scholars/sages: European academic or monastery aesthetic — robes, leather-bound
  books, stone study — not pandit's home with Sanskrit texts.

LOCATION RULES:
- Architecture: European medieval or universally rustic — stone castles, timber halls,
  thatched cottages, cobblestone streets, European countryside.
- Do NOT use: Indian palace architecture (sandstone with elephant carvings), Indian
  village mud huts with thatched roofs, temple ghats, Indian riverbank architecture.
- Rivers and natural environments are universal — keep them culturally neutral.

The story's PHILOSOPHICAL MESSAGE is universal. Only the visual wrapping changes.
Keep the narrative structure and emotional arc intact while adapting the visual culture.
"""


def generate_story_bible(
    narrations: list[str],
    llm: LLMProvider,
    audience_profile: str = "western_english",
) -> StoryBible:
    """Single LLM call to extract a StoryBible from all scene narrations."""
    narration_block = "\n".join(
        f"Scene {i + 1}: {n}" for i, n in enumerate(narrations)
    )
    audience_directive = (
        _WESTERN_ENGLISH_BIBLE_DIRECTIVE
        if audience_profile == "western_english"
        else ""
    )
    prompt = _STORY_BIBLE_PROMPT.format(
        narrations=narration_block,
        audience_directive=audience_directive,
    )

    try:
        response = llm.generate(prompt, temperature=0.3)
        raw = response.text.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            ).strip()
        data = json.loads(raw)

        world = WorldRules(**(data.get("world") or {}))
        characters = [CharacterEntry(**c) for c in (data.get("characters") or [])]
        locations = [LocationEntry(**loc) for loc in (data.get("locations") or [])]
        do_not_change = data.get("do_not_change") or []

        return StoryBible(
            world=world,
            characters=characters,
            locations=locations,
            style=GlobalStyle(),
            do_not_change=do_not_change,
        )
    except Exception as e:
        logger.warning("Story Bible generation failed: {} — using empty bible", e)
        return StoryBible()


def load_or_generate_story_bible(
    project_id: str,
    workspace_dir: str,
    narrations: list[str],
    llm: LLMProvider,
    audience_profile: str = "western_english",
) -> StoryBible:
    """Load cached bible from disk, or generate and persist a new one."""
    bible_path = Path(workspace_dir) / project_id / "story-bible" / "bible.json"
    if bible_path.exists():
        try:
            data = json.loads(bible_path.read_text(encoding="utf-8"))
            bible = StoryBible(**data)
            logger.info("Story Bible loaded from cache ({} chars, {} locs)", len(bible.characters), len(bible.locations))
            return bible
        except Exception as e:
            logger.warning("Cached Story Bible invalid: {} — regenerating", e)

    bible = generate_story_bible(narrations, llm, audience_profile=audience_profile)

    bible_path.parent.mkdir(parents=True, exist_ok=True)
    bible_path.write_text(
        json.dumps(bible.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "Story Bible generated: {} characters, {} locations, {} locked rules",
        len(bible.characters), len(bible.locations), len(bible.do_not_change),
    )
    return bible
