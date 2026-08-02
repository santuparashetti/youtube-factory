# KAI ANCHOR CHARACTER — SPEC

**Status:** Ready for implementation  
**Scope:** Pipeline-wide narrative anchor — composer, scene planner, prompt builder,
           post-composition validator, settings  
**Touches:** `ATMA_THEORY_COMPOSER.md`, `scene_planner.py`, `pipeline.py`,
            `settings.py`, `scene_plan` Pydantic model + new `KAI_PROFILE.md`  
**Depends on:** `AUDIENCE_VISUAL_DIRECTIVE_SPEC.md` (must be implemented first — Kai is
               a Western character by definition; the audience rule is the foundation)  
**Token budget:** Low-medium — one new file, three prompt injections, one schema field,
                 one validator, one settings block  

---

## WHY

The pipeline currently generates each scene's visual prompt in isolation. Each image
stands alone. There is no visual thread connecting scene 1 to scene 8 to scene 15 —
the viewer's eye has nothing to follow across the full 7–9 minutes.

"Kai" is a pipeline-internal anchor character — a neutral Western everyman who appears
in every scene where a human presence adds value. He is the viewer's proxy: someone
experiencing the truth of the script for the first time, alongside the audience. In
scenes with real historical figures, he steps to the periphery and watches. In generic
or conceptual scenes, he is the subject. In pure symbolic/atmospheric scenes, he is
absent entirely.

**What this achieves:**
- Viewer subconsciously follows one face across the whole video
- Emotional arc has a carrier — Kai's journey from the open-loop doubt to the closing
  realisation IS the video's emotional through-line
- Every scene feels like it belongs to the same film, not a slideshow of stock images

**The critical constraint — Kai is INVISIBLE to the viewer:**
The name "Kai" is a pipeline-internal identifier ONLY. It must NEVER appear in:
- Script markdown (`.md`) output
- TTS input text
- Subtitle / caption files (`.srt`, `.vtt`, any format)
- Any viewer-facing rendered output

"Kai" exists only in: system prompts, `scene-plan.json` (internal artifact), `KAI_PROFILE.md`,
`Settings`, and image prompt text (sent to external image generator — not viewer-facing).
The character on screen is nameless. He is "a man", "a figure", "someone" — the
everyman the viewer inhabits without being told to.

---

## ARCHITECTURE OVERVIEW

```
[1] KAI_PROFILE.md  ← locked visual spec (new file, single source of truth)
         |
         ├──▶ [2] ATMA_THEORY_COMPOSER.md
         |         Composer writes scripts with Kai's role in mind.
         |         Uses everyman language ("a man", "someone", "imagine a figure").
         |         NEVER outputs the name "Kai".
         |         Open-loop opening → Kai established.
         |         Climax breath → Kai's realisation.
         |         Closing → Kai's arc completes.
         |
         ├──▶ [3] scene_planner system prompt + output model
         |         Classifies each scene:  anchor_role = "primary" | "spectator" | "absent"
         |         Builds visual_prompt with Kai spec injected per role.
         |         anchor_role stored in scene-plan.json per scene.
         |
         ├──▶ [4] _refine_prompt_from_score
         |         Re-prompts must preserve anchor_role and re-inject Kai spec.
         |         Must not drop Kai on refinement.
         |
         └──▶ [5] Post-composition validator (new)
                   Scans script output for "Kai" (case-insensitive).
                   Raises ComposerViolation if found.
                   Also scans subtitle artifact at Phase 1 close.

[6] SharedSettings.ANCHOR_CHARACTER_ENABLED / ANCHOR_CHARACTER_ID
```

---

## [1] NEW FILE — `KAI_PROFILE.md`

**Create at:** `src/ytfactory/prompts/KAI_PROFILE.md`

This file is the single source of truth for Kai's visual appearance. All prompt
injections derive from it. Do not duplicate the spec inline in Python strings — load
or import this file where needed.

