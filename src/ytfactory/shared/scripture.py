"""Shared scripture/sacred-text extraction utilities.

Used by both LightNormalizationPipeline (to protect spans from LLM mutation)
and DocumentaryScriptEnhancerPipeline (same guarantee, applied again).

Detection strategy (in priority order):
  1. Explicit source-side markers: <scripture>...</scripture> or [scripture]...[/scripture]
  2. Unicode runs from Indic script ranges (Devanagari, Kannada, Tamil, Telugu, etc.)
"""

from __future__ import annotations

import re


# ── Indic Unicode ranges ───────────────────────────────────────────────────────

_SCRIPTURE_RANGES = (
    ("ऀ", "ॿ"),  # Devanagari  (Sanskrit, Hindi, Marathi)
    ("ಀ", "೿"),  # Kannada
    ("஀", "௿"),  # Tamil
    ("ఀ", "౿"),  # Telugu
    ("਀", "੿"),  # Gurmukhi   (Punjabi)
    ("ঀ", "৿"),  # Bengali
    ("ഀ", "ൿ"),  # Malayalam
    ("઀", "૿"),  # Gujarati
    ("ऀ", "ॿ"),  # Devanagari (also covers Nepali, Sanskrit)
)

_EXPLICIT_MARKER_RE = re.compile(
    r"<scripture>(.*?)</scripture>"
    r"|\[scripture\](.*?)\[/scripture\]",
    re.DOTALL | re.IGNORECASE,
)


def _build_indic_re() -> re.Pattern[str]:
    parts = [rf"[{lo}-{hi}]" for lo, hi in _SCRIPTURE_RANGES]
    combined = "|".join(parts)
    # Match a run of Indic chars plus surrounding ASCII punctuation / spaces
    return re.compile(
        rf"(?:{combined})[\w\s,;:।॥।॥‌‍'\"]*(?:{combined})[\w\s,;:।॥।॥‌‍'\"]*"
        rf"|(?:{combined})+"
    )


_INDIC_RE = _build_indic_re()


# ── Public API ─────────────────────────────────────────────────────────────────


def extract_scripture_spans(text: str) -> tuple[str, dict[str, str]]:
    """Replace scripture/sacred-text spans with {{SCRIPTURE_N}} placeholders.

    Returns:
        (placeholder_text, mapping of placeholder key → original span).

    Callers should pass ``placeholder_text`` to the LLM, then call
    ``restore_scripture_spans(llm_output, mapping)`` to reinstate the originals.
    """
    placeholders: dict[str, str] = {}
    counter = [0]  # mutable for closures

    def _replace(span: str) -> str:
        counter[0] += 1
        key = f"SCRIPTURE_{counter[0]}"
        placeholders[key] = span
        return f"{{{{{key}}}}}"

    # 1. Explicit markers (highest reliability — check first)
    result = _EXPLICIT_MARKER_RE.sub(lambda m: _replace(m.group(0)), text)

    # 2. Unicode Indic runs (already-replaced spans won't match since {{...}} contains no Indic chars)
    result = _INDIC_RE.sub(lambda m: _replace(m.group(0)), result)

    return result, placeholders


def restore_scripture_spans(text: str, placeholders: dict[str, str]) -> str:
    """Replace {{SCRIPTURE_N}} placeholders back with their original text."""
    for key, original in placeholders.items():
        text = text.replace(f"{{{{{key}}}}}", original)
    return text


def check_placeholders_preserved(
    original_placeholder_text: str,
    enhanced_placeholder_text: str,
) -> bool:
    """All {{SCRIPTURE_N}} placeholders from the input must appear in the output."""
    for key in re.findall(r"\{\{(SCRIPTURE_\d+)\}\}", original_placeholder_text):
        if f"{{{{{key}}}}}" not in enhanced_placeholder_text:
            return False
    return True


def check_scripture_verbatim(
    original_text: str,
    enhanced_text: str,
    placeholders: dict[str, str],
) -> list[str]:
    """Return a list of scripture originals that are missing from the enhanced text.

    Each value in ``placeholders`` must appear byte-for-byte in ``enhanced_text``.
    Returns an empty list if all spans are present (pass), or a list of missing
    spans for error reporting.
    """
    missing: list[str] = []
    for original_span in placeholders.values():
        if original_span not in enhanced_text:
            missing.append(original_span[:80] + ("…" if len(original_span) > 80 else ""))
    return missing
