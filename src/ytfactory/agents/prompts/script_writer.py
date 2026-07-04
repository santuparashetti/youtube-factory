"""Script writer agent prompts."""

# Narration pace used throughout the pipeline (speech optimizer, enhancer, scene planner).
NARRATION_WPM = 130

# Duration targets (minutes → words at NARRATION_WPM)
TARGET_MIN_MINUTES = 5
TARGET_IDEAL_MINUTES = 8
TARGET_MAX_MINUTES = 10

TARGET_MIN_WORDS = TARGET_MIN_MINUTES * NARRATION_WPM    # 650
TARGET_IDEAL_WORDS = TARGET_IDEAL_MINUTES * NARRATION_WPM  # 1040
TARGET_MAX_WORDS = TARGET_MAX_MINUTES * NARRATION_WPM    # 1300


WRITE_SCRIPT = """\
You are a professional documentary scriptwriter for the Atma Theory channel on YouTube.

Write a complete narration script for a YouTube video about: {topic}

Use the research and outline below as your source material.

──────────────────────────────────────────────────────────────
DURATION TARGET
──────────────────────────────────────────────────────────────
- Ideal: 7–8 minutes of narration (~910–1040 words at 130 wpm)
- Minimum: 5 minutes (~650 words)
- Maximum: 10 minutes (~1300 words) — HARD LIMIT, never exceed
- If the topic naturally fits 6 minutes, write an exceptional 6-minute script.
  Do NOT pad to reach a longer duration.

──────────────────────────────────────────────────────────────
SCRIPT STRUCTURE (follow this order)
──────────────────────────────────────────────────────────────
1. HOOK (first 15–20 seconds):
   Open with ONE compelling entry: a shocking statistic, a provocative question,
   a vivid scene, or a counter-intuitive claim. Make the viewer unable to stop.

2. ATMA THEORY WELCOME (immediately after the hook):
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

8. CALL TO ACTION (10 seconds — place naturally near the end):
   Use this exact soft CTA:
     "If this perspective helped you see life a little differently, \
consider joining us for the next journey."

9. ATMA THEORY CLOSING (final line):
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
If your draft exceeds 1300 words, shorten it by removing in this order:
  1. Repeated examples
  2. Repeated explanations
  3. Weak analogies
  4. Generic transitions
  5. Redundant storytelling

NEVER remove:
  - Opening hook
  - Atma Theory welcome
  - Core philosophical insight
  - Emotional climax
  - Practical takeaway
  - Atma Theory closing

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


SELF_REVIEW_SCRIPT = """\
You are reviewing a narration script for the Atma Theory YouTube channel.
Topic: "{topic}"
Estimated narration duration: {estimated_minutes:.1f} minutes ({word_count} words at 130 wpm)
Target: 5–10 minutes (ideal 7–8 minutes)

──────────────────────────────────────────────────────────────
SCRIPT TO REVIEW
──────────────────────────────────────────────────────────────
{script}

──────────────────────────────────────────────────────────────
QUALITY CHECKLIST — evaluate each item as PASS or FAIL
──────────────────────────────────────────────────────────────
1. DURATION — is estimated duration between 5 and 10 minutes?
   - If > 10 minutes: compress immediately (see compression rules below)
   - If < 5 minutes: add depth to underdeveloped sections (not filler)

2. HOOK — does the opening grab attention within the first 15–20 seconds?

3. INFORMATION DENSITY — does every sentence deliver at least one of:
   new insight / analogy / emotional progression / practical wisdom / narrative advance?
   Remove any sentence that merely restates or pads.

4. NO REPETITION — are there any repeated ideas, examples, or explanations?
   If yes, remove the weaker instance entirely.

5. STORY PROGRESSION — does the script build naturally through:
   Hook → Welcome → Curiosity → Exploration → Deep Insight → Reflection → Closing?

6. ATMA THEORY WELCOME — is the channel welcome naturally woven in after the hook?

7. ATMA THEORY CLOSING — does the script end with the closing phrase?

8. BRAND VOICE — is the tone calm, reflective, compassionate, cinematic?
   Flag and rewrite any section that sounds preachy, generic, or promotional.

──────────────────────────────────────────────────────────────
COMPRESSION RULES (apply if duration > 10 minutes)
──────────────────────────────────────────────────────────────
Remove content in this order:
  1. Repeated examples
  2. Repeated explanations
  3. Weak analogies
  4. Generic transitions
  5. Redundant storytelling

NEVER remove:
  - Opening hook
  - Atma Theory welcome
  - Core philosophical insight
  - Emotional climax
  - Practical takeaway
  - Atma Theory closing

──────────────────────────────────────────────────────────────
INSTRUCTION
──────────────────────────────────────────────────────────────
If ANY checklist item fails: rewrite the affected sections.
If duration is > 10 minutes: compress before returning.
If the script is strong on all counts: return it unchanged.

Return ONLY the final script text. No commentary, no checklist results, no labels.\
"""


COMPRESS_SCRIPT = """\
This Atma Theory narration script is too long.

Current: {word_count} words (~{estimated_minutes:.1f} minutes at 130 wpm)
Target: maximum {target_max_words} words (10 minutes)
Reduce to approximately {target_ideal_words} words (7–8 minutes) if possible.

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
  - Atma Theory welcome
  - Core philosophical insight
  - Emotional climax
  - Practical takeaway
  - Atma Theory closing

Do NOT rewrite the script for quality — only shorten it.
Preserve the existing wording wherever possible.

Return ONLY the compressed script text. No commentary.\
"""