```markdown
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
Kai is present but peripheral — a silent witness at the edge of the frame.

Prompt construction:
[Scene-specific historical staging] — [Brief Kai descriptor] at the edge, watching,
still, not drawing attention.

Brief Kai descriptor for spectator mode:
"a young man — lean, dark hair, simple dark shirt — standing at the periphery,
watching in silence"

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
```

---

## [2] INJECTION — `ATMA_THEORY_COMPOSER.md`

**File:** `src/ytfactory/prompts/ATMA_THEORY_COMPOSER.md`  
**Where:** Add as `## VISUAL ANCHOR CHARACTER` immediately after the five structural
composition directives (open loop, shadow beat, parallel examples, emotional arc,
climax breath). It is a sixth composition directive — not a rule or restriction, but
a directive held alongside the others as the script is written whole-cloth.

**Insert this block verbatim:**

```markdown
## VISUAL ANCHOR CHARACTER

There is a visual anchor character who will appear in the video's images throughout
the full runtime. Internally he is called "Kai" — this name is a pipeline handle ONLY
and must NEVER appear anywhere in the script you write. Not once. Not as a reference,
not hidden, not abbreviated.

**Who he is (for your composition):**
He is the viewer's proxy — a nameless, neutral young man experiencing the script's
truth for the first time, alongside the audience. He is not the narrator. He is not
a character with named dialogue. He is the silent human thread the viewer follows
without being asked to.

**How to write with him in mind:**

- The OPEN LOOP should land on him. The opening doubt, the inciting question — write
  it as something a person (unnamed, "someone", "a man") might feel. This establishes
  his presence before any story begins.
  Example framing: "Imagine someone who has tried everything…" / "There is a kind of
  person who…" / "Most of us have felt…"

- STORY EXAMPLES may use him as the lens. When you write a generic person experiencing
  something ("a researcher who…", "a woman who worked through the night…"), that person
  IS Kai in the viewer's mind — even without naming him.

- The CLIMAX BREATH is his moment. The realisation lands on him first. Write it so a
  human being feels it, not just understands it intellectually.

- The CLOSING completes his arc. He was searching at the open — at the close, something
  has shifted. The script's final lines before "This is Atma Theory." should carry that
  arc to completion.

**Hard constraint:**
The name "Kai" must NEVER appear in the script output. No exceptions. If you write it
anywhere — even in a parenthetical, even as a placeholder, even misspelled — the
pipeline will reject the output as a violation. Write "the man", "a figure", "someone",
"a person" — never "Kai".
```

---

## [3] SCENE PLANNER — System Prompt + Output Model

### 3A — Scene-plan.json schema update

**File:** wherever the `ScenePlan` or per-scene Pydantic model is defined  
**Add one field to the per-scene model:**

```python
from typing import Literal

class Scene(BaseModel):
    # ... existing fields ...
    anchor_role: Literal["primary", "spectator", "absent"] = "absent"
    # "primary"   — Kai is the subject of this scene
    # "spectator" — Kai observes from periphery; real figure is primary
    # "absent"    — purely symbolic/atmospheric; no Kai injection
```

### 3B — Scene planner system prompt injection

**File:** `src/ytfactory/agents/nodes/scene_planner.py`  
**Where:** Append to the scene planner's system prompt, before the output format
instructions (i.e., before "Now generate scenes for the following script:").

**Insert this block verbatim:**

