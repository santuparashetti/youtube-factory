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
Your ONLY job is to wrap the given narration text in Speechify-compatible
SSML markup. You must NOT add, remove, reorder, or rewrite any words.

CRITICAL — NARRATION FIDELITY (absolute constraint):
- Every single word in your output must appear in the input, in the same order.
- Do NOT invent new sentences, phrases, or clauses.
- Do NOT paraphrase, expand, or summarise any part of the narration.
- If the input is one sentence, your SSML must contain exactly one sentence.
- Treat the input text as sacred — your job is decoration, not rewriting.

The default mood is calm and contemplative. Only deviate toward other \
emotions when the script text strongly calls for it. When in doubt, \
choose calm over energetic, warm over cheerful, assertive over angry.

Actively vary emotions throughout the script — avoid repeating the same \
emotion more than 2-3 sentences in a row unless the mood genuinely sustains.

Inject the following intelligently based on story mood and feeling:

- <break time="Xs" /> pauses (use seconds format, e.g. time="1.5s"):
    after profound statements: 1.5–2.5s
    between regular sentences: 0.8–1.2s
    between paragraphs/sections: 2.5–4.0s

- <speechify:style emotion="...">text</speechify:style> switching as mood shifts.
  CRITICAL STRUCTURE RULE — put <break> tags INSIDE style blocks, not between them:

  CORRECT:
    <speechify:style emotion="calm">Sentence one.<break time="1.0s" />Sentence two.<break time="1.5s" />Sentence three.</speechify:style>

  WRONG (causes audio clipping — never do this):
    <speechify:style emotion="calm">Sentence one.</speechify:style><break time="1.0s" /><speechify:style emotion="calm">Sentence two.</speechify:style>

  Group all consecutive sentences that share the same emotion into ONE style block
  with breaks inside. Only open a NEW style block when the emotion genuinely changes.
  When the emotion changes, place the break AFTER the closing tag:
    <speechify:style emotion="calm">Calm sentence one.<break time="1.0s" />Calm sentence two.</speechify:style><break time="0.8s" /><speechify:style emotion="warm">Warm sentence three.</speechify:style>

  IMPORTANT: speechify:style ALWAYS wraps its text with an opening AND a
  closing tag. NEVER write it self-closing (<speechify:style emotion="..." />) — this is invalid.
  ALWAYS include a matching </speechify:style> closing tag.
  Available emotions: angry, cheerful, sad, terrified, relaxed, fearful, \
surprised, calm, assertive, energetic, warm, direct, bright

- <prosody pitch="..." volume="...">
  Adjust pitch for transitions; adjust volume for quiet intimacy or emphasis.
  pitch: x-low/low/medium/high/x-high or %
  volume: x-soft/medium/loud/x-loud or dB/%
  DO NOT set rate — leave speech rate at the TTS provider default.
  Never include rate="slow", rate="x-slow", or any rate attribute.

- <emphasis level="strong|moderate"> on 1–2 key words per paragraph \
maximum. Do not over-emphasise.

SSML rules (strict):
- Wrap everything in <speak>...</speak>
- Do NOT nest <speechify:style> inside itself
- Escape & → &amp;  < → &lt;  > → &gt; in spoken text only, never in tags
- Max break time is 10s
- Do NOT place <break> or <speechify:style> tags at the very end before </speak> \
— they add dead silence after the last word
- Return raw SSML only. No explanation, no markdown, no preamble.\
"""

# All SSML tags that strip_ssml must remove.
_TAG_RE = re.compile(
    r"<speak>"
    r"|</speak>"
    r"|<speechify:style(?:\s[^>]*)?\s*/>"   # self-closing (legacy/malformed)
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
# Matches a closing break tag followed by optional whitespace then a letter —
# used to inject a warm-up comma so the TTS decoder has phonetic context
# before the next word starts (prevents first-word clipping after silences).
_BREAK_THEN_WORD = re.compile(r'(<break[^/]*/>\s*)([A-Za-z])')
# <break/> followed by a <speechify:style> open tag then a letter — the style
# tag blocks _BREAK_THEN_WORD from firing.  Inject comma AFTER the style open
# tag so the TTS decoder gets phonetic context before the first word.
_BREAK_THEN_STYLE_THEN_WORD = re.compile(
    r'(<break[^/]*/>\s*<speechify:style[^>]*>)([A-Za-z])',
    re.IGNORECASE,
)
# Fix capital-S namespace: <Speechify:style → <speechify:style (and closing tag).
_SPEECHIFY_OPEN_CAP = re.compile(r'<Speechify:style\b', re.IGNORECASE)
_SPEECHIFY_CLOSE_CAP = re.compile(r'</Speechify:style\s*>', re.IGNORECASE)
# LLMs sometimes emit self-closing <speechify:style .../> which is invalid per
# Speechify docs — the tag must wrap its text.  If the LLM emits
# <speechify:style emotion="calm"/> with no content, just drop it entirely.
_SPEECHIFY_SELFCLOSE = re.compile(r'<speechify:style\b[^>]*/>', re.IGNORECASE)
# Trailing break tags before </speak> add dead air at the end of the clip.
# The </speechify:style> before </speak> is fine (it closes the last style block).
_TRAILING_BREAKS_BEFORE_SPEAK_CLOSE = re.compile(
    r'(\s*<break[^/]*/>\s*)+</speak>',
    re.IGNORECASE,
)


def _normalize_ssml(ssml: str) -> str:
    """Normalise SSML before sending to Speechify.

    - Strip newlines (keeps the payload on one line)
    - Normalise <Speechify:style → <speechify:style (both open and close tags)
    - Drop self-closing <speechify:style .../> — per docs it must wrap its text
    - Strip trailing <break> tags before </speak> (add dead silence)
    - Inject a warm-up comma after each <break> tag so the TTS decoder has
      phonetic context before the next word (prevents first-word clipping).
    """
    ssml = ssml.replace("\n", "")
    ssml = _SPEECHIFY_OPEN_CAP.sub("<speechify:style", ssml)        # fix open-tag capitalisation
    ssml = _SPEECHIFY_CLOSE_CAP.sub("</speechify:style>", ssml)     # fix close-tag capitalisation
    ssml = _SPEECHIFY_SELFCLOSE.sub("", ssml)                       # drop invalid self-closing tags
    ssml = _TRAILING_BREAKS_BEFORE_SPEAK_CLOSE.sub("</speak>", ssml) # strip trailing dead air
    ssml = _BREAK_THEN_WORD.sub(r'\1, \2', ssml)                    # warm-up comma: break → word
    ssml = _BREAK_THEN_STYLE_THEN_WORD.sub(r'\1, \2', ssml)        # warm-up comma: break → style → word
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
        ssml = ssml.lstrip()  # normalise any leading whitespace the model emitted
        ssml = _normalize_ssml(ssml)

        logger.info(
            "SsmlEnhancer: enhanced {} chars → {} chars SSML",
            len(script),
            len(ssml),
        )
        return ssml
