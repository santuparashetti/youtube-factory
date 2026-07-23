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


HOOK_GENERATOR_PROMPT = """\
Generate the opening 10–20 seconds of a video script.
Rules:
- No channel introduction, no "welcome to", no naming the video's frame/structure.
- Must open with one of: unexpected story, contradiction, powerful
  question, shocking fact, emotional situation.
- Introduce the mystery within the first 10 seconds.
Template: "Imagine... / But... / Because..."
"""

REHOOK_INJECTOR_PROMPT = """\
Given a script, insert a one-sentence curiosity hook every 30–45
seconds of estimated narration time. Never let a gap exceed 45 seconds.
Do not repeat rehook phrasing within the same script.
"""

TRANSITION_GENERATOR_PROMPT = """\
Replace flat "Truth N" / "Lesson N" style transitions with:
Story → Reflection → Question → Next Story.
If a story's resolution is followed by a return to the overarching
theme, you MUST insert a bridge line (reflection or question) between
the resolution and the theme recap. Never cut directly from a story's
resolution to a theme-label sentence.
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


_RELIGION_AGNOSTIC_RULES = """\
───────────────────────────────────────────────────────────────
RELIGION-AGNOSTIC PRESENTATION (ADR-0012 — hard constraint)
───────────────────────────────────────────────────────────────
This is a PRESENTATION rule, not a content rule. Philosophy and teaching content must be
preserved exactly (fidelity rules above still apply). Only the attribution and labeling
layer changes — never the substance of what is taught.

MUST NEVER APPEAR IN YOUR OUTPUT:
  - Specific tradition or religion names: Vedanta, Advaita Vedanta, Hindu philosophy,
    Sanatan Dharma, or any other explicit religious/philosophical tradition label
  - Named scripture or text titles: Bhagavad Gita, Upanishads, Puranas, or any other
    text by title, including chapter/verse citations (e.g. "Gita Chapter 2")
  - Untranslated Sanskrit presented as Sanskrit: translate the idea into plain English —
    do not label the phrase as Sanskrit or attribute it to a named source text

MAY APPEAR:
  - Named ancient teachers/wisdom figures (e.g. Adi Shankaracharya, Buddha, Rumi) —
    treat them as historical wisdom figures, not representatives of a named tradition.
    This functions like citing Marcus Aurelius: a real person, long ago, who thought
    deeply about this — it does not require the viewer to identify with any religion.
  - Universal framing: "the sages," "the ancient teachers," "ancient wisdom" — all fine.
  - Story and analogy material — unaffected by this policy.

SOURCE ATTRIBUTION LADDER (choose in order):
  1. Named historical teacher when the source material actually names one
     ("Adi Shankaracharya taught..."). Do NOT substitute a different tradition's figure.
  2. Generic ancient attribution when no specific named teacher is available
     ("One ancient teaching says...", "The sages observed...", "Ancient wisdom holds...")
  3. No attribution at all when neither adds anything to the moment.

REWRITE EXAMPLES:
  "as the Gita teaches..."           → "as one ancient teaching puts it..."
  "the Upanishads describe..."       → "the ancient teachers understood..."
  "in Hindu philosophy..."           → "across wisdom traditions..."
  "the Sanskrit term Dukkha means"   → "the teaching captures something..."

PREFERRED REPLACEMENT PHRASES:
  "Ancient wisdom" · "Ancient teachers" · "Timeless insight" · "A timeless principle"
  "One ancient teaching..." · "The sages understood..." · "Wise people throughout history..."
  "Across generations, people have discovered..."

Generalizing an attribution is NOT fabrication. "An ancient teaching says..." is safe.
Inventing a specific alternate source to fill the gap ("a Greek philosopher said...") IS
fabrication and remains prohibited by the Fabrication Guardrail above.\
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

