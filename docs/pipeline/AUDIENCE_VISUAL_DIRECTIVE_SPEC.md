# AUDIENCE VISUAL DIRECTIVE — SPEC

**Status:** Ready for implementation  
**Scope:** Pipeline-wide injection — composer, scene planner, visual prompt refinement, settings  
**Touches:** `ATMA_THEORY_COMPOSER.md`, `scene_planner.py`, `pipeline.py`, `settings.py` + new canonical directive file  
**Token budget:** Low — three prompt injections + one settings field + one new markdown file  

---

## WHY

The ATMA channel's audience is English-speaking (US, UK, AU, CA). Currently the pipeline
has no global rule governing character appearance or scene atmosphere in visual prompts.
Left unconstrained, LLM-generated image prompts default toward South Asian characters and
Indian settings — which reads as "this content is for Indian viewers" and misaligns with
the actual audience.

This spec creates one canonical rule file and injects it into every stage that produces
or refines visual output: the composer (for script-level example choices), the scene planner
(for per-scene image prompts), and the visual prompt refinement path. Subtitles are derived
downstream from the script — no direct injection needed there.

---

## ARCHITECTURE OVERVIEW

```
[1] AUDIENCE_VISUAL_DIRECTIVE.md   ← single source of truth (new file)
         |
         ├──▶ [2] ATMA_THEORY_COMPOSER.md       (script: names, examples, analogies)
         |
         ├──▶ [3] scene_planner system prompt    (per-scene visual_prompt generation)
         |
         └──▶ [4] _refine_prompt_from_score      (prompt refinement must not drift)

[5] Settings.AUDIENCE_PROFILE = "western_english"   ← runtime tag, future-proofing
```

Subtitles flow from script → TTS → WhisperX. No separate injection needed.

---

## [1] NEW FILE — `AUDIENCE_VISUAL_DIRECTIVE.md`

**Create at:** `src/ytfactory/prompts/AUDIENCE_VISUAL_DIRECTIVE.md`  
(or `src/video_core/prompts/AUDIENCE_VISUAL_DIRECTIVE.md` if shared across factories)

```markdown
# AUDIENCE & CHARACTER DIRECTIVE

Target audience: English-speaking viewers (US, UK, AU, CA).
All visual output — image prompts, scene descriptions, character references — must
feel internationally relevant and familiar to this audience. Content must not read
as India-centric unless the underlying fact demands it.

---

## CHARACTER & SCENE PRIORITY

Apply in this strict order for every scene:

### PRIORITY 1 — SYMBOLIC / ABSTRACT (always prefer this)
Use metaphor, concept, nature, objects, textures, or universal imagery.
No identifiable human character required.
Examples:
- A cracked hourglass, sand falling in slow motion
- An empty park bench at dusk, long shadows
- Close-up of hands turning pages in a worn leather book
- Storm clouds parting over a mountain ridge
- A single candle flame in a dark room

### PRIORITY 2 — WESTERN / ENGLISH-SPEAKING CHARACTER (default human fallback)
When a human presence genuinely strengthens the scene and symbolic is insufficient.
- Appearance: European or American — light to medium complexion, Western clothing
- Settings: Western city skylines, modern offices, university libraries, green
  suburban streets, European countryside, international airports, coffee shops,
  research labs, grey winter mornings
- Tone: universally relatable, not regionally specific

Examples:
- A woman in her early 40s, dark blazer, looking out a rain-streaked office window
- A young man sitting at a cluttered desk in a European apartment, papers everywhere
- Two people in conversation across a small café table, city street visible behind

### PRIORITY 3 — INDIAN / SOUTH ASIAN CHARACTER OR SETTING (last resort only)
Use ONLY when the specific scene is about a named Indian person, an Indian historical
event, or an India-specific statistic that is the direct subject of the script at
that moment. Not a default. Not a tie-breaker. A last resort.

---

## RULE OF THUMB FOR EVERY PROMPT

Ask: "Can I make this point with a symbol or a Western character?"
If YES → do that. Do not use an Indian setting.
If NO (fact is about India/Indian figure) → Indian setting is appropriate.

A Western viewer seeing Indian characters in a generic wisdom or psychology video reads
it as "this content is not for me." Avoid that signal unless the content demands it.

---

## PROHIBITED DEFAULTS

These must NOT appear in visual prompts unless the script explicitly names them:
- Indian street markets, auto-rickshaws, temple ghats (as generic "atmosphere")
- Men in kurtas or women in sarees as generic characters
- South Asian faces as default human representation
- Indian city skylines (Mumbai, Delhi, Bangalore) as generic urban settings
```

