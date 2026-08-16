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
Your ONLY job is to wrap the given narration text in Speechify-compatible SSML.

ABSOLUTE RULE — every word in your output must come from the input, in the same order.
Do NOT add sentences, phrases, or words. Do NOT paraphrase or expand.
If the input has one sentence, your SSML has exactly one sentence.
The text is fixed. Your job is markup only.

━━━ SSML STRUCTURE (follow exactly) ━━━

Use this pattern — breaks go INSIDE style blocks:

<speak>
  <speechify:style emotion="calm">
    First sentence.<break time="1.2s"/>Second sentence.<break time="1.5s"/>Third sentence.
  </speechify:style>
</speak>

When the emotion genuinely changes, close the block and open a new one:

<speak>
  <speechify:style emotion="calm">Opening sentences.<break time="1.0s"/>More calm text.</speechify:style>
  <speechify:style emotion="warm">Shift to warmth here.<break time="1.2s"/>Continue warmth.</speechify:style>
</speak>

━━━ RULES ━━━

speechify:style:
- ALWAYS use opening + closing tags: <speechify:style emotion="X">text</speechify:style>
- NEVER self-closing: <speechify:style emotion="X"/> is invalid
- Do NOT nest style blocks inside each other
- Available emotions: angry, cheerful, sad, terrified, relaxed, fearful, \
surprised, calm, assertive, energetic, warm, direct, bright
- Default to calm; only switch when the text clearly calls for it
- Do not repeat the same emotion more than 2–3 sentences in a row

<break time="Xs"/>:
- Place breaks INSIDE style blocks, between sentences
- After profound statements: 1.5–2.5s
- Between regular sentences: 0.8–1.2s
- Between paragraphs or sections: 2.5–4.0s
- Do NOT place a break at the very end before </speak> — it adds dead silence

<prosody pitch="..." volume="...">:
- Use for quiet intimacy or emphasis; do NOT set rate (leave at default)

<emphasis level="strong|moderate">:
- At most 1–2 key words per paragraph

Escape & → &amp;  < → &lt;  > → &gt; in spoken text only, never in tags.
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
# Trailing breaks before </speak> add dead air at the end of the clip.
_TRAILING_BREAKS_BEFORE_SPEAK_CLOSE = re.compile(
    r'(\s*<break[^/]*/>\s*)+</speak>',
    re.IGNORECASE,
)


def _normalize_ssml(ssml: str) -> str:
    """Clean up LLM output before sending to Speechify.

    Only fixes known format issues — no structural manipulation.
    """
    ssml = ssml.replace("\n", "")                                       # single line for API
    ssml = _SPEECHIFY_OPEN_CAP.sub("<speechify:style", ssml)           # fix capitalisation
    ssml = _SPEECHIFY_CLOSE_CAP.sub("</speechify:style>", ssml)        # fix capitalisation
    ssml = _SPEECHIFY_SELFCLOSE.sub("", ssml)                          # drop invalid self-closing
    ssml = _TRAILING_BREAKS_BEFORE_SPEAK_CLOSE.sub("</speak>", ssml)   # strip trailing dead air
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
        ssml = ssml.lstrip()
        ssml = _normalize_ssml(ssml)

        logger.info(
            "SsmlEnhancer: enhanced {} chars → {} chars SSML",
            len(script),
            len(ssml),
        )
        return ssml
