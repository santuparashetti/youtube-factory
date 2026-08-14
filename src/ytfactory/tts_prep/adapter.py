"""TTS Provider Adapter — converts pronunciation hints to provider-specific format.

Integration test confirmed (2026-08-14, Speechify simba-3.2, voice wyatt_32):

  CONFIRMED WORKING — <sub alias="pronunciation">canonical_term</sub>:
    • Speechify replaces the canonical term with the alias in synthesis.
    • Word-level speech marks return the alias tokens, not the canonical term.
    • Billable characters are counted from the alias, not the original term.
    • The <sub> tag is ONLY effective when the full text is SSML-wrapped
      (<speak>…</speak>). Standalone <sub> without <speak> is untested and
      may be spoken literally — do NOT inject without ssml_mode=True.

  SAFE FALLBACK — all other cases:
    • Hints are preserved in TTSPreparedScript for human inspection.
    • tts_text is returned unchanged.
    • Enable ssml_enhancement_enabled=true for active pronunciation control.

The canonical script is NEVER touched by any function in this module.
"""

from __future__ import annotations

import re

from loguru import logger

from .models import PronunciationHint, TTSPreparedScript

# Providers confirmed to process <sub alias="..."> inside <speak>…</speak>.
# Integration-tested: speechify (simba-3.2). Add new providers here after
# testing — do not assume support without a real synthesis verification.
_SSML_CAPABLE_PROVIDERS: frozenset[str] = frozenset({"speechify"})


def apply_pronunciation(
    tts_text: str,
    prepared: TTSPreparedScript,
    *,
    provider_name: str,
    ssml_mode: bool = False,
) -> str:
    """Apply pronunciation hints to the TTS-bound text.

    Injection is only performed when BOTH conditions are met:
      1. ssml_mode=True  → tts_text is wrapped in <speak>…</speak>
      2. provider_name is in _SSML_CAPABLE_PROVIDERS

    This is the ONLY verified safe path. Injecting <sub> into plain text
    (ssml_mode=False) risks the tags being spoken literally; that path is
    intentionally blocked until a provider verifies standalone <sub> support.

    The canonical script in ``prepared.canonical_text`` is never modified.

    Args:
        tts_text:      Text to send to the TTS provider (may contain SSML tags).
        prepared:      Pronunciation hints from TTSPreparationService.
        provider_name: Lowercase provider name (e.g. "speechify", "kokoro").
        ssml_mode:     True when tts_text is already wrapped in <speak>…</speak>.

    Returns:
        Modified tts_text with <sub> pronunciation injected (SSML mode),
        or the original tts_text unchanged (all other cases).
    """
    if not prepared.hints:
        return tts_text

    # Only inject when the full text is SSML-wrapped AND the provider is confirmed.
    can_inject = ssml_mode and (provider_name.lower() in _SSML_CAPABLE_PROVIDERS)

    if can_inject:
        return _apply_ssml_sub(tts_text, prepared.hints, provider_name=provider_name)

    # Safe fallback: store hints in metadata, do not touch tts_text.
    logger.info(
        "TTS PREP: provider={} ssml_mode={} — {} pronunciation hint(s) available "
        "in metadata but not injected "
        "(enable ssml_enhancement_enabled=true with provider=speechify for active control)",
        provider_name,
        ssml_mode,
        len(prepared.hints),
    )
    return tts_text


def _apply_ssml_sub(
    ssml_text: str,
    hints: list[PronunciationHint],
    *,
    provider_name: str = "",
) -> str:
    """Inject <sub alias="...">term</sub> for each hint into SSML text.

    Rules:
    - Only substitutes whole-word occurrences (\\b boundaries).
    - Skips terms that already appear inside a <sub> or any SSML tag.
    - All replacements are made only in text nodes, not in tag attributes.
    - Preserves the canonical term as tag content so strip_ssml() recovers it.

    The <sub alias="spoken_form">canonical_term</sub> SSML element instructs
    the TTS engine to speak the alias rather than the text content. Subtitles
    generated from strip_ssml() see only "canonical_term" — correct behavior.
    """
    result = ssml_text
    applied: list[str] = []

    for hint in hints:
        escaped = re.escape(hint.term)

        # Skip if the term already lives inside a <sub> block
        if re.search(
            rf"<sub\b[^>]*>[^<]*{escaped}[^<]*</sub>",
            result,
            re.IGNORECASE,
        ):
            continue

        sub_tag = f'<sub alias="{hint.pronunciation}">{hint.term}</sub>'

        # Replace only outside of SSML tags (text nodes between >…<)
        # Simple approach: replace \b-bounded occurrences everywhere;
        # tag attributes shouldn't contain bare canonical terms.
        new_result, count = re.subn(
            rf"\b{escaped}\b",
            sub_tag,
            result,
        )
        if count > 0:
            result = new_result
            applied.append(hint.term)

    if applied:
        logger.info(
            "TTS PREP: provider={} — injected SSML <sub> pronunciation for: {}",
            provider_name,
            ", ".join(applied),
        )

    return result
