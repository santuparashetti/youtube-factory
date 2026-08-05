# KAI — ANCHOR CHARACTER PROFILE (PIPELINE INTERNAL)

This is an internal pipeline document. The name "Kai" and this profile must NEVER
appear in any viewer-facing output: not in script text, narration, subtitles, or
captions. This character is nameless to the viewer.

---

## IDENTITY / PURPOSE

Kai is the viewer's proxy. He is not a hero, not a teacher, not a narrator.
He is someone experiencing the truth of the video's message for the first time —
curious, searching, present. The viewer sees themselves in him without being told to.

## LOCKED VISUAL SPECIFICATION

Use this description verbatim (or compressed form below) in every image prompt
where Kai appears.

**Full spec:**
Male. Late 20s to early 30s. Lean, average build — not athletic or heroic, not
frail. Short dark hair, neatly kept but unstyled. Clean-shaven or very light
stubble. Plain, casual Western clothing — simple dark shirt (navy, charcoal, or
dark olive), plain trousers or jeans. No accessories, no jewelry, no tattoos,
no distinctive markings. Expression: calm, present, quietly thoughtful — not
performing emotion, not reacting dramatically.

**Compressed spec (use in LLM prompts to save tokens):**
"lean young man, late 20s, short dark hair, light stubble, simple dark shirt,
plain trousers, calm expression"

---

## ANCHOR ROLE DEFINITIONS

### PRIMARY
Kai is the subject of the scene. He is feeling, experiencing, deciding, or reflecting.
The camera (in image terms) treats him as the main point of interest.

Prompt construction:
[FULL KAI SPEC] — [scene-specific staging: what he is doing, where, emotional state]

Example:
"Lean young man, late 20s, short dark hair, light stubble, simple dark shirt —
sitting at a small wooden desk in a dimly lit room, staring at a blank notebook,
pen resting unused beside it. Soft grey morning light from one window. Still."

### SPECTATOR
A real historical figure, named person, or documented event is the primary subject.
Kai is present but barely noticeable — an ambient figure deep in the background,
not a visible witness. He should look like someone who happened to be there, not
someone watching the event. He is NEVER the focus of attention.

Prompt construction:
[Scene-specific historical staging] — [Brief Kai descriptor] small in the far
background or at the very edge of the frame, partially obscured by environment
elements (a pillar, a crowd, shadow, depth-of-field blur).

Brief Kai descriptor for spectator mode:
"barely visible in the background — a young man, lean, dark hair, simple dark
shirt, standing still among the periphery, partially obscured"

SPECTATOR SCALE RULES:
- Kai should occupy no more than 5-10% of the frame area in spectator scenes.
- Place Kai at the furthest edge or deepest background plane of the composition.
- Kai may be partially hidden behind architecture, crowd members, or environmental
  elements — this is preferred over full visibility.
- Kai should NEVER be in the foreground or midground of a spectator scene.
- If the scene is crowded, Kai blends into the crowd — not standing apart from it.

Do NOT use the full spec in spectator mode — it would compete with the primary subject.
Brief descriptor only.

### ABSENT
The scene is fully symbolic, abstract, or atmospheric. No human presence needed or
appropriate. Pure environment, object, texture, metaphor.

No Kai injection. Standard visual prompt only.

---

## SCENE PRIORITY RULES

- Opening scene (first non-title scene): Kai should be PRIMARY unless strongly symbolic
- Climax breath scene: Kai should be PRIMARY — this is his moment of realisation
- Closing scene (before brand card): Kai should be PRIMARY — arc completes here
- Historical figure scenes: Kai should be SPECTATOR
- Pure metaphor / data / atmospheric scenes: ABSENT

---

## WHAT KAI IS NOT

- Not a named protagonist the narrator speaks about
- Not a character with dialogue or agency the script describes
- Not Indian or South Asian in appearance (see AUDIENCE_VISUAL_DIRECTIVE.md)
- Not dramatic, heroic, or emotive beyond quiet thoughtfulness
- Not referenced by name in any output the viewer sees