---

## [2] INJECTION — `ATMA_THEORY_COMPOSER.md`

**File:** `src/ytfactory/prompts/ATMA_THEORY_COMPOSER.md`  
**Where:** Add as a new section immediately after the `## AUDIENCE` or `## VOICE` section,
or before the `## STRUCTURE` section — wherever the composer is told who it is writing for.
If no such section exists, add it before `## STRUCTURE`.

**Insert this block verbatim:**

```markdown
## CHARACTERS & EXAMPLES — AUDIENCE RULE

When choosing storytelling examples, analogies, or named characters in the script:

- **Default to universal or Western-context figures.**
  ("A researcher at a university in Zurich", "a nurse working a night shift in London",
  "a young woman who built a company in her garage in Portland")

- **Symbolic / abstract framing is always preferred** over naming any character at all.
  ("Imagine standing at the edge of a decision you cannot unmake...")

- **Indian names, places, or contexts: only when the source discourse is specifically
  about an Indian person, Indian historical event, or India-specific fact.**
  If the Kannada discourse references a universal concept, do not anchor it to an
  Indian example. Find the Western or universal equivalent instead.

- The audience is English-speaking (US, UK, AU, CA). Examples must feel immediately
  familiar to them — not like a translation of something written for another audience.

This rule applies to every example, every analogy, every named figure in the script.
```

---

## [3] INJECTION — Scene Planner System Prompt

**File:** `src/ytfactory/agents/nodes/scene_planner.py`

**Step A — Locate the system prompt.**
Find where the scene planner builds its LLM call. Look for a string assigned as the
`system` prompt (may be a triple-quoted string, a `.md` file loaded via `Path(...).read_text()`,
or a constant like `SCENE_PLANNER_SYSTEM_PROMPT`).

**Step B — Append this block to the end of that system prompt** (before any closing
instruction like "Now generate scenes for the following script:"):

```
---

## VISUAL CHARACTER & SCENE RULE (apply to every visual_prompt you write)

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
```

**Step C — If `visual_prompt` examples exist in the system prompt**, update them to
reflect Western/symbolic defaults. Replace any example prompts that use South Asian
settings with Western or symbolic equivalents.

---

## [4] INJECTION — Visual Prompt Refinement (`_refine_prompt_from_score`)

**File:** `src/ytfactory/pipeline.py` (or wherever `_refine_prompt_from_score` lives)  
**Context:** This function is called when an image prompt scores below threshold and
needs to be re-generated. The refinement LLM call must carry the audience rule so it
does not drift toward Indian defaults when trying to "improve" a prompt.

**Find the refinement system prompt / instruction string inside `_refine_prompt_from_score`.**

**Append this to that instruction** (after the existing guidance, before the prompt is sent):

```
Character and scene rule (non-negotiable):
- Prefer symbolic or abstract imagery first.
- If human characters appear, default to Western/English-speaking appearance
  and setting (European or American look, Western environment).
- Indian characters or Indian settings only if the scene's script content is
  explicitly about an Indian person or Indian fact. Never as a default or fallback.
```

**Note:** The hardcoded `8.5` threshold at `pipeline.py:283` inside this function is a
separate known issue (logged in MASTER_CONTEXT open threads). Do not fix it in this
spec — keep concerns separate.

---

## [5] SETTINGS — `AUDIENCE_PROFILE` field

**File:** `src/video_core/settings.py` or `src/ytfactory/settings.py`  
**Where:** Add to `SharedSettings` (preferred, so all factories inherit it).

```python
# Audience profile — governs character/scene defaults in all visual prompts.
# "western_english" = US/UK/AU/CA audience; Western characters + symbolic defaults.
# Future: "india_english" for India-targeted English content, "kannada" for Kannada variant.
AUDIENCE_PROFILE: str = "western_english"
```

