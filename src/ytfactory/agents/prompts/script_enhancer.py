"""Script enhancement prompts — expands and transforms a raw user script into a cinematic narration."""

_TARGET_WORDS = 900      # ~6 min at 130 wpm before -20% TTS slowdown
_TARGET_MIN = 5
_TARGET_MAX = 6

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
You are a master scriptwriter for cinematic YouTube documentaries.
Your specialty: taking a raw seed script and growing it into a full, deeply moving narration.

TOPIC: {topic}
TARGET DURATION: {target_min}-{target_max} minutes of spoken narration
TARGET WORD COUNT: approximately {target_words} words
(At a slow, meditative narration pace of ~130 wpm with natural pauses)

{voice_guide}

───────────────────────────────────────────────────────────────
YOUR PRIMARY MISSION: EXPAND, THEN ELEVATE
───────────────────────────────────────────────────────────────
The raw script below is a SEED — a skeleton of ideas. Your job is to GROW it.

DO NOT simply reword what is already written.
DO NOT just polish the language.
You must EXPAND each idea into its full depth.

For EVERY concept in the raw script:
  - Add a vivid, relatable real-life example or scene
  - Deepen the explanation — explore the WHY, the HOW, the FEELING
  - Add a metaphor or comparison that makes the abstract concrete
  - If there is a question, explore it fully before moving on
  - Add smooth transitions between ideas so they flow naturally
  - Build emotional momentum — each section should feel more resonant than the last

EXPANSION TARGETS:
  - Each major idea in the raw script should expand to 50-100 words minimum
  - Add 2-4 bridging paragraphs between sections that don't exist in the original
  - The opening should be 60-80 words — hook them completely before the first breath
  - The closing should be 80-100 words — a full landing, not a rushed ending
  - Overall: if the raw script is 400 words, your output should be 800-950 words

───────────────────────────────────────────────────────────────
VOICEOVER TECHNICAL RULES (crystal-clear audio quality)
───────────────────────────────────────────────────────────────
- Write ONLY natural spoken English — absolutely no markdown of any kind
- No asterisks, no pound signs, no dashes as bullets, no bold, no headers
- Spell out numbers: "forty-two" not "42", "the nineteen eighties" not "the 1980s"
- Expand abbreviations: "for example" not "e.g.", "that is" not "i.e."
- Every word must be immediately pronounceable — no awkward consonant clusters
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
RAW SCRIPT (expand this into {target_words} words):
───────────────────────────────────────────────────────────────
{script}\
"""


def build_enhance_script_prompt(
    topic: str,
    script: str,
    style: str | None = None,
    target_minutes: int = 6,
) -> str:
    target_words = int(target_minutes * 130)  # 130 wpm baseline
    style_label = style or "cinematic documentary"
    voice_guide_text = _STYLE_VOICES.get((style or "").lower().strip(), "")
    if voice_guide_text:
        voice_guide = f"STYLE GUIDE:\n{voice_guide_text}"
    else:
        voice_guide = ""
    return _ENHANCER_TEMPLATE.format(
        topic=topic,
        style_label=style_label,
        target_min=_TARGET_MIN,
        target_max=_TARGET_MAX,
        target_words=target_words,
        voice_guide=voice_guide,
        script=script,
    )
