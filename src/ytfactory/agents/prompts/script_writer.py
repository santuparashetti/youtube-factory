"""Script writer agent prompts — V2 pacing and duration rules."""

# Narration pace used throughout the pipeline (speech optimizer, enhancer, scene planner).
NARRATION_WPM = 130

# Tolerance window: requested duration ±1 minute is acceptable.
DURATION_TOLERANCE_MINUTES = 1

# Default targets (used when state provides no target_minutes).
TARGET_MIN_MINUTES = 5
TARGET_IDEAL_MINUTES = 7
TARGET_MAX_MINUTES = 10

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
DURATION TARGET
──────────────────────────────────────────────────────────────
- Requested: {target_minutes} minutes of narration (~{ideal_words} words at 130 wpm)
- Acceptable range: {min_m}–{max_m} minutes ({min_words}–{max_words} words) — hard limit
- If the topic naturally fits fewer words, write a tight, exceptional script.
  Do NOT pad to reach the target — every sentence must earn its place.
- Prefer a slightly slower, more reflective narration pace over adding extra sentences.

──────────────────────────────────────────────────────────────
SCRIPT STRUCTURE (follow this order)
──────────────────────────────────────────────────────────────
1. HOOK (first 15–20 seconds):
   Open with ONE compelling entry: a shocking statistic, a provocative question,
   a vivid scene, or a counter-intuitive claim. Make the viewer unable to stop.

2. CHANNEL WELCOME (immediately after the hook):
   Flow naturally from the hook into this exact welcome line:
     "{welcome}"
   Write 1–2 sentences that bridge seamlessly. The welcome is a continuation,
   not an announcement.

3. TOPIC TRANSITION:
   One sentence introducing the subject. Begin with:
     "{topic_transition}..."

4. BUILD CURIOSITY:
   Raise the stakes. Surface the tension, paradox, or hidden truth at the
   heart of this topic. Make the viewer need to know more.

5. MAIN EXPLORATION (3–5 sections):
   Each section flows into the next. Use storytelling, concrete examples,
   and specific facts from the research. Never use bullet points.

6. DEEP INSIGHT:
   The pivotal revelation — the idea that reframes everything the viewer
   thought they understood about this topic.

7. PRACTICAL REFLECTION (30 seconds):
   Draw the insight back to the listener's own life. Specific and actionable.

8. BRAND SIGNATURE (one line, immediately after reflection):
   Re-affirm the channel identity with quiet confidence:
     "{closing_brand}"
   This is the moment of re-grounding — not a promotional statement. One line only.

9. CALL TO ACTION (10 seconds — place naturally after the brand signature):
   Use this exact soft CTA:
     "{cta}"

10. CLOSING QUOTE (final line):
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
COMPRESSION (if your draft runs long)
──────────────────────────────────────────────────────────────
If your draft exceeds {max_words} words, shorten by removing in this order:
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
- End every major section with a line that hooks into the next.

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
QUALITY CHECKLIST — evaluate each item as PASS or FAIL
──────────────────────────────────────────────────────────────
1. DURATION — is estimated duration within the {min_m}–{max_m} minute window?
   - If > {max_m} minutes: compress immediately (see compression rules below)
   - If < {min_m} minutes: deepen underdeveloped sections (no filler — quality only)

2. HOOK — does the opening grab attention within the first 15–20 seconds?

3. INFORMATION DENSITY — does every sentence deliver at least one of:
   new insight / analogy / emotional progression / practical wisdom / narrative advance?
   Remove any sentence that merely restates or pads.

4. NO REPETITION — are there any repeated ideas, examples, or explanations?
   If yes, remove the weaker instance entirely.

5. STORY PROGRESSION — does the script build naturally through:
   Hook → Welcome → Curiosity → Exploration → Deep Insight → Reflection
   → Brand Signature → CTA → Closing Quote?

6. CHANNEL WELCOME — is the channel welcome naturally woven in after the hook?

7. BRAND SIGNATURE — does the channel brand assertion appear once, after reflection
   and before the CTA? It must not appear in the middle of the teaching.

8. CHANNEL CLOSING — does the script end with the closing quote (after the CTA)?

9. BRAND VOICE — is the tone calm, reflective, compassionate, cinematic?
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
