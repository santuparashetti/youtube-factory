"""Composer prompt — loads ATMA_THEORY_COMPOSER.md as the system prompt for
the whole-cloth composition stage (see ComposerPipeline).

Replaces the retired transform-based enhancer (Pass 1/2/3: mode selection,
coverage floor, no-reorder ban) and the Structural Retention Pass — both
kept archived, not deleted, until the composer is proven (see
src/ytfactory/structural_retention/, src/ytfactory/script_enhancer/pipeline.py).

The composer writes one continuous piece in a single LLM call; there is no
mode/coverage-floor/reorder-ban concept here — that belonged to the transform
model this stage replaces.
"""

import functools
from pathlib import Path

from ytfactory.beats_extractor.pipeline import format_beats_list

_SURGICAL_TRIM_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "prompts"
    / "SURGICAL_TRIM_PROMPT.md"
)


@functools.lru_cache(maxsize=1)
def _load_surgical_trim_prompt() -> str:
    return _SURGICAL_TRIM_PROMPT_PATH.read_text(encoding="utf-8").strip()

_COMPOSER_FRAMEWORK_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "script_enhancer"
    / "prompts"
    / "ATMA_THEORY_COMPOSER.md"
)


@functools.lru_cache(maxsize=1)
def _load_composer_framework() -> str:
    return _COMPOSER_FRAMEWORK_PATH.read_text(encoding="utf-8").strip()


_SCRIPTURE_PROTECTION = """\
───────────────────────────────────────────────────────────────
SCRIPTURE PROTECTION (absolute hard constraint — overrides everything above)
───────────────────────────────────────────────────────────────
These spans must appear byte-for-byte in your output, wherever you place
them. Compose around a span however serves the piece, but never alter the
span itself.
{scripture_list}"""

_RECOMPOSE_DIRECTIVE_TEMPLATE = """\
───────────────────────────────────────────────────────────────
LENGTH CORRECTION — this is a fresh compose, not an edit of your last draft
───────────────────────────────────────────────────────────────
Your previous composition ran {direction} — about {current_minutes:.1f} minutes
against the {lo}-{hi} minute target. Compose again, whole, from the base script,
{instruction}. Do not surgically trim or pad the previous draft — write a new
draft that lands in range because of what you choose to include and how you
pace it, the same way you composed the first time.
"""


def _format_scripture_list(placeholders: dict[str, str]) -> str:
    if not placeholders:
        return "(No scripture spans detected in this script.)"
    lines = []
    for key, original in placeholders.items():
        preview = original[:120] + ("…" if len(original) > 120 else "")
        lines.append(f'  {{{{{key}}}}} → "{preview}"')
    return "\n".join(lines)


def build_composer_system_prompt(placeholders: dict[str, str] | None = None) -> str:
    framework = _load_composer_framework()
    scripture = _SCRIPTURE_PROTECTION.format(
        scripture_list=_format_scripture_list(placeholders or {})
    )
    return f"{framework}\n\n{scripture}"


def build_composer_user_prompt(base_script: str, recompose_directive: str = "") -> str:
    directive = f"{recompose_directive}\n" if recompose_directive else ""
    return f"{directive}BASE SCRIPT:\n{base_script}"


def build_recompose_directive(current_minutes: float, target_range: tuple[int, int] = (6, 8)) -> str:
    lo, hi = target_range
    if current_minutes < lo:
        direction = "short"
        instruction = (
            "including more of the source's supporting material and letting "
            "the pacing breathe more"
        )
    else:
        direction = "long"
        instruction = "choosing fewer stories and cutting harder for the strongest material only"
    return _RECOMPOSE_DIRECTIVE_TEMPLATE.format(
        direction=direction, current_minutes=current_minutes, lo=lo, hi=hi, instruction=instruction
    )


# ── Script A / B variant prompts ──────────────────────────────────────────────
# Each variant owns distinct narrative strengths so the polisher can pick the
# best sections from both rather than just choosing between temperature variants.
# Protected beats are injected dynamically from the beats_extractor — no
# story-specific content is hardcoded here.

