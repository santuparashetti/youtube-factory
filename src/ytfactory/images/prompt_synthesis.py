"""
Image Prompt Synthesis V2 — single-pass LLM synthesis with bounded repair.

Flow per batch:
  1. ONE LLM call → raw prompts
  2. Deterministic validation
  3. If blocking failures: ONE targeted repair LLM call for those scenes only
  4. Re-validate repaired prompts → export only PASS
  5. Emergency last-resort placeholder for scenes that survive repair but still fail

Replaces:
  - Phase 2 batch synthesis (build_visual_prompts_prompt loop)
  - Layer 3 fidelity validation + retry loop
  - run_prompt_qa_pass (LLM repair pass)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from video_core.providers.llm.base import LLMProvider
from ytfactory.scenes.models import VisualBible
from ytfactory.story_bible.models import StoryBible

logger = logging.getLogger(__name__)

# Kai hardcoded injection markers (from scene_planner._KAI_MARKERS)
_KAI_INJECTION_MARKERS: frozenset[str] = frozenset(
    [
        "lean young man",
        "light stubble",
        "simple dark shirt",
        "plain trousers",
    ]
)

# Forbidden metadata block openers that old synthesis emitted
_META_INSTRUCTION_RE = re.compile(
    r"^(PRIMARY SUBJECT|PRIMARY ACTION|ANT|NEGATIVE PROMPT|SHOT TYPE|"
    r"CHARACTER STAGING|ENVIRONMENT PROMPT)\s*:",
    re.MULTILINE | re.IGNORECASE,
)

# Prohibited text/branding generation directives
_TEXT_BRANDING_RE = re.compile(
    r"\b(show(?:ing)?\s+(?:the\s+)?(?:text|title|words?)|"
    r"include\s+(?:the\s+)?(?:text|title|logo)|"
    r"display\s+(?:the\s+)?(?:text|logo|title)|"
    r"render\s+(?:the\s+)?(?:text|logo)|"
    r"write\s+(?:the\s+)?(?:text|words?|title))\b",
    re.IGNORECASE,
)

# Broken article-article joins that indicate a truncated generation, e.g.
# "through a The figure", "at the foot of an immense The repeated marks",
# "of a Leave clearly framed". Article followed (immediately, or with one
# intervening adjective) by another article/determiner is never grammatically valid.
_BROKEN_JOIN_RE = re.compile(
    r"\b(?:a|an|the|A|An|The)\s+(?:\w+\s+)?(?:A|An|The|Their|Its|This|That|These|Those)\b(?!-)",
)

# All images are rendered at 1280×720 (16:9). Every prompt must specify the ratio.
_ASPECT_RATIO_RE = re.compile(r"\b16:9\b|\b16\s*/\s*9\b", re.IGNORECASE)

# Orphaned leading article followed by a Title-case word — the first sentence was
# truncated to only its article, leaving e.g. "A Above it, …", "A Loose paper, …",
# "A Three subtle traces…".  A capital article (sentence-start) followed immediately
# by another Title-case word (uppercase first char + lowercase second char) is never
# a valid image-prompt opening.  The (?!-) guard excludes hyphen-joined compounds
# like "An In-depth view" where "In-" starts the adjective, not a new sentence.
_LEADING_ORPHAN_RE = re.compile(r"^(?:A|An|The)\s+[A-Z][a-z](?!-)")

# Trailing bare article — generation was cut off mid-sentence at the very end,
# leaving e.g. "…every step bringing it closer. The"
_TRAILING_TRUNCATION_RE = re.compile(r"\b(?:a|an|the)\s*$", re.IGNORECASE)

# Mid-sentence splice: a lowercase article (a / an / the) immediately followed by a
# capitalised word that CANNOT be a proper noun (prepositions, negations, conjunctions,
# common discourse markers, participial verbs used as sentence openers).
# These words appear capitalised only when they begin a new sentence — finding them
# after a lowercase article means two fragments were spliced mid-clause, e.g.
# "looking down at a On the desk…" or "framed by a No visible text".
# The (?!-) guard excludes hyphenated compounds like "an In-depth view".
_SPLICE_STARTERS_PATTERN = (
    r"On|In|At|Above|Below|Through|Under|Over|Around|Near|Between|"
    r"Within|Without|Across|Along|Behind|Beside|Beyond|During|Inside|"
    r"Outside|Toward|Towards|Upon|Per|Via|Versus|Opposite|"
    r"No|Not|Never|Neither|Nor|Nothing|Nowhere|"
    r"But|And|Or|So|Yet|"
    r"However|Therefore|Thus|Meanwhile|Instead|Otherwise|"
    r"Looking|Standing|Sitting|Walking|Facing|Reaching|Holding|Running|Turning"
)
_MID_SENTENCE_SPLICE_RE = re.compile(
    rf"\b(?:a|an|the)\s+(?:{_SPLICE_STARTERS_PATTERN})\b(?!-)"
)

# Checks whose failure means the prompt is structurally unusable for image generation.
# Blocking checks replace report.prompts[idx] with a narration-derived placeholder
# rather than deleting the entry, so the scene_planner vp_map always has a usable
# value and never falls back to the stale visual_prompt stored in scene-plan.json.
_BLOCKING_CHECKS = frozenset({
    "broken_join", "leading_orphan", "trailing_truncation", "empty_prompt",
    "mid_sentence_splice", "readable_text",
})

# ── Scene Prompt QA patterns ──────────────────────────────────────────────────

# B: Photorealistic treatment applied to a character/living-subject noun.
# Matches "photorealistic [0-3 intervening words] <character noun>".
_PHOTO_CHAR_RE = re.compile(
    r"\b(?:photorealistic|realistic|hyperrealistic|lifelike)\s+"
    r"(?:\w+\s+){0,3}"
    r"(?:character|figure|person|human|man|woman|boy|girl|child|"
    r"warrior|scholar|sage|monk|priest|king|queen|soldier|farmer|"
    r"pilgrim|travell?er|merchant|vendor|villager|elder)\b",
    re.IGNORECASE,
)
# Exclude matches where the context reveals a non-living subject (statue, painting, etc.)
_PHOTO_CHAR_ARTIFACT_RE = re.compile(
    r"\b(?:statue|idol|sculpture|carving|figurine|portrait|painting|"
    r"fresco|relief|effigy|motif)\b",
    re.IGNORECASE,
)

# B: Cartoon/animated/illustrated treatment applied to an environment/background noun.
# Environments must always be photorealistic in V2 hybrid style.
_CARTOON_ENV_RE = re.compile(
    r"\b(?:cartoon(?:ish)?|animated|hand[- ]drawn|hand[- ]painted|2D|illustrated)\s+"
    r"(?:\w+\s+){0,2}"
    r"(?:environment|background|setting|landscape|scene|backdrop|world)\b",
    re.IGNORECASE,
)

# E: Compositor-owned UI elements (subscribe buttons, end-screen overlays) requested
# as image content. These are added in post-production; the image generator must not
# attempt to render them.
_COMPOSITOR_TEXT_ELEM_RE = re.compile(
    r"\b(?:subscribe\s+(?:button|graphic|icon)|"
    r"like\s+button|"
    r"channel\s+(?:name|logo|branding)\s+(?:text|overlay|graphic)|"
    r"end[- ]screen\s+(?:overlay|content|text|graphic)|"
    r"end[- ]card\s+(?:overlay|text))\b",
    re.IGNORECASE,
)

# Detects readable text rendered as image content rather than compositor-produced text:
# quoted literals with "word appears", title-graphic pop-ups, Devanagari/Sanskrit script
# directives, and "single line of writing:" patterns.
# All such content belongs to the compositor, not the image generator.
_READABLE_TEXT_RE = re.compile(
    r"(?:"
    r"the\s+word\s+['‘’“”]?\w+['‘’“”]?\s+"
        r"(?:appears?|glows?|fades?\s+in?|floats?|emerges?|displays?)"
    r"|"
    r"title\s+graphic\s+"
        r"(?:['‘’“”][^'’”]{1,120}['’”]\s+)?"
        r"(?:appears?|pops?\s+up|fades?\s+in?)"
    r"|"
    r"(?:appears?\s+in|in|written\s+in|rendered\s+in)\s+(?:\w+\s+){0,2}devanagari\s+script"
    r"|"
    r"(?:in\s+(?:bold\s*,\s*)?|appears?\s+in\s+)sanskrit[\s-]+style\s+"
        r"(?:script|lettering|text|font)"
    r"|"
    r"(?:a\s+)?single\s+line\s+of\s+writing\s*:"
    r"|"
    r"lines?\s+of\s+text\s+appear"
    r")",
    re.IGNORECASE,
)

# Positive character/animal terms used in environment-only leakage checks.
_ENV_ONLY_CHAR_RE = re.compile(
    r"\b(?:ant|ants|bee|bees|bird|birds|butterfly|butterflies|"
    r"insect|insects|creature|creatures|animal|animals|"
    r"person|people|man|woman|child|human|humans|figure|"
    r"silhouette|character|characters)\b",
    re.IGNORECASE,
)

# Negation prefix: strips "no|not|without ..." before character terms to avoid false
# positives like "no ant" or "without any person".  Uses \w+[^\w\s]*\s* to handle
# punctuation directly after the negated word (e.g. "no ant,").
_NEGATION_PREFIX_RE = re.compile(
    r"\b(?:no|not|without|absent|devoid\s+of|free\s+of|empty\s+of|"
    r"exclude|excluding|never|invisible|hidden|barely)\s+(?:\w+[^\w\s]*\s*){0,3}",
    re.IGNORECASE,
)

# Recurring narrative animals — detected to catch unlisted-animal leakage in scenes
# where character_presence is non-empty but doesn't include the animal.
_UNLISTED_ANIMAL_RE = re.compile(
    r"\b(?:ant|ants|bee|bees|bird|birds|butterfly|butterflies|insect|insects)\b",
    re.IGNORECASE,
)

# C: Transition signals in narration that justify an environment change between scenes.
_ENV_TRANSITION_SIGNAL_RE = re.compile(
    r"\b(?:now|then|later|meanwhile|suddenly|next|as\s+(?:we|they|he|she)|"
    r"enter|enters|arrives?|moves?\s+to|cuts?\s+to|shifts?\s+to|"
    r"returns?\s+to|travels?\s+to|cross\s+cut|hard\s+cut|transition|"
    r"teleport|flash(?:es)?(?:\s+(?:forward|back))?)\b",
    re.IGNORECASE,
)

# Engagement/CTA scenes: match any [ENGAGEMENT: type] prefix to detect the type.
# Only the two compositor-owned types below receive pre-assigned templates and are
# excluded from the LLM batch.  All other engagement types (value_promise,
# journey_invitation, etc.) contain real narration content and go through synthesis.
_ENGAGEMENT_RE = re.compile(r"^\s*\[ENGAGEMENT:\s*(\w+)")
_COMPOSITOR_CTA_TYPES = frozenset({"subscribe_promise", "branding_end"})

# Compositor-aware placeholder for subscribe-CTA scenes (scene_21-style).
_CTA_SUBSCRIBE_PLACEHOLDER = (
    "High-angle cinematic view from directly above a natural worn-wood desk surface; "
    "an open handwritten journal and a small brass ink lamp sit at the near edge, "
    "a narrow path of ink marks leads toward an open window at the far end; clean "
    "warm centre with soft directional morning light, generous open space in the "
    "upper two-thirds reserved for compositor subscribe-call text and button overlay; "
    "photorealistic environment, no text, no watermark, no characters, shallow depth "
    "of field, 16:9 aspect ratio."
)

# Compositor-aware placeholder for end-screen branding scenes (scene_22-style).
_CTA_ENDSCREEN_PLACEHOLDER = (
    "Clean negative-space composition: a soft off-white plaster wall with warm "
    "diffused morning light and a textured natural stone ledge anchoring the lower "
    "frame; generous open areas in the right-side panel and lower quarter reserved "
    "for compositor end-screen thumbnail cards and subscribe graphic; photorealistic, "
    "no characters, no text, no watermark, 16:9 aspect ratio."
)

_PROMPT_MIN_WORDS = 10
_PROMPT_MAX_WORDS = 500
_DEFAULT_BATCH_SIZE = 10
_DEFAULT_TEMPERATURE = 0.35

_SYNTHESIS_SYSTEM_PROMPT = """\
You are a cinematic image-prompt writer for a documentary video.

