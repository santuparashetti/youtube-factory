"""Script enhancement prompts — transforms a raw user script into a cinematic narration.

Public API:
  build_enhance_script_prompt() — legacy single-pass prompt (preserved for callers)
  build_pass1_prompt()          — ADR-0011 Pass 1: faithful documentary rendering
  build_pass2_prompt()          — ADR-0011 Pass 2: viewer retention optimization + Narrative Score
"""

from ytfactory.agents.prompts.script_writer import (
    DURATION_TOLERANCE_MINUTES,
    NARRATION_WPM,
)

_STYLE_VOICES: dict[str, str] = {
    "spiritual": """\
VOICE & TONE
You are a calm, intimate guide speaking directly to the listener's soul — like a wise elder
sharing hard-earned truth. Your narration should feel like a guided meditation meets a TED talk.

STRUCTURE (build in this arc):
1. Open with a startling question or uncomfortable truth that stops people mid-scroll
2. Name the force / concept clearly and directly
3. Show how it controls ordinary life — concrete, relatable examples people recognize in themselves
4. Deepen: explore the inner mechanics. Why does this happen? What does it feel like inside?
5. Introduce the contrast — what the sages, monks, or wise ones discovered
6. The revelation: the truth that changes everything
7. Practical wisdom: how to see clearly and act from a different place
8. Close with a line so true that people pause, rewind, and share it

LANGUAGE:
- Grounded metaphors from nature, seasons, rivers, fire, light, shadow, seeds
- Alternate: short punchy lines (1 sentence), medium flowing thoughts (2-3 sentences), longer immersive passages (4-5 sentences)
- Moments of stillness: one word, or one line, alone — surrounded by silence
- Speak in second person ("you") to create intimacy
- Every paragraph should leave the listener feeling something""",
    "documentary": """\
VOICE & TONE: Confident documentary narrator — authoritative, warm, slightly dramatic.
Think BBC/National Geographic. Measured, clear, well-paced.
STRUCTURE: Establish → evidence → implication → broader meaning.
LANGUAGE: Precise verbs, specific details, active voice, cinematic descriptions.""",
    "history": """\
VOICE & TONE: Compelling historical storyteller — dramatic, evocative, reverent.
STRUCTURE: Context → key moment → consequence → legacy.
LANGUAGE: Rich sensory details. Place the listener inside the moment.""",
    "educational": """\
VOICE & TONE: Brilliant teacher making something genuinely fascinating.
STRUCTURE: Hook → concept → simple analogy → real implication → next concept.
LANGUAGE: Plain, direct, occasionally playful. Define jargon the moment you use it.""",
}

