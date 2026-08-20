"""Shared script text utilities."""

from __future__ import annotations

import re

_LEADING_H1_RE = re.compile(r"^#[ \t]+(.+)", re.MULTILINE)

# Bracketed production tags — never spoken
_TTS_DIRECTIVE_RE = re.compile(
    r"\[(?:Visual|Text Overlay|ENGAGEMENT|NARRATIVE_ENDING|End Screen)[^\]]*\]",
    re.IGNORECASE,
)

# Section/timestamp markers: "--- [0:45 - CHALLENGE]" or "[3:00 - REVEAL]" (with or without ---)
_SECTION_MARKER_RE = re.compile(
    r"(?:---\s*)?\[\d+:\d+[^\]]*\]",
    re.IGNORECASE,
)

# Splitting on speaker role labels: "Host:", "Visual:", "Audio:"
# Using a capturing group so split() retains the role name in the result list.
_ROLE_SPLIT_RE = re.compile(r"\b(Host|Visual|Audio)\s*:", re.IGNORECASE)


def strip_tts_directives(text: str) -> str:
    """Remove production directives from narration text before TTS synthesis.

    Handles:
    - Bracketed tags:        [Visual: ...], [ENGAGEMENT: ...], [NARRATIVE_ENDING]
    - Section markers:       --- [0:45 - CHALLENGE], [3:00 - REVEAL]
    - Speaker role labels:   Host:, Visual:, Audio: (bare, anywhere in text)

    When "Host:" or "Visual:" labels are present the text is split on role
    boundaries — only "Host:" segments are kept (spoken content); "Visual:"
    and "Audio:" segments are discarded (production direction).  Plain
    narration with no role labels is returned unchanged (after bracket/marker
    cleanup).
    """
    # 1. Strip bracketed directives
    cleaned = _TTS_DIRECTIVE_RE.sub("", text)

    # 2. Strip section/timestamp markers
    cleaned = _SECTION_MARKER_RE.sub("", cleaned)

    # 3. If role labels exist, split and keep only Host: segments
    if _ROLE_SPLIT_RE.search(cleaned):
        parts = _ROLE_SPLIT_RE.split(cleaned)
        # parts layout (capturing split): [pre, role1, text1, role2, text2, ...]
        spoken: list[str] = []
        pre = parts[0].strip()
        if pre:
            spoken.append(pre)
        for i in range(1, len(parts), 2):
            role = parts[i].strip().lower()
            segment = parts[i + 1].strip() if i + 1 < len(parts) else ""
            if role == "host" and segment:
                spoken.append(segment)
            # visual / audio segments are production direction — discard
        cleaned = " ".join(spoken)

    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def strip_script_heading(text: str) -> tuple[str, str]:
    """Remove the leading H1 heading from a script file.

    The heading (e.g. ``# WHEN SUFFERING KNOCKS...``) is a structural label for
    the script file, not spoken narration.  Strip it before passing to the scene
    planner, TTS, or any other stage that consumes narration text.

    Returns:
        (body_text, heading_text) — heading_text is the bare heading string
        without the leading ``#``, or ``""`` if no heading was found.
    """
    stripped = text.lstrip()
    m = _LEADING_H1_RE.match(stripped)
    if not m:
        return text, ""
    heading = m.group(1).strip()
    body = stripped[m.end():].lstrip("\n")
    return body, heading