═══════════════════════════════════════════════════════════════════
NARRATION-FIRST METHODOLOGY (apply before writing every prompt)
═══════════════════════════════════════════════════════════════════
The narration is the primary source of WHAT the image must depict.
Visual style, VisualBible, StoryBible, anchors, era, environment, and shot design \
determine HOW that content is depicted — they never replace it.

Before writing each prompt, perform this internal check:
1. Extract the concrete visual subjects, actions, objects, locations, and relationships \
   explicitly described by the narration.
2. Determine which elements MUST be visible for the viewer to understand what is \
   being said.
3. Preserve those elements in the final prompt.
4. Apply visual style, cinematic composition, lighting, camera language, environment, \
   palette, and continuity constraints.
5. Do not replace a narration-specific visual with a generic symbolic environment \
   merely because it looks more cinematic.

NARRATION COVERAGE — answer these before finalising:
- What is the viewer supposed to SEE while hearing this narration?
- What concrete subject/action carries the meaning?
- Is that subject actually present in the prompt?
- Would a viewer understand the narration from the image without reading the narration?
If the answer to any is no, revise before returning.

NO GENERIC FALLBACK:
Never produce a prompt whose main visual is merely "cinematic wide shot + beautiful \
landscape + atmospheric lighting." Every scene requires a scene-specific visual subject, \
action, object, environment, or metaphor derived from the narration and scene context. \
Every prompt must answer: WHAT / WHO / WHERE / WHAT action / WHY this visual / HOW it looks.

═══════════════════════════════════════════════════════════════════
VISUAL STYLE (apply to every scene without exception)
═══════════════════════════════════════════════════════════════════
- ENVIRONMENT: 100% photorealistic cinematic photography — real-world textures, natural \
lighting, lens characteristics.
- EVERY HUMAN, ANIMAL, BIRD, OR INSECT: 100% hand-painted 2D storybook / illustrated \
style — visible ink outline, painterly or cel-shaded treatment, graphic-novel quality. \
NOT photorealistic.
- When a character appears inside a photorealistic environment: apply the two styles \
independently (illustrated subject + photorealistic environment). \
Do NOT convert the whole scene to a single style because a character is present.
- Integrate illustrated subjects into the photographic environment through believable \
scale, lighting, contact shadows, atmospheric perspective, and composition.
- "Photorealistic environment" NEVER means "no characters." When characters/animals are \
required by narration or scene direction, include them as illustrated subjects.

