"""transcript.txt — natural-paragraph text derived from per-scene SRT files.

Strips only SRT formatting overhead (sequence numbers, timestamp lines) —
subtitle text and the blank lines that separate SRT blocks are kept as-is,
so blank lines read as paragraph breaks. Produces the flat text YouTube
expects when uploading a transcript manually for auto-translated captions.
"""

from __future__ import annotations

from pathlib import Path

from .artifacts import subtitles_directory


def _is_srt_overhead(line: str) -> bool:
    stripped = line.strip()
    return stripped.isdigit() or "-->" in stripped


def build_transcript(project_id: str) -> Path:
    """Concatenate every scene's .srt text into subtitles/transcript.txt.

    Scene order comes from the zero-padded scene-NNN.srt filenames, which
    sort correctly as plain strings.
    """
    directory = subtitles_directory(project_id)
    srt_files = sorted(directory.glob("scene-*.srt"))

    file_texts: list[str] = []
    for srt_file in srt_files:
        kept_lines = [
            raw_line
            for raw_line in srt_file.read_text(encoding="utf-8").splitlines()
            if not _is_srt_overhead(raw_line)
        ]
        # Trim blank lines at the file's edges so the "\n\n".join below is
        # the only separator at a scene boundary — never a double blank.
        while kept_lines and not kept_lines[0].strip():
            kept_lines.pop(0)
        while kept_lines and not kept_lines[-1].strip():
            kept_lines.pop()
        if kept_lines:
            file_texts.append("\n".join(kept_lines))

    transcript_path = directory / "transcript.txt"
    transcript_path.write_text("\n\n".join(file_texts), encoding="utf-8")
    return transcript_path