_ENHANCER_TEMPLATE = """\
You are a careful editor, not a rewriter.
{task_instruction}

TOPIC: {topic}
TARGET DURATION: {target_minutes} minutes of spoken narration
ACCEPTABLE RANGE: {min_m}–{max_m} minutes ({min_words}–{max_words} words at ~130 wpm)
CURRENT SCRIPT: {raw_words} words (~{raw_est:.1f} min) — you must {direction_verb} by ~{word_gap} words

{voice_guide}

───────────────────────────────────────────────────────────────
CHANNEL FRAME (additive only — do not rewrite the author's content around these)
───────────────────────────────────────────────────────────────
These elements are added to the script as-is. They frame the author's content;
they do not replace or restructure it.

  WELCOME (insert once, after the author's opening sentence):
    "{welcome}"

  TOPIC TRANSITION (insert only if the author's script has no natural transition
  from the opening into the main idea — otherwise skip it):
    "{topic_transition}..."

  BRAND SIGNATURE (insert once, after the practical reflection, before the CTA):
    "{closing_brand}"
  This re-affirms the channel identity — one line only, quietly confident.

  CALL TO ACTION (near the end, after the brand signature, one sentence):
    "{cta}"

  CLOSING (append as the final line after the CTA):
    "{closing}"

If the author's script already opens with a strong hook that flows naturally into
the main idea, insert the welcome between the first and second paragraph — do not
write bridging sentences around it. The welcome must stand on its own, not be
woven into the author's sentences.

{strategy_section}

───────────────────────────────────────────────────────────────
HOW TO THINK ABOUT DURATION
───────────────────────────────────────────────────────────────
A narrator speaking at a meditative pace does not rush between ideas.
The audience thinks during the space between paragraphs.
That thinking time is part of the duration.

A three-sentence paragraph spoken without breathing = fast.
The same three sentences each given their own paragraph = slow, contemplative.

You are writing for thinking, not just listening.
The objective is to make the audience think — not to increase the word count.

───────────────────────────────────────────────────────────────
VOICEOVER TECHNICAL RULES
───────────────────────────────────────────────────────────────
- Write ONLY natural spoken English — absolutely no markdown of any kind
- No asterisks, no pound signs, no dashes as bullets, no bold, no headers
- Spell out numbers: "forty-two" not "42", "the nineteen eighties" not "the 1980s"
- Expand abbreviations: "for example" not "e.g.", "that is" not "i.e."
- Every word must be immediately pronounceable
- Use commas rhythmically — they create breathing space in the voice
- Use ellipsis (...) only for intentional dramatic pause moments (maximum 5 per script)
- Contractions are natural: "it's", "you're", "we've", "don't"
- Avoid parentheses, brackets, semicolons — use periods and commas instead

───────────────────────────────────────────────────────────────
OUTPUT FORMAT
───────────────────────────────────────────────────────────────
Return ONLY the narration text. Nothing else.
No title. No "Here is the script:". No explanations. No section labels.
Separate major narrative sections with ONE blank line.
The text will be read aloud word-for-word.

───────────────────────────────────────────────────────────────
AUTHOR'S SCRIPT (preserve — do not rewrite):
───────────────────────────────────────────────────────────────
{script}\
"""


_EXPAND_STRATEGY = """\
───────────────────────────────────────────────────────────────
EXPANSION STRATEGY — follow this priority order exactly
───────────────────────────────────────────────────────────────
CRITICAL: The script is UNDER the target. You must ONLY add content — never remove or
shorten existing sentences. The final output MUST be longer than the original script.

Work through these priorities in order. Do not reach for a lower priority
until the higher ones are exhausted.

PRIORITY 1 — PRESERVE THE ORIGINAL WORDING
  The author's sentences are final. Do not rephrase them for clarity, style, or
  rhythm — even if you think a sentence could be improved. Keep every word.
  If a sentence is awkward, keep it. The author's imperfections are part of their voice.

PRIORITY 2 — EXTEND DURATION THROUGH PACING AND SILENCE
  Before adding a single new word, reshape how the existing content breathes.

  Techniques (apply freely to the existing text):
    — Break long paragraphs at thought boundaries. One complete idea per paragraph.
    — Give any sentence that carries a key insight its own paragraph.
    — Place a single standalone line at emotional peaks. Let it sit alone.
    — Short sentences slow the reader. Separate a short sentence from what
      surrounds it to make it land.

  This reshaping alone can add 20–40% to the spoken duration without adding words.
  Try it fully before moving to priority 5.

PRIORITY 3 — ADD MEANINGFUL PAUSES AT THOUGHT BOUNDARIES
  After each major idea completes, create visual breathing space in the text.
  A short one-sentence paragraph following a longer one tells the narrator:
  slow down, let this land before continuing.

  Signal pause locations by placing a short sentence on its own line,
  separated by blank lines above and below.

PRIORITY 4 — NATURALLY SLOW THE NARRATION
  Dense text is read fast. Sparse text is read slow.
  — Short sentences slow the reader more than long ones.
  — A paragraph with only one sentence naturally creates a pause.
  — Ellipsis (...) signals a long internal pause. Use sparingly — maximum 5 per script.
  — Do not tell the narrator to slow down. Arrange the words so they naturally do.

PRIORITY 5 — ADD NEW CONTENT ONLY WHEN NECESSARY
  Only reach for new content if priorities 1–4 still leave the script under target.
  When you do add content, it must meet the standard below.

PRIORITY 6 — WHAT VALID NEW CONTENT LOOKS LIKE
  New content must introduce something the author has not already said:
    ✓  A specific real-world example that illustrates an idea the author left abstract
    ✓  A fresh analogy that approaches the same idea from a different angle
    ✓  A question the listener is likely asking right now, followed by its answer
    ✓  A brief observation or contrast that deepens the author's point
  New content must match the author's vocabulary, sentence length, and tone exactly.
  A skilled reader should not be able to identify which sentences you added.

PRIORITY 7 — NEVER ADD ANY OF THE FOLLOWING
    ✗  Filler commentary: "This is a profound insight", "As we can see", "What this means is"
    ✗  Repetitive explanations of something the author already made clear
    ✗  Generic motivational language: "You have the strength", "Believe in yourself"
    ✗  Unnecessary introductions: "In this journey, we will explore..."
    ✗  Summaries of what was just said
    ✗  Transitions that announce themselves: "Now let's turn to..."\
"""