═══════════════════════════════════════════════════════════════════
CHARACTER / ANIMAL PRESENCE — CRITICAL
═══════════════════════════════════════════════════════════════════
If VISUAL_DIRECTION, narration, scene analysis, visual anchor, or story beat \
explicitly requires a human, animal, bird, or insect, that subject MUST appear in the \
prompt. NEVER remove an explicitly required subject by adding:
  "no people" / "no characters" / "no animals" / "environment only" / \
  "without showing any characters"
unless scene analysis explicitly requires absence.

For scenes listed under CHARACTERS_PRESENT: render every listed character.
For scenes with empty CHARACTERS_PRESENT (marked "environment-only — no characters"): \
the scene plan has EXPLICITLY excluded all living subjects. \
Do NOT render any human, animal, bird, or insect — even if the narration mentions one. \
This overrides narration priority. The scene shows the physical environment only.

Do not inject any global recurring character into scenes where they are explicitly absent.
Do not invent characters, props, actions, or settings not supported by narration or \
scene context.

Examples of MANDATORY character inclusion:
- "a tiny ant crawls across a massive rock toward Mount Everest" → illustrated ant + \
  Himalayan environment with extreme scale contrast. NOT just landscape.
- "a bird sees the ant and asks…" → both illustrated bird AND illustrated ant.
- "scientists in a lab, musicians practicing, programmers coding" → those subjects and \
  actions, not an empty workspace.

═══════════════════════════════════════════════════════════════════
ABSTRACT / PHILOSOPHICAL NARRATION
═══════════════════════════════════════════════════════════════════
When narration is abstract, philosophical, emotional, or conceptual, use a concrete \
visual metaphor that preserves the narration's central idea. Do not default to a generic \
mountain, landscape, empty room, stone, path, or atmospheric environment unless it \
meaningfully represents the specific narration.

Examples of required specificity:
- consistency → repeated physical actions / accumulated progress
- persistence → continued movement despite distance or difficulty
- self-reliance → visibly self-built structure or independent effort

═══════════════════════════════════════════════════════════════════
SOURCE HIERARCHY — when inputs conflict, use this priority
═══════════════════════════════════════════════════════════════════
  1. VISUAL_DIRECTION  ← script writer's explicit on-screen intent; PRIMARY image anchor
  2. Narration prose   ← provides mood, context, and supporting detail
  3. Scene / beat purpose
  4. Continuity requirements
  5. Visual Bible
  6. Story / scene context
  7. Global style
  8. Creative enhancement  ← must never override higher items

When VISUAL_DIRECTION is present:
- It is the PRIMARY driver of what appears in the image — the image must contain what it \
  describes as its central subject.
- Narration prose provides emotional tone and atmosphere only; it does NOT override \
  VISUAL_DIRECTION.
- Example: VISUAL_DIRECTION "empty meditation hall, single candle flame" → the image \
  MUST show that space and that candle, even if narration is abstract.
- Example: VISUAL_DIRECTION "host on camera, speaking to viewer" → the image MUST show \
  the host in direct address framing.

When VISUAL_DIRECTION is absent, Narration prose is the primary anchor (same as before).

═══════════════════════════════════════════════════════════════════
ANCHOR ENVIRONMENTS — VISUAL CONTINUITY
═══════════════════════════════════════════════════════════════════
The VISUAL BIBLE section lists ANCHOR ENVIRONMENTS — the dominant recurring visual \
worlds for this video. They establish the visual continuity of the series.

When choosing an environment for a scene:
1. If the narration or [Visual:] direction clearly specifies a setting, use it.
2. Otherwise select the anchor environment whose textures, scale, and atmosphere best \
   fit the scene's narration and emotional tone.
3. Reference the anchor's key elements (light quality, surface textures, props, \
   spatial scale) — do not just name it; describe it visually.
4. Do NOT force an anchor environment into a scene where narration clearly requires \
   a different setting — narration takes priority (Source Hierarchy rule 1).
5. Target natural recurring use across the sequence. Most scenes should be grounded \
   in one of the listed anchor environments unless narration explicitly requires otherwise.

═══════════════════════════════════════════════════════════════════
ADJACENT CONTEXT
═══════════════════════════════════════════════════════════════════
Use PREV_NARRATION and NEXT_NARRATION for continuity only — era matching, environment \
transitions, lighting progression, recurring subjects.
Do not let adjacent context override the current scene's primary subject or action.

═══════════════════════════════════════════════════════════════════
PROMPT QUALITY — INTERNAL SELF-CHECK BEFORE RETURNING
═══════════════════════════════════════════════════════════════════
Return ONE rich, coherent, image-generator-ready prompt per scene.

Before returning each prompt, internally reject and rewrite if it contains:
- Broken joins: "the The", "a A", "a The", "through a The", "an immense The", \
  "of a Leave" — any article followed immediately by another capitalised article. \
  These indicate a truncated or spliced generation. Fix by completing or removing \
  the fragment.
- Orphaned fragments: a sentence-start word or phrase that follows an article \
  with no predicate (e.g. "...stands at the foot of an immense The repeated \
  marks form…" — the word "immense" lost its noun).
- Unfinished clauses: sentences that stop mid-idea without a verb or object.
- Duplicated fragments: the same phrase, clause, or sentence appearing twice.
- Metadata labels: "PRIMARY SUBJECT:", "PRIMARY ACTION:", "ANT:", etc.
- Analysis notes: commentary about what the prompt is doing rather than describing \
  the image (e.g. "This prompt conveys…", "Note that…").
- Unsupported subjects: major characters, objects, or actions not grounded in the \
  narration, scene analysis, or story bible.

Do NOT output the checklist or reasoning. Output only the final image prompt.
Enrich with composition, camera, scale, lighting, atmosphere, depth, palette and \
cinematic detail AFTER all semantic requirements are satisfied.

═══════════════════════════════════════════════════════════════════
TEXT, BRANDING, AND PRODUCTION METADATA
═══════════════════════════════════════════════════════════════════
- Do not generate readable text, titles, subtitles, logos, UI, or branding.
- For compositor-owned text/CTA/end-screen areas: create clean space and visual \
  framing only. Do not generate actual text.
- Tags such as [ENGAGEMENT: ...], [NARRATIVE_ENDING], [ENGAGEMENT: subscribe_promise], \
  [ENGAGEMENT: branding_end], [Text Overlay: ...] are production metadata, not image \
  content. Do not render the tag. Preserve the visual meaning of the narration and \
  provide clean composition/negative space for compositor-owned overlays.

═══════════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════
Return a JSON array — one object per scene, in scene index order:
[
  {"index": <scene_index>, "visual_prompt": "<prompt>"},
  ...
]

PROMPT REQUIREMENTS:
- One coherent, image-generator-ready cinematic prose prompt per scene.
- ASPECT RATIO: Every prompt MUST end with ", 16:9 aspect ratio." — this is a \
  hard requirement for all 1280×720 image generation.