_BRAND_BLOCK_PRESERVATION = """\
──────────────────────────────────────────────────────────────
BRAND BLOCK PRESERVATION (hard constraint — do not alter)
──────────────────────────────────────────────────────────────
If the input script already contains any brand blocks defined in brand_config.yaml,
preserve them EXACTLY as written — do not paraphrase, reorder, merge, split, or
rewrite them:

  - "This is Atma Theory." (channel signature)
  - The CTA line from brand_config.yaml
  - "Clear mind.\nMeaningful life." (signature)

These blocks are matched verbatim downstream by scene_planner._mark_asset_scenes()
to place brand asset cards — paraphrasing them breaks the match. Pass them through
unchanged even under expand/shorten modes. Channel frame insertions (welcome,
topic_transition, closing_brand, cta, closing) are the ONLY new brand material
this pass may add.
"""

_STRUCTURAL_TRANSFORMATION_RULES = """\
──────────────────────────────────────────────────────────────
STRUCTURAL TRANSFORMATION RULES (apply to delivery only — never to content)
──────────────────────────────────────────────────────────────
These rules change HOW the material is delivered. Apply them to the existing
content without introducing new arguments, facts, or conclusions.

  1. Story before philosophy — open each section with observation/scene,
     not an abstract claim. Structure: Observation → Story → Conflict → Reflection → Insight
  2. Earn every insight — delay the conclusion until Question → Curiosity →
     Story → Emotion → Reflection → Realization has played out
  3. One continuous journey — end every section with a bridge line into the next topic
  4. Emotional escalation — sections should generally intensify:
     Personal → Nature → History → Civilization → Universal Truth →
     Personal Transformation → Challenge to Viewer. Flag (do not silently fix)
     any place that would require changing content order to break continuity
  5. One dominant visual symbol — identify the strongest visual metaphor
     introduced early (grass, river, fire, mountain, seed, light, tree, etc.)
     and re-touch it at intervals; the ending should return to it explicitly
  6. Visual-first phrasing — replace abstract statements with an image the viewer
     can picture, wherever this does not require inventing new facts
  7. Rhythm variation — avoid repeated "Not X, not Y, but Z" constructions or
     other repeated syntactic patterns; alternate long cinematic sentences with
     short ones, statements with questions
  8. Continuous curiosity — at minimum every ~30–60 seconds of runtime, raise
     or resolve a question ("what happened," "why," "what changed," "what's next,"
     "how is this connected")
  9. Reward curiosity — every open question introduced must be resolved later
     in the script — no dangling hooks
  10. Memorable lines — preserve or lightly sharpen naturally-occurring quotable
      lines; do not manufacture new inspirational quotes not implied by the source
  11. Show scale — where examples are given, make visible any implied progression:
      individual → family → community → history → civilization → humanity → self
  12. Humanize historical figures — for any historical figure already in the script,
      emphasize struggle/sacrifice/uncertainty/courage/transformation using only
      facts present in the draft — never invented specifics
  13. Invisible transitions — replace hard section breaks with bridging phrases
      ("This same truth appeared again...", "But centuries later...")
  14. Spoken-performance check — every rewritten sentence readable aloud in one
      breath at a natural pace; flag anything that reads well but sounds stilted spoken
  15. Restraint — no motivational-speaker tone, no exaggeration, no overdramatization;
      calm documentary confidence throughout
"""

_SELF_REVIEW_CHECKLIST = """\
──────────────────────────────────────────────────────────────
SELF-REVIEW CHECKLIST (evaluate before returning — this is a leading indicator
for downstream Retention & Quality Standards scoring)
──────────────────────────────────────────────────────────────
Confirm ALL of the following before returning:
- Opening creates immediate curiosity
- Every section flows into the next with no visible seam
- Emotional intensity generally increases section over section
- One dominant visual metaphor unifies the piece and recurs
- Sentence rhythm is varied, not repetitive
- Something genuinely new lands roughly every 30–60 seconds
- Abstract ideas are shown as scenes wherever possible
- The ending reconnects to the opening image/idea
- Philosophy, historical accuracy, stories, and author's voice are all unchanged
- Overall feel is premium documentary, not lecture

Refine until each criterion is satisfied. A script that fails this internal
check will score poorly at quality_review downstream.
"""