_SHORTEN_STRATEGY = """\
───────────────────────────────────────────────────────────────
SHORTENING STRATEGY — follow this priority order exactly
───────────────────────────────────────────────────────────────
CRITICAL: The script is OVER the target. You must remove content — but preserve
the author's voice, core message, and narrative arc completely.

Work through these priorities in order:

PRIORITY 1 — CUT REDUNDANT EXAMPLES AND REPETITION
  Identify ideas the author explains more than once. Keep the sharpest version;
  cut the rest. Cut entire paragraphs before cutting individual sentences.

PRIORITY 2 — TIGHTEN VERBOSE PASSAGES
  Find passages where 3 sentences say what 1 could. Distil to the essential idea.
  Keep the author's exact wording for the surviving sentence.

PRIORITY 3 — REMOVE LOW-VALUE TRANSITIONS
  Cut sentences that merely announce what comes next ("Now let us look at...",
  "With that in mind..."). Move directly from idea to idea.

PRIORITY 4 — PRESERVE THE CORE
  Never cut: the opening hook, the central argument, any unique insight, the closing.
  Never rephrase what you keep — only decide what stays and what goes.

PRIORITY 5 — NEVER ADD ANY OF THE FOLLOWING
    ✗  New content of any kind
    ✗  Filler commentary or summaries
    ✗  Rephrased versions of cut sentences\
"""

_POLISH_STRATEGY = """\
───────────────────────────────────────────────────────────────
POLISH STRATEGY — minimal changes only
───────────────────────────────────────────────────────────────
The script is already within the target duration range. Do NOT add or remove
significant content. Your only job is to insert the channel frame elements
below and ensure the script reads cleanly for voiceover.

Do not rewrite sentences. Do not restructure paragraphs. Make no changes
beyond inserting the channel frame elements at the specified positions.\
"""


_VOICEOVER_RULES = """\
───────────────────────────────────────────────────────────────
VOICEOVER TECHNICAL RULES
───────────────────────────────────────────────────────────────
- Write ONLY natural spoken English — absolutely no markdown of any kind
- No asterisks, no pound signs, no dashes as bullets, no bold, no headers
- Spell out numbers: "forty-two" not "42", "the nineteen eighties" not "the 1980s"
- Expand abbreviations: "for example" not "e.g.", "that is" not "i.e."
- Every word must be immediately pronounceable
- Use commas rhythmically — they create breathing space in the voice
- Use ellipsis (...) only for intentional dramatic pause moments (maximum 5 per script)
- Contractions are natural: "it's", "you're", "we've", "don't"
- Avoid parentheses, brackets, semicolons — use periods and commas instead\
"""

