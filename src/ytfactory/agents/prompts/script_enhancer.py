"""Script enhancement prompts — transforms a raw user script into a cinematic narration."""

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
You are a master scriptwriter for cinematic YouTube documentaries for the Atma Theory channel.
Your task: take a raw seed script and grow it into a full, deeply moving narration
while staying faithful to the source — preserving its structure, tone, and meaning.

TOPIC: {topic}
TARGET DURATION: {target_minutes} minutes of spoken narration
ACCEPTABLE RANGE: {min_m}–{max_m} minutes ({min_words}–{max_words} words at ~130 wpm)

{voice_guide}

───────────────────────────────────────────────────────────────
ATMA THEORY BRAND STRUCTURE (mandatory — weave in naturally)
───────────────────────────────────────────────────────────────
The finished script must follow this arc:

1. HOOK — open with a compelling question, uncomfortable truth, or vivid scene.

2. WELCOME — immediately after the hook, flow naturally into this exact line:
     "{welcome}"
   Write 1-2 sentences that bridge from the hook to the welcome seamlessly.
   The welcome must feel like a continuation of the opening thought.

3. TOPIC TRANSITION — one sentence moving into the subject, starting with:
     "{topic_transition}..."

4. MAIN CONTENT — the full exploration. Expand every idea deeply.

5. REFLECTION — draw the insight back to the listener's own life.

6. CALL TO ACTION (near the end, soft and conversational):
     "If this perspective helped you see life a little differently, \
consider joining us for the next journey."

7. CLOSING — end with this exact phrase, written so it lands with quiet impact:
     "{closing}"

Brand voice: calm, reflective, compassionate, wise, conversational, cinematic.
Never: preachy, sales-driven, overly dramatic, or promotional.

───────────────────────────────────────────────────────────────
PRESERVATION FIRST — THEN ELEVATE
───────────────────────────────────────────────────────────────
The raw script below is the SOURCE OF TRUTH.

DO NOT rewrite it unnecessarily.
DO NOT add filler words to reach the target duration.
Treat it as a seed: expand only where the idea is underdeveloped.

For each concept in the raw script:
  - Preserve the original phrasing wherever it reads naturally
  - Add a vivid, relatable example ONLY if the idea lacks one
  - Deepen the explanation ONLY if it feels incomplete
  - Add smooth transitions where ideas don't connect naturally

PACING OVER PADDING:
  If the script is shorter than target, prefer slower, more deliberate delivery:
  - Break key insights into shorter paragraphs (they naturally slow narration)
  - Give important lines room to breathe — one idea per paragraph
  - Use short standalone lines at emotional peaks (pause effect)
  Do NOT add new ideas simply to fill time.

EXPANSION TARGETS (apply only where needed):
  - Each major idea should reach at least 40 words if underdeveloped
  - Add 1-2 bridging sentences between disconnected sections
  - If the opening is under 40 words, strengthen it — but do not pad it

───────────────────────────────────────────────────────────────
VOICEOVER TECHNICAL RULES
───────────────────────────────────────────────────────────────
- Write ONLY natural spoken English — absolutely no markdown of any kind
- No asterisks, no pound signs, no dashes as bullets, no bold, no headers
- Spell out numbers: "forty-two" not "42", "the nineteen eighties" not "the 1980s"
- Expand abbreviations: "for example" not "e.g.", "that is" not "i.e."
- Every word must be immediately pronounceable
- Use commas rhythmically — they create breathing space in the voice
- Use ellipsis (...) only for intentional dramatic pause moments (maximum 5-6 per script)
- Contractions are natural: "it's", "you're", "we've", "don't"
- Avoid parentheses, brackets, semicolons — use periods and commas instead
- Each paragraph = one complete thought, 15-25 seconds to speak aloud

───────────────────────────────────────────────────────────────
OUTPUT FORMAT
───────────────────────────────────────────────────────────────
Return ONLY the narration text. Nothing else.
No title. No "Here is the script:". No explanations. No section labels.
Separate major narrative sections with ONE blank line.
The text will be read aloud word-for-word — every word must earn its place.

───────────────────────────────────────────────────────────────
RAW SCRIPT (source of truth — preserve and elevate):
───────────────────────────────────────────────────────────────
{script}\
"""


def build_enhance_script_prompt(
    topic: str,
    script: str,
    style: str | None = None,
    target_minutes: int = 7,
    welcome: str | None = None,
    closing: str | None = None,
    topic_transition: str | None = None,
) -> str:
    from ytfactory.agents.prompts.branding import (
        get_closing,
        get_transition,
        get_welcome,
    )

    min_m = target_minutes - DURATION_TOLERANCE_MINUTES
    max_m = target_minutes + DURATION_TOLERANCE_MINUTES
    target_words = target_minutes * NARRATION_WPM
    min_words = min_m * NARRATION_WPM
    max_words = max_m * NARRATION_WPM

    voice_guide_text = _STYLE_VOICES.get((style or "").lower().strip(), "")
    voice_guide = f"STYLE GUIDE:\n{voice_guide_text}" if voice_guide_text else ""

    return _ENHANCER_TEMPLATE.format(
        topic=topic,
        target_minutes=target_minutes,
        min_m=min_m,
        max_m=max_m,
        target_words=target_words,
        min_words=min_words,
        max_words=max_words,
        voice_guide=voice_guide,
        welcome=welcome or get_welcome(),
        closing=closing or get_closing(),
        topic_transition=topic_transition or get_transition(),
        script=script,
    )
