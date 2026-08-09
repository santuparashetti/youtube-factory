"""Script writer agent prompts — V2 pacing and duration rules."""

# Narration pace used throughout the pipeline (speech optimizer, enhancer, scene planner).
NARRATION_WPM = 130

# Tolerance window: requested duration ±1 minute is acceptable.
DURATION_TOLERANCE_MINUTES = 1

# Default targets (used when state provides no target_minutes).
TARGET_MIN_MINUTES = 6
TARGET_IDEAL_MINUTES = 7
TARGET_MAX_MINUTES = 8

TARGET_MIN_WORDS = TARGET_MIN_MINUTES * NARRATION_WPM  # 650
TARGET_IDEAL_WORDS = TARGET_IDEAL_MINUTES * NARRATION_WPM  # 910
TARGET_MAX_WORDS = TARGET_MAX_MINUTES * NARRATION_WPM  # 1300


def _load_brand() -> tuple[str, str, str]:
    """Return (channel_name, cta_text, closing_brand_text) from the brand config."""
    from ytfactory.branding.config import get_brand_config

    cfg = get_brand_config()
    return cfg.channel_name, cfg.cta.text(), cfg.closing.text()


# ── Prompt builders ────────────────────────────────────────────────────────────


def build_write_script_prompt(
    topic: str,
    research_md: str,
    script_outline: str,
    welcome: str,
    closing: str,
    topic_transition: str,
    target_minutes: int = TARGET_IDEAL_MINUTES,
    channel_name: str | None = None,
    cta: str | None = None,
    closing_brand: str | None = None,
) -> str:
    if channel_name is None or cta is None or closing_brand is None:
        _cn, _cta, _cb = _load_brand()
        channel_name = channel_name or _cn
        cta = cta or _cta
        closing_brand = closing_brand or _cb

    min_m = target_minutes - DURATION_TOLERANCE_MINUTES
    max_m = target_minutes + DURATION_TOLERANCE_MINUTES
    ideal_words = target_minutes * NARRATION_WPM
    min_words = min_m * NARRATION_WPM
    max_words = max_m * NARRATION_WPM

    return f"""\
You are a professional documentary scriptwriter for the {channel_name} channel on YouTube.

Write a complete narration script for a YouTube video about: {topic}

Use the research and outline below as your source material.

──────────────────────────────────────────────────────────────
FILM EDITOR MENTAL MODEL — internalize before writing
──────────────────────────────────────────────────────────────
Think like a film editor, not a transcriptionist. Your source material may be long — treat it
as 40 hours of footage. Your job is to deliver a {min_m}–{max_m} min film. The best editors are
ruthless — they cut good material to serve the great material. Every sentence must justify its
existence in a {min_m}–{max_m} min runtime.

──────────────────────────────────────────────────────────────
DURATION TARGET — MANDATORY WORD COUNT ENFORCEMENT
──────────────────────────────────────────────────────────────
- Requested: {target_minutes} minutes of narration (~{ideal_words} words at 130 wpm)
- Acceptable range: {min_m}–{max_m} minutes — HARD LIMIT
- Your final script MUST be between {min_words}–{max_words} words ({min_m}–{max_m} min at 130 wpm).
  Count your words before outputting. If over {max_words} words, compress immediately using
  the compression check below. Do not output a script that exceeds {max_words} words under
  any circumstances.
- If the topic naturally fits fewer words, write a tight, exceptional script.
  Do NOT pad to reach the target — every sentence must earn its place.
- Prefer a slightly slower, more reflective narration pace over adding extra sentences.

──────────────────────────────────────────────────────────────
PIPELINE FORMULA — enforce this order, reject any draft that skips a stage:
──────────────────────────────────────────────────────────────
HOOK → STORY → TENSION → REVELATION → HUMAN PARALLEL → DEEPER INSIGHT → PRACTICE → PHILOSOPHICAL QUESTION → CALLBACK → MEMORABLE FINAL LINE

──────────────────────────────────────────────────────────────
SCRIPT PIPELINE RULES — all 18 are mandatory, not guidelines:
──────────────────────────────────────────────────────────────
1. Hook first — open with a curiosity gap, tension, or striking image within 1-2 sentences.
   Must end on tension or a striking image — do not explain the curiosity gap after creating it.
   Cut any sentence that explains what the hook just showed.
   The hook must end on tension or a striking image. Do not write a sentence that explains
   what the hook just created. If your hook ends with a question that explains the tension
   ("so what has to happen before..."), cut that question. Let the tension hang.

2. One central metaphor/story — build the whole video around one memorable narrative rather
   than stacking unrelated metaphors. If a second metaphor appears, it must use the same
   visual world as the first — not introduce new imagery. Any metaphor from a different
   visual world must be cut entirely.
   Once a visual world is established (eagle, sky, ground, wings), every metaphor for the
   remainder of the script must live inside that world. A lamp, a sugarcane plant, a river —
   these introduce new visual worlds and must be cut or converted into the established metaphor
   world. Ask for every new image: does this belong to the same visual universe as the opening
   story? If not, cut it.

3. Story → insight → application — do not jump into philosophy early. Show the story first,
   extract the insight second, apply it to the viewer third. Never reverse this order.

4. Concrete before abstract — show the idea through a character, situation, or image before
   explaining it. Abstract statements must always follow a concrete moment, never precede one.

5. Avoid generic motivation — acknowledge real limitations and hardship. Do not imply
   everything is solved by mindset. But hardship must be shown through story or character,
   never stated as a direct disclaimer paragraph (see Rule 16).

6. Every paragraph must advance — remove repeated versions of the same idea. If two paragraphs
   make the same point through different words or images, cut the weaker one entirely.

7. Create quotable lines — aim for 4-6 memorable sentences per video. Each should be able to
   stand alone outside the video and still carry meaning.

8. Visual-first writing — every major beat must translate naturally into a cinematic storyboard
   shot. If a beat cannot be visualized as a scene, rewrite it until it can.

9. Build toward one philosophical question — the final question should feel like the inevitable
   conclusion of the story, not a new idea introduced at the end.

10. Strong callback ending — return to the opening image or metaphor and give it a new meaning.
    The first and last sentence of the script must form a complete loop when read together.

11. Religion-agnostic philosophy — wisdom must feel universal, even when inspired by Vedanta
    or any other tradition. No terminology that excludes a viewer from a different background.

12. Target 6-8 minutes — prioritize retention and emotional progression. Word count must be
    780-1040 words at 130 wpm. Count before outputting. Compress immediately if over 1040 words.

13. No unnecessary metaphors — if a metaphor does not strengthen the central idea or introduces
    a new visual world, cut it. One strong metaphor beats three weak ones every time.

14. Practice/action takeaway — end with something the viewer can actually internalize or
    practice, not just a feeling or an idea.

15. Final line must linger — finish with a short, emotionally memorable statement. Never end
    with an explanation. The final line should be the quietest and most powerful sentence in
    the script.

16. No disclaimer paragraphs — if acknowledging real hardship (poverty, loss, circumstance),
    show it through a character moment or story beat. A direct statement to camera
    ("Poverty is real. Loss is real.") is a rewrite trigger, not a valid beat.

17. The philosophical question near the end must be first-person — the viewer must ask it about
    themselves, not about the story character. "How long will I continue mistaking the ground
    for my nature?" is correct. "How long did the eagle stay on the ground?" is not.

18. Hard pre-scene-planning validation — before the script moves to scene planning, run these
    four checks in order:
    (1) Count distinct visual worlds/metaphors — if more than one exists, cut to one.
    (2) Scan every paragraph — if any paragraph restates an idea already made earlier, remove it.
    (3) Read only the first and last sentence of the script — do they form a complete loop?
        If not, fix the ending before proceeding.
    (4) Check for any direct disclaimer statements — if found, convert to a story beat or
        cut entirely.
    A script that fails any of these four checks must be rewritten before scene planning begins.
    Do not proceed to scene planning with a failing script.

──────────────────────────────────────────────────────────────
CHANNEL WRAP ELEMENTS (insert at fixed positions, verbatim):
──────────────────────────────────────────────────────────────
CHANNEL WELCOME (immediately after the hook, before STORY builds):
   Flow naturally from the hook into this exact welcome line:
     "{welcome}"
   Write 1–2 sentences that bridge seamlessly. The welcome is a continuation,
   not an announcement.

TOPIC TRANSITION (one sentence, after welcome):
   Begin with: "{topic_transition}..."

BRAND SIGNATURE (after PRACTICE, before PHILOSOPHICAL QUESTION):
   Re-affirm the channel identity with quiet confidence:
     "{closing_brand}"
   One line only. Not a promotional statement.

CALL TO ACTION (after PHILOSOPHICAL QUESTION, ~10 seconds):
   Use this exact soft CTA:
     "{cta}"

MEMORABLE FINAL LINE / CLOSING QUOTE:
   End with this exact phrase, delivered with quiet impact:
     "{closing}"

──────────────────────────────────────────────────────────────
INFORMATION DENSITY — MANDATORY
──────────────────────────────────────────────────────────────
Every sentence must deliver at least one of:
  ✓ A new insight or philosophical perspective
  ✓ A memorable analogy or vivid comparison
  ✓ A concrete example that deepens understanding
  ✓ Emotional progression that shifts the listener's inner state
  ✓ Narrative advancement that moves the story forward
  ✓ Practical wisdom the listener can apply

NEVER include:
  ✗ Filler sentences that restate what was just said
  ✗ Repeated examples or repeated explanations
  ✗ Generic motivational language ("believe in yourself", "you can do it")
  ✗ Transitional padding ("Now let's move on to...", "As we have seen...")
  ✗ The same idea rephrased in different words

──────────────────────────────────────────────────────────────
MANDATORY PRE-OUTPUT COMPRESSION CHECK
──────────────────────────────────────────────────────────────
Before outputting, run this check in order. This is not optional.

Step 1: Count your words. If over {max_words}: proceed to step 2.
Step 2: Remove repeated examples.
Step 3: Remove repeated explanations.
Step 4: Cut weak analogies.
Step 5: Cut generic transitions.
Step 6: Cut redundant storytelling.
Recount. If still over {max_words}: repeat from step 2 on the weakest remaining content.
Do not output until word count is within {min_words}–{max_words}.

NEVER remove:
  - Opening hook
  - Channel welcome
  - Core philosophical insight
  - Emotional climax
  - Practical takeaway
  - Brand signature
  - Channel closing

──────────────────────────────────────────────────────────────
BRAND VOICE
──────────────────────────────────────────────────────────────
Always: calm, reflective, compassionate, intelligent, cinematic, conversational.
Never: preachy, repetitive, promotional, robotic, or generic.

──────────────────────────────────────────────────────────────
WRITING GUIDELINES
──────────────────────────────────────────────────────────────
- Write for the ear. Every sentence must sound natural spoken aloud.
- Narration pace: ~130 words per minute.
- Mix sentence lengths: short punchy lines with longer flowing passages.
- Address the viewer directly as "you".
- No stage directions, no [MUSIC], no [CUT TO], no section labels.
- No markdown formatting — pure narration text only.
- End every major section with a re-hook: a question, raised stake, or curiosity gap —
  never a summary sentence or a transition announcement.

──────────────────────────────────────────────────────────────
BASE SCRIPT TREATMENT
──────────────────────────────────────────────────────────────
The source material below is raw material — not an outline to follow, not a script to rewrite
word-for-word. You are a documentary editor. Mine it for the best ideas, strongest moments,
and most powerful insights. You are NOT expected to use all of it. Using less is better if it
means higher quality. Ruthlessly cut anything that is repetitive, slow, or doesn't directly
serve the {min_m}–{max_m} min arc.

──────────────────────────────────────────────────────────────
SOURCE MATERIAL
──────────────────────────────────────────────────────────────
Research:
{research_md}

Outline:
{script_outline}

Write the complete narration script now.\
"""