```
---

## KAI ANCHOR CHARACTER — SCENE CLASSIFICATION (PIPELINE INTERNAL)

For every scene you generate, you must:
  1. Decide the `anchor_role` — one of: "primary", "spectator", or "absent"
  2. Build the `visual_prompt` with Kai's spec injected per that role

"Kai" is a pipeline-internal identifier. It must NOT appear in any text the viewer
sees. In visual_prompts you write, Kai's physical description appears — his name
does not need to.

### CLASSIFICATION RULES

**"absent"** — No human character needed or appropriate.
Assign when: the scene is fully symbolic, atmospheric, or abstract — a metaphor,
a data point, a texture, an environment. No human presence would strengthen it.

**"primary"** — Kai is the subject; he is feeling, experiencing, or reflecting.
Assign when: the scene is about someone experiencing an emotion, making a choice,
or sitting with a realisation. No named real historical figure is present.
ALWAYS assign primary to:
- The first non-symbolic scene (establishes Kai for the viewer)
- The climax breath scene (his realisation moment)
- The final scene before the brand card (arc completes)

**"spectator"** — A real figure is primary; Kai witnesses.
Assign when: the scene depicts a named historical person, a documented real event,
or a specific cultural/factual moment where a real character takes centre stage.
Kai is present at the edge — a witness — but the frame belongs to the real figure.

---

### PROMPT CONSTRUCTION BY ROLE

**PRIMARY visual_prompt structure:**
Start with the compressed Kai spec, then the scene-specific staging.

Compressed Kai spec (use verbatim at start of prompt):
"Lean young man, late 20s, short dark hair, light stubble, simple dark shirt,
plain trousers, calm expression"

Then add: what he is doing, where he is, the emotional quality of the moment.

Example:
"Lean young man, late 20s, short dark hair, light stubble, simple dark shirt,
plain trousers, calm expression — sitting at a small wooden desk in a dimly lit
room, staring at a blank page, the pen lying unused. One window. Grey morning
light. Still."

**SPECTATOR visual_prompt structure:**
Write the historical/factual scene first (primary subject, setting, action).
Then append the brief Kai descriptor at the end.

Brief Kai descriptor for spectator mode (append verbatim):
"At the edge of the frame, a young man — lean, dark hair, simple dark shirt —
stands watching in silence."

Example:
"A man in late 19th century clothing writes feverishly at a cluttered desk by
candlelight, papers scattered across the floor, ink-stained hands moving without
pause. At the edge of the frame, a young man — lean, dark hair, simple dark
shirt — stands watching in silence."

**ABSENT visual_prompt structure:**
Standard symbolic/atmospheric prompt only. No Kai reference at all.

Example:
"A cracked hourglass lying on its side on a stone floor, sand pooled beneath
it, soft diffused grey light. No human figure."

---

### OUTPUT FORMAT (per scene, append anchor_role field)

```json
{
  "scene_id": 1,
  "anchor_role": "primary",
  "visual_prompt": "...",
  "mood": "...",
  ...existing fields...
}
```
```

---

## [4] VISUAL PROMPT REFINEMENT — `_refine_prompt_from_score`

**File:** `src/ytfactory/pipeline.py` (around line 283)  
**Context:** When a scene's image prompt scores below threshold and is re-generated,
the refinement call must preserve the anchor_role and re-inject Kai's spec. It must
not drop Kai on a re-prompt (a common failure mode: refinement strips character context
because it only sees the low-scoring prompt, not the role).

**Step A:** Pass `anchor_role` into `_refine_prompt_from_score` as a parameter.
Read it from the scene object in `scene-plan.json` before calling the function.

```python
def _refine_prompt_from_score(
    self,
    prompt: str,
    score: float,
    anchor_role: str = "absent",   # ← add this parameter
    ...
) -> str:
```

**Step B:** Append this block to the refinement instruction string inside the function,
keyed on `anchor_role`:

```python
KAI_ROLE_REFINEMENT = {
    "primary": (
        "This scene features Kai as the primary subject. "
        "The refined prompt MUST begin with: "
        "'Lean young man, late 20s, short dark hair, light stubble, simple dark shirt, "
        "plain trousers, calm expression' — then continue with scene-specific staging. "
        "Do not remove this character. Do not replace him with a different character."
    ),
    "spectator": (
        "This scene has a real historical/factual primary subject. "
        "The refined prompt must keep the primary subject as the focus. "
        "At the end of the prompt, append: "
        "'At the edge of the frame, a young man — lean, dark hair, simple dark shirt — "
        "stands watching in silence.' "
        "Do not promote this background figure to primary subject."
    ),
    "absent": (
        "This scene is purely symbolic or atmospheric. "
        "Do NOT introduce any human character in the refined prompt."
    ),
}

# Add to the refinement instruction:
role_instruction = KAI_ROLE_REFINEMENT.get(anchor_role, KAI_ROLE_REFINEMENT["absent"])
refinement_instruction += f"\n\nANCHOR CHARACTER RULE:\n{role_instruction}"
```

