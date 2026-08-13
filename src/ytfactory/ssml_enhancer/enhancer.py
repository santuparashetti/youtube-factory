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
Transform the narration script into Speechify-compatible SSML.

The default mood is calm and contemplative. Only deviate toward other \
emotions when the script text strongly calls for it. When in doubt, \
choose calm over energetic, warm over cheerful, assertive over angry.

Actively vary emotions throughout the script — avoid repeating the same \
emotion more than 2-3 sentences in a row unless the mood genuinely sustains.

Inject the following intelligently based on story mood and feeling:

- <break time="Xs" /> pauses:
    after profound statements: 1.5–2.5s
    between regular sentences: 0.8–1.2s
    between paragraphs/sections: 2.5–4.0s

- <speechify:style emotion="..."> switching as mood shifts.
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
- Preserve all original words exactly — only add tags, never remove or \
rewrite any word
- Return raw SSML only. No explanation, no markdown, no preamble.\
"""

# All SSML tags that strip_ssml must remove.
_TAG_RE = re.compile(
    r"<speak>"
    r"|</speak>"
    r"|<speechify:style(?:\s[^>]*)?\s*/>"     # self-closing (unlikely but safe)
    r"|<speechify:style(?:\s[^>]*)? *>"
    r"|</speechify:style>"
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

        logger.info(
            "SsmlEnhancer: enhanced {} chars → {} chars SSML",
            len(script),
            len(ssml),
        )
        return ssml