_PASS1_TEMPLATE = """\
You are a faithful documentary editor. Your only role in this pass is to faithfully render \
the original discourse as a clean, documentary-quality narration that loses nothing.

TOPIC: {topic}
TARGET DURATION: {target_minutes} minutes of spoken narration
ACCEPTABLE RANGE: {min_m}-{max_m} minutes ({min_words}-{max_words} words at ~{wpm} wpm)
CURRENT LENGTH: {raw_words} words (~{raw_est:.1f} min) — you must {direction_verb} by ~{word_gap} words

{voice_guide}

{architecture_context}

{comparison_context}

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

{brand_block_preservation}

{structural_transformation_rules}

REGISTER-SHIFT BRIDGES (expands Rule 13: Invisible transitions):
When a section shifts from abstract metaphor/personification to direct audience
address ("you"), or from any register to a clearly different one, do NOT insert a
hard cut. Insert exactly one bridge line that carries the listener across:
  "This same feeling — the one you've tried to name — ..."
  "You know this moment, even if you've never put words to it ..."
  "And here is where it leads, if we follow it honestly ..."
The bridge must acknowledge the register shift, not ignore it.

{religion_agnostic_rules}

──────────────────────────────────────────────────────────────
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

{architecture_context}

{comparison_context}

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

{religion_agnostic_rules}

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

{brand_block_preservation}

──────────────────────────────────────────────────────────────
CHANNEL FRAME (additive only — do not rewrite the author's content around these)
──────────────────────────────────────────────────────────────
{welcome_block}
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

Rule 4 — Delay branding and frame naming.
Never interrupt the opening hook. Channel name, subscribe requests, and greetings belong after
emotional engagement — naturally after the hook or near the conclusion.
Do not name the video's structural frame ("four truths", "three lessons", "key takeaway") in
the opening 10–20 seconds. Name the frame only after the first curiosity hook has landed.
Introducing the frame too early turns mystery into a checklist — viewers leave.

Rule 5 — Maintain curiosity.
Whenever possible: raise a question, delay the answer, reward the audience later.
A question without an immediate answer creates a knowledge gap the viewer wants closed.
Continuously create reasons for the viewer to keep watching. Never let a curiosity gap
go unresolved for more than 45 seconds of narration — reward patience, don't abuse it.

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
Assume the audience has no prior spiritual background and no familiarity with any specific
tradition, text, or philosophical lineage. Do not name them — the RELIGION-AGNOSTIC
PRESENTATION rules above govern this.
Introduce ideas through universal human experience before abstract concepts whenever practical.
Ancient wisdom should feel accessible to any viewer, not academic or tradition-exclusive.

───────────────────────────────────────────────────────────────
SELF-REVIEW CHECKLIST (evaluate before returning — this is a leading indicator
for downstream Retention & Quality Standards scoring)
───────────────────────────────────────────────────────────────
- Opening creates immediate curiosity
- Every section flows into the next with no visible seam
- Emotional intensity generally increases section over section
- One dominant visual metaphor unifies the piece and recurs
- Sentence rhythm is varied, not repetitive
- Something genuinely new lands roughly every 30–60 seconds
- Abstract ideas are shown as scenes wherever possible
- The ending reconnects to the opening image/idea
- Philosophy, historical accuracy, stories, and author's voice are all unchanged
- Overall feel is premium documentary, not lecture

A script that fails this internal check will score poorly at quality_review downstream.

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
EDITOR'S NOTES:
dominant_visual_symbol: [name of visual metaphor]
rule_skips: [none, or comma-separated Section 3 rules skipped with reason]
factual_gaps: [none, or brief description of any factual gap noticed but not filled]

Return only narration + score block + editor's notes. No other explanations.
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
    architecture_analysis: dict | None = None,
    comparison_report: dict | None = None,
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

    architecture_context = (
        _format_architecture_summary(architecture_analysis)
        if architecture_analysis
        else ""
    )
    comparison_context = (
        _format_comparison_summary(comparison_report)
        if comparison_report
        else ""
    )

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
        religion_agnostic_rules=_RELIGION_AGNOSTIC_RULES,
        brand_block_preservation=_BRAND_BLOCK_PRESERVATION,
        structural_transformation_rules=_STRUCTURAL_TRANSFORMATION_RULES,
        strategy_section=strategy_section,
        voiceover_rules=_VOICEOVER_RULES,
        script=script,
        architecture_context=architecture_context,
        comparison_context=comparison_context,
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
    architecture_analysis: dict | None = None,
    comparison_report: dict | None = None,
) -> str:
    """ADR-0011 Pass 2: viewer retention optimization prompt with Narrative Score block."""
    from ytfactory.agents.prompts.branding import (
        get_closing,
        get_closing_brand,
        get_cta,
        get_transition,
        get_welcome,
    )
    from ytfactory.branding.config import get_brand_config

    target_words = target_minutes * NARRATION_WPM

    voice_guide_text = _STYLE_VOICES.get((style or "").lower().strip(), "")
    voice_guide = f"STYLE GUIDE:\n{voice_guide_text}" if voice_guide_text else ""

    architecture_context = (
        _format_architecture_summary(architecture_analysis)
        if architecture_analysis
        else ""
    )
    comparison_context = (
        _format_comparison_summary(comparison_report)
        if comparison_report
        else ""
    )

    welcome_text = welcome or get_welcome()
    if welcome is None and not get_brand_config().opening.enabled:
        welcome_block = ""
    else:
        welcome_block = (
            f"  WELCOME (insert once, after the author's opening sentence):\n"
            f'    "{welcome_text}"'
        )

    return _PASS2_TEMPLATE.format(
        topic=topic,
        target_minutes=target_minutes,
        target_words=target_words,
        wpm=NARRATION_WPM,
        voice_guide=voice_guide,
        scripture_list=_format_scripture_list(placeholders or {}),
        religion_agnostic_rules=_RELIGION_AGNOSTIC_RULES,
        brand_block_preservation=_BRAND_BLOCK_PRESERVATION,
        self_review_checklist=_SELF_REVIEW_CHECKLIST,
        welcome_block=welcome_block,
        closing=closing or get_closing(),
        topic_transition=topic_transition or get_transition(),
        cta=cta or get_cta(),
        closing_brand=closing_brand or get_closing_brand(),
        voiceover_rules=_VOICEOVER_RULES,
        script=script,
        architecture_context=architecture_context,
        comparison_context=comparison_context,
    )


def build_analysis_prompt(source_transcript: str) -> str:
    return """\
