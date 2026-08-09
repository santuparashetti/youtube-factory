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

# ── Entity Grounding Prompts ───────────────────────────────────────────────────

ENTITY_EXTRACTION_PROMPT = """\
You are a script analyst. Read the following narration segment carefully.

NARRATION:
{narration}

Answer ONLY in JSON. Do not add any explanation.

{{
  "characters": [list every being that is literally present — animal, human, mythological],
  "environment": [list the setting elements mentioned or strongly implied],
  "objects": [list any specific physical objects mentioned],
  "human_classification": one of: "no_human_allowed" | "human_optional" | "human_required" | "named_person_required" | "human_symbolic",
  "human_names": [list only named humans — e.g. "Bhagiratha", "Vinoba Bhave"],
  "human_description": "brief description if a human is present but unnamed, else empty string",
  "scene_category": one of: "animal_only" | "human_named" | "human_implied" | "human_symbolic" | "abstract" | "brand_card"
}}

RULES:
- Only include what is LITERALLY in the narration. Do NOT infer or add.
- If the narration is about an eagle and chick with no human present, human_classification = "no_human_allowed".
- If the narration says "you feel it within" or "you just watch", that is a VIEWER ADDRESS
  — no human character is present in the scene. human_classification = "no_human_allowed".
- Poetic/rhetorical questions ("Can Indians not become scientists?") have no characters present.
  scene_category = "abstract". human_classification = "no_human_allowed".
- A metaphorical human ("one day I too should soar") is NOT a character. human_classification = "no_human_allowed".
- If a specific named person is the clear subject, human_classification = "named_person_required".
- If a human is clearly required but not named, human_classification = "human_required".
- If a human might appear but is not required, human_classification = "human_optional".
- human_symbolic: use this scene_category (with human_classification = "human_optional") when the
  narration is philosophical or addresses a universal human quality (wisdom, craft, endurance) and
  a symbolic human figure — an elderly sage, artisan hands, a distant figure in a landscape — is
  APPROPRIATE even though no specific person is named. Use this when the narration contains phrases
  like "ancient teachers", "the wise", "your hands", "your eyes", "your feet", or philosophical
  second-person address. Do NOT use "no_human_allowed" for these — a symbolic human is expected.
- animal_only: use ONLY when the animal IS the story — the unambiguous primary subject being
  described, not an incidental mention. "The chick flew" → animal_only.
  "Birds sing and dance in the Sharad season" → abstract (the season is the subject, birds are
  incidental imagery) — do NOT classify incidental animal mentions as animal_only.
"""

SCENE_ANALYSIS_PROMPT = """\
You are a documentary script analyst. Analyze the following narration scene for visual storytelling.

NARRATION:
{narration}

Answer ONLY in JSON. Do not add any explanation.

{{
  "scene_id": {scene_id},
  "characters": [list every being LITERALLY present — animal, human, mythological],
  "allowed_characters": [same as characters — these are the ONLY entities permitted in the visual],
  "primary_subject": "the single most important subject in this scene",
  "secondary_subjects": ["other subjects present, if any"],
  "environment": "specific location or setting from the narration",
  "primary_action": "what is happening in one phrase",
  "emotional_beat": "dominant emotion: wonder|mystery|hope|peace|grief|isolation|determination|reverence|longing|fear|regret",
  "story_goal": "what this scene reveals about the story in one phrase",
  "human_requirement": "required|optional|forbidden|permitted_symbolic",
  "named_person": "named human if present, else empty string",
  "camera_focus": "what the camera should look at",
  "scene_characters": [only characters literally present — subject to forbidden_chars check],
  "scene_objects": [specific physical objects literally present],
  "forbidden_characters": [characters that must NOT appear — e.g. generic man, woman, child, monk],
  "forbidden_objects": [objects or elements that must NOT appear in the visual],
  "visual_focus": "the single focal point the viewer's eye should land on",
  "continuity_reference": "reference to previous scene for character/appearance continuity, or empty string",
  "story_time": "time of day or era implied by narration (e.g. dawn, golden hour, ancient) or empty string",
  "camera_constraints": "specific camera constraints from narration (e.g. wide shot only, no close-up) or empty string"
}}

RULES:
- Only include what is LITERALLY in the narration. Do NOT invent characters, actions, or settings.
- If the narration is about an eagle and chick with no human present, characters = ["Mother Eagle", "Eagle Chick"].
  human_requirement = "forbidden". named_person = "".
- If the narration says "you feel it within" or "you just watch", that is a VIEWER ADDRESS —
  no human character is present. characters = []. human_requirement = "forbidden".
- A metaphorical human ("one day I too should soar") is NOT a character. Do not list it.
- ANALOGY / EXAMPLE SCENES: If the narration describes people as examples or analogies
  ("the person who has a house wants a bigger one", "someone who earns and earns"),
  these are NOT viewer-address and NOT purely metaphorical. They describe observable
  human behavior. Use human_requirement = "permitted_symbolic" and allow the described
  person as a symbolic character. Do NOT classify these as "forbidden".
- OBJECT RULE: If the narration explicitly mentions a physical object ("gold", "coin",
  "river", "body"), do NOT add it to forbidden_objects. Only forbid objects that would
  be anachronistic, invented, or contradictory to the narration. Objects the narration
  names — even in a philosophical context — are permitted in the visual.
- Never invent: man, woman, monk, traveller, sage, observer, narrator, silhouette, child
  unless explicitly present in the narration.
- Never replace animals with humans.
- forbidden_characters should include generic humans/animals that would be wrong as invented substitutes.
- If no characters are present, characters = [] and allowed_characters = [].
- story_time, visual_focus, camera_constraints are optional — use empty string when not implied.
- continuity_reference is only needed when the narration clearly follows a previous scene's protagonist.
- human_requirement = "permitted_symbolic": use when the narration is philosophical or addresses a
  universal human quality (wisdom, craft, endurance) — a symbolic human figure (elderly sage,
  artisan hands, a distant figure) is APPROPRIATE though no one is named. Narration containing
  "ancient teachers", "the wise", "your hands", "your eyes", "your feet", philosophical
  second-person address, or ANALOGY SCENES describing people as examples should use this
  instead of "forbidden".
- animal_only classification (reflected via primary_subject) requires the animal to be the
  unambiguous primary subject. "Birds sing in the Sharad season" → the season/mood is the primary
  subject, not the birds — do not treat incidental animal mentions as requiring an animal-only shot.
"""

