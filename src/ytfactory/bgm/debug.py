"""BGMDebugWriter — writes BGM V2 diagnostic files to bgm-debug/."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .vad import SpeechTimeline


class BGMDebugWriter:
    """Writes diagnostic files to ``<project_dir>/bgm-debug/``.

    Files written:
        speech_timeline.json   — VAD-detected speech segments
        ducking_events.json    — state-machine events (duck / restore)
        mix_profile.json       — BGMConfig values used for this mix
        ffmpeg_filter.txt      — full filter_complex string sent to FFmpeg
        audio_levels.csv       — tabular speech/silence level annotations
    """

    def __init__(self, project_dir: Path) -> None:
        self._out = project_dir / "bgm-debug"

    def write(
        self,
        timeline: SpeechTimeline,
        mix_profile: dict,
        ffmpeg_filter: str,
    ) -> None:
        """Write all five debug files."""
        self._out.mkdir(parents=True, exist_ok=True)
        self._write_json("speech_timeline.json", timeline.to_dict())
        self._write_json("ducking_events.json", self._build_ducking_events(timeline))
        self._write_json("mix_profile.json", mix_profile)
        (self._out / "ffmpeg_filter.txt").write_text(ffmpeg_filter, encoding="utf-8")
        self._write_audio_levels(timeline)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_ducking_events(self, timeline: SpeechTimeline) -> dict:
        events: list[dict] = []
        for seg in timeline.segments:
            events.append(
                {"time": round(seg.start, 3), "state": "duck", "energy": round(seg.energy, 3)}
            )
            events.append({"time": round(seg.end, 3), "state": "restore"})
        return {"event_count": len(events), "events": events}

    def _write_audio_levels(self, timeline: SpeechTimeline) -> None:
        rows: list[list[str]] = [["time_s", "event", "bgm_state"]]
        for seg in timeline.segments:
            rows.append([f"{seg.start:.3f}", "speech_start", "ducked"])
            rows.append([f"{seg.end:.3f}", "speech_end", "restoring"])
        path = self._out / "audio_levels.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)

    def _write_json(self, name: str, data: dict) -> None:
        (self._out / name).write_text(json.dumps(data, indent=2), encoding="utf-8")