def build_review_prompt(
    topic: str,
    script: str,
    word_count: int,
    estimated_minutes: float,
    target_minutes: int = TARGET_IDEAL_MINUTES,
    channel_name: str | None = None,
) -> str:
    if channel_name is None:
        channel_name, *_ = _load_brand()

    min_m = target_minutes - DURATION_TOLERANCE_MINUTES
    max_m = target_minutes + DURATION_TOLERANCE_MINUTES

    return f"""\
You are reviewing a narration script for the {channel_name} YouTube channel.
Topic: "{topic}"
Estimated narration duration: {estimated_minutes:.1f} minutes ({word_count} words at 130 wpm)
Requested target: {target_minutes} minutes — acceptable range {min_m}–{max_m} minutes

──────────────────────────────────────────────────────────────
SCRIPT TO REVIEW
──────────────────────────────────────────────────────────────
{script}

──────────────────────────────────────────────────────────────
SCRIPT QUALITY GATE — must pass all 4 before scene planning is triggered:
──────────────────────────────────────────────────────────────
[ ] Single visual world — only one metaphor universe exists in the script
[ ] No repeated beats — no two paragraphs make the same point
[ ] Hook-to-ending loop — first and last sentence form a complete callback
[ ] No disclaimer paragraphs — all hardship is shown, not stated

If any check fails: return the script to the writer with the specific failure reason.
Do not pass it to scene planning.

──────────────────────────────────────────────────────────────
QUALITY CHECKLIST — evaluate each item as PASS or FAIL
──────────────────────────────────────────────────────────────
1. DURATION — is estimated duration within the {min_m}–{max_m} minute window?
   - If > {max_m} minutes: compress immediately (see compression rules below)
   - If < {min_m} minutes: deepen underdeveloped sections (no filler — quality only)

2. PIPELINE FORMULA — does the script follow this order without skipping a stage?
   HOOK → STORY → TENSION → REVELATION → HUMAN PARALLEL → DEEPER INSIGHT →
   PRACTICE → PHILOSOPHICAL QUESTION → CALLBACK → MEMORABLE FINAL LINE

3. HOOK — does the opening end on tension or a striking image, without explaining
   the curiosity gap it just created? Cut any sentence that explains the hook.

4. SINGLE VISUAL WORLD — does the script use only one central metaphor universe?
   Any metaphor from a different visual world is a FAIL — cut it entirely.

5. NO REPEATED BEATS — do any two paragraphs make the same point?
   If yes, remove the weaker one entirely.

6. CALLBACK LOOP — do the first and last sentence of the script form a complete loop?
   If not, fix the ending before passing to scene planning.

7. NO DISCLAIMER PARAGRAPHS — is all hardship shown through story or character,
   never stated as a direct paragraph? Direct statements are a rewrite trigger.

8. PHILOSOPHICAL QUESTION — is the final question first-person (about the viewer),
   not third-person (about the story character)?

9. CHANNEL WELCOME — is the channel welcome naturally woven in after the hook?

10. BRAND SIGNATURE — does the channel brand assertion appear once, after PRACTICE
    and before PHILOSOPHICAL QUESTION? Must not appear mid-teaching.

11. CHANNEL CLOSING — does the script end with the closing quote (after the CTA)?

12. BRAND VOICE — is the tone calm, reflective, compassionate, cinematic?
    Flag and rewrite any section that sounds preachy, generic, or promotional.

──────────────────────────────────────────────────────────────
COMPRESSION RULES (apply if duration > {max_m} minutes)
──────────────────────────────────────────────────────────────
Remove content in this order:
  1. Repeated examples
  2. Repeated explanations
  3. Weak analogies
  4. Generic transitions
  5. Redundant storytelling

NEVER remove:
  - Opening hook
  - Channel welcome
  - Core philosophical insight
  - Emotional climax
  - Practical takeaway
  - Brand signature
  - Channel closing

──────────────────────────────────────────────────────────────
INSTRUCTION
──────────────────────────────────────────────────────────────
If ANY checklist item fails: rewrite the affected sections.
If duration is > {max_m} minutes: compress before returning.
If the script is strong on all counts: return it unchanged.

Return ONLY the final script text. No commentary, no checklist results, no labels.\
"""