FAITHFULNESS_VALIDATION_PROMPT = """\
You are a QA reviewer for image prompt generation.

NARRATION:
{narration}

SCENE CATEGORY: {scene_category}
HUMAN_CLASSIFICATION: {human_classification}

GENERATED VISUAL PROMPT:
{visual_prompt}

Answer ONLY in JSON:
{{
  "pass": true/false,
  "violation": "describe the violation if fail, else empty string",
  "severity": "critical" | "minor" | "none"
}}

CHECK FOR:
1. If human_classification=no_human_allowed, does the prompt contain any human figure
   (man, woman, person, figure, face, hand, body)? → FAIL (critical)
2. If scene_category="animal_only", is the animal the clear subject? → FAIL if not (critical)
3. If human_classification=named_person_required, is the named person described specifically
   (not as a generic "man in grey linen")? → FAIL if generic (minor)
4. Does the prompt describe anything NOT in the narration without strong visual justification? → FAIL (minor)
"""

# ── Task 2.6 Part 2 — LLM validation for ENVIRONMENT_MISMATCH / ─────────────
# HUMAN_CLASSIFICATION_VIOLATED. Cheap, targeted, binary check — only called
# when deterministic checks leave exactly these two failure types remaining.
LLM_VALIDATION_PROMPT = """\
You are a visual prompt reviewer. Answer in JSON only.

SCENE CATEGORY: {scene_category}
HUMAN CLASSIFICATION: {human_classification}
REQUIRED ENVIRONMENT: {environment}
VISUAL PROMPT: {visual_prompt}

Check:
1. ENVIRONMENT: Does the prompt depict a setting that matches or is compatible with the required environment?
   (Symbolic/abstract imagery that evokes the environment counts as a match.)
2. HUMAN: Does the prompt correctly follow the human classification rule?
   - NO_HUMAN_ALLOWED: no human figures, body parts, or implied human presence
   - HUMAN_REQUIRED / HUMAN_SYMBOLIC / HUMAN_OPTIONAL: appropriate human presence

Return ONLY this JSON, nothing else:
{{"environment_ok": true/false, "human_ok": true/false, "reason": "one sentence"}}"""


def build_llm_validation_prompt(
    scene_category: str,
    human_classification: str,
    environment: str,
    visual_prompt: str,
) -> str:
    """Build the Task 2.6 LLM validation prompt for a single scene."""
    return LLM_VALIDATION_PROMPT.format(
        scene_category=scene_category,
        human_classification=human_classification,
        environment=environment or "unspecified",
        visual_prompt=visual_prompt,
    )


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
SCRIPT QUALITY GATE — run before planning; BLOCK if any check fails
──────────────────────────────────────────────────────────────
Before producing any scene JSON, silently run all 4 checks on the script below.
If any check fails, do NOT output scene JSON. Instead output ONLY:
  QUALITY_GATE_FAIL: <check name> — <one sentence describing the specific failure>

[ ] Single visual world — only one metaphor universe exists in the script.
    If more than one visual world is present → FAIL.
[ ] No repeated beats — a repeated beat is when two paragraphs make the SAME point
    at the SAME narrative stage with nothing new added between them. A story-level
    observation (about the eagle) and its later philosophical conclusion (about the
    human) are NOT repeated beats — they are the story-to-insight progression required
    by the pipeline formula. A thematic echo or callback is NOT a repeated beat. Only
    flag as FAIL if the identical idea appears twice within the same narrative stage —
    both in story, or both in the human parallel — with no development between them.
    If the identical idea appears twice within the same narrative stage with no
    development → FAIL.
[ ] Hook-to-ending loop — identify the final narrative sentence by finding the last
    sentence BEFORE any of these brand wrap markers: 'This is the Atma Theory',
    'If these ideas resonate', 'Clear mind', 'Meaningful life', 'join us on this
    journey'. The brand wrap is NOT part of the story and must be completely ignored
    for this check. Evaluate ONLY whether the final narrative sentence echoes or
    resolves the opening image. If it does, this check PASSES regardless of what
    the brand wrap says.
    If the final narrative sentence does not echo or resolve the opening image → FAIL.
[ ] No disclaimer paragraphs — a disclaimer paragraph is one that LISTS or EXPLAINS
    hardships directly to the viewer as facts about the world ('poverty is real',
    'loss is real', 'circumstances can narrow choices'). This check does NOT apply
    to: (a) story beats about the eagle's fear or situation, (b) practice or action
    sections that frame what a discipline does and does not promise, (c) philosophical
    statements about the nature of fear or identity. Only flag as FAIL if the paragraph
    reads as a direct explanatory statement of worldly hardship addressed to the viewer,
    with no story or character grounding.
    If such a direct explanatory hardship paragraph exists → FAIL.

Only proceed to scene planning if all 4 checks PASS.