**Usage pattern (for any future conditional logic):**

```python
if settings.AUDIENCE_PROFILE == "western_english":
    # inject western directive into prompt
    ...
```

For this spec, `AUDIENCE_PROFILE` is a declared intent field — it does not require
conditional branching yet. The directive text is injected unconditionally (it already
encodes the western_english logic). The field exists so future factory variants can
override it without changing prompt files.

---

## TEST ASSERTIONS

Add to the relevant test files:

### scene_planner tests (`tests/test_scene_planner.py` or equivalent)

```python
def test_scene_planner_system_prompt_contains_audience_rule():
    """Audience/character directive must be present in the scene planner system prompt."""
    prompt = build_scene_planner_system_prompt()  # or however it is constructed
    assert "SYMBOLIC / ABSTRACT" in prompt
    assert "WESTERN / ENGLISH-SPEAKING" in prompt
    assert "western_english" in prompt or "US, UK, AU, CA" in prompt

def test_visual_prompt_does_not_default_to_indian_setting(sample_generic_scene):
    """For a generic motivational scene, visual_prompt must not contain Indian defaults."""
    # sample_generic_scene = a scene with no India-specific script content
    result = run_scene_planner(sample_generic_scene)
    indian_markers = ["kurta", "sari", "saree", "rickshaw", "ghat", "Mumbai", "Delhi",
                      "Bangalore", "Bengaluru", "temple bells", "marigold garland"]
    for marker in indian_markers:
        assert marker.lower() not in result["visual_prompt"].lower(), (
            f"Indian marker '{marker}' found in generic scene visual_prompt"
        )
```

### composer tests (`tests/test_composer.py`)

```python
def test_composer_prompt_contains_audience_character_rule():
    """ATMA_THEORY_COMPOSER.md must include the character/audience rule section."""
    composer_prompt = load_composer_system_prompt()
    assert "CHARACTERS & EXAMPLES" in composer_prompt
    assert "Western" in composer_prompt or "western" in composer_prompt
    assert "US, UK, AU, CA" in composer_prompt

def test_composer_output_does_not_use_indian_names_for_generic_script(generic_base_script):
    """Composer should not default to Indian names/places for generic content."""
    # generic_base_script = a discourse about universal concept (not India-specific)
    result = run_composer(generic_base_script)
    indian_name_markers = ["Ramesh", "Priya", "Suresh", "Arjun", "Meena",
                           "Bengaluru", "Mumbai", "Chennai"]
    for name in indian_name_markers:
        assert name not in result["script"], (
            f"Indian name/place '{name}' found in composer output for generic script"
        )
```

### settings tests

```python
def test_audience_profile_default_is_western_english():
    settings = SharedSettings()
    assert settings.AUDIENCE_PROFILE == "western_english"
```

---

## IMPLEMENTATION ORDER

1. **Create** `AUDIENCE_VISUAL_DIRECTIVE.md` — no code change, pure content
2. **Patch** `ATMA_THEORY_COMPOSER.md` — prompt-only change, no code
3. **Patch** scene planner system prompt — locate system prompt string, append block
4. **Patch** `_refine_prompt_from_score` — append to refinement instruction
5. **Add** `AUDIENCE_PROFILE` to `SharedSettings`
6. **Run** test assertions above; also run full existing suite to confirm no regressions
7. **Validate** on one real pipeline run — inspect `scene-plan.json` output and confirm
   `visual_prompt` fields for generic scenes are symbolic or Western, not Indian defaults

---

## TOKEN EFFICIENCY NOTES

- `AUDIENCE_VISUAL_DIRECTIVE.md` is the canonical text. Do not duplicate it inline in
  multiple Python files — load it once where needed, or embed the condensed version
  (the "Priority 1/2/3" block) in prompts rather than the full file.
- The injected blocks in composer and scene planner are intentionally terse — they
  enumerate the rule without re-explaining rationale (rationale lives in this spec and
  in the directive file).
- The `PROHIBITED DEFAULTS` list in the directive is for human clarity; omit it from
  runtime LLM prompt injections to save tokens. The positive priority list is sufficient
  for the model.
- This spec itself: ~950 tokens. Hand to coding agent as-is; no further summarisation
  needed before implementation.