_PASS1_TEMPLATE = """\
You are a faithful documentary editor. Your only role in this pass is to faithfully render \
the original discourse as a clean, documentary-quality narration that loses nothing.

TOPIC: {topic}
TARGET DURATION: {target_minutes} minutes of spoken narration
ACCEPTABLE RANGE: {min_m}–{max_m} minutes ({min_words}–{max_words} words at ~{wpm} wpm)
CURRENT LENGTH: {raw_words} words (~{raw_est:.1f} min) — you must {direction_verb} by ~{word_gap} words

{voice_guide}

───────────────────────────────────────────────────────────────
SCRIPTURE PROTECTION (absolute hard constraint — overrides every other rule)
───────────────────────────────────────────────────────────────
The following spans are protected scripture or sacred text. They must appear in your output
exactly as written — no rephrasing, no compression, no splitting, no reordering.
You may change the narration surrounding a span (how it is introduced or framed), but never the span itself.
If uncertain whether a span qualifies as protected, default to treating it as protected.

{scripture_list}

───────────────────────────────────────────────────────────────
PASS 1 GOALS (apply in priority order — do not skip)
───────────────────────────────────────────────────────────────
1. Preserve meaning exactly
2. Preserve philosophy exactly — no softening, reframing, or alternative interpretation
3. Preserve emotional intent
4. Preserve every story and analogy
5. Preserve every historical reference
6. Preserve humor and speaker personality
7. Improve clarity (fix genuinely awkward phrasing only where meaning is unambiguous)
8. Improve flow (smooth abrupt transitions only where the discourse clearly jumps)

WHAT PASS 1 MUST NOT DO:
- Do not optimize for viewer retention
- Do not introduce new stories, analogies, or examples not already in the original
- Do not rearrange the order of ideas
- Do not cut content to improve pacing — preserve coverage
- Do not add channel branding, welcome message, CTA, or closing
- Do not rewrite sentences that are already clear
- If retention and fidelity ever conflict, fidelity always wins — no exceptions

───────────────────────────────────────────────────────────────
AMBIGUITY FLAGS FROM LIGHT NORMALIZATION ([FLAG:...] markers)
───────────────────────────────────────────────────────────────
The input may contain [FLAG: <reason>]...[/FLAG] spans. These were inserted by the
upstream normalization stage to mark spans it could not confidently classify as either
an artifact or intentional speech.

Your handling:
  - If you can resolve the ambiguity with high confidence (clearly intentional speech OR
    clearly a transcription artifact), resolve it and remove the [FLAG:...][/FLAG] tags.
  - If you cannot resolve it with confidence, leave the flagged span unchanged and remove
    only the [FLAG:...][/FLAG] wrapper tags (keep the content, drop the markers).
  - Never silently remove or alter the flagged content without resolving the ambiguity.
  - Never forward [FLAG:...][/FLAG] tags into your output — either resolve or unwrap them.

{strategy_section}

{voiceover_rules}

───────────────────────────────────────────────────────────────
OUTPUT FORMAT
───────────────────────────────────────────────────────────────
Return ONLY the narration text. No title. No "Here is the script:". No explanations. No section labels.
Separate major narrative sections with ONE blank line. The text will be read aloud word-for-word.

───────────────────────────────────────────────────────────────
ORIGINAL DISCOURSE (render faithfully):
───────────────────────────────────────────────────────────────
{script}\
"""

