"""Scene planner agent prompts."""

# ── Style-specific visual guidance injected into PLAN_SCENES ─────────────────

_STYLE_GUIDES: dict[str, str] = {
    "spiritual": """\
VISUAL STYLE — Spiritual Documentary
Approach: silence as teacher, nature as metaphor, light as consciousness.
Core metaphors to draw from:
  • desire → traveler pursuing endlessly receding horizon / moth flying toward flame
  • ego → mirror maze / throne standing alone in empty hall
  • peace → still mountain lake at dawn / snow-covered valley
  • attachment → vine gripping ancient stone / anchor preventing boat from sailing
  • freedom → bird leaving open cage / cliff overlooking ocean
  • wisdom → monk beneath ancient tree / open book in morning light
  • time → worn stone staircase / autumn leaves on still water
  • hope → first light breaking through storm clouds / single candle in darkness
Color palette: warm amber/gold (enlightenment), cool silver-blue (inner peace), deep indigo (consciousness), white mist (transcendence).
Camera: contemplative wide shots, behind-subject perspectives, high angle (humility), macro sacred details.
Lighting: candlelight, temple lamp glow, golden hour, pre-dawn blue.
Avoid: identifiable faces, yoga poses, specific religious symbols, generic sunsets.\
""",

    "documentary": """\
VISUAL STYLE — Documentary
Approach: authentic observation, environmental storytelling, human scale in vast environments.
Core metaphors: weathered textures as history, movement as change, empty spaces as absence.
Camera: eye-level and low-angle for authenticity, drone for scale, observational framing.
Color: neutral, natural, slightly desaturated — gravitas over beauty.
Weather: use real conditions (overcast, rain, harsh sun) — never perfect.
Avoid: staged scenes, studio lighting, fantasy elements, cartoon.\
""",

    "history": """\
VISUAL STYLE — Historical Documentary
Approach: evidence of time's passage, architecture as witness, textures as testimony.
Core metaphors: ruined walls (fall), worn roads (journeys), empty thrones (power), ancient artifacts (civilization).
Camera: wide sweeping establishing shots, low-angle hero framing, macro on aged textures.
Color: warm sepia/amber with dramatic shadow, earth tones, occasional dramatic gold.
Lighting: golden-hour chiaroscuro, dusty shafts through ruins.
Figures: silhouettes only — never detailed faces.\
""",

    "educational": """\
VISUAL STYLE — Educational / Explainer
Approach: clear visual communication, one strong focal point, immediately readable symbolism.
Core metaphors: familiar environments made symbolic, objects as concepts.
Camera: eye-level for accessibility, medium shots for context, close-ups for emphasis.
Color: consistent, slightly elevated, clean without being sterile.
Rule: the concept must be visible within 2 seconds — no visual complexity.
Avoid: cluttered scenes, overlapping symbols, abstract imagery that needs explanation.\
""",
}

_DEFAULT_STYLE_GUIDE = """\
VISUAL STYLE — Cinematic Documentary
Approach: symbolic storytelling, emotional authenticity, memorable imagery.
Camera: vary shot size and angle intentionally across scenes.
Color: restrained palette, avoid oversaturation.
Lighting: always meaningful — never decorative.\
"""


def _style_guide(style: str | None) -> str:
    if not style:
        return _DEFAULT_STYLE_GUIDE
    return _STYLE_GUIDES.get(style.lower().strip(), _DEFAULT_STYLE_GUIDE)


# ── Main prompts ──────────────────────────────────────────────────────────────

