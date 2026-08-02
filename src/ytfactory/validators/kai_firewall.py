"""kai_firewall.py — Pipeline-internal name firewall.

"Kai" is an internal anchor character identifier. It must NEVER appear in any
viewer-facing output. This validator enforces that constraint at artifact boundaries.
"""

from __future__ import annotations

import re
from pathlib import Path


class KaiFirewallViolation(Exception):
    """Raised when the pipeline-internal name 'Kai' is detected in viewer-facing output."""


KAI_PATTERN = re.compile(r"\bkai\b", re.IGNORECASE)

VIEWER_FACING_ARTIFACTS = [
    "script.md",        # composer output
    "final_script.md",  # post-human-review
    "subtitles.srt",    # WhisperX output
    "subtitles.vtt",    # alternate subtitle format
    "captions.txt",     # any caption artifact
]


def check_artifact(text: str, artifact_name: str) -> None:
    """Scan text for the pipeline-internal name 'Kai'.

    Raises KaiFirewallViolation if found.

    Call at:
    - After composer output (before editorial_qa)
    - After TTS input assembly (before the TTS provider call)
    - After WhisperX subtitle generation
    """
    matches = KAI_PATTERN.findall(text)
    if matches:
        raise KaiFirewallViolation(
            f"Pipeline-internal name 'Kai' detected in viewer-facing artifact "
            f"'{artifact_name}'. Found {len(matches)} occurrence(s). "
            f"This name must never appear in script, TTS input, subtitles, or captions. "
            f"Check ATMA_THEORY_COMPOSER.md injection and scene_planner output."
        )


def check_file(path: Path) -> None:
    """Convenience wrapper for file-based artifacts."""
    if path.exists():
        check_artifact(path.read_text(encoding="utf-8"), path.name)