def build_compress_prompt(
    script: str,
    word_count: int,
    estimated_minutes: float,
    target_minutes: int = TARGET_IDEAL_MINUTES,
    channel_name: str | None = None,
) -> str:
    if channel_name is None:
        channel_name, *_ = _load_brand()

    max_m = target_minutes + DURATION_TOLERANCE_MINUTES
    max_words = max_m * NARRATION_WPM
    ideal_words = target_minutes * NARRATION_WPM

    return f"""\
This {channel_name} narration script is too long.

Current: {word_count} words (~{estimated_minutes:.1f} minutes at 130 wpm)
Target: maximum {max_words} words ({max_m} minutes)
Reduce to approximately {ideal_words} words ({target_minutes} minutes) if possible.

──────────────────────────────────────────────────────────────
SCRIPT
──────────────────────────────────────────────────────────────
{script}

──────────────────────────────────────────────────────────────
COMPRESSION RULES
──────────────────────────────────────────────────────────────
Remove content in this order:
  1. Repeated examples
  2. Repeated explanations
  3. Weak analogies
  4. Generic transitions
  5. Redundant storytelling

NEVER remove:
  - Opening hook
  - Channel welcome
  - Core philosophical insight
  - Emotional climax
  - Practical takeaway
  - Brand signature
  - Channel closing

Do NOT rewrite the script for quality — only shorten it.
Preserve the existing wording wherever possible.

Return ONLY the compressed script text. No commentary.\
"""