- Naturally express: primary subject, action, environment, era, composition, \
  camera/lens, depth, lighting, atmosphere, color, emotional tone, continuity.
- Do NOT output metadata block headers such as PRIMARY SUBJECT:, PRIMARY ACTION:, \
  ANT:, NEGATIVE PROMPT:, etc.
- Do NOT repeat the narration verbatim.
- Do NOT invent unsupported characters, props, history, or symbolism.
- Add rich cinematic detail only where it strengthens the narrated moment.
"""

# Semantic integrity repair prompt — used for scenes whose first-pass prompt failed a
# blocking deterministic check.  This is ONE bounded LLM call (not a retry loop).
# It performs comprehensive semantic and linguistic review, not just structural patching.
# If the repaired prompt still fails deterministic re-validation, the scene is reported
# as definitively failed.
_REPAIR_SYSTEM_PROMPT = """\
You are the semantic integrity reviewer for documentary image prompts.

For each scene you receive:
  NARRATION     — what the viewer will hear (primary authority on WHAT to show)
  ISSUE         — the structural problem that triggered this review
  BROKEN_PROMPT — the original prompt that failed validation

Your task: write a fresh, complete image prompt that passes every check below.

═══════════════════════════════════════════════════════
STRUCTURAL INTEGRITY
═══════════════════════════════════════════════════════
- Grammatically coherent from first word to last.
- No incomplete sentences or trailing fragments.
- No article-article or article-sentence-starter splices: \
  "a On", "the The", "a winding The", "an At the far end" — any lowercase article \
  immediately followed by a capitalised word that starts a new sentence is a splice. \
  Rewrite the clause as one grammatical unit.
- No duplicated phrases, clauses, or sentences appearing more than once.
- No orphaned fragments: every noun phrase must have a verb; every clause must be complete.

═══════════════════════════════════════════════════════
NARRATION FIDELITY — primary constraint
═══════════════════════════════════════════════════════
- Identify the main subject, action, environment, and core meaning in NARRATION.
- Those elements must be visually present in the final prompt.
- Preserve the original visual concept from BROKEN_PROMPT where it correctly represents \
  the narration — the goal is to repair, not reinvent.
- Do not omit an explicitly required subject, action, or object that the narration describes.
- Do not substitute a generic cinematic landscape for a narration-specific visual.

═══════════════════════════════════════════════════════
VISUAL COHERENCE
═══════════════════════════════════════════════════════
- All described elements are spatially and tonally compatible.
- No contradictory directives within the same prompt \
  (e.g. "empty room" + "a figure stands at the desk").
- Scale, lighting, and depth relationships are internally consistent.

═══════════════════════════════════════════════════════
READABLE TEXT — COMPOSITOR RULE (applies when ISSUE contains "readable_text")
═══════════════════════════════════════════════════════
When the ISSUE is "readable_text", the prompt must NEVER request rendering of readable \
text, even if the narration quotes a verse, scripture, inscription, or written word.
All text-on-screen elements belong to the compositor, not the image generator.
Replace the readable-text concept with a visual metaphor or atmospheric description:
- A narration about a Sanskrit verse → describe the physical medium (aged parchment, \
  stone surface with abstract geometric carvings, soft candlelight on a book face)
- A narration about words appearing → describe light, motion, or texture that conveys \
  the feeling of the words without rendering the words themselves
- Leave clean negative space if compositor text overlay is required for this scene
This rule overrides NARRATION FIDELITY — do not include the literal text under any framing.

═══════════════════════════════════════════════════════
SCOPE DISCIPLINE
═══════════════════════════════════════════════════════
- Do NOT add major subjects, characters, objects, or settings not in NARRATION.
- Do NOT copy structurally broken fragments from BROKEN_PROMPT.
- Do NOT output metadata headers (PRIMARY SUBJECT:, ANT:, NEGATIVE PROMPT:, etc.).

═══════════════════════════════════════════════════════
STYLE
═══════════════════════════════════════════════════════
- Photorealistic environment.
- Every human, animal, bird, or insect: illustrated 2D storybook / painterly style.
- End every prompt with ", 16:9 aspect ratio."
- One coherent prose prompt per scene — no bullet lists, no analysis notes.