**Note:** The hardcoded `8.5` threshold at `pipeline.py:283` is a separate known issue
(open thread in MASTER_CONTEXT). Do not fix it in this spec — keep concerns isolated.

---

## [5] POST-COMPOSITION VALIDATOR — "Kai" Name Firewall

**File:** Create a new validator or add to existing `editorial_qa` / post-processing.
Suggested location: `src/ytfactory/validators/kai_firewall.py`

**Purpose:** Scan every viewer-facing text artifact for the string "Kai" (case-insensitive).
Raise a hard error if found. This is the enforcement layer for the critical constraint.

```python
"""
kai_firewall.py — Pipeline-internal name firewall.

"Kai" is an internal anchor character identifier. It must NEVER appear in any
viewer-facing output. This validator enforces that constraint at artifact boundaries.
"""

class KaiFirewallViolation(Exception):
    """Raised when the pipeline-internal name 'Kai' is detected in viewer-facing output."""
    pass

KAI_PATTERN = re.compile(r'\bkai\b', re.IGNORECASE)

VIEWER_FACING_ARTIFACTS = [
    "script.md",        # composer output
    "final_script.md",  # post-human-review
    "subtitles.srt",    # WhisperX output
    "subtitles.vtt",    # alternate subtitle format
    "captions.txt",     # any caption artifact
]

def check_artifact(text: str, artifact_name: str) -> None:
    """
    Scan text for the pipeline-internal name 'Kai'.
    Raises KaiFirewallViolation if found.
    
    Call at:
    - After composer output (before editorial_qa)
    - After TTS input assembly (before Cartesia call)
    - After WhisperX subtitle generation
    """
    matches = KAI_PATTERN.findall(text)
    if matches:
        raise KaiFirewallViolation(
            f"Pipeline-internal name 'Kai' detected in viewer-facing artifact "
            f"'{artifact_name}'. Found {len(matches)} occurrence(s). "
            f"This name must never appear in script, TTS input, subtitles, or captions. "
            f"Check ATMA_THEORY_COMPOSER.md injection and scene_planner output."
        )

def check_file(path: Path) -> None:
    """Convenience wrapper for file-based artifacts."""
    if path.exists():
        check_artifact(path.read_text(encoding="utf-8"), path.name)
```

**Wire the firewall at three points in the pipeline graph:**

1. **After composer node** — before `editorial_qa`:
   ```python
   check_artifact(state["script"], "script.md")
   ```

2. **After TTS input is assembled** — before Cartesia call:
   ```python
   check_artifact(tts_input_text, "tts_input")
   ```

3. **After WhisperX subtitle generation** — before Phase 1 closes:
   ```python
   check_file(project_dir / "subtitles.srt")
   ```

---

## [6] SETTINGS

**File:** `src/video_core/settings.py` (`SharedSettings`)  
**Add:**

```python
# Anchor character — pipeline-internal identifier.
# ANCHOR_CHARACTER_ID is used in system prompts and internal artifacts ONLY.
# It must NEVER appear in viewer-facing output. KaiFirewallViolation enforces this.
ANCHOR_CHARACTER_ENABLED: bool = True
ANCHOR_CHARACTER_ID: str = "Kai"
```

**Usage pattern:**
```python
if settings.ANCHOR_CHARACTER_ENABLED:
    # inject Kai-aware instructions into scene planner system prompt
    scene_planner_prompt += load_kai_scene_instructions()
```