def build_expand_pacing_prompt(
    script: str,
    word_count: int,
    estimated_minutes: float,
    target_minutes: int = TARGET_IDEAL_MINUTES,
    channel_name: str | None = None,
) -> str:
    if channel_name is None:
        channel_name, *_ = _load_brand()

    min_m = target_minutes - DURATION_TOLERANCE_MINUTES
    min_words = min_m * NARRATION_WPM
    shortfall_min = target_minutes - estimated_minutes

    return f"""\
This {channel_name} narration script is shorter than the requested duration.

Current: {word_count} words (~{estimated_minutes:.1f} minutes at 130 wpm)
Requested: {target_minutes} minutes — minimum acceptable: {min_m} minutes ({min_words} words)
Shortfall: approximately {shortfall_min:.1f} minutes

──────────────────────────────────────────────────────────────
SCRIPT
──────────────────────────────────────────────────────────────
{script}

──────────────────────────────────────────────────────────────
PACING GUIDELINES — prefer these over adding new words
──────────────────────────────────────────────────────────────
The goal is a slower, more reflective delivery — not a longer script.

PREFERRED APPROACH (do these first):
  1. Slow the narration pace of existing lines — write for deliberate, unhurried delivery
  2. After key insights, leave reflection space: short standalone lines the narrator pauses on
  3. Give important ideas room to breathe — one idea per paragraph, not three per paragraph
  4. Use short single-sentence paragraphs at emotional peaks (they naturally slow delivery)

ONLY IF STILL BELOW MINIMUM after pacing adjustments:
  5. Deepen one underdeveloped section with a meaningful example or analogy
  6. Expand the practical reflection section with one additional concrete observation

NEVER:
  ✗ Add filler, repetition, or transitional padding
  ✗ Repeat ideas already expressed
  ✗ Add generic motivational language
  ✗ Restate the same point in different words

──────────────────────────────────────────────────────────────
PRESERVATION RULES
──────────────────────────────────────────────────────────────
- Keep the existing script structure and flow intact
- Preserve the original wording wherever possible
- Only make minimal edits — do not rewrite sections that work well
- Maintain: calm, reflective, compassionate, cinematic brand voice

Return ONLY the revised script text. No commentary.\
"""