──────────────────────────────────────────────────────────────
FILM EDITOR MENTAL MODEL — internalize before planning
──────────────────────────────────────────────────────────────
Think like a film editor, not a transcriptionist. Your script is 40 hours of footage.
Your job is to deliver a 6–8 min film. The best editors are ruthless — they cut good material
to serve the great material. Every scene must justify its existence in a 360–480 second runtime.

──────────────────────────────────────────────────────────────
RULES
──────────────────────────────────────────────────────────────
- You are SELECTING the best 18–25 scenes from the script — not converting every paragraph
  into a scene. Each scene must earn its place. For every scene ask: Does this deliver a new
  emotion, insight, or narrative beat that no prior scene already achieved? If not, cut it.
- Short dramatic lines (under 15 words): group 3-5 related lines into one scene.
- Longer paragraphs (40+ words): one paragraph = one or two scenes.
- Strip all markdown from narration: plain spoken text only, no **, ##, *, etc.
- Use EXACT words from the script verbatim in narration. Do NOT paraphrase.
- Duration: word_count ÷ 2 seconds (slow meditative pace, ~120 wpm).
- Target 18–25 scenes total.

HARD DURATION BUDGET — MANDATORY:
- Total video = 6–8 minutes = 360–480 seconds.
- Calculate each scene's duration_seconds using: word_count ÷ 2.
- Sum all scene durations before outputting. If total > 480 seconds, remove or compress
  the lowest-impact scenes first. Do not output scenes that exceed 480 seconds total.

──────────────────────────────────────────────────────────────
HOOK (first 15 seconds — critical for retention)
──────────────────────────────────────────────────────────────
- The first 2–3 scenes MUST be SHORT: 6–10 words maximum each (3–5 seconds).
  Any hook scene exceeding 10 words must be split or trimmed. No exceptions.
- The viewer must feel tension or curiosity within the first 15 seconds —
  no setup, no context-setting, no slow build.
- Open with the most provocative, surprising, or emotionally charged line.
- Each hook scene = one punchy idea. Do NOT group multiple sentences into scene 1.
- Avoid slow scene-setting in the opening — drop the viewer into the most compelling moment.

──────────────────────────────────────────────────────────────
MANDATORY PRE-OUTPUT CHECKS
──────────────────────────────────────────────────────────────
Before outputting, run all three checks in order. This is not optional.

CHECK 1 — Duration Budget:
  Sum all scene duration_seconds values.
  If total > 480 seconds: remove or compress lowest-impact scenes until total ≤ 480.
  If total < 360 seconds: verify no essential scenes were cut.
  Do not output until total is within 360–480 seconds.

CHECK 2 — Scene Selection Quality:
  For each scene, ask: Does this deliver a new emotion, insight, or narrative beat?
  If any scene repeats what a prior scene already achieved: cut it.

CHECK 3 — Consecutive Scene Scan:
  Scan all scenes in order. Flag any two consecutive scenes that share the same mood,
  use the same shot type, or deliver the same narrative beat.
  Resolve every flag by merging or cutting one of the pair.

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


# ── Task 2.8 — Storyboard Mode + Strict Scene Fidelity ────────────────────────
# Must be the first thing the generation model reads (position 0 in the
# template) — shapes how the model treats visual_prompt vs narration.

STORYBOARD_MODE_BLOCK = """\
STORYBOARD MODE

Generate only what is explicitly visible in the visual_prompt.
The visual_prompt is the authoritative source.
The narration provides emotional context only.
Do NOT invent people, animals, objects, actions, or environments not explicitly described.
Preserve intentional emptiness and negative space.
If uncertain, omit rather than invent.
Match the requested shot type, camera angle, composition, lighting, and environment exactly.
"""

STRICT_SCENE_FIDELITY_BLOCK = """\
STRICT SCENE FIDELITY

- The visual_prompt is the single source of truth.
- Narration influences only mood and storytelling intent, never the visible subjects.
- Never invent characters, animals, props, architecture, or actions.
- Never continue subjects from previous scenes unless explicitly requested.
- Preserve intentional emptiness and negative space.
- When uncertain, omit rather than invent.
- Match the requested camera angle, composition, lighting, and scale exactly.
- Treat every scene as an independent storyboard frame, not an artistic reinterpretation.
- Verify that the generated image matches the visual_prompt before considering the scene complete.
"""

# Condensed header prepended to every visual_prompt written to
# image_prompts_manifest.json / IMAGE_PROMPTS.md — the manual-image-gen path
# (Leonardo, Midjourney, etc.) never sees the generation template above, so
# the instruction has to travel with the prompt text itself.
STORYBOARD_HEADER = (
    "16:9 aspect ratio. "
    "Storyboard Mode. "
    "The visual_prompt is the authoritative source. "
    "Do not invent people, animals, objects, actions, or environments "
    "not explicitly described. "
    "Preserve intentional emptiness and negative space. "
    "If uncertain, omit rather than invent. "
    "Match shot type, camera angle, composition, lighting, and "
    "environment exactly.\n\n"
)


def prepend_storyboard_header(visual_prompt: str) -> str:
    """Prepend the storyboard header to a final output prompt. Idempotent."""
    if visual_prompt.startswith("16:9 aspect ratio. Storyboard Mode"):
        return visual_prompt
    return STORYBOARD_HEADER + visual_prompt


