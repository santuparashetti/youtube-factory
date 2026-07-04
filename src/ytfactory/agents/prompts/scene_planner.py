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
You are a documentary film director — not an image prompt generator.
Your task: direct {num_scenes} scenes as one coherent film sequence for a {style_label} video.

{style_guide}

{prev_context_block}══════════════════════════════════════════════════
BANNED — these patterns are forbidden
══════════════════════════════════════════════════

Opening phrase ban — the very first words of every prompt matter:
  ✗  "A figure..."  |  "A person..."  |  "A silhouette..."  |  "A traveler walks..."  |  "A bird..."
  ✓  Lead with something specific: "Worn stone steps disappear into morning mist"  |  "Candlelight on cracked plaster"

Camera-as-subject ban:
  ✗  "The camera is positioned at a low angle, capturing the temple."
  ✓  Weave it naturally: "Seen from ground level, the temple towers against storm-grey sky."

Narration-copy ban — the most important rule:
  ✗  Narration: "he forgot to live"  →  Prompt: "a man who forgot to live"
  ✓  Narration: "he forgot to live"  →  Prompt: "an untouched dinner cooling on a windowsill, the city below moving without him"

Generic environment ban — these phrases reveal nothing:
  ✗  "lush greenery"  |  "vast landscape"  |  "open plain"  |  "beautiful surroundings"
  ✓  Be specific: "overgrown weeds pushing through cracked pavement"  |  "salt flats cracked into perfect hexagons at low tide"

Passive construction ban:
  ✗  "The subject is shown..."  |  "We see..."  |  "There is a man..."

══════════════════════════════════════════════════
CHARACTER BIBLE
══════════════════════════════════════════════════

Scan the narrations below. If a recurring protagonist appears (referred to as "he", "she", "you", or as a specific described person):
  — Choose ONE physical description and lock it in: age, build, ethnicity, clothing
  — Example: "a lean man in his early 40s, close-cropped dark hair, plain grey linen shirt, worn dark trousers"
  — Use the SAME description in every scene where a human figure appears
  — If the narration is philosophical with no clear protagonist, use environments, objects, and symbols — do NOT invent random human subjects per scene

══════════════════════════════════════════════════
STORYBOARD — complete this before writing any prompt
══════════════════════════════════════════════════

1. Read all {num_scenes} narrations below.
2. Define the emotional arc: opening mood → mid-point peak → closing resolution.
3. Assign each scene a role: Hook | Establishing | Rising | Revelation | Reflection | Symbolic | Resolution
4. Choose ONE hero frame — the most visually powerful image in this batch, strong enough for a YouTube thumbnail. Give it 20 extra words of environmental and atmospheric detail.
5. Plan shot diversity — no two adjacent scenes share the same: shot size + environment category + dominant color.
6. List the metaphors you will use — commit to them, each used only once in this batch.

PER-SCENE INTERNAL REASONING (work through this silently before writing each prompt):
  A. Core meaning — what is this scene ABOUT beneath the words?
  B. Dominant emotion — one only: wonder | mystery | hope | peace | grief | isolation | determination | reverence | longing | fear | regret
  C. Best metaphor — what image makes the audience FEEL the idea without being told it?
     Library:  desire → traveler toward a horizon that keeps receding
               ego → an ornate throne in a vast echoing hall, dust settling
               peace → glacier lake at pre-dawn, surface still as polished stone
               attachment → vine grown through an iron gate it can no longer pass
               fear → a long shadow stretching across an empty road toward dusk
               time → stone steps worn concave by generations of crossings
               hope → one lit window in a long row of dark buildings at 3am
               freedom → a cage door open, white feathers still drifting
               transformation → cracked earth after the first monsoon rain
               loneliness → one chair at a set table, the second place never touched
  D. Specific subject — not "a lake" but "a glacier-fed alpine lake, its surface not yet broken by wind"
  E. Environment — two or three concrete details that reveal emotion without stating it:
     ✓  "an untouched dinner cooling, a voicemail light blinking unanswered, rain against the window"
     ✗  "a peaceful place, lush surroundings, beautiful landscape"
  F. Camera — only if it changes the emotional meaning:
     wide (scale/isolation) | macro (sacred detail) | overhead (pattern/ritual) | low angle (power/awe) | behind subject (contemplation)
     Omit entirely if the meaning doesn't depend on it.
  G. Lighting — one specific choice: pre-dawn blue | warm candlelight | storm-filtered gold | overcast flat | harsh noon | volumetric shafts
  H. Self-critique — before writing: Is this specific? Does it avoid every banned pattern above?
     Have I repeated an environment or metaphor from another scene in this batch?
     Would a documentary director choose this exact frame?

══════════════════════════════════════════════════
WRITING RULES
══════════════════════════════════════════════════

— One natural flowing paragraph per scene.
— Begin with the scene's strongest visual element — never with "A person" or "The camera."
— 60–90 words per scene. Hero frame: 85–110 words.
— Weave camera and lighting into the description naturally — not as separate sentences starting "The lighting is..." or "The camera is..."
— Vary endings — do NOT paste the same phrase at the close of every scene.
— Include somewhere in each prompt: no text, no watermark, photorealistic.
— The {style_label} feeling should come through the imagery — not by stating it as a keyword.

Return ONE JSON array. Index values MUST match the scene numbers exactly — do not reset to 1.
[{{"index": N, "visual_prompt": "..."}}]

══════════════════════════════════════════════════
SCENES
══════════════════════════════════════════════════
{scene_list}\
"""

_ENHANCE_TEMPLATE = _VISUAL_PROMPTS_TEMPLATE  # kept for backward compatibility


def build_visual_prompts_prompt(
    scenes: list[dict],
    style: str | None = None,
    prev_context: list[str] | None = None,
) -> str:
    style_label = f"{style} documentary" if style else "cinematic documentary"
    num_scenes = len(scenes)
    scene_list = "\n".join(
        f"Scene {s['index']}: {s.get('narration', '')}"
        for s in scenes
    )
    if prev_context:
        entries = "\n".join(f"  • {entry}" for entry in prev_context)
        prev_context_block = (
            "══════════════════════════════════════════════════\n"
            "ALREADY USED IN THIS VIDEO — do not repeat these\n"
            "══════════════════════════════════════════════════\n"
            f"{entries}\n\n"
        )
    else:
        prev_context_block = ""
    return _VISUAL_PROMPTS_TEMPLATE.format(
        style_label=style_label,
        style_guide=_style_guide(style),
        num_scenes=num_scenes,
        prev_context_block=prev_context_block,
        scene_list=scene_list,
    )


def build_enhance_prompt(topic: str, scene_json: str, style: str | None = None) -> str:
    """Legacy — kept for any direct callers."""
    style_label = f"{style} documentary" if style else "documentary"
    return _ENHANCE_TEMPLATE.format(
        style_label=style_label,
        style_guide=_style_guide(style),
        num_scenes="N",
        prev_context_block="",
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