_PASS2_TEMPLATE = """\
You are a cinematic documentary writer and viewer retention specialist.
You have received a faithfully-rendered Pass 1 script that accurately represents the original discourse.
Your role is to optimize it for long-form YouTube viewer retention without compromising philosophical fidelity.

TOPIC: {topic}
TARGET DURATION: {target_minutes} minutes (~{target_words} words at ~{wpm} wpm)

{voice_guide}

───────────────────────────────────────────────────────────────
SCRIPTURE PROTECTION (absolute hard constraint)
───────────────────────────────────────────────────────────────
These spans must appear byte-for-byte in your output.
You may change surrounding narration but never the spans themselves.
{scripture_list}

───────────────────────────────────────────────────────────────
FABRICATION GUARDRAIL
───────────────────────────────────────────────────────────────
You may introduce new illustrative material to support retention, but it must be:
  - Drawn from the source discourse when possible (always preferred — zero fabrication risk)
  - Generic or clearly hypothetical ("imagine someone who...", "consider a person who...")
  - NEVER a specific named person, date, or event presented as fact unless present in the original
  - NEVER stated as verified historical fact if it was not in the original discourse

───────────────────────────────────────────────────────────────
PRIORITY ORDER (fidelity overrides retention — always)
───────────────────────────────────────────────────────────────
1. Preserve meaning
2. Preserve philosophy
3. Preserve speaker intent
4. Preserve stories and analogies
5. Increase viewer retention
6. Improve storytelling
7. Improve cinematic narration
8. Improve English

If retention and philosophical fidelity ever conflict, fidelity wins — no exceptions.
A pacing choice that alters, softens, or reframes the underlying philosophy must be rejected.

───────────────────────────────────────────────────────────────
CHANNEL FRAME (additive only — do not rewrite the author's content around these)
───────────────────────────────────────────────────────────────
  WELCOME (insert once, after the author's opening sentence):
    "{welcome}"
  TOPIC TRANSITION (insert only if no natural transition exists — otherwise skip):
    "{topic_transition}..."
  BRAND SIGNATURE (insert once, after the practical reflection, before the CTA):
    "{closing_brand}"
  CALL TO ACTION (near the end, after the brand signature):
    "{cta}"
  CLOSING (append as the final line after the CTA):
    "{closing}"

───────────────────────────────────────────────────────────────
VIEWER RETENTION RULES (apply all ten)
───────────────────────────────────────────────────────────────
Rule 1 — Prefer stories over abstract philosophy.
Whenever an idea can be communicated through story, analogy, historical example, or relatable life
situation, prefer that. People remember stories, not lectures. New material is subject to the Fabrication Guardrail.

Rule 2 — Avoid long uninterrupted philosophical exposition.
If a section contains continuous explanation for too long, introduce variation: story, analogy, question,
practical example, emotional reflection. Alternate naturally. Never feel repetitive.

Rule 3 — Preserve cinematic pacing.
Do NOT merge short sentences into long paragraphs. Intentional pauses remain.
Write for narration, not reading. Each key idea may deserve its own line.

Rule 4 — Delay branding.
Never interrupt the opening hook. Channel name, subscribe requests, and greetings belong after
emotional engagement — naturally after the hook or near the conclusion.

Rule 5 — Maintain curiosity.
Whenever possible: raise a question, delay the answer, reward the audience later.
Continuously create reasons for the viewer to keep watching.

Rule 6 — End chapters with momentum.
Avoid complete conclusions. Create transitions that pull viewers forward.
Instead of "This is why suffering exists." prefer "But understanding suffering... is only the beginning."

Rule 7 — Create memorable lines.
Generate concise reflections that viewers remember. They must emerge from the original discourse.
Never invent philosophy. Never assert a fabricated fact (see Fabrication Guardrail).

Rule 8 — Reduce unnecessary repetition.
Remove only repetition that weakens pacing. Never remove repetition that increases emotional impact.
Distinguish rhetorical repetition (keep) from spoken-language redundancy (consider removing).

Rule 9 — Preserve speaker voice.
The script must never feel AI-generated. It should feel like the original teacher speaking more clearly.

Rule 10 — Do not rewrite for the sake of rewriting.
If a section already satisfies fidelity, retention, and pacing, leave it unchanged.
A lightly-touched section that works is better than an over-edited one.

───────────────────────────────────────────────────────────────
DOCUMENTARY IDENTITY
───────────────────────────────────────────────────────────────
The documentary should feel like one continuous conversation — not visible chapters.
Transitions should be invisible. Flow from idea to idea on emotional momentum and curiosity.

───────────────────────────────────────────────────────────────
AUDIENCE ACCESSIBILITY
───────────────────────────────────────────────────────────────
Assume the audience has no prior knowledge of Vedanta, Bhagavad Gita, or Hindu philosophy.
Introduce spiritual ideas through universal human experience before scripture whenever practical.
Ancient wisdom should feel accessible, not academic.

───────────────────────────────────────────────────────────────
NARRATIVE DENSITY SELF-REVIEW (evaluate before returning)
───────────────────────────────────────────────────────────────
• Story Density: Is there a meaningful story, analogy, or situation within the first minute? Every major section?
• Narrative Variety: Do story, reflection, philosophy, question, history, and practical application alternate?
• Curiosity Check: Would a viewer naturally want to hear the next section?
• Quote Density: Approximately every 45–90 seconds, a memorable reflection or resonant statement?
• Emotional Rhythm: Does intensity naturally vary — curiosity, tension, reflection, calm, inspiration?
• Cinematic Breathing Room: Are important ideas given room, not compressed into dense paragraphs?
• Audience Accessibility: Can someone with no prior spiritual background follow the message?
• Documentary Test: Narrated over cinematic visuals with music — does it feel like a professional documentary?

Continue refining until satisfied with all dimensions.

{voiceover_rules}

───────────────────────────────────────────────────────────────
OUTPUT FORMAT
───────────────────────────────────────────────────────────────
Return the narration text, then immediately append your self-assessment in this EXACT format
(no variations, no extra lines between blocks):

---NARRATIVE SCORE---
Hook: X/10
Story Density: X/10
Curiosity: X/10
Emotional Rhythm: X/10
Accessibility: X/10
Overall: X/10
---END SCORE---

Return only narration + score block. No other explanations.
Only return when your honest assessment is Overall >= 8.5.

───────────────────────────────────────────────────────────────
PASS 1 SCRIPT (optimize this):
───────────────────────────────────────────────────────────────
{script}\
"""