_VISUAL_PROMPTS_TEMPLATE = """\
""" + STORYBOARD_MODE_BLOCK + "\n" + STRICT_SCENE_FIDELITY_BLOCK + """
⚠ ABSOLUTE CONSTRAINTS — read before generating:
FORBIDDEN WORDS (never use in any prompt):
- silhouette → describe the actual subject directly
- face, faces → describe expression or gaze without naming anatomy
- profile → use camera angle instead (e.g. "side-angle shot")
- shoulder, shoulders, torso, chest, arm, arms, leg, legs, forehead → forbidden
- eye, eyes → only permitted when preceded by an animal name (e.g. "eagle's eye")
- hand, hands, finger, fingers → only permitted in human_required/human_symbolic scenes
- text, writing, typography, watermark → never in any image prompt
- ethereal glow → use specific lighting (e.g. "golden hour light", "soft diffused light")

ANIMAL_ONLY SCENES: if human_classification=NO_HUMAN_ALLOWED, generate ONLY the
animal subject. No human anatomy, no human observers, no implied human presence.

You are a documentary film director — not an image prompt generator.
Your task: direct {num_scenes} scenes as ONE coherent cinematic documentary for a {style_label} video.
This is a visual story, not a collection of independent images. Every frame connects to the next.

    {style_guide}

    {entity_constraints_section}{scene_analysis_section}{prev_context_block}══════════════════════════════════════════════════
STORY-FIRST RULES (highest priority — never override these)
═════════════════════════════════════════════════════

1. The visual must describe what is LITERALLY in the narration — not a rewrite of the story.

METAPHOR-LITERAL RULE — when the narration contains figurative language, depict the LITERAL
story moment, never the figure of speech as a physical object:
  ✗  "it is a map of a mind that has lost its way" → a leather map on a table
  ✓  "it is a map of a mind that has lost its way" → the literal scene: the crowd dispersing
     from the riverbank, the untouched coins, the still water — whatever the story moment is
  ✗  "a sea of grief" → an ocean
  ✓  "a sea of grief" → the person experiencing grief, in their actual setting
  ✗  "he burned every bridge" → literal flames on a bridge
  ✓  "he burned every bridge" → the person walking alone from a door that is closing
  The literal story moment always takes priority. Metaphors in narration are prose devices —
  never render them as physical objects.

2. Characters may ONLY come from the narration or Scene Analysis below.
   NEVER invent: man, woman, monk, traveller, sage, observer, narrator, silhouette, child
   unless explicitly present. NEVER replace animals with humans.
3. Narration determines: story beat, action, emotion, exact cinematic moment.
4. Visual Prompt describes ONLY: composition, framing, camera, lens, lighting, environment,
   atmosphere, colours. It must never rewrite the story.
5. Priority: Story > Narration > Scene Analysis > Camera > Artistic enhancement.

═════════════════════════════════════════════════════
BANNED — these patterns are forbidden
═════════════════════════════════════════════════════

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

═════════════════════════════════════════════════════
HUMAN SUBJECT QUALITY — mandatory when a human appears in the scene
═════════════════════════════════════════════════════

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

═════════════════════════════════════════════════════
CLOTHING & CULTURAL AUTHENTICITY — mandatory for every human scene
═════════════════════════════════════════════════════

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

═════════════════════════════════════════════════════
CULTURAL AUTHENTICITY — identify once, apply throughout
═════════════════════════════════════════════════════

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

═════════════════════════════════════════════════════
CHARACTER BIBLE
═════════════════════════════════════════════════════

Scan the narrations below. If a recurring protagonist appears (referred to as "he", "she", "you", or as a specific described person):
  — Choose ONE physical description and lock it in: age, build, ethnicity, clothing
  — Example: "a lean man in his early 40s, close-cropped dark hair, plain grey linen shirt, worn dark trousers"
  — Use the SAME description in every scene where a human figure appears
  — If the narration is philosophical with no clear protagonist, use environments, objects, and symbols — do NOT invent random human subjects per scene

═════════════════════════════════════════════════════
STORYBOARD — complete this before writing any prompt
═════════════════════════════════════════════════════

1. Read all {num_scenes} narrations below.
2. Define the emotional arc: opening mood → mid-point peak → closing resolution.
3. Assign each scene a role: Hook | Establishing | Rising | Revelation | Reflection | Symbolic | Resolution
   HOOK scenes (first 2–3): the most visually striking, emotionally gripping frames. These must arrest scrolling — think thumbnail-worthy intensity, dramatic angles, vivid contrast. NOT gentle establishing shots.
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

═════════════════════════════════════════════════════
PROMPT STRUCTURE — every prompt must include ALL 10 elements
═════════════════════════════════════════════════════

Write one flowing paragraph per scene that naturally weaves in all of these:
  1. Scene objective — the visual idea or emotion being conveyed
  2. Main subject — the hero of the frame (person, object, or environment)
  3. Environment — specific location with two or three concrete physical details
  4. Emotional tone — the dominant feeling communicated through composition
  5. Camera shot — the ASSIGNED shot type for this scene (from the brackets)
  6. Lens / composition — focal length, depth of field, rule-of-thirds or symmetry;
     state where the main subject sits in the frame using ONE of these exact phrases:
     "positioned on the left", "positioned on the right", or "centered in the frame"
  7. Lighting — one specific, meaningful light source or quality
  8. Color palette — two or three dominant colors that carry the emotion
  9. Cinematic details — texture, atmosphere, subtle motion, or environmental storytelling
  10. Quality markers — include "no text, no watermark, photorealistic" in every prompt

═════════════════════════════════════════════════════
VISUAL CONTINUITY
═════════════════════════════════════════════════════

This is ONE documentary, not 30 independent images:
  — Each scene must feel like it could be the next cut in a real film
  — The protagonist (if any) maintains the same appearance across all scenes
  — The color temperature should shift gradually: warm → cool → warm (or follow a deliberate arc)
  — Avoid sudden unexplained location jumps — use transitional environments when needed
  — Do NOT create one masterpiece per scene; create one coherent visual journey

═════════════════════════════════════════════════════
WRITING RULES
═════════════════════════════════════════════════════

— One natural flowing paragraph per scene.
— Begin with the scene's strongest visual element — never with "A person" or "The camera."
— 60–90 words per scene. Hero frame: 85–110 words.
— Weave camera shot, angle, and lighting into the description naturally.
— Vary endings — do NOT paste the same phrase at the close of every scene.
— Include in every prompt: no text, no watermark, photorealistic.
— The {style_label} feeling should come through the imagery — not by stating it as a keyword.

Return ONE JSON array. Index values MUST match the scene numbers exactly — do not reset to 1.
[{{"index": N, "anchor_role": "primary|spectator|absent", "visual_prompt": "...", "scene_group_id": "snake_case_group_name_or_null", "environment_anchor": "canonical environment description or null", "visual_metadata": {{"version": 1, "era": "ANCIENT|HISTORICAL|MODERN|SYMBOLIC|TRANSITIONAL", "narrative_role": "STORY|ANALOGY|METAPHOR|EXPLANATION|ESTABLISHING|CTA", "environment": "FOREST|TEMPLE|ASHRAM|KINGDOM|BATTLEFIELD|CITY|OFFICE|HOME|MOUNTAIN|RIVER|ABSTRACT|COSMIC", "mood": "PEACEFUL|MYSTERIOUS|REVERENT|REFLECTIVE|HOPEFUL|FEARFUL|CURIOUS|LONELY|DETERMINED", "visual_style": "DOCUMENTARY|CINEMATIC|REALISTIC|DREAMLIKE|PAINTING|ANIME|WATERCOLOR", "allow_modern_objects": true_or_false, "reason": "..."}}}}]

Every scene object MUST include "scene_group_id" and "environment_anchor" explicitly, even when null:
  "scene_group_id": "snake_case_group_name"  ← or null if this scene is not part of a group
  "environment_anchor": "canonical environment description"  ← or null if not part of a group
Do NOT omit these fields. Scenes with no group: output "scene_group_id": null, "environment_anchor": null

═════════════════════════════════════════════════════════
VISUAL METADATA — classify every scene
═════════════════════════════════════════════════════════

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

════════════════════════════════════════════════════
VISUAL ENGAGEMENT & TONE MATCHING
════════════════════════════════════════════════════

A scene's visual must serve the emotional beat, not just the keyword:

  MOTION — if narration extends past ~8 seconds on one idea without a new visual
  anchor, the visual must progress: camera movement, changing subject, passing time,
  environmental shift. Holding a single static frame for many seconds is forbidden.

  VISUAL VARIETY — across the full scene list:
    — No shot type (establishing / wide / medium / close-up / drone / etc.) may repeat
      in more than 2 consecutive scenes. Break the run with a contrasting shot type.
    — Alternate between distant and intimate shots at least once every 4 scenes.
    — At least 1 in every 5 scenes must be a close-up or extreme close-up — texture,
      object, hands, eyes — to give the eye somewhere to land.
    — At least 1 in every 6 scenes must introduce clear movement in the frame (action,
      crowd, water, wind, subject in motion) rather than a still environment.

  TONE MATCH — the image's emotional register must match the narration's:
    resilience / strength → forward motion, open space, human presence, warm light
    warmth / intimacy → golden light, soft shadows, domestic detail, safety
    grief / loss → muted tones, still water, open landscape, solitary figure
    NEVER pair a resilience monologue with desolate / abandoned / dark imagery.
    NEVER pair warmth/intimacy with shadow-absorbed or cold visual environments.

  BRIGHTNESS — for beats coded as warmth, safety, hope, or human connection:
    floors are bright natural daylight, golden hour, warm interior light, soft fill.
    If the narration is somber (grief, fear, loss) then darker lighting is fine.
    Default is NOT dark mood — only darken when the emotional beat requires it.

══════════════════════════════════════════════════════
VISUAL CHARACTER & SCENE RULE (apply to every visual_prompt you write)
══════════════════════════════════════════════════════

Priority order — strict:

1. SYMBOLIC / ABSTRACT — always prefer. Concept, metaphor, object, nature, texture.
   No human character needed. Use this whenever the scene allows it.

2. WESTERN / ENGLISH-SPEAKING CHARACTER — default when a human is genuinely needed.
   Appearance: European or American. Setting: Western city, office, library, countryside,
   modern home, international airport. Neutral-but-Western feel.

3. INDIAN / SOUTH ASIAN character or setting — ONLY if this specific scene in the
   script is about a named Indian person, Indian historical event, or an India-specific
   statistic. Not a default. Not when in doubt.

Never use Indian street scenes, South Asian faces, or Indian cultural markers as generic
"atmosphere" for philosophical, psychological, or motivational content.
The target viewer is English-speaking (US, UK, AU, CA).

══════════════════════════════════════════════════════
KAI ANCHOR CHARACTER — SCENE CLASSIFICATION (PIPELINE INTERNAL)
══════════════════════════════════════════════════════

For every scene you generate, you must:
  1. Decide the `anchor_role` — one of: "primary", "spectator", or "absent"
  2. Build the `visual_prompt` with Kai's spec injected per that role

"Kai" is a pipeline-internal identifier. It must NOT appear in any text the viewer
sees, and it must NOT appear in the visual_prompt either. In visual_prompts you write,
Kai's physical description appears — his name never does.

CLASSIFICATION RULES

"absent" — No human character needed or appropriate.
Assign when: the scene is fully symbolic, atmospheric, or abstract — a metaphor,
a data point, a texture, an environment. No human presence would strengthen it.

"primary" — Kai is the subject; he is feeling, experiencing, or reflecting.
Assign when: the scene is about someone experiencing an emotion, making a choice,
or sitting with a realisation. No named real historical figure is present.
ALWAYS assign primary to:
- The first non-symbolic scene (establishes Kai for the viewer)
- The climax breath scene (his realisation moment)
- The final scene before the brand card (arc completes)

"spectator" — A real figure is primary; Kai witnesses.
Assign when: the scene depicts a named historical person, a documented real event,
or a specific cultural/factual moment where a real character takes centre stage.
Kai is present at the edge — a witness — but the frame belongs to the real figure.

PROMPT CONSTRUCTION BY ROLE

### PRIMARY — STRICT CONSTRUCTION RULE

anchor_role = "primary" means Kai IS the subject. The visual_prompt MUST begin
with the compressed Kai spec, verbatim, before any scene-specific staging.

The compressed spec is fixed. Copy it exactly:
"Lean young man, late 20s, short dark hair, light stubble, simple dark shirt,
plain trousers, calm expression"

Then add " — " and the scene-specific staging (what he is doing, where, the mood).

CORRECT:
"Lean young man, late 20s, short dark hair, light stubble, simple dark shirt,
plain trousers, calm expression — sitting alone in an empty boardroom, hands
flat on the table, staring at the door. Low afternoon light."

WRONG (never do this):
"A man sits alone in an empty boardroom..." [no Kai spec at the start]
"A single human figure..." [too generic — missing the locked spec]

### CLOSING SCENE RULE

The last non-asset scene in every video MUST be anchor_role = "primary".
This is the scene where Kai's arc completes — regardless of what the script
says, Kai must be the primary subject here. Do not classify the closing scene
as "spectator" or "absent" under any circumstances.

SPECTATOR visual_prompt structure:
Write the historical/factual scene first (primary subject, setting, action).
Then append the brief Kai descriptor at the end (verbatim):
"At the edge of the frame, a young man — lean, dark hair, simple dark shirt —
stands watching in silence."
Example:
"A man in late 19th century clothing writes feverishly at a cluttered desk by
candlelight, papers scattered across the floor, ink-stained hands moving without
pause. At the edge of the frame, a young man — lean, dark hair, simple dark
shirt — stands watching in silence."

ABSENT visual_prompt structure:
Standard symbolic/atmospheric prompt only. No Kai reference at all.
Example:
"A cracked hourglass lying on its side on a stone floor, sand pooled beneath
it, soft diffused grey light. No human figure."

---

## CHARACTER COMPLETENESS RULE (applies to ALL scenes)

Every human character visually present in a scene MUST be explicitly described
in the visual_prompt. Do not leave any character's appearance to the image
generator's assumption — generators will default to whatever is convenient,
which destroys cross-scene consistency.

For EVERY non-Kai character in the scene, specify all five of:

1. ROLE       — what they are in this scene (e.g. instructor, executive,
                scholar, villager, child)
2. APPEARANCE — age range, build, skin tone, hair. Default: Western European
                (light to medium complexion, Western hair and features) UNLESS
                the script explicitly names a cultural identity for this
                character (e.g. "a Japanese elder", "an African-American CEO")
3. CLOTHING   — specific garment, color, style
                (e.g. "simple grey linen shirt, dark trousers"
                      "formal dark navy business suit, white shirt, slim tie")
4. POSITION   — where in the frame relative to the composition
                (e.g. "centre-left", "background right", "foreground")
5. ACTION     — what they are doing in this exact moment
                (e.g. "extending a payment envelope", "standing at attention",
                       "turning to walk away")

For GROUP characters (e.g. a group of executives), describe the GROUP as a unit:
  - Number: approximate count ("8 to 10 executives")
  - Shared appearance: "Western European appearance, late 40s to 60s"
  - Shared clothing: "formal dark business suits"
  - Formation: "standing in neat rows"
  - Expression/action: "strained forced smiles"

Kai's appearance is locked via KAI_COMPRESSED_SPEC — if his spec is already
in the prompt, do NOT re-describe him here. Just add the secondary characters.

NEVER write: "a man in a suit", "some executives", "an instructor"
ALWAYS write: "a man in his 50s, Western European, silver hair, simple grey
linen shirt and dark trousers, standing centre-left, turning to walk away"

## CROSS-SCENE CHARACTER LOCKING (within a scene_group)

If this scene is part of a scene_group (scene_group_id is not null) AND it is
NOT the first scene in the group:

  For every secondary character who appeared in the first scene of this group,
  do NOT re-invent their description. Instead:
  1. Reference them explicitly: "same instructor as in scene [first_scene_id]"
  2. Repeat ONLY their key locking descriptors (role + clothing key item):
     "same instructor as in scene 5 — grey linen shirt, dark trousers"
  3. Then describe only what CHANGES for this character in this scene
     (their new action, position, expression).

This ensures the image generator receives a consistent character description
and does not re-invent the character's appearance between scenes.

EXAMPLE (scene 6, same group as scene 5):
  WRONG:  "An instructor in a grey coat collects payment..."
  CORRECT: "Same instructor as in scene 5 — grey linen shirt, dark trousers —
            now turning to walk away, holding a small payment envelope."

---

## SCENE CONTINUITY RULE

Before writing visual_prompts, identify SCENE GROUPS — consecutive scenes
that are part of the same story moment (same physical location, same time
of day, continuous or directly sequential action).

For each group:
  1. Assign a short descriptive scene_group_id to all scenes in the group
     (e.g. "laughing_club_park", "gallery_sale", "home_dawn_sequence")
     Use snake_case, max 4 words, descriptive of the location/moment.
     Scenes NOT part of any group: leave scene_group_id as null.

  2. For the FIRST scene in the group:
     - Write a full, detailed environment_anchor — the canonical description
       of this location: what type of space, time of day, lighting quality,
       color palette, key environmental elements.
     - This anchor is the CONTRACT that all subsequent scenes in the group
       must match exactly.
     Example environment_anchor:
     "Manicured urban park at pre-dawn. Cool flat blue light with first
      hints of golden hour on the skyline. City skyscrapers visible in
      morning haze behind. Dew on grass. Color palette: slate grey, muted
      navy, faint cold amber."

  3. For SUBSEQUENT scenes in the same group:
     - Open the visual_prompt with: "Continuous from scene [first_scene_id].
       [environment_anchor short form repeated verbatim]."
     - Only describe what CHANGES: character positions, actions, emotional
       state, specific focal point.
     - Do NOT re-describe the environment from scratch — reference the anchor.
     - The environment_anchor field for non-first scenes: copy the same value
       as the first scene in the group (for post-processing reference).

EXAMPLE — scenes 5 and 6 are both at the laughing club in the park:

Scene 5 (first in group):
  scene_group_id: "laughing_club_park"
  environment_anchor: "Manicured urban park at pre-dawn. Cool flat blue light
    with first hints of golden hour catching the city skyline. Skyscrapers
    in soft morning haze. Dew on grass. Slate grey, muted navy, cold amber."
  visual_prompt: "[full scene 5 description with environment included]"

Scene 6 (subsequent in same group):
  scene_group_id: "laughing_club_park"
  environment_anchor: "Manicured urban park at pre-dawn. Cool flat blue light
    with first hints of golden hour catching the city skyline. Skyscrapers
    in soft morning haze. Dew on grass. Slate grey, muted navy, cold amber."
  visual_prompt: "Continuous from scene 5. Manicured urban park, pre-dawn,
    cool blue light, city skyline in haze. [then: what changed — the payment
    transaction, characters' updated positions and actions]"

════════════════════════════════════════════════════
SCENES  (shot type pre-assigned in [brackets])
════════════════════════════════════════════════════
{scene_list}\
"""