You are an expert YouTube documentary editor analyzing an author's original source material.

Your task is to understand and map the author's architecture. Do NOT rewrite anything.

SOURCE TRANSCRIPT:
{source_transcript}

Extract and output the following in a concise structured format:
- central_philosophy: The core belief or thesis in 1-2 sentences
- main_thesis: The primary argument or message
- supporting_ideas: List of key supporting points
- stories: Any stories, parables, or anecdotes (titles/brief descriptions)
- historical_examples: Any historical references
- analogies: Any analogies used
- emotional_progression: The emotional arc of the piece (e.g., curiosity -> story -> reflection -> insight)
- ending_message: The closing takeaway
- progression_of_ideas: The step-by-step flow of ideas — describe the exact order in which the author builds their argument. Use the format:
  Idea A
  ->
  Idea B
  ->
  Idea C
  etc.
- has_clear_progression: true if there is a clear narrative architecture; false if it is built from repeated refrains, parallel parables, or a meditative/poetic structure
- implicit_structure: the closest implicit structure present if has_clear_progression is false; empty string otherwise

Output ONLY valid JSON. No explanations. No markdown fences.
""".format(source_transcript=source_transcript)


def build_comparison_prompt(
    source_transcript: str,
    generated_script: str,
) -> str:
    return """\
You are an expert YouTube documentary editor comparing a generated script against the original author's source material.

Your task is to identify gaps, losses, and weaknesses in the generated script compared to the original. Do NOT rewrite anything yet — just report.

ORIGINAL SOURCE TRANSCRIPT:
{source_transcript}

GENERATED SCRIPT:
{script}