This flag allows disabling the Kai system entirely (e.g., for a future shorts_factory
where per-scene brevity means anchor continuity doesn't apply) without touching prompt
files.

---

## TEST ASSERTIONS

### Firewall tests (`tests/test_kai_firewall.py`)

```python
def test_kai_not_in_composer_output(generic_base_script):
    """Composer output must never contain the string 'Kai'."""
    result = run_composer(generic_base_script)
    assert "kai" not in result["script"].lower(), (
        "Pipeline-internal name 'Kai' found in composer script output"
    )

def test_kai_firewall_raises_on_violation():
    """check_artifact() must raise KaiFirewallViolation when 'Kai' is present."""
    with pytest.raises(KaiFirewallViolation):
        check_artifact("Kai sat at the window, waiting.", "test_script.md")

def test_kai_firewall_case_insensitive():
    for variant in ["kai", "Kai", "KAI", "kAi"]:
        with pytest.raises(KaiFirewallViolation):
            check_artifact(f"The man named {variant} looked up.", "test_script.md")

def test_kai_firewall_passes_clean_text():
    """Firewall must not flag clean text that doesn't contain 'Kai'."""
    check_artifact("A man sat at the window, quietly watching.", "test_script.md")
    # No exception raised — clean text passes

def test_subtitles_never_contain_kai(full_pipeline_run):
    """End-to-end: subtitle artifact must not contain 'Kai'."""
    srt_path = full_pipeline_run / "subtitles.srt"
    check_file(srt_path)  # No exception = pass
```

### Scene planner tests (`tests/test_scene_planner.py`)

```python
def test_every_scene_has_anchor_role(sample_script):
    """Every scene in scene-plan.json must have a valid anchor_role."""
    plan = run_scene_planner(sample_script)
    valid_roles = {"primary", "spectator", "absent"}
    for scene in plan["scenes"]:
        assert "anchor_role" in scene, f"Scene {scene['scene_id']} missing anchor_role"
        assert scene["anchor_role"] in valid_roles, (
            f"Scene {scene['scene_id']} has invalid anchor_role: {scene['anchor_role']}"
        )

def test_opening_scene_is_not_absent(sample_script):
    """First scene should involve Kai (primary or spectator), not absent."""
    plan = run_scene_planner(sample_script)
    first_scene = plan["scenes"][0]
    assert first_scene["anchor_role"] != "absent", (
        "Opening scene has anchor_role='absent' — Kai should be established early"
    )

def test_primary_prompt_contains_kai_spec(sample_script):
    """Scenes with anchor_role=primary must include compressed Kai spec in visual_prompt."""
    plan = run_scene_planner(sample_script)
    kai_markers = ["dark hair", "simple dark shirt", "lean young man", "late 20s"]
    for scene in plan["scenes"]:
        if scene["anchor_role"] == "primary":
            prompt = scene["visual_prompt"].lower()
            found = any(m.lower() in prompt for m in kai_markers)
            assert found, (
                f"Scene {scene['scene_id']} is primary but visual_prompt "
                f"doesn't contain Kai spec markers"
            )

def test_spectator_prompt_contains_brief_kai_descriptor(sample_script):
    """Scenes with anchor_role=spectator must include brief Kai descriptor."""
    plan = run_scene_planner(sample_script)
    for scene in plan["scenes"]:
        if scene["anchor_role"] == "spectator":
            assert "dark hair" in scene["visual_prompt"].lower() or \
                   "watching" in scene["visual_prompt"].lower(), (
                f"Scene {scene['scene_id']} is spectator but visual_prompt "
                f"doesn't contain brief Kai descriptor"
            )

def test_absent_prompt_contains_no_kai_markers(sample_script):
    """Scenes with anchor_role=absent must have no Kai visual spec injected."""
    plan = run_scene_planner(sample_script)
    kai_markers = ["dark hair", "simple dark shirt", "lean young man", "light stubble"]
    for scene in plan["scenes"]:
        if scene["anchor_role"] == "absent":
            prompt = scene["visual_prompt"].lower()
            for marker in kai_markers:
                assert marker not in prompt, (
                    f"Scene {scene['scene_id']} is absent but visual_prompt "
                    f"contains Kai marker '{marker}'"
                )

def test_kai_name_not_in_any_visual_prompt(sample_script):
    """The name 'Kai' must not appear in any visual_prompt (use description, not name)."""
    plan = run_scene_planner(sample_script)
    for scene in plan["scenes"]:
        assert "kai" not in scene["visual_prompt"].lower(), (
            f"Scene {scene['scene_id']} visual_prompt contains the name 'Kai'"
        )
```

### Settings tests

```python
def test_anchor_character_settings_defaults():
    settings = SharedSettings()
    assert settings.ANCHOR_CHARACTER_ENABLED is True
    assert settings.ANCHOR_CHARACTER_ID == "Kai"
```

---

## IMPLEMENTATION ORDER

1. **Create** `KAI_PROFILE.md` — no code change
2. **Update** per-scene Pydantic model — add `anchor_role` field with default `"absent"`
3. **Update** scene planner system prompt — add classification + prompt construction block
4. **Verify** scene-plan.json output now includes `anchor_role` on each scene
5. **Patch** `ATMA_THEORY_COMPOSER.md` — add `## VISUAL ANCHOR CHARACTER` directive
6. **Create** `kai_firewall.py` — the validator
7. **Wire** firewall at 3 points: post-composer, pre-TTS, post-subtitle
8. **Patch** `_refine_prompt_from_score` — add `anchor_role` parameter + role instruction
9. **Add** `ANCHOR_CHARACTER_ENABLED` / `ANCHOR_CHARACTER_ID` to `SharedSettings`
10. **Run** full test suite — verify no regressions against existing 3078 tests
11. **Validate** on one real pipeline run:
    - Inspect `scene-plan.json` — confirm every scene has `anchor_role`
    - Confirm opening and climax scenes are `"primary"`
    - Confirm historical figure scenes are `"spectator"`
    - Confirm firewall passes (no KaiFirewallViolation raised)
    - Generate one image per role type and manually confirm visual consistency

---

## ALIGNMENT WITH STRUCTURED-PROMPT-SCHEMA (OPEN THREAD)

The structured-prompt-schema migration (flat `visual_prompt` strings → structured schema)
is an open thread, not yet started. When that migration is built, `anchor_role` should
become a first-class field in the structured schema (not embedded in the string).
The `anchor_role` field added here is forward-compatible — it already lives at the same
level as `visual_prompt` in the scene object, so the migration only needs to move
`visual_prompt` to a sub-schema, leaving `anchor_role` unchanged.

---

## ALIGNMENT WITH `AUDIENCE_VISUAL_DIRECTIVE_SPEC.md`

Kai is a Western character by definition — this satisfies the audience directive's
Priority 2 (Western character) for all `anchor_role = "primary"` scenes without
additional prompt text. The `absent` path falls through to the directive's Priority 1
(symbolic). The `spectator` path lets the historical figure be the primary subject while
Kai's brief Western descriptor maintains the channel's visual language in the frame.

No conflict. Both specs apply simultaneously. Implement audience directive first.

---

## TOKEN EFFICIENCY NOTES

- `KAI_PROFILE.md` is the source of truth. LLM prompts use the **compressed spec only**
  (~18 tokens: "lean young man, late 20s, short dark hair, light stubble, simple dark
  shirt, plain trousers, calm expression"). Full spec is for humans, not runtime.
- `anchor_role` classification is one field the scene planner already determines
  implicitly (it knows if a scene has a real historical figure). Making it explicit
  adds ~2 tokens to each scene's output — negligible.
- Spectator mode uses an even shorter Kai descriptor (~14 tokens) — deliberately terse
  so the historical figure's prompt is not crowded.
- Firewall is a regex scan — zero LLM cost, negligible compute.
- This spec itself: ~1,100 tokens. Hand to coding agent as-is.