_ENHANCE_TEMPLATE = _VISUAL_PROMPTS_TEMPLATE  # kept for backward compatibility


# Task 2.5 Fix B — environment values that are non-specific and must NOT
# generate a "REQUIRED SETTING" constraint (there is nothing concrete to pin).
_SKIP_ENVIRONMENT_VALUES: frozenset[str] = frozenset(
    {"unspecified", "abstract", "no specific location", ""}
)


def _build_environment_block(environment: str) -> str:
    """Per-scene hard environment constraint — one line, no paragraph
    (Task 2.5 token-efficiency rule). Empty string when environment is
    unspecified/abstract; injecting a constraint there would be misleading."""
    if not environment or environment.strip().lower() in _SKIP_ENVIRONMENT_VALUES:
        return ""
    return (
        f"REQUIRED SETTING: {environment}\n"
        "The image MUST be set here. Do not use a different location.\n"
    )


# ── Task 2.7 — Narrative-Visual Bridge ────────────────────────────────────────

VISUAL_ANCHOR_INJECTION = """\
REQUIRED VISUAL: {visual_anchor}
This is what the image MUST show. Build the entire prompt around this.
All style, lighting, camera, and era decisions serve this required visual.
"""

NARRATION_CONTEXT = """\
NARRATION FOR THIS SCENE:
"{narration}"
The visual prompt must be traceable to something in this narration.
"""