Return JSON: [{"index": N, "visual_prompt": "..."}]
"""


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class SynthesisIssue:
    scene_index: int
    check: str
    detail: str


@dataclass
class SynthesisReport:
    prompts: dict[int, str]
    validation_issues: list[SynthesisIssue] = field(default_factory=list)
    failed_scenes: list[int] = field(default_factory=list)
    llm_call_count: int = 0


# ── Internal helpers ──────────────────────────────────────────────────────────


def _build_visual_bible_section(visual_bible: VisualBible) -> str:
    color_arc_parts = " | ".join(
        f"{phase}: {desc}" for phase, desc in visual_bible.color_arc.items()
    )
    shot_arc_parts = " | ".join(
        f"{phase}: {desc}" for phase, desc in visual_bible.shot_arc.items()
    )
    return (
        "=== VISUAL BIBLE ===\n"
        f"Dominant metaphor: {visual_bible.dominant_metaphor}\n"
        f"Anchor environments: {'; '.join(visual_bible.anchor_environments)}\n"
        f"Color arc: {color_arc_parts}\n"
        f"Shot arc: {shot_arc_parts}\n"
        f"Visual motifs: {', '.join(visual_bible.visual_motifs)}\n"
    )


def _lookup_character_spec(char_id: str, story_bible: StoryBible | None) -> str:
    """Return character appearance + clothing from Story Bible, or the raw ID."""
    if not story_bible:
        return char_id
    char_id_lower = char_id.lower()
    for char in story_bible.characters:
        if char.slug.lower() == char_id_lower or char.name.lower() == char_id_lower:
            parts: list[str] = []
            if char.appearance:
                parts.append(char.appearance)
            if char.clothing:
                parts.append(f"wearing: {char.clothing}")
            return f"{char.name}: {' — '.join(parts)}" if parts else char.name
    return char_id


_VISUAL_TAG_RE = re.compile(r"\[Visual:\s*(.*?)\s*\]", re.IGNORECASE | re.DOTALL)


def _extract_visual_direction(narration: str) -> tuple[str, str]:
    """Split narration into (prose_without_tags, joined_visual_directions).

    Returns the cleaned narration and a single string with all [Visual: ...] tag
    contents joined by ' | ', or an empty string if none were found.
    """
    directions: list[str] = []

    def _collect(m: re.Match) -> str:
        directions.append(m.group(1).strip())
        return " "

    cleaned = _VISUAL_TAG_RE.sub(_collect, narration)
    cleaned = re.sub(r"  +", " ", cleaned).strip()
    return cleaned, " | ".join(directions)


def _build_scene_block(
    scene: dict,
    prev_scene: dict | None,
    next_scene: dict | None,
    story_bible: StoryBible | None,
) -> str:
    idx = scene.get("index", "?")
    raw_narration = (scene.get("narration") or "").strip()
    narration, visual_direction = _extract_visual_direction(raw_narration)
    prev_narration = (
        (prev_scene.get("narration") or "none").strip()[:150]
        if prev_scene
        else "none"
    )
    next_narration = (
        (next_scene.get("narration") or "none").strip()[:150]
        if next_scene
        else "none"
    )

    shot_type = scene.get("shot_type") or "medium"
    beat = scene.get("assigned_beat") or scene.get("narrative_phase") or ""
    story_context = (scene.get("story_context") or "").strip()
    action_constraints = (scene.get("action_constraints") or "").strip()
    visual_anchor = (scene.get("visual_anchor") or "").strip()

    sa = scene.get("scene_analysis") or {}
    if isinstance(sa, dict):
        sa_environment = sa.get("environment") or ""
        sa_primary = sa.get("primary_subject") or ""
        sa_emotional = sa.get("emotional_beat") or ""
        sa_story_goal = sa.get("story_goal") or ""
    else:
        sa_environment = getattr(sa, "environment", "") or ""
        sa_primary = getattr(sa, "primary_subject", "") or ""
        sa_emotional = getattr(sa, "emotional_beat", "") or ""
        sa_story_goal = getattr(sa, "story_goal", "") or ""

    char_ids: list[str] = scene.get("character_presence") or []
    if char_ids:
        chars_section = "\n".join(
            f"  - {_lookup_character_spec(cid, story_bible)}" for cid in char_ids
        )
    else:
        chars_section = (
            "  STRICT ENVIRONMENT-ONLY — Do NOT render any human, animal, insect, or bird.\n"
            "  Show only the physical environment regardless of what the narration mentions."
        )

    lines = [f"--- SCENE {idx} ---"]
    if visual_direction:
        lines.append(f"VISUAL_DIRECTION: {visual_direction}")
    lines += [
        f"NARRATION: {narration or '(no narration)'}",
        f"PREV_NARRATION: {prev_narration}",
        f"NEXT_NARRATION: {next_narration}",
    ]
    if beat:
        lines.append(f"BEAT: {beat}")
    lines.append(f"SHOT_TYPE: {shot_type}")
    if sa_environment:
        lines.append(f"ENVIRONMENT: {sa_environment}")
    if sa_primary:
        lines.append(f"PRIMARY_SUBJECT: {sa_primary}")
    if sa_emotional:
        lines.append(f"EMOTIONAL_TONE: {sa_emotional}")
    if sa_story_goal:
        lines.append(f"STORY_GOAL: {sa_story_goal}")
    if story_context:
        lines.append(f"STORY_CONTEXT: {story_context}")
    if action_constraints:
        lines.append(f"ACTION_CONSTRAINTS: {action_constraints}")
    if visual_anchor:
        lines.append(f"VISUAL_ANCHOR: {visual_anchor}")
    lines.append(f"CHARACTERS_PRESENT:\n{chars_section}")

    return "\n".join(lines)


def _parse_synthesis_response(
    text: str, batch: list[dict]
) -> dict[int, str] | None:
    """Parse LLM response text → {scene_index: visual_prompt}."""
    text = text.strip()
    # Strip markdown code fences
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"```\s*$", "", text).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: find JSON array anywhere in the text
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return None

    # json_object mode (response_format={"type":"json_object"}) causes some models
    # to wrap the array in a dict like {"scenes": [...]} rather than returning a
    # bare array. Unwrap the first list value found.
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                data = v
                break

    if not isinstance(data, list):
        return None

    result: dict[int, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        prompt = (item.get("visual_prompt") or "").strip()
        if idx is not None and prompt:
            result[int(idx)] = prompt

    if not result:
        return None

    # Safety net: if LLM reset indexes (e.g. returned 1-N instead of the batch's indexes),
    # remap by position so correct scenes receive their prompts.
    expected_indexes = {s["index"] for s in batch}
    returned_indexes = set(result.keys())
    if not (returned_indexes & expected_indexes) and len(result) == len(batch):
        logger.warning(
            "Synthesis: LLM returned indexes %s instead of %s — remapping by position",
            sorted(returned_indexes),
            sorted(expected_indexes),
        )
        ordered_prompts = [result[k] for k in sorted(result.keys())]
        result = {
            scene["index"]: ordered_prompts[i] for i, scene in enumerate(batch)
        }

    return result


# ── Validation ────────────────────────────────────────────────────────────────


def validate_synthesis_result(
    prompt: str,
    scene_index: int,
    character_presence: list[str],
) -> list[SynthesisIssue]:
    """Deterministic validation of a single synthesised prompt."""
    issues: list[SynthesisIssue] = []

    if not prompt or not prompt.strip():
        issues.append(
            SynthesisIssue(scene_index, "empty_prompt", "Prompt is empty or whitespace")
        )
        return issues  # nothing else to check

    word_count = len(prompt.split())
    if word_count < _PROMPT_MIN_WORDS:
        issues.append(
            SynthesisIssue(
                scene_index,
                "too_short",
                f"Prompt has {word_count} words (min {_PROMPT_MIN_WORDS})",
            )
        )
    elif word_count > _PROMPT_MAX_WORDS:
        issues.append(
            SynthesisIssue(
                scene_index,
                "too_long",
                f"Prompt has {word_count} words (max {_PROMPT_MAX_WORDS})",
            )
        )

    # Accidental Kai injection — only flag on environment-only scenes (no characters listed)
    if not character_presence:
        prompt_lower = prompt.lower()
        kai_hits = [m for m in _KAI_INJECTION_MARKERS if m in prompt_lower]
        if kai_hits:
            issues.append(
                SynthesisIssue(
                    scene_index,
                    "kai_injection",
                    f"Global Kai markers in environment-only scene: {kai_hits}",
                )
            )

    if _META_INSTRUCTION_RE.search(prompt):
        issues.append(
            SynthesisIssue(
                scene_index,
                "meta_instructions",
                "Prompt contains forbidden metadata block headers (PRIMARY SUBJECT:, ANT:, …)",
            )
        )

    if _TEXT_BRANDING_RE.search(prompt):
        issues.append(
            SynthesisIssue(
                scene_index,
                "text_branding",
                "Prompt contains prohibited text/branding generation directive",
            )
        )

    if _READABLE_TEXT_RE.search(prompt):
        issues.append(
            SynthesisIssue(
                scene_index,
                "readable_text",
                "Prompt requests rendering of readable text (quoted literal, 'word appears', "
                "Devanagari/Sanskrit-style directive, or 'line of writing:') — "
                "convert to compositor negative-space placeholder",
            )
        )

    match = _BROKEN_JOIN_RE.search(prompt)
    if match:
        issues.append(
            SynthesisIssue(
                scene_index,
                "broken_join",
                f"Broken article-article join at {match.start()!r}: {match.group()!r} "
                f"(truncated generation fragment)",
            )
        )

    if _LEADING_ORPHAN_RE.search(prompt):
        issues.append(
            SynthesisIssue(
                scene_index,
                "leading_orphan",
                f"Prompt starts with an orphaned article before a preposition "
                f"('{prompt[:40].strip()}'…) — first sentence was truncated",
            )
        )

    if _TRAILING_TRUNCATION_RE.search(prompt):
        issues.append(
            SynthesisIssue(
                scene_index,
                "trailing_truncation",
                "Prompt ends with a bare article — generation was truncated mid-sentence",
            )
        )

    match = _MID_SENTENCE_SPLICE_RE.search(prompt)
    if match:
        issues.append(
            SynthesisIssue(
                scene_index,
                "mid_sentence_splice",
                f"Mid-sentence splice at position {match.start()}: {match.group()!r} "
                f"(lowercase article followed by capitalised sentence-starter — two fragments spliced)",
            )
        )

    if not _ASPECT_RATIO_RE.search(prompt):
        issues.append(
            SynthesisIssue(
                scene_index,
                "missing_aspect_ratio",
                "Prompt must include '16:9 aspect ratio' (required for 1280×720 generation)",
            )
        )

    return issues


def validate_scene_prompt_qa(
    prompt: str,
    scene_index: int,
    *,
    narration: str = "",
    character_presence: list[str] | None = None,
    prev_environment: str = "",
) -> list[SynthesisIssue]:
    """Lightweight Scene Prompt QA using existing scene metadata (deterministic, no LLM).

    Checks:
      B – Character/environment style contract (ERROR)
      C – Environment continuity against previous scene (WARNING)
      D – Character-presence contradiction (WARNING)
      E – Compositor-owned UI elements requested as image content (ERROR)

    Issue check names use 'qa_*_error' for hard violations and 'qa_*_warning' for soft ones.
    These issues are added to SynthesisReport.validation_issues but do NOT trigger repair.
    """
    issues: list[SynthesisIssue] = []

    if not prompt or not prompt.strip():
        return issues

    # B1: Photorealistic character — ERROR
    m = _PHOTO_CHAR_RE.search(prompt)
    if m and not _PHOTO_CHAR_ARTIFACT_RE.search(m.group()):
        issues.append(
            SynthesisIssue(
                scene_index,
                "qa_photo_char_error",
                f"Photorealistic treatment on living subject '{m.group()[:60]}' — "
                "characters must use 2D illustrated style (hybrid style contract)",
            )
        )

    # B2: Cartoon/animated environment — ERROR
    m = _CARTOON_ENV_RE.search(prompt)
    if m:
        issues.append(
            SynthesisIssue(
                scene_index,
                "qa_cartoon_env_error",
                f"Cartoon/animated treatment on environment '{m.group()[:60]}' — "
                "environments must be photorealistic (hybrid style contract)",
            )
        )

    # C: Environment continuity — WARNING (only when prev_environment provided)
    if prev_environment:
        _STOP = frozenset({
            "a", "an", "the", "of", "in", "at", "on", "is", "are", "was",
            "with", "and", "or", "but", "for", "to", "from", "by", "as",
            "into", "near", "no", "not", "it", "its",
        })
        prev_tokens = {
            w.lower().strip(".,;:!?")
            for w in prev_environment.split()
            if w.lower() not in _STOP and len(w) > 3
        }
        prompt_head = " ".join(prompt.split()[:100])
        curr_tokens = {
            w.lower().strip(".,;:!?")
            for w in prompt_head.split()
            if w.lower() not in _STOP and len(w) > 3
        }
        if (
            len(prev_tokens) >= 2
            and len(curr_tokens) >= 2
            and not (prev_tokens & curr_tokens)
            and not _ENV_TRANSITION_SIGNAL_RE.search(narration)
        ):
            issues.append(
                SynthesisIssue(
                    scene_index,
                    "qa_env_continuity_warning",
                    f"Abrupt environment change: prev='{prev_environment[:60]}' — "
                    "no shared tokens with current prompt and no narration transition signal",
                )
            )

    # D: character_presence lists subjects but prompt explicitly excludes characters — WARNING
    if character_presence:
        _no_char_re = re.compile(
            r"\b(?:no\s+(?:characters?|people|persons?|humans?|figures?)|"
            r"environment[\s-]+only|"
            r"without\s+(?:any\s+)?(?:characters?|people|figures?))\b",
            re.IGNORECASE,
        )
        if _no_char_re.search(prompt):
            issues.append(
                SynthesisIssue(
                    scene_index,
                    "qa_char_presence_warning",
                    f"Scene has character_presence={character_presence!r} but prompt "
                    "explicitly excludes characters — contradicts scene plan",
                )
            )

    # E: Compositor-owned UI element requested as image content — ERROR
    m = _COMPOSITOR_TEXT_ELEM_RE.search(prompt)
    if m:
        issues.append(
            SynthesisIssue(
                scene_index,
                "qa_compositor_text_error",
                f"Compositor-owned UI element '{m.group()[:60]}' in prompt — "
                "these are added in post-production, not rendered by the image generator",
            )
        )

    # F1: Environment-only scene (character_presence=[]) but prompt has positive
    # character/animal mention — ERROR.
    # Strip negation phrases first to avoid false positives on "no ant" / "no person".
    if character_presence is not None and not character_presence:
        stripped = _NEGATION_PREFIX_RE.sub("", prompt)
        m = _ENV_ONLY_CHAR_RE.search(stripped)
        if m:
            issues.append(
                SynthesisIssue(
                    scene_index,
                    "qa_character_leakage_error",
                    f"Environment-only scene (character_presence=[]) but prompt contains "
                    f"character/animal term '{m.group()[:40]}' — remove or convert to "
                    "environment description",
                )
            )

    # F2: Recurring narrative animal appears in prompt but is not listed in
    # character_presence — WARNING (catches ant/bee leakage into non-ant scenes).
    if character_presence:
        m = _UNLISTED_ANIMAL_RE.search(prompt)
        if m:
            term = m.group().lower().rstrip("s")  # normalize plural → singular
            if not any(term in cp.lower() or cp.lower().rstrip("s") == term for cp in character_presence):
                issues.append(
                    SynthesisIssue(
                        scene_index,
                        "qa_unlisted_animal_warning",
                        f"Animal '{m.group()[:40]}' appears in prompt but is not listed in "
                        f"character_presence={character_presence!r} — "
                        "remove unless narration explicitly includes it",
                    )
                )

    return issues


# ── Main entry point ──────────────────────────────────────────────────────────


def synthesize_visual_prompts(
    scenes: list[dict],
    llm: LLMProvider,
    *,
    visual_bible: VisualBible,
    story_bible: StoryBible | None = None,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    temperature: float = _DEFAULT_TEMPERATURE,
) -> SynthesisReport:
    """
    Single-pass synthesis: ONE LLM call per batch → final visual_prompt per scene.

    Replaces Phase 2 batch synthesis + Layer 3 fidelity validation + QA repair pass.
    Returns a SynthesisReport whose .prompts dict maps scene_index → visual_prompt.
    """
    report = SynthesisReport(prompts={})

    synthesis_scenes = [
        s for s in scenes
        if s.get("scene_type", "generated_image") == "generated_image"
    ]
    if not synthesis_scenes:
        return report

    # Pre-assign compositor-aware templates only for the two compositor-owned CTA types
    # (subscribe_promise and branding_end).  These have no real narration content — the
    # LLM cannot generate a meaningful visual from "[ENGAGEMENT: branding_end]" text.
    # All other engagement types (value_promise, journey_invitation, etc.) contain real
    # narration after the tag and must go through LLM synthesis.
    llm_scenes: list[dict] = []
    for scene in synthesis_scenes:
        narration = (scene.get("narration") or "").strip()
        m = _ENGAGEMENT_RE.match(narration)
        if m and m.group(1) in _COMPOSITOR_CTA_TYPES:
            idx = scene["index"]
            eng_type = m.group(1)
            report.prompts[idx] = (
                _CTA_SUBSCRIBE_PLACEHOLDER
                if eng_type == "subscribe_promise"
                else _CTA_ENDSCREEN_PLACEHOLDER
            )
            logger.info(
                "Synthesis: scene %d is compositor-owned CTA (%s) — "
                "template pre-assigned, excluded from LLM batch",
                idx,
                eng_type,
            )
        else:
            llm_scenes.append(scene)
    synthesis_scenes = llm_scenes

    bible_section = _build_visual_bible_section(visual_bible)

    for batch_start in range(0, len(synthesis_scenes), batch_size):
        batch = synthesis_scenes[batch_start : batch_start + batch_size]
        batch_nums = f"{batch[0]['index']}–{batch[-1]['index']}"

        # Build per-scene blocks with adjacent context from the full scene list
        scene_blocks: list[str] = []
        for scene in batch:
            # Locate scene in full list to get prev/next across batch boundaries
            try:
                full_idx = next(
                    i for i, s in enumerate(scenes) if s.get("index") == scene.get("index")
                )
            except StopIteration:
                full_idx = batch_start + batch.index(scene)
            prev_scene = scenes[full_idx - 1] if full_idx > 0 else None
            next_scene = (
                scenes[full_idx + 1] if full_idx < len(scenes) - 1 else None
            )
            scene_blocks.append(
                _build_scene_block(scene, prev_scene, next_scene, story_bible)
            )

        user_prompt = (
            bible_section
            + "\n\n"
            + "\n\n".join(scene_blocks)
            + "\n\n"
            "NARRATION COVERAGE CONTRACT — before finalising each prompt verify:\n"
            "  • Main subject of the narration is visually present\n"
            "  • Main action or state described is shown\n"
            "  • VISUAL_DIRECTION (if present) is the primary image anchor\n"
            "  • Important concrete objects or relationships are represented\n"
            "  • The prompt uses an anchor environment from the Visual Bible where appropriate\n"
            "  • A viewer could understand what the narration says from the image alone\n\n"
            "Generate one cinematic visual_prompt per scene above. "
            'Return JSON array: [{"index": N, "visual_prompt": "..."}]'
        )

        response = llm.generate(
            user_prompt,
            temperature=temperature,
            system_prompt=_SYNTHESIS_SYSTEM_PROMPT,
        )
        report.llm_call_count += 1

        parsed = _parse_synthesis_response(response.text, batch)

        if parsed is None:
            logger.warning(
                "Synthesis batch %s parse failed — retrying", batch_nums
            )
            response = llm.generate(
                user_prompt,
                temperature=temperature,
                system_prompt=_SYNTHESIS_SYSTEM_PROMPT,
            )
            report.llm_call_count += 1
            parsed = _parse_synthesis_response(response.text, batch)

        if parsed:
            report.prompts.update(parsed)
            # If LLM omitted any scene from the JSON response, write a clean
            # placeholder so vp_map always has a key — prevents the assignment
            # loop from silently keeping the original broken scene-planner text.
            for s in batch:
                idx = s["index"]
                if idx not in report.prompts:
                    title = (s.get("title") or "contemplative moment")
                    report.prompts[idx] = (
                        f"Cinematic wide shot, {title}, "
                        "golden hour lighting, silhouette, spiritual documentary, "
                        "no text, no watermark, photorealistic"
                    )
                    if idx not in report.failed_scenes:
                        report.failed_scenes.append(idx)
                    logger.warning(
                        "Synthesis batch %s: scene %d absent from LLM response — placeholder written",
                        batch_nums,
                        idx,
                    )
            logger.debug("Synthesis batch %s: %d prompts", batch_nums, len(parsed))
        else:
            logger.error(
                "Synthesis batch %s failed after retry — scenes will use fallback",
                batch_nums,
            )
            for s in batch:
                report.failed_scenes.append(s["index"])

    # Deterministic validation after first-pass synthesis
    for s in synthesis_scenes:
        idx = s["index"]
        prompt = report.prompts.get(idx, "")
        issues = validate_synthesis_result(
            prompt, idx, s.get("character_presence") or []
        )
        if issues:
            report.validation_issues.extend(issues)
            for issue in issues:
                logger.warning(
                    "Synthesis validation scene %d [%s]: %s",
                    idx,
                    issue.check,
                    issue.detail,
                )

    # Collect scenes with blocking failures for ONE targeted repair attempt.
    # Non-blocking issues (missing_aspect_ratio, too_short, etc.) are logged only.
    scenes_to_repair: set[int] = set()
    for issue in report.validation_issues:
        if issue.check in _BLOCKING_CHECKS:
            scenes_to_repair.add(issue.scene_index)

    # ── Repair pass: ONE bounded LLM call for structurally broken prompts ─────
    if scenes_to_repair:
        logger.warning(
            "Synthesis: %d scene(s) have blocking issues — attempting ONE repair pass: %s",
            len(scenes_to_repair),
            sorted(scenes_to_repair),
        )
        repair_blocks: list[str] = []
        for idx in sorted(scenes_to_repair):
            scene_obj = next(
                (s for s in synthesis_scenes if s.get("index") == idx), None
            )
            narration = (scene_obj.get("narration") or "(no narration)") if scene_obj else "(no narration)"
            broken = report.prompts.get(idx, "")
            failing_checks = ", ".join(
                i.check
                for i in report.validation_issues
                if i.scene_index == idx and i.check in _BLOCKING_CHECKS
            )
            repair_blocks.append(
                f"--- SCENE {idx} ---\n"
                f"NARRATION: {narration}\n"
                f"ISSUE: {failing_checks}\n"
                f"BROKEN_PROMPT: {broken}"
            )

        repair_prompt = "\n\n".join(repair_blocks) + (
            "\n\nWrite a fresh, complete image prompt for each scene above. "
            "Do NOT copy broken fragments. "
            'Return JSON: [{"index": N, "visual_prompt": "..."}]'
        )
        repair_response = llm.generate(
            repair_prompt,
            temperature=temperature,
            system_prompt=_REPAIR_SYSTEM_PROMPT,
        )
        report.llm_call_count += 1

        repair_fake_batch = [{"index": idx} for idx in sorted(scenes_to_repair)]
        repaired = _parse_synthesis_response(repair_response.text, repair_fake_batch)

        still_broken: set[int] = set()
        if repaired:
            for idx in sorted(scenes_to_repair):
                repaired_prompt = repaired.get(idx, "")
                if not repaired_prompt:
                    still_broken.add(idx)
                    continue
                repair_issues = validate_synthesis_result(
                    repaired_prompt, idx,
                    next(
                        (s.get("character_presence") or [] for s in synthesis_scenes if s.get("index") == idx),
                        [],
                    ),
                )
                blocking_repair_issues = [i for i in repair_issues if i.check in _BLOCKING_CHECKS]
                if blocking_repair_issues:
                    report.validation_issues.extend(blocking_repair_issues)
                    still_broken.add(idx)
                    logger.warning(
                        "Synthesis: repair for scene %d still fails [%s] — using emergency fallback",
                        idx,
                        ", ".join(i.check for i in blocking_repair_issues),
                    )
                else:
                    report.prompts[idx] = repaired_prompt
                    logger.info("Synthesis: scene %d repaired successfully", idx)
        else:
            still_broken = set(scenes_to_repair)
            logger.error("Synthesis: repair pass parse failed — all repaired scenes fall back")

        # Repair failed for `still_broken` scenes: store a clean title-based placeholder
        # directly in report.prompts so vp_map always has a usable entry for every
        # generated_image scene.  The primary `if s["index"] in vp_map` branch in
        # scene_planner's assignment loop then handles it unconditionally — no reliance
        # on the elif fallback or on the scene's pre-existing visual_prompt being empty.
        for idx in still_broken:
            scene_obj = next((s for s in synthesis_scenes if s.get("index") == idx), None)
            title = (scene_obj.get("title") or "contemplative moment") if scene_obj else "contemplative moment"
            report.prompts[idx] = (
                f"Cinematic wide shot, {title}, "
                "golden hour lighting, silhouette, spiritual documentary, no text, no watermark, photorealistic"
            )
            if idx not in report.failed_scenes:
                report.failed_scenes.append(idx)
            logger.error(
                "Synthesis: scene %d — repair failed after re-validation, placeholder written. "
                "Manual review required.",
                idx,
            )

    # Scene Prompt QA pass — deterministic, no LLM, separate from corruption validator.
    # Issues are logged and recorded but do NOT trigger further repair.
    for i, scene in enumerate(synthesis_scenes):
        idx = scene["index"]
        if idx in report.failed_scenes:
            continue
        prompt = report.prompts.get(idx, "")
        if not prompt:
            continue
        prev_env = ""
        if i > 0:
            prev_sa = synthesis_scenes[i - 1].get("scene_analysis") or {}
            if isinstance(prev_sa, dict):
                prev_env = prev_sa.get("environment") or ""
            else:
                prev_env = getattr(prev_sa, "environment", "") or ""
        qa_issues = validate_scene_prompt_qa(
            prompt,
            idx,
            narration=scene.get("narration") or "",
            character_presence=scene.get("character_presence") or [],
            prev_environment=prev_env,
        )
        for issue in qa_issues:
            if issue.check.endswith("_error"):
                logger.error("Scene QA scene %d [%s]: %s", idx, issue.check, issue.detail)
            else:
                logger.warning("Scene QA scene %d [%s]: %s", idx, issue.check, issue.detail)
        report.validation_issues.extend(qa_issues)

    return report


def validate_and_repair_cached(
    scenes: list[dict],
    llm: LLMProvider,
    temperature: float = _DEFAULT_TEMPERATURE,
) -> tuple[list[dict], bool]:
    """Validate cached visual_prompts and repair any blocking structural failures.

    Called from scene_planner's idempotency (early-return) path to ensure that
    scene plans loaded from disk are free of structural malformations before
    IMAGE_PROMPTS.md is written.  Reuses the same ONE-repair-call mechanic and
    emergency fallback as synthesize_visual_prompts().

    Returns:
        (scenes, any_repaired) — scenes with visual_prompt updated in-place for
        repaired/fallback entries; any_repaired=True if at least one scene changed.
    """
    scenes_to_repair: set[int] = set()
    repair_issues_by_idx: dict[int, list[str]] = {}

    for scene in scenes:
        if scene.get("scene_type") == "brand_card":
            continue
        idx = scene.get("index", 0)
        vp = scene.get("visual_prompt", "")
        issues = validate_synthesis_result(vp, idx, scene.get("character_presence") or [])
        blocking = [i for i in issues if i.check in _BLOCKING_CHECKS]
        if blocking:
            scenes_to_repair.add(idx)
            repair_issues_by_idx[idx] = [i.check for i in blocking]

    if not scenes_to_repair:
        return scenes, False

    logger.warning(
        "validate_and_repair_cached: %d scene(s) with blocking structural issues "
        "in cached plan — attempting ONE repair pass: %s",
        len(scenes_to_repair),
        sorted(scenes_to_repair),
    )

    scene_by_idx = {s.get("index", 0): s for s in scenes}
    repair_blocks: list[str] = []
    for idx in sorted(scenes_to_repair):
        scene_obj = scene_by_idx.get(idx, {})
        narration = scene_obj.get("narration") or "(no narration)"
        broken = scene_obj.get("visual_prompt", "")
        failing = ", ".join(repair_issues_by_idx.get(idx, []))
        repair_blocks.append(
            f"--- SCENE {idx} ---\n"
            f"NARRATION: {narration}\n"
            f"ISSUE: {failing}\n"
            f"BROKEN_PROMPT: {broken}"
        )

    repair_prompt = "\n\n".join(repair_blocks) + (
        "\n\nWrite a fresh, complete image prompt for each scene above. "
        "Do NOT copy broken fragments. "
        'Return JSON: [{"index": N, "visual_prompt": "..."}]'
    )

    try:
        repair_response = llm.generate(
            repair_prompt,
            temperature=temperature,
            system_prompt=_REPAIR_SYSTEM_PROMPT,
        )
    except Exception:
        logger.exception(
            "validate_and_repair_cached: repair LLM call failed — writing placeholders for all broken scenes"
        )
        for idx in sorted(scenes_to_repair):
            scene_obj = scene_by_idx.get(idx, {})
            title = (scene_obj.get("title") or "contemplative moment")
            scene_obj["visual_prompt"] = (
                f"Cinematic wide shot, {title}, "
                "golden hour lighting, silhouette, spiritual documentary, "
                "no text, no watermark, photorealistic"
            )
        return scenes, True

    repair_fake_batch = [{"index": idx} for idx in sorted(scenes_to_repair)]
    repaired_map = _parse_synthesis_response(repair_response.text, repair_fake_batch)

    still_broken: set[int] = set()
    any_repaired = False

    if repaired_map:
        for idx in sorted(scenes_to_repair):
            repaired_prompt = repaired_map.get(idx, "")
            if not repaired_prompt:
                still_broken.add(idx)
                continue
            repair_issues = validate_synthesis_result(
                repaired_prompt, idx,
                scene_by_idx.get(idx, {}).get("character_presence") or [],
            )
            if any(i.check in _BLOCKING_CHECKS for i in repair_issues):
                still_broken.add(idx)
                logger.warning(
                    "validate_and_repair_cached: scene %d still broken after repair — "
                    "emergency fallback",
                    idx,
                )
            else:
                scene_by_idx[idx]["visual_prompt"] = repaired_prompt
                any_repaired = True
                logger.info(
                    "validate_and_repair_cached: scene %d repaired successfully", idx
                )
    else:
        still_broken = set(scenes_to_repair)
        logger.error(
            "validate_and_repair_cached: repair parse failed — "
            "emergency fallback for all %d scene(s)",
            len(scenes_to_repair),
        )

    for idx in still_broken:
        scene_obj = scene_by_idx.get(idx, {})
        title = (scene_obj.get("title") or "contemplative moment")
        scene_obj["visual_prompt"] = (
            f"Cinematic wide shot, {title}, "
            "golden hour lighting, silhouette, spiritual documentary, "
            "no text, no watermark, photorealistic"
        )
        any_repaired = True
        logger.error(
            "validate_and_repair_cached: scene %d — repair failed after re-validation, "
            "placeholder written. Manual review required.",
            idx,
        )

    return scenes, any_repaired