def _format_scripture_list(placeholders: dict[str, str]) -> str:
    if not placeholders:
        return "(No scripture spans detected in this script.)"
    lines = []
    for key, original in placeholders.items():
        preview = original[:120] + ("…" if len(original) > 120 else "")
        lines.append(f'  {{{{{key}}}}} → "{preview}"')
    return "\n".join(lines)


def build_pass1_prompt(
    topic: str,
    script: str,
    style: str | None = None,
    target_minutes: int = 7,
    mode: str = "expand",
    raw_words: int = 0,
    placeholders: dict[str, str] | None = None,
) -> str:
    """ADR-0011 Pass 1: faithful documentary rendering prompt (no retention optimization)."""
    min_m = target_minutes - DURATION_TOLERANCE_MINUTES
    max_m = target_minutes + DURATION_TOLERANCE_MINUTES
    target_words = target_minutes * NARRATION_WPM
    min_words = min_m * NARRATION_WPM
    max_words = max_m * NARRATION_WPM
    raw_est = raw_words / NARRATION_WPM if raw_words else 0.0
    word_gap = abs(target_words - raw_words)

    if mode == "shorten":
        direction_verb = "remove"
        strategy_section = _SHORTEN_STRATEGY
    elif mode == "polish":
        direction_verb = "preserve"
        strategy_section = _POLISH_STRATEGY
    else:
        direction_verb = "add"
        strategy_section = _EXPAND_STRATEGY

    voice_guide_text = _STYLE_VOICES.get((style or "").lower().strip(), "")
    voice_guide = f"STYLE GUIDE:\n{voice_guide_text}" if voice_guide_text else ""

    return _PASS1_TEMPLATE.format(
        topic=topic,
        target_minutes=target_minutes,
        min_m=min_m,
        max_m=max_m,
        min_words=min_words,
        max_words=max_words,
        wpm=NARRATION_WPM,
        raw_words=raw_words,
        raw_est=raw_est,
        direction_verb=direction_verb,
        word_gap=int(word_gap),
        voice_guide=voice_guide,
        scripture_list=_format_scripture_list(placeholders or {}),
        strategy_section=strategy_section,
        voiceover_rules=_VOICEOVER_RULES,
        script=script,
    )