def _build_anchor_block(visual_anchor: str) -> str:
    """Mandatory-first-line visual directive derived from narration (Part 2).
    Empty when no anchor was produced — generation proceeds unchanged, no
    regression on scenes the batch anchor pass didn't cover."""
    if not visual_anchor:
        return ""
    return VISUAL_ANCHOR_INJECTION.format(visual_anchor=visual_anchor)


def _build_narration_context_block(narration: str) -> str:
    """Always-present narration block (Part 3) — the model must always be
    able to see what is being said, anchor or no anchor."""
    if not narration:
        return ""
    return NARRATION_CONTEXT.format(narration=narration)


def build_visual_prompts_prompt(
    scenes: list[dict],
    style: str | None = None,
    prev_context: list[str] | None = None,
    entity_constraints_section: str = "",
    scene_analysis_section: str = "",
) -> str:
    style_label = f"{style} documentary" if style else "cinematic documentary"
    num_scenes = len(scenes)

    # V4: include shot_type in [brackets] when present (injected by ImagePromptEngineV4)
    scene_lines = []
    for s in scenes:
        shot = s.get("shot_type", "")
        shot_tag = f" [{shot}]" if shot else ""
        narration = s.get("narration", "")
        scene_lines.append(f"Scene {s['index']}{shot_tag}: {narration}")

        anchor_block = _build_anchor_block(s.get("visual_anchor", ""))
        if anchor_block:
            scene_lines.append(anchor_block.rstrip("\n"))

        environment = s.get("scene_analysis", {}).get("environment", "")
        env_block = _build_environment_block(environment)
        if env_block:
            scene_lines.append(env_block.rstrip("\n"))

        narration_block = _build_narration_context_block(narration)
        if narration_block:
            scene_lines.append(narration_block.rstrip("\n"))
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
        entity_constraints_section=entity_constraints_section,
        scene_analysis_section=scene_analysis_section,
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
        entity_constraints_section="",
        scene_analysis_section="",
        scene_list=scene_json,
    )


