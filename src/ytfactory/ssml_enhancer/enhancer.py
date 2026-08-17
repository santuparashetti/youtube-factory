"""SSML Enhancement — transform raw narration into Speechify-compatible SSML.

Runs immediately before the TTS call when SSML_ENHANCEMENT_ENABLED=true.
Produces two outputs:
  ssml_script  — sent to Speechify TTS only
  clean_script — derived via strip_ssml(), used for subtitle generation only
"""

from __future__ import annotations

import re

from loguru import logger

from video_core.providers.llm.base import LLMProvider
from ytfactory.emotion.policy import NarrativePhase, emotion_policy

_SYSTEM_PROMPT = """\
You are an expert audio director for a spiritual philosophy channel.
Your ONLY job is to wrap the given narration text in Speechify-compatible SSML
that sounds deeply natural, expressive, and emotionally alive.

ABSOLUTE RULE — every word in your output must come from the input, in the same order.
Do NOT add sentences, phrases, or words. Do NOT paraphrase or expand.
The text is fixed. Your job is markup only.

━━━ SANSKRIT ━━━

The input may contain Sanskrit in two forms:

1. [SANSKRIT] placeholder — Devanagari script was detected and pre-replaced.
   Output [SANSKRIT] exactly as-is.

2. Romanized Sanskrit — Latin-script transliterations in the input, typically quoted,
   e.g. "Satkara-sevito dirghakala-nairantaryabhyaso dridhabhumih."
   These are Sanskrit sutras or mantras written in Roman script.
   Recognise them by: hyphenated compound Sanskrit words, endings like -ah, -ih, -am,
   -bhyaso, -bhumih, -nairantarya, or any text that is clearly not English.

For BOTH forms, replace with exactly this in your SSML output:
  In the words of the ancient seers.<break time="3.0s"/><prosody volume="silent">''</prosody><break time="20ms"/>

Never attempt to pronounce, transliterate, or explain Sanskrit text.
The Sanskrit appears on screen during the 3-second pause.

━━━ APPROACH ━━━

Make the narration feel like a master storyteller speaking from the heart.
Use emotion, prosody, and emphasis dynamically — based on what the words actually mean.
Give listeners breathing room: use <break> tags wherever a pause helps the listener absorb
the meaning. Place breaks BETWEEN sentences, inside a style block — never at the very end
of a block (before </speechify:style>) and never between style blocks.

━━━ STRUCTURE ━━━

Group sentences by emotional beat. Each beat gets a <speechify:style> block.
Inside each block, place a <break> between sentences so the listener has time to absorb.
Wrap key phrases in <prosody> for pacing and intimacy.

<speak>
  <speechify:style emotion="calm">
    <prosody rate="medium" pitch="low">Opening thought that needs gravitas.</prosody>
    <break time="1.3s"/>
    A second sentence in the same emotional register.
  </speechify:style>
  <speechify:style emotion="warm">
    A sentence that lifts with warmth.<break time="1.2s"/>
    <prosody rate="medium" pitch="low">A phrase within it that returns to centre.</prosody>
  </speechify:style>
  <speechify:style emotion="assertive">
    <emphasis level="strong">Key word</emphasis> drives this sentence home.
  </speechify:style>
</speak>

━━━ TAGS ━━━

<speechify:style emotion="X">:
- ALWAYS opening + closing tags, NEVER self-closing
- Do NOT nest style blocks
- Available emotions: angry, cheerful, sad, terrified, relaxed, fearful,
  surprised, calm, assertive, energetic, warm, direct, bright
- Choose the emotion that fits the meaning — use the full palette, not just calm
- One emotional beat per block (a sentence or short group of sentences)

<break time="Xs"/>:
- Use SPARINGLY — only when the listener genuinely needs a moment to absorb what was just said
- A profound truth, a surprising turn, a question that lands — these earn a break
- Routine sentence transitions do NOT need a break; the style block transition already creates breath
- Never place between style blocks — only inside a block, between sentences
- Typical range 1.0s–2.0s; longer after a statement that needs to echo in silence

<prosody rate="medium" pitch="low">:
- ALWAYS use exactly rate="medium" pitch="low" — no other values
- Wrap phrases or full sentences that need grounded, measured delivery
- Do NOT set volume

<emphasis level="strong">:
- Use ONLY on the first word of a sentence that immediately follows a <break> tag
- This helps the voice engine commit to the first phoneme cleanly after silence
- Do NOT use emphasis elsewhere — let the emotion and prosody carry the weight

Escape & → &amp; in spoken text only, never in tags.
Return raw SSML only. No explanation, no markdown, no preamble.\
"""

