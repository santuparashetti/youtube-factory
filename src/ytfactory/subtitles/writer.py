"""
SubtitleWriter — format-agnostic subtitle serialization.

Currently implements SRT. Designed for extension:
  - Add WebVTTWriter for WebVTT format
  - Add ASSWriter for Advanced SubStation Alpha
  - All writers implement the SubtitleWriter protocol

SRT format reference:
  1
  00:00:01,000 --> 00:00:04,000
  Line one of subtitle
  Line two of subtitle

  2
  ...
"""

from __future__ import annotations

from .models import SubtitleCue, SubtitleFormat


def _fmt_srt_time(seconds: float) -> str:
    """
    Format a timestamp in SRT format: HH:MM:SS,mmm.

    Handles scenes longer than 59 seconds correctly.
    Clamps milliseconds to [0, 999] to avoid rounding to 1000.
    """
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    if ms >= 1000:
        ms = 999
        s = min(s + 1, 59)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class SRTWriter:
    """Serialize SubtitleCue objects to SRT format."""

    def write(self, cues: list[SubtitleCue]) -> str:
        """
        Produce a valid SRT string from a list of subtitle cues.

        Each cue becomes one SRT block:
            <index>
            <start> --> <end>
            <line1>
            [<line2>]

        Blocks are separated by blank lines. Returns empty string if no cues.
        """
        if not cues:
            return ""

        blocks: list[str] = []
        for cue in cues:
            start = _fmt_srt_time(cue.start)
            end = _fmt_srt_time(cue.end)
            text = "\n".join(line for line in cue.lines if line.strip())
            if not text:
                continue
            blocks.append(f"{cue.index}\n{start} --> {end}\n{text}\n")

        return "\n".join(blocks)


def get_writer(fmt: SubtitleFormat | str = SubtitleFormat.SRT) -> SRTWriter:
    """
    Factory: return the appropriate writer for the given format.

    Raises ValueError for unsupported formats — do not silently fall back.
    """
    fmt = SubtitleFormat(fmt) if isinstance(fmt, str) else fmt
    if fmt == SubtitleFormat.SRT:
        return SRTWriter()
    raise ValueError(
        f"Unsupported subtitle format: {fmt!r}. "
        f"Valid formats: {[f.value for f in SubtitleFormat]}"
    )