def build_scene_analysis_prompt(narration: str, scene_id: int) -> str:
    """Build a prompt for structured scene analysis."""
    return SCENE_ANALYSIS_PROMPT.format(narration=narration, scene_id=scene_id)


def build_scene_analysis_section(analysis_map: dict[int, dict]) -> str:
    """Build the scene analysis section for the batch visual prompt."""
    if not analysis_map:
        return ""
    lines = ["SCENE ANALYSIS (source of truth for each scene):", ""]
    for scene_id, analysis in sorted(analysis_map.items()):
        lines.append(f"Scene {scene_id}:")
        lines.append(f"  characters={', '.join(analysis.get('characters', [])) or 'none'}")
        lines.append(f"  allowed_characters={', '.join(analysis.get('allowed_characters', [])) or 'none'}")
        lines.append(f"  scene_characters={', '.join(analysis.get('scene_characters', [])) or 'none'}")
        lines.append(f"  scene_objects={', '.join(analysis.get('scene_objects', [])) or 'none'}")
        lines.append(f"  forbidden_characters={', '.join(analysis.get('forbidden_characters', [])) or 'none'}")
        lines.append(f"  forbidden_objects={', '.join(analysis.get('forbidden_objects', [])) or 'none'}")
        lines.append(f"  primary_subject={analysis.get('primary_subject', '')}")
        lines.append(f"  secondary_subjects={', '.join(analysis.get('secondary_subjects', [])) or 'none'}")
        lines.append(f"  environment={analysis.get('environment', '')}")
        lines.append(f"  primary_action={analysis.get('primary_action', '')}")
        lines.append(f"  emotional_beat={analysis.get('emotional_beat', '')}")
        lines.append(f"  story_goal={analysis.get('story_goal', '')}")
        lines.append(f"  human_requirement={analysis.get('human_requirement', 'forbidden')}")
        lines.append(f"  named_person={analysis.get('named_person', '')}")
        lines.append(f"  visual_focus={analysis.get('visual_focus', '')}")
        lines.append(f"  continuity_reference={analysis.get('continuity_reference', '')}")
        lines.append(f"  story_time={analysis.get('story_time', '')}")
        lines.append(f"  camera_focus={analysis.get('camera_focus', '')}")
        lines.append(f"  camera_constraints={analysis.get('camera_constraints', '')}")
        lines.append("")
    lines.append("RULES:")
    lines.append("- ONLY use characters listed in allowed_characters for this scene.")
    lines.append("- NEVER use any character listed in forbidden_characters.")
    lines.append("- NEVER include any object listed in forbidden_objects.")
    lines.append("- NEVER invent: man, woman, monk, traveller, sage, observer, narrator, silhouette, child.")
    lines.append("- NEVER replace animals with humans.")
    lines.append("")
    return "\n".join(lines)