# All SSML tags that strip_ssml must remove.
_TAG_RE = re.compile(
    r"<speak>"
    r"|</speak>"
    r"|<speechify:style(?:\s[^>]*)?\s*/>"   # self-closing (invalid but strip safely)
    r"|<speechify:style(?:\s[^>]*)? *>"     # wrapping open tag
    r"|</speechify:style>"                  # wrapping close tag
    r"|<break(?:\s[^/]*)?\s*/>"
    r"|<prosody(?:\s[^>]*)? *>"
    r"|</prosody>"
    r"|<emphasis(?:\s[^>]*)? *>"
    r"|</emphasis>"
    r"|<sub(?:\s[^>]*)? *>"
    r"|</sub>",
    re.IGNORECASE,
)

_WHITESPACE_RE = re.compile(r"[ \t]+")
_NEWLINE_RE = re.compile(r"\n{2,}")
# LLMs sometimes capitalise the namespace: <Speechify:style — fix to lowercase.
_SPEECHIFY_OPEN_CAP = re.compile(r'<Speechify:style\b', re.IGNORECASE)
_SPEECHIFY_CLOSE_CAP = re.compile(r'</Speechify:style\s*>', re.IGNORECASE)
# Self-closing <speechify:style .../> is invalid — drop it.
_SPEECHIFY_SELFCLOSE = re.compile(r'<speechify:style\b[^>]*/>', re.IGNORECASE)
# Trailing breaks/warm-ups before </speak> — dead air at end of clip.
_TRAILING_BREAKS_BEFORE_SPEAK_CLOSE = re.compile(
    r'(\s*(?:<break[^/]*/>\s*|<prosody rate="x-fast"[^>]*>[^<]*</prosody>\s*))+</speak>',
    re.IGNORECASE,
)
# Spurious warm-ups injected by LLM at the START of a style block.
_WARMUP_AT_BLOCK_START = re.compile(
    r'(<speechify:style\b[^>]*>)\s*(?:<prosody rate="x-fast"[^>]*>[^<]*</prosody>\s*)',
    re.IGNORECASE,
)
# Real pause breaks not already followed by the warm-up prosody.
_PAUSE_BREAK_RE = re.compile(
    r'(<break time="[^"]+"/>)'
    r'(?!\s*<prosody rate="x-fast")',
    re.IGNORECASE,
)
# Bridge token appended after every real pause — keeps Speechify synthesis
# context warm so the next word (or next block) starts without clipping.
_WARMUP = '<prosody rate="x-fast" volume="x-soft">m</prosody>'

# Sanskrit handling — Devanagari lines are masked before the LLM sees them
# and replaced with a silence break in the SSML output.
_SANSKRIT_LINE_RE = re.compile(r'[^\n]*[ऀ-ॿ][^\n]*', re.MULTILINE)
# Romanized Sanskrit: quoted strings containing ≥2 hyphenated compound words
# where each part is ≥5 chars (e.g. "Satkara-sevito dirghakala-nairantaryabhyaso dridhabhumih.")
# Sanskrit compound words are long; English hyphenated phrases (well-known) have short parts.
_ROMANIZED_SANSKRIT_RE = re.compile(
    r'"[^"\n]*\b\w{5,}-\w{5,}\b[^"\n]*\b\w{4,}-\w{4,}\b[^"\n]*"'
)
_SANSKRIT_PLACEHOLDER = "[SANSKRIT]"
_SANSKRIT_PLACEHOLDER_RE = re.compile(r'\[SANSKRIT\]')
_SANSKRIT_BREAK = (
    "In the words of the ancient seers."
    '<break time="3.0s"/>'
    '<prosody rate="x-fast" volume="x-soft">m</prosody>'
)


