"""Shared script text utilities."""

from __future__ import annotations

import re

_LEADING_H1_RE = re.compile(r"^#[ \t]+(.+)", re.MULTILINE)


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