# ── Cinematic Pacing System ───────────────────────────────────────────────────
# Single batch LLM call over all scenes. Produces per-scene reflection beats
# (post-narration silent hold) and music metadata (action, mood, intensity).
# The director pass (pure Python) enforces distribution targets after this call.
#
# Music schema stored in scene_pacing["music"]:
#   action    — what the BGM should do: continue | continue_softly | slight_swell |
#               emotional_swell | resolve | fade | fade_to_silence | hold
#   mood      — emotional character: neutral | reflective | building | dramatic |
#               resolving | fading
#   intensity — target music presence 0.0–1.0 (BGM mixer future use; 0=silent, 1=full)

_PACING_TEMPLATE = """\
You are a documentary film editor assigning cinematic pacing to {total} scenes.

SCENES (index | emotional_beat | narration excerpt):
{scene_list}

REFLECTION BEAT RULES:
1. Add ONLY after: philosophical insight, emotional realization, turning point, \
climax, moral conclusion, final contemplation. NOT after every scene.
2. Limit: at most {max_reflections} reflection-enabled scenes ({pct}% of {total}).
3. Never enable two consecutive scenes.
4. Last scene (index {last_idx}): ALWAYS enabled, duration 5.0–8.0.
5. Duration — minor: 1.5–2.0 | normal: 2.5–3.0 | major: 3.5–5.0 | ending: 5.0–8.0
6. NEVER add reflection beats to the first 3 scenes (the hook). The opening must be fast-paced.

MUSIC FIELDS (assign all three per scene):
action:    continue | continue_softly | slight_swell | emotional_swell | resolve | fade
mood:      neutral | reflective | building | dramatic | resolving | fading
intensity: 0.0–1.0  (music presence; lower = more ducked)

Action guide: hook(first 3 scenes)→slight_swell/building/0.6 | insight→continue_softly/reflective/0.3 \
| turning_point→slight_swell/building/0.55 | climax→emotional_swell/dramatic/0.85 \
| after_climax→resolve/resolving/0.5 | ending→continue_softly/reflective/0.3 | default→continue/neutral/0.5

Return ONLY valid JSON. Keys are scene index as strings. Each value is an object:
{{"1": {{"enabled": false, "duration": 0.0, "action": "continue", "mood": "neutral", "intensity": 0.5}}, \
"2": {{"enabled": true, "duration": 2.8, "action": "continue_softly", "mood": "reflective", "intensity": 0.3}}, ...}}

Return ALL {total} entries. No markdown, no explanation.\
"""

_VALID_MOODS: frozenset[str] = frozenset({
    "neutral", "reflective", "building", "dramatic", "resolving", "fading",
})


def build_pacing_prompt(scenes: list[dict]) -> str:
    """Build a batch prompt for the Cinematic Pacing pass."""
    total = len(scenes)
    max_reflections = max(2, int(total * 0.22))
    last_idx = scenes[-1]["index"] if scenes else 1

    lines: list[str] = []
    for s in scenes:
        beat = (s.get("scene_analysis") or {}).get("emotional_beat", "—")
        narration_excerpt = s.get("narration", "")[:60].rstrip(" ,.")
        lines.append(f"  {s['index']} | {beat} | {narration_excerpt}")

    return _PACING_TEMPLATE.format(
        total=total,
        max_reflections=max_reflections,
        pct=22,
        last_idx=last_idx,
        scene_list="\n".join(lines),
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