_SCRIPT_A_TEMPLATE = """\
You are writing Script A for Atma Theory YouTube channel.

CONTEXT:
This script will be judged against Script B. The best sections \
from both will be recomposed into a final hybrid. Write your \
strengths so distinctly that they are irreplaceable in the merge. \
Do not try to cover everything — own your sections deeply.

UNIVERSALIZATION RULE — NON-NEGOTIABLE:
Do not introduce Sanskrit, Pali, Arabic, Hebrew, or any non-English \
spiritual terminology that is not already present in the source \
material provided to you.
If the source expresses a teaching in plain English, keep it in \
plain English. Do not reach into the source tradition for \
terminology the source has already translated.
Correct: "Bodies are temporary. Wealth is not permanent."
Forbidden: Any Sanskrit transliteration or untranslated term.

SPECIFICALLY FORBIDDEN — do not write this phrase \
in any form, any spelling, any capitalization:
"anityani sharirani" / "vibhavo naiva Shashvatah"
The meaning of this teaching is: \
"Bodies are temporary. Wealth is not permanent."
Write it exactly that way — plain English only.
Do not quote, transliterate, or reference the \
original-language source under any circumstances.

THE IRON RULE:
Every word cut must be repetition or filler.
No story beat, example, or philosophical insight \
may be lost in the name of word count.
If it carries unique meaning — it stays.
Metaphor mappings from the beat list must appear \
explicitly in the script, not just implied.

HARD RULES:
- {target_words} words (hard cap). Count before returning.
- Self-check before outputting:
  Count your words. \
  If over {target_words}: condense sentences, remove filler, never remove beats. \
  If under {target_words} by more than 100: expand key moments — you may be too sparse.
- After writing, verify: is every protected beat present?
- If a beat is missing, restore it before trimming elsewhere.
- End with: "This is Atma Theory. If this reflection resonated \
  with you, stay with us on the journey. Clear mind. Meaningful life."
- Output [WORD COUNT: XXX] at the end.

SCRIPT A STRENGTHS — own these deeply:
- Prioritize philosophical clarity and memorable, balanced statements
- The central teaching should be stated with simplicity and force
- The emotional resolution should be spacious
- Opening: establish the setting and its central tension in one sentence
- Philosophical reframe: state the non-denial principle explicitly
- Circular closing: mirror the opening, resolve the central tension

PROTECTED BEATS — all must appear in your script:
{beats_list}

TOPIC: {topic}
SOURCE STORY: {source_story}"""

_SCRIPT_B_TEMPLATE = """\
You are writing Script B for Atma Theory YouTube channel.

CONTEXT:
This script will be judged against Script A. The best sections \
from both will be recomposed into a final hybrid. Write your \
strengths so distinctly that they are irreplaceable in the merge. \
Do not try to cover everything — own your sections deeply.

UNIVERSALIZATION RULE — NON-NEGOTIABLE:
Do not introduce Sanskrit, Pali, Arabic, Hebrew, or any non-English \
spiritual terminology that is not already present in the source \
material provided to you.
If the source expresses a teaching in plain English, keep it in \
plain English. Do not reach into the source tradition for \
terminology the source has already translated.
Correct: "Bodies are temporary. Wealth is not permanent."
Forbidden: Any Sanskrit transliteration or untranslated term.

SPECIFICALLY FORBIDDEN — do not write this phrase \
in any form, any spelling, any capitalization:
"anityani sharirani" / "vibhavo naiva Shashvatah"
The meaning of this teaching is: \
"Bodies are temporary. Wealth is not permanent."
Write it exactly that way — plain English only.
Do not quote, transliterate, or reference the \
original-language source under any circumstances.

THE IRON RULE:
Every word cut must be repetition or filler.
No story beat, example, or philosophical insight \
may be lost in the name of word count.
If it carries unique meaning — it stays.
Metaphor mappings from the beat list must appear \
explicitly in the script, not just implied.

HARD RULES:
- {target_words} words (hard cap). Count before returning.
- Self-check before outputting:
  Count your words. \
  If over {target_words}: condense sentences, remove filler, never remove beats. \
  If under {target_words} by more than 100: expand key moments — you may be too sparse.
- After writing, verify: is every protected beat present?
- If a beat is missing, restore it before trimming elsewhere.
- End with: "This is Atma Theory. If this reflection resonated \
  with you, stay with us on the journey. Clear mind. Meaningful life."
- Output [WORD COUNT: XXX] at the end.

SCRIPT B STRENGTHS — own these deeply:
- Prioritize psychological precision and narrative tension
- Show how the mechanism of distraction works step by step
- The application to ordinary life should be concrete and recognizable
- Tension: connect the story's trap directly to the psychological hunger behind it
- Modern examples: specific and recognizable — real moments people live through
- Forward momentum: end with the character moving, not just realizing

PROTECTED BEATS — all must appear in your script:
{beats_list}

TOPIC: {topic}
SOURCE STORY: {source_story}"""


def build_script_a_prompt(
    topic: str,
    source_story: str,
    beats: list[dict] | None = None,
    target_words: int = 773,
) -> str:
    beats_text = format_beats_list(beats) if beats else "(No beats extracted for this script.)"
    return _SCRIPT_A_TEMPLATE.format(
        topic=topic, source_story=source_story, beats_list=beats_text, target_words=target_words
    )


def build_script_b_prompt(
    topic: str,
    source_story: str,
    beats: list[dict] | None = None,
    target_words: int = 773,
) -> str:
    beats_text = format_beats_list(beats) if beats else "(No beats extracted for this script.)"
    return _SCRIPT_B_TEMPLATE.format(
        topic=topic, source_story=source_story, beats_list=beats_text, target_words=target_words
    )


def build_trim_system_prompt(
    current_words: int,
    target_min: int = 780,
    target_max: int = 1040,
) -> str:
    min_to_cut = max(0, current_words - target_max)
    max_to_cut = max(0, current_words - target_min)
    return _load_surgical_trim_prompt().format(
        current_words=current_words,
        target_min=target_min,
        target_max=target_max,
        min_to_cut=min_to_cut,
        max_to_cut=max_to_cut,
    )