_PLAN_SCENES_TEMPLATE = """\
You are an expert video editor. Split the script below into scenes for: {topic}

──────────────────────────────────────────────────────────────
RULES
──────────────────────────────────────────────────────────────
- Cover the ENTIRE script — no content left out.
- Short dramatic lines (under 15 words): group 3-5 related lines into one scene.
- Longer paragraphs (40+ words): one paragraph = one or two scenes.
- Strip all markdown from narration: plain spoken text only, no **, ##, *, etc.
- Use EXACT words from the script verbatim in narration. Do NOT paraphrase.
- Duration: word_count / 2 seconds (slow meditative pace, ~120 wpm).
- Target 18–25 scenes total.

──────────────────────────────────────────────────────────────
OUTPUT — ONLY valid JSON, no markdown fences, nothing else
──────────────────────────────────────────────────────────────
{{"topic":"{topic}","scenes":[{{"index":1,"title":"3-5 word title","narration":"exact spoken words","duration_seconds":12}}]}}

Keep narration and title SHORT. visual_prompt is NOT needed here — it is added later.

Script:
{script}\
"""


def build_plan_scenes_prompt(topic: str, script: str, style: str | None = None) -> str:
    return _PLAN_SCENES_TEMPLATE.format(topic=topic, script=script)


_VISUAL_PROMPTS_TEMPLATE = """\
You are a Visual Director, Storyboard Artist, and Cinematographer \
planning imagery for a {style_label} YouTube documentary. \
Your job is to create unforgettable visual sequences, not generic AI images.

{style_guide}

══════════════════════════════════════════════════
INTERNAL REASONING — do NOT output this section
══════════════════════════════════════════════════

Read ALL {num_scenes} scene narrations below before writing a single prompt.
Plan a visual sequence — a connected storyboard — not isolated images.

BATCH PLANNING
Ask yourself:
• What is the emotional arc across these scenes? Where does it begin, peak, and resolve?
• Assign each scene a role: Hook | Establishing | Discovery | Conflict | Reflection | Symbolic | Revelation | Resolution
• Plan shot diversity — no two adjacent scenes should share the same framing, angle, or environment.
• Identify which scene deserves the strongest visual impact (the hero frame).

PER-SCENE INTERNAL REASONING (work through all 10 steps silently for each scene):
1. CORE IDEA: Summarize the scene in one sentence. What is it fundamentally about?
2. DOMINANT EMOTION: Choose exactly ONE — wonder, mystery, hope, peace, grief, isolation, determination, reverence, fear, regret, joy, longing
3. VISUAL STRATEGY: symbolic metaphor | environmental storytelling | nature symbolism | architectural symbolism | macro detail | documentary realism | object symbolism
4. METAPHOR SEARCH: Can the abstract idea become a powerful symbol? Apply the golden rule: never ask "what image matches these words?" — ask "what image makes the audience FEEL this idea?"
   Examples: desire=traveler pursuing receding horizon, ego=empty golden throne, peace=still lake at dawn, attachment=vine gripping stone, hope=sunrise after rain, fear=shadow growing on wall, time=worn steps, wisdom=elder beneath ancient tree, freedom=bird leaving cage, transformation=ice melting into river, loneliness=single cabin in snow
5. SUBJECT: What is the primary visual element — figure, object, place, or natural phenomenon?
6. ENVIRONMENT: Where does this happen? The environment must reinforce emotion, not merely contain the subject.
7. CAMERA DECISIONS:
   Shot size: extreme wide (isolation/scale) | wide (establishing) | medium (human story) | close portrait (inner conflict) | macro (sacred detail)
   Angle: eye-level (neutral) | low angle (strength/awe) | high angle (vulnerability) | overhead (patterns/rituals) | behind subject (contemplation/journey)
8. LIGHTING: golden hour (hope/peace) | blue hour (mystery/reflection) | candlelight/practical (spiritual) | storm light (conflict/transformation) | overcast (melancholy/uncertainty) | harsh noon (exposure/clarity)
9. COLOR LANGUAGE: warm gold (enlightenment) | deep blue (reflection) | green (renewal) | amber (nostalgia) | white (purity/transcendence) | gray (uncertainty) | deep indigo (consciousness)
10. SELF-CRITIQUE — silently ask:
    • Is this generic? Reject "person standing", "mountain at sunset", "lake" alone.
    • Have I repeated a location, symbol, or framing from another scene in this batch?
    • Would this frame be memorable the day after watching?
    • Does the environment carry emotional meaning, or is it just a backdrop?
    • Would a documentary director choose this shot?

BATCH SELF-REVIEW (before writing any output):
✓ Each scene differs from its neighbors — different framing, environment, emotional tone
✓ Emotional progression flows naturally through the sequence
✓ At least one scene is strong enough to be a YouTube thumbnail
✓ No symbol, location, or camera angle is repeated without narrative purpose
✓ Visual rhythm alternates: wide ↔ close, dark ↔ bright, human ↔ nature, literal ↔ symbolic

══════════════════════════════════════════════════
PROMPT CONSTRUCTION — output these
══════════════════════════════════════════════════

For each scene write ONE final image prompt using this order:
[Subject + action] [Environment with meaningful detail] [Camera framing] [Lighting] [Composition/mood] [Style] [Negative]

Requirements:
• 60–90 words per prompt — specific enough for high-quality generation
• Lead with the primary subject or visual element, NOT style keywords like "cinematic" or "photorealistic"
• Write in descriptive sentences, not comma-separated keyword lists
• Model-agnostic: works across Pollinations, Flux, Midjourney, Leonardo, Firefly, Imagen
• No visible faces, no religious symbols, no specific brands, no text in image
• End each prompt with: "cinematic documentary style, photorealistic, subtle film grain. No text, no watermark, no cartoon."

Return ONE single JSON array containing ALL {num_scenes} scenes — no explanation, no markdown fences, nothing else.
CRITICAL: The "index" value MUST match the scene number shown in the SCENES section exactly. Do NOT reset to 1. If the first scene shown is Scene 15, the first object must be {{"index": 15, "visual_prompt": "..."}}.
[{{"index": SCENE_NUMBER_HERE, "visual_prompt": "..."}}, ...]

══════════════════════════════════════════════════
SCENES
══════════════════════════════════════════════════
{scene_list}\
"""

