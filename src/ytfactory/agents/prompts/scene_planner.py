"""Scene planner agent prompts."""

# ── Style-specific visual guidance injected into PLAN_SCENES ─────────────────

_STYLE_GUIDES: dict[str, str] = {
    "spiritual": """\
VISUAL STYLE — Spiritual Documentary
Approach: silence as teacher, nature as metaphor, light as consciousness.
Core metaphors to draw from:
  • desire → traveler pursuing endlessly receding horizon / moth flying toward flame
  • ego → mirror maze / solitary bench in a vast empty courtyard
  • peace → glacier-fed alpine lake, surface unbroken at pre-dawn / snow-covered valley
  • attachment → vine grown through an iron gate it can no longer pass / anchor preventing boat from sailing
  • freedom → bird leaving open cage / cliff overlooking ocean
  • wisdom → monk beneath ancient tree / worn pages of a journal, pen resting mid-sentence
  • time → worn stone staircase / autumn leaves on still water
  • hope → first light breaking through storm clouds / one lit window in a row of dark buildings
Color palette: warm amber/gold (enlightenment), cool silver-blue (inner peace), deep indigo (consciousness), soft pre-dawn blue (transcendence).
Camera: contemplative wide shots, behind-subject environmental portraits, high angle (humility), profile shots revealing emotional weight.
Lighting: temple lamp glow, golden hour, pre-dawn blue — warm and purposeful.
Avoid: identifiable faces, yoga poses, specific religious symbols, generic sunsets, candles as main subject, mist as shorthand for mystery.\
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
Core metaphors: ruined walls (fall), worn roads (journeys), crumbling columns (power), ancient artifacts (civilization).
Camera: wide sweeping establishing shots, low-angle hero framing, close-up on aged textures and worn surfaces.
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
Your task: direct {num_scenes} scenes as ONE coherent cinematic documentary for a {style_label} video.
This is a visual story, not a collection of independent images. Every frame connects to the next.

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

REPETITIVE OBJECT ban — these appear too often in AI-generated spirituality videos:
  ✗  mist / fog (unless narratively essential) | candles | mountain lakes | empty thrones
  ✗  fireplaces | lotus flowers | hourglasses | open books lying on tables
  ✓  Use fresh, specific visual equivalents that express the same emotion without the cliché

AI VISUAL CLICHÉ ban — these reveal the image was AI-generated and look generic:
  ✗  giant hands holding a tiny figure | floating clocks or melting watches
  ✗  cracked desert floor merging with the sky | cosmic portals or vortexes
  ✗  glowing eyes on a dark figure | glowing chakras or third-eye beams
  ✗  broken chains or shattered glass for "freedom" | floating orbs of light
  ✗  fractal universe inside a teardrop | silhouette with radiant rays behind it
  ✗  digital matrix rain | ethereal glow emanating from a person's body
  ✓  Real situations: a man sitting with his back to us, watching rain on glass
  ✓  Specific textures: worn timber dock at pre-dawn, water absolutely still

ANATOMY SAFETY — when a human figure must appear:
  ✓  Show the subject from behind, in profile, or from the chest up — never isolated hands
  ✓  Specify: "natural posture," "realistic proportions" in the prompt
  ✓  Avoid requesting gesturing hands — if hands must appear, show them resting or holding an object
  ✗  No disembodied hands | no floating hands | no macro shot of a hand
  ✗  No extreme close-up on body parts unless the scene critically demands it

CULTURAL MIXING ban — every visual element must belong to the same cultural world:
  ✗  Indian sage inside a Japanese temple | Buddhist monk inside a Roman palace
  ✗  Modern office worker wearing ancient robes | Greek philosopher inside an Indian ashram
  ✗  Sanskrit scholar in a Tudor library | Mughal courtier in a Greek amphitheatre
  ✗  Ancient warrior using modern objects | contemporary professional in historical ruins as background set
  ✓  Identify the culture from the narration — then match environment, clothing, architecture,
     objects, lighting, and atmosphere to that single culture

══════════════════════════════════════════════════
HUMAN SUBJECT QUALITY — mandatory when a human appears in the scene
══════════════════════════════════════════════════

AI image models render environments beautifully but often produce blurry faces,
unnatural eyes, and stiff postures.  When a human subject appears, include ALL of
these phrases explicitly in the prompt so the model prioritises human quality:

  — "highly detailed human face"
  — "natural facial expression"
  — "realistic eyes"
  — "authentic skin texture"
  — "natural posture"
  — "seamless integration with the environment"
  — "documentary-quality realism"

Subject Dominance Rule — for establishing shot, wide shot, drone, or wide cinematic
when a human is present:
  Add: "subject remains visually prominent and detailed despite wide framing"
  Without this, the model may render a tiny, low-detail person inside a large environment.

══════════════════════════════════════════════════
CLOTHING & CULTURAL AUTHENTICITY — mandatory for every human scene
══════════════════════════════════════════════════

Before writing each prompt, ask: "Is the clothing appropriate for the story,
location, era, and culture?" If not — rewrite the clothing description.

RULE: Every human subject must wear contextually appropriate clothing.

FORBIDDEN — never describe or imply:
  ✗  Naked / nude / nudity / unclothed people
  ✗  Shirtless men / bare-chested figures / bare torso
  ✗  Topless / revealing clothing / skimpy outfits
  ✗  Sensationalized body exposure
  ✗  Glamour-style posing that focuses on the body
  ✗  Clothing that distracts from the narrative
  ✓  Focus stays on the story, emotion, and message — not the body

CONTEXT → CLOTHING (infer when not stated in the script):
  Office / workplace          → professional attire — shirt, blazer, business clothing
  Home / apartment            → casual everyday wear — t-shirt, jeans, comfortable clothing
  Park / outdoor / street     → casual outdoor clothing — t-shirt, hoodie, jacket
  Meditation (modern)         → simple modest clothing — loose cotton, minimal
  Temple / puja / pilgrimage  → modest traditional attire — kurta, dhoti, regional devotional dress
  Ashram / ancient India      → traditional dhoti and angavastram, saffron or white robes
  Ancient Greek               → draped chiton and himation
  Buddhist / East Asian       → traditional grey or saffron monk's robes
  Medieval Europe             → period wool tunic, cloak, period armour
  Modern India / urban        → kurta, shirt, casual contemporary clothing
  Indigenous / historical     → accurate traditional regional attire for that culture

AUTHENTIC EXCEPTIONS — reduced or traditional clothing is culturally legitimate ONLY for:
  ✓  Hindu sadhus / Naga sadhus (traditional practice)
  ✓  Jain Digambara monks (sky-clad is an ancient authentic tradition)
  ✓  Ancient yogis and Vedic ascetics in authentic historical contexts
  ✓  Indigenous peoples in historically accurate cultural scenes
  Even then — depict with respect, no sexualization, no exaggerated physique,
  no glamour posing. Use phrases like "depicted with cultural dignity and reverence."

FOR MODERN SCENES: always prefer realistic everyday clothing:
  T-shirt | shirt | kurta | hoodie | jacket | sweater | office attire |
  casual everyday wear | traditional regional clothing where appropriate

══════════════════════════════════════════════════
CULTURAL AUTHENTICITY — identify once, apply throughout
══════════════════════════════════════════════════

Before writing a single prompt, read ALL narrations and identify the single cultural,
historical, and geographical world the video inhabits.  Then keep every scene inside
that world.  The environment, people, clothing, architecture, objects, and atmosphere
must all belong to the same culture.

Context → authentic visual elements (examples — not exhaustive):

  Ancient Indian spirituality / philosophy
    Sages, monks, ashrams, river ghats, banyan trees, Himalayan or Deccan landscapes,
    dhoti, saffron or white robes, meditation halls, ancient temples, oil lamps (diyas),
    clay vessels, Sanskrit manuscripts, peacocks, marigolds.

  Contemporary / modern life
    City streets, offices, apartments, cafés, metro stations, glass towers, smartphones,
    laptops, cars; contemporary casual or business clothing; diverse modern settings.

  Ancient Greek philosophy
    Marble colonnades and porticos, draped tunics (chiton) and himation, agora,
    olive groves, Aegean coastline, amphorae, scroll rolls, symposium settings.

  East Asian spirituality (Buddhist, Daoist, Zen)
    Wooden temples, tatami floors, rock and moss gardens, bamboo groves,
    grey monk's robes, rice-paper lanterns, mountain mist, lotus ponds,
    stone lanterns, cedar forests.

  Islamic golden age / Middle Eastern
    Minarets, geometric tile work, souks, desert landscapes, flowing robes and kufiya,
    astrolabes, qalam and inkpot, courtyard gardens with fountains.

  Medieval / feudal Europe
    Stone castles and keeps, torchlit great halls, dirt roads and market squares,
    period-accurate armour, wool tunics, quill and parchment, taverns, forest clearings.

  Sub-Saharan African
    Savannah, baobab trees, or dense jungle; traditional textiles and beadwork;
    clay or thatch architecture; communal fire circles; specific regional dress.

  Universal / timeless narration
    When the script contains no specific cultural or historical reference, prefer
    contemporary settings (city, nature, modern home) — never invent a historical context.

⚠ NEVER mix elements from unrelated cultures in the same scene.
⚠ NEVER invent a cultural context that is absent from the narration.

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
5. Verify shot diversity — check that the shot types assigned to each scene in [brackets] vary meaningfully.
6. List the metaphors you will use — commit to them, each used only once in this batch.

PER-SCENE INTERNAL REASONING (work through this silently before writing each prompt):
  A. Cultural context — what culture, era, and geography does this narration inhabit?
     Ancient Indian philosophy → sages, ashrams, river ghats, banyan trees, dhotis, diyas
     Modern / contemporary → city, office, apartment, contemporary clothing, technology
     Ancient Greek → marble colonnades, tunics and himation, agora, olive groves
     East Asian Buddhist / Daoist → wooden temples, bamboo, rock gardens, grey robes
     Medieval / feudal → stone castles, torchlit halls, period armour, quill and parchment
     Universal / timeless → default to contemporary unless the script implies otherwise
     ⚠ Confirm: do my chosen environment, clothing, and objects all belong to this one culture?
     ⚠ Clothing check: Is clothing appropriate to the story, location, era, and culture?
        If the scene has a human — explicitly name what they are wearing.
        If modern: t-shirt, shirt, kurta, jeans, office attire, etc.
        If historical: period-accurate attire matching the culture identified above.
        NEVER describe bare torso, nudity, shirtless figures unless the scene is an
        authentic cultural exception (sadhu, Jain monk, ancient ascetic). Even then:
        depict with dignity, no glamour, no exaggeration of physique.
  B. Core meaning — what is this scene ABOUT beneath the words?
  C. Dominant emotion — one only: wonder | mystery | hope | peace | grief | isolation | determination | reverence | longing | fear | regret
  D. Best metaphor — what image makes the audience FEEL the idea without being told it?
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
  E. Specific subject — not "a lake" but "a glacier-fed alpine lake, its surface not yet broken by wind"
  F. Environment — two or three concrete details that reveal emotion without stating it:
     ✓  "an untouched dinner cooling, a voicemail light blinking unanswered, rain against the window"
     ✗  "a peaceful place, lush surroundings, beautiful landscape"
  G. Shot type — the ASSIGNED SHOT TYPE for this scene is shown in [brackets] in the SCENES section below.
     Use that exact shot type. It determines camera distance and composition:
       establishing shot → wide view, scene-setting, full environment visible
       wide shot → landscape-scale subject, environmental context dominant
       medium shot → subject waist-up or object at mid-distance, context visible
       close-up → face or meaningful object filling most of the frame — NOT isolated body parts
       over-the-shoulder → looking past a figure at what they face
       low angle → camera below subject, looking up — conveys power or awe
       high angle → camera above subject, looking down — conveys scale or vulnerability
       drone → aerial overhead or diagonal pull-back, reveals geography
       tracking shot → camera moves laterally alongside a subject in motion
       static → locked-off camera, world moves within frame — conveys stillness
       handheld → slightly unsteady camera suggests intimacy or documentary feel
       environmental portrait → subject embedded in their environment, context tells the story
       profile shot → subject in profile, revealing character through posture and silhouette
       wide cinematic → ultra-wide horizontal composition, landscape or architectural grandeur
  H. Lighting — one specific choice: pre-dawn blue | warm candlelight | storm-filtered gold | overcast flat | harsh noon | volumetric shafts
  I. Color palette — two or three dominant colors: e.g. "muted ochre, slate grey, faint amber"
  J. Self-critique — before writing: Is this specific? Does it avoid every banned pattern above?
     Have I confirmed every element belongs to the same cultural context (step A)?
     Have I repeated an environment or metaphor from another scene in this batch?
     Would a documentary director choose this exact frame?
     Does this image naturally connect to the scene before and after it?

══════════════════════════════════════════════════
PROMPT STRUCTURE — every prompt must include ALL 10 elements
══════════════════════════════════════════════════

Write one flowing paragraph per scene that naturally weaves in all of these:
  1. Scene objective — the visual idea or emotion being conveyed
  2. Main subject — the hero of the frame (person, object, or environment)
  3. Environment — specific location with two or three concrete physical details
  4. Emotional tone — the dominant feeling communicated through composition
  5. Camera shot — the ASSIGNED shot type for this scene (from the brackets)
  6. Lens / composition — focal length, depth of field, rule-of-thirds or symmetry
  7. Lighting — one specific, meaningful light source or quality
  8. Color palette — two or three dominant colors that carry the emotion
  9. Cinematic details — texture, atmosphere, subtle motion, or environmental storytelling
  10. Quality markers — include "no text, no watermark, photorealistic" in every prompt

══════════════════════════════════════════════════
VISUAL CONTINUITY
══════════════════════════════════════════════════

This is ONE documentary, not 30 independent images:
  — Each scene must feel like it could be the next cut in a real film
  — The protagonist (if any) maintains the same appearance across all scenes
  — The color temperature should shift gradually: warm → cool → warm (or follow a deliberate arc)
  — Avoid sudden unexplained location jumps — use transitional environments when needed
  — Do NOT create one masterpiece per scene; create one coherent visual journey

══════════════════════════════════════════════════
WRITING RULES
══════════════════════════════════════════════════

— One natural flowing paragraph per scene.
— Begin with the scene's strongest visual element — never with "A person" or "The camera."
— 60–90 words per scene. Hero frame: 85–110 words.
— Weave camera shot, angle, and lighting into the description naturally.
— Vary endings — do NOT paste the same phrase at the close of every scene.
— Include in every prompt: no text, no watermark, photorealistic.
— The {style_label} feeling should come through the imagery — not by stating it as a keyword.

Return ONE JSON array. Index values MUST match the scene numbers exactly — do not reset to 1.
[{{"index": N, "visual_prompt": "...", "visual_metadata": {{"version": 1, "era": "ANCIENT|HISTORICAL|MODERN|SYMBOLIC|TRANSITIONAL", "narrative_role": "STORY|ANALOGY|METAPHOR|EXPLANATION|ESTABLISHING|CTA", "environment": "FOREST|TEMPLE|ASHRAM|KINGDOM|BATTLEFIELD|CITY|OFFICE|HOME|MOUNTAIN|RIVER|ABSTRACT|COSMIC", "mood": "PEACEFUL|MYSTERIOUS|REVERENT|REFLECTIVE|HOPEFUL|FEARFUL|CURIOUS|LONELY|DETERMINED", "visual_style": "DOCUMENTARY|CINEMATIC|REALISTIC|DREAMLIKE|PAINTING|ANIME|WATERCOLOR", "allow_modern_objects": true_or_false, "reason": "..."}}}}]

═════════════════════════════════════════════════
VISUAL METADATA — classify every scene
═════════════════════════════════════════════════

For EACH scene, include a visual_metadata object with these exact fields:

  version: 1 (always)

  era: one of ANCIENT | HISTORICAL | MODERN | SYMBOLIC | TRANSITIONAL
    ANCIENT — pre-medieval, mythological, Vedic, scriptural settings
    HISTORICAL — documented history, medieval, early modern
    MODERN — contemporary, office, city, technology
    SYMBOLIC — timeless concepts, consciousness, abstract
    TRANSITIONAL — ancient and modern coexist intentionally

  narrative_role: one of STORY | ANALOGY | METAPHOR | EXPLANATION | ESTABLISHING | CTA
    STORY — advancing the narrative
    ANALOGY — drawing a comparison to familiar life
    METAPHOR — visual representation of an abstract idea
    EXPLANATION — clarifying a concept
    ESTABLISHING — setting the scene or context
    CTA — call to action or closing

  environment: one of FOREST | TEMPLE | ASHRAM | KINGDOM | BATTLEFIELD | CITY |
                OFFICE | HOME | MOUNTAIN | RIVER | ABSTRACT | COSMIC
    Pick the single best match. Use ABSTRACT or COSMIC only for symbolic scenes.

  mood: one of PEACEFUL | MYSTERIOUS | REVERENT | REFLECTIVE | HOPEFUL |
        FEARFUL | CURIOUS | LONELY | DETERMINED
    Pick the dominant emotion the scene should convey.

  visual_style: one of DOCUMENTARY | CINEMATIC | REALISTIC | DREAMLIKE |
                 PAINTING | ANIME | WATERCOLOR
    Independent of era. DOCUMENTARY is the default for this channel.

  allow_modern_objects: boolean (true or false)
    ANCIENT or HISTORICAL era → false
    MODERN era → true
    SYMBOLIC → planner decides
    TRANSITIONAL → true

  reason: short string explaining the classification (for debugging only)

Choose values that match the narration content. Do not invent metadata that contradicts the scene.

═════════════════════════════════════════════════
SCENES  (shot type pre-assigned in [brackets])
═════════════════════════════════════════════════
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

    # V4: include shot_type in [brackets] when present (injected by ImagePromptEngineV4)
    scene_lines = []
    for s in scenes:
        shot = s.get("shot_type", "")
        shot_tag = f" [{shot}]" if shot else ""
        scene_lines.append(f"Scene {s['index']}{shot_tag}: {s.get('narration', '')}")
    scene_list = "\n".join(scene_lines)

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