Analyze and return ONLY valid JSON with these fields:
- missing_ideas: Ideas present in the original but missing or only weakly represented in the generated script
- missing_examples: Specific examples, stories, or analogies from the original that were dropped or weakened
- lost_progression: Any breaks or reordering in the progression of ideas compared to the original
- flattened_emotional_arc: Places where the emotional intensity was reduced
- weak_transitions: Sections where transitions feel abrupt or missing
- repetition: Ideas that are repeated unnecessarily in the generated script
- missed_curiosity_opportunities: Places where the original built curiosity that the generated script lost
- abrupt_jumps: Ideas that jump without smooth transition in the generated script
- lost_storytelling_moments: Story beats that were diluted or removed
- overall_assessment: concise summary of the gaps

No explanations. No markdown fences. Output ONLY valid JSON.
""".format(source_transcript=source_transcript, script=generated_script)


def _format_architecture_summary(analysis: dict) -> str:
    lines = [
        f"CENTRAL PHILOSOPHY: {analysis.get('central_philosophy', 'N/A')}",
        f"MAIN THESIS: {analysis.get('main_thesis', 'N/A')}",
        "",
        "SUPPORTING IDEAS:",
    ]
    for idea in analysis.get("supporting_ideas", []):
        lines.append(f"  - {idea}")
    lines.extend(
        [
            "",
            "STORIES:",
        ]
    )
    for story in analysis.get("stories", []):
        lines.append(f"  - {story}")
    lines.extend(
        [
            "",
            "HISTORICAL EXAMPLES:",
        ]
    )
    for ex in analysis.get("historical_examples", []):
        lines.append(f"  - {ex}")
    lines.extend(
        [
            "",
            "ANALOGIES:",
        ]
    )
    for analogy in analysis.get("analogies", []):
        lines.append(f"  - {analogy}")
    lines.extend(
        [
            "",
            f"EMOTIONAL PROGRESSION: {analysis.get('emotional_progression', 'N/A')}",
            f"ENDING MESSAGE: {analysis.get('ending_message', 'N/A')}",
            "",
            "PROGRESSION OF IDEAS:",
        ]
    )
    has_clear = analysis.get("has_clear_progression", True)
    if has_clear:
        for step in analysis.get("progression_of_ideas", []):
            lines.append(f"  {step}")
    else:
        implicit = analysis.get("implicit_structure", "unknown")
        lines.append(f"  [No clear linear progression — closest implicit structure: {implicit}]")
    return "\n".join(lines)


def _format_comparison_summary(comparison: dict) -> str:
    lines = [
        "GENERATED SCRIPT GAPS (generated script vs original source):",
        "",
        f"OVERALL ASSESSMENT: {comparison.get('overall_assessment', 'N/A')}",
        "",
        "MISSING IDEAS:",
    ]
    for idea in comparison.get("missing_ideas", []):
        lines.append(f"  - {idea}")
    lines.extend(
        [
            "",
            "MISSING EXAMPLES / STORIES:",
        ]
    )
    for ex in comparison.get("missing_examples", []):
        lines.append(f"  - {ex}")
    lines.extend(
        [
            "",
            "LOST PROGRESSION:",
            f"  {comparison.get('lost_progression', 'None detected')}",
            "",
            "FLATTENED EMOTIONAL ARC:",
        ]
    )
    for arc in comparison.get("flattened_emotional_arc", []):
        lines.append(f"  - {arc}")
    lines.extend(
        [
            "",
            "WEAK TRANSITIONS:",
        ]
    )
    for t in comparison.get("weak_transitions", []):
        lines.append(f"  - {t}")
    lines.extend(
        [
            "",
            "REPETITION:",
        ]
    )
    for r in comparison.get("repetition", []):
        lines.append(f"  - {r}")
    lines.extend(
        [
            "",
            "MISSED CURIOSITY OPPORTUNITIES:",
        ]
    )
    for c in comparison.get("missed_curiosity_opportunities", []):
        lines.append(f"  - {c}")
    lines.extend(
        [
            "",
            "ABRUPT JUMPS:",
        ]
    )
    for j in comparison.get("abrupt_jumps", []):
        lines.append(f"  - {j}")
    lines.extend(
        [
            "",
            "LOST STORYTELLING MOMENTS:",
        ]
    )
    for s in comparison.get("lost_storytelling_moments", []):
        lines.append(f"  - {s}")
    return "\n".join(lines)


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