_ENHANCE_TEMPLATE = _VISUAL_PROMPTS_TEMPLATE  # kept for backward compatibility


def build_visual_prompts_prompt(
    scenes: list[dict],
    style: str | None = None,
) -> str:
    style_label = f"{style} documentary" if style else "cinematic documentary"
    num_scenes = len(scenes)
    scene_list = "\n".join(
        f"Scene {s['index']}: {s.get('narration', '')}"
        for s in scenes
    )
    return _VISUAL_PROMPTS_TEMPLATE.format(
        style_label=style_label,
        style_guide=_style_guide(style),
        num_scenes=num_scenes,
        scene_list=scene_list,
    )


def build_enhance_prompt(topic: str, scene_json: str, style: str | None = None) -> str:
    """Legacy — kept for any direct callers."""
    style_label = f"{style} documentary" if style else "documentary"
    return _ENHANCE_TEMPLATE.format(
        style_label=style_label,
        style_guide=_style_guide(style),
        num_scenes="N",
        scene_list=scene_json,
    )


# ── Legacy constants (kept for backward compatibility) ────────────────────────

PLAN_SCENES = _PLAN_SCENES_TEMPLATE.replace("{style_guide}", _DEFAULT_STYLE_GUIDE)

ENHANCE_VISUAL_PROMPTS = build_visual_prompts_prompt([], style=None)  # legacy alias

FIX_JSON_PROMPT = """\
The JSON below is malformed or incomplete. Fix it so it is valid JSON.
Accept either format:
  {{"scenes": [{{"index":1,"title":"...","narration":"...","duration_seconds":10}}]}}
  or a plain array: [{{"index":1,"title":"...","narration":"...","duration_seconds":10}}]

Required fields per scene: index (integer), title (string), narration (string), duration_seconds (number).
Do NOT add visual_prompt — it is not needed here.

Malformed JSON:
{broken_json}

Return ONLY the corrected valid JSON. No explanation. No code fences.\
"""