def _mask_sanskrit(script: str) -> str:
    """Replace Sanskrit (Devanagari and romanized sutras) with [SANSKRIT] placeholder."""
    script = _SANSKRIT_LINE_RE.sub(_SANSKRIT_PLACEHOLDER, script)
    script = _ROMANIZED_SANSKRIT_RE.sub(_SANSKRIT_PLACEHOLDER, script)
    return script


def _normalize_ssml(ssml: str) -> str:
    """Clean up LLM output before sending to Speechify.

    Only fixes known format issues — no structural manipulation.
    """
    ssml = ssml.replace("\n", "")                                                          # single line for API
    ssml = _SPEECHIFY_OPEN_CAP.sub("<speechify:style", ssml)                              # fix capitalisation
    ssml = _SPEECHIFY_CLOSE_CAP.sub("</speechify:style>", ssml)                          # fix capitalisation
    ssml = _SPEECHIFY_SELFCLOSE.sub("", ssml)                                             # drop invalid self-closing
    ssml = _WARMUP_AT_BLOCK_START.sub(r'\1', ssml)                                        # strip spurious warm-ups at block start
    ssml = _TRAILING_BREAKS_BEFORE_SPEAK_CLOSE.sub("</speak>", ssml)                     # strip trailing dead air before </speak>
    ssml = _SANSKRIT_PLACEHOLDER_RE.sub(_SANSKRIT_BREAK, ssml)                           # restore Sanskrit as silence
    ssml = _SANSKRIT_LINE_RE.sub(_SANSKRIT_BREAK, ssml)                                   # safety net: Devanagari that leaked through
    ssml = _PAUSE_BREAK_RE.sub(r'\1' + _WARMUP, ssml)                                    # warm-up after every real pause
    return ssml


def strip_ssml(text: str) -> str:
    """Strip all SSML tags and unescape XML entities, returning clean text."""
    stripped = _TAG_RE.sub("", text)
    stripped = stripped.replace("&amp;", "&")
    stripped = stripped.replace("&lt;", "<")
    stripped = stripped.replace("&gt;", ">")
    stripped = stripped.replace("&quot;", '"')
    stripped = stripped.replace("&apos;", "'")
    stripped = _WHITESPACE_RE.sub(" ", stripped)
    stripped = _NEWLINE_RE.sub("\n", stripped)
    return stripped.strip()


class SsmlEnhancer:
    """Wraps an LLM provider and applies the SSML enhancement prompt."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def enhance(self, script: str, narrative_phase: str = "") -> str:
        """Return Speechify-compatible SSML for *script*.

        Args:
            script: Raw narration text for this scene.
            narrative_phase: NarrativePhase value (e.g. "TENSION"). When
                provided, the emotion target for this phase is injected into
                the system prompt as a constraint so the LLM starts with the
                phase-appropriate emotion and transitions only at boundaries.

        Falls back to the raw script on any LLM error so the pipeline is
        not blocked — the caller logs the warning.
        """
        phase_block = ""
        if narrative_phase:
            phase = emotion_policy.parse_phase(narrative_phase)
            if phase != NarrativePhase.UNKNOWN:
                phase_block = "\n\n" + emotion_policy.build_prompt_block(phase)

        system_prompt = _SYSTEM_PROMPT + phase_block
        script = _mask_sanskrit(script)

        try:
            response = self._llm.generate(
                script,
                system_prompt=system_prompt,
                temperature=0.3,
            )
            ssml = response.text.strip()
        except Exception as exc:
            logger.error("SsmlEnhancer: LLM call failed — {}. Passing raw script to TTS.", exc)
            raise

        if not ssml.lstrip().lower().startswith("<speak"):
            logger.warning(
                "SsmlEnhancer: output missing <speak> wrapper — "
                "discarding and passing raw script to TTS."
            )
            return script
        ssml = ssml.lstrip()
        ssml = _normalize_ssml(ssml)

        logger.info(
            "SsmlEnhancer: enhanced {} chars → {} chars SSML",
            len(script),
            len(ssml),
        )
        return ssml