def build_pass2_prompt(
    topic: str,
    script: str,
    style: str | None = None,
    target_minutes: int = 7,
    placeholders: dict[str, str] | None = None,
    welcome: str | None = None,
    closing: str | None = None,
    topic_transition: str | None = None,
    cta: str | None = None,
    closing_brand: str | None = None,
) -> str:
    """ADR-0011 Pass 2: viewer retention optimization prompt with Narrative Score block."""
    from ytfactory.agents.prompts.branding import (
        get_closing,
        get_closing_brand,
        get_cta,
        get_transition,
        get_welcome,
    )

    target_words = target_minutes * NARRATION_WPM

    voice_guide_text = _STYLE_VOICES.get((style or "").lower().strip(), "")
    voice_guide = f"STYLE GUIDE:\n{voice_guide_text}" if voice_guide_text else ""

    return _PASS2_TEMPLATE.format(
        topic=topic,
        target_minutes=target_minutes,
        target_words=target_words,
        wpm=NARRATION_WPM,
        voice_guide=voice_guide,
        scripture_list=_format_scripture_list(placeholders or {}),
        welcome=welcome or get_welcome(),
        closing=closing or get_closing(),
        topic_transition=topic_transition or get_transition(),
        cta=cta or get_cta(),
        closing_brand=closing_brand or get_closing_brand(),
        voiceover_rules=_VOICEOVER_RULES,
        script=script,
    )


def build_enhance_script_prompt(
    topic: str,
    script: str,
    style: str | None = None,
    target_minutes: int = 7,
    welcome: str | None = None,
    closing: str | None = None,
    topic_transition: str | None = None,
    cta: str | None = None,
    closing_brand: str | None = None,
    mode: str = "expand",  # "expand" | "shorten" | "polish"
    raw_words: int = 0,
) -> str:
    from ytfactory.agents.prompts.branding import (
        get_closing,
        get_closing_brand,
        get_cta,
        get_transition,
        get_welcome,
    )

    min_m = target_minutes - DURATION_TOLERANCE_MINUTES
    max_m = target_minutes + DURATION_TOLERANCE_MINUTES
    target_words = target_minutes * NARRATION_WPM
    min_words = min_m * NARRATION_WPM
    max_words = max_m * NARRATION_WPM

    raw_est = raw_words / NARRATION_WPM if raw_words else 0.0
    word_gap = abs(target_words - raw_words)

    if mode == "shorten":
        task_instruction = (
            "Your task: take the author's raw script and SHORTEN it to fit the target duration "
            "while preserving their voice and core message."
        )
        direction_verb = "remove"
        strategy_section = _SHORTEN_STRATEGY
    elif mode == "polish":
        task_instruction = (
            "Your task: insert the channel frame elements into the author's script "
            "with minimal changes. The script is already within the target duration range."
        )
        direction_verb = "preserve"
        strategy_section = _POLISH_STRATEGY
    else:  # expand
        task_instruction = (
            "Your task: take the author's raw script and EXPAND it to reach the target duration "
            "while preserving their voice, rhythm, and message as completely as possible."
        )
        direction_verb = "add"
        strategy_section = _EXPAND_STRATEGY

    voice_guide_text = _STYLE_VOICES.get((style or "").lower().strip(), "")
    voice_guide = f"STYLE GUIDE:\n{voice_guide_text}" if voice_guide_text else ""

    return _ENHANCER_TEMPLATE.format(
        task_instruction=task_instruction,
        topic=topic,
        target_minutes=target_minutes,
        min_m=min_m,
        max_m=max_m,
        target_words=target_words,
        min_words=min_words,
        max_words=max_words,
        raw_words=raw_words,
        raw_est=raw_est,
        direction_verb=direction_verb,
        word_gap=int(word_gap),
        voice_guide=voice_guide,
        strategy_section=strategy_section,
        welcome=welcome or get_welcome(),
        closing=closing or get_closing(),
        topic_transition=topic_transition or get_transition(),
        cta=cta or get_cta(),
        closing_brand=closing_brand or get_closing_brand(),
        script=script,
    )
