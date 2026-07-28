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
against the 7-9 minute target. Compose again, whole, from the base script,
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


def build_recompose_directive(current_minutes: float, target_range: tuple[int, int] = (7, 9)) -> str:
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
        direction=direction, current_minutes=current_minutes, instruction=instruction
    )
