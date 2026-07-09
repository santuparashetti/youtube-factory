"""BGMDebugWriter — writes BGM V2/V3 diagnostic files to bgm-debug/."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .vad import PauseClassifier, PauseEvent, PauseType, SpeechTimeline


class BGMDebugWriter:
    """Writes diagnostic files to ``<project_dir>/bgm-debug/``.

    V2 files (always written):
        speech_timeline.json   — VAD/Kokoro speech segments
        ducking_events.json    — duck / restore state events
        mix_profile.json       — BGMConfig values used for this mix
        ffmpeg_filter.txt      — full filter_complex string sent to FFmpeg
        audio_levels.csv       — tabular speech/silence level annotations

    V3 files (written when pause_events is provided):
        state_timeline.json    — full state machine trace (narration/BGM level/
                                 state changes/duck curves) for debug inspection
        bgm-mix-report.json    — quality summary: pumping score, transitions,
                                 pause classifications, adaptive params used
    """

    def __init__(self, project_dir: Path) -> None:
        self._out = project_dir / "bgm-debug"

    def write(
        self,
        timeline: SpeechTimeline,
        mix_profile: dict,
        ffmpeg_filter: str,
        *,
        long_silence_threshold_ms: int = 2500,
    ) -> None:
        """Write all debug files.

        When *mix_profile* contains ``adaptive_mixing=True``, also writes
        ``state_timeline.json`` and ``bgm-mix-report.json``.
        """
        self._out.mkdir(parents=True, exist_ok=True)

        classifier = PauseClassifier(long_silence_threshold_ms=long_silence_threshold_ms)
        pause_events = classifier.classify(timeline)

        self._write_json("speech_timeline.json", timeline.to_dict())
        self._write_json("ducking_events.json", self._build_ducking_events(timeline, pause_events))
        self._write_json("mix_profile.json", mix_profile)
        (self._out / "ffmpeg_filter.txt").write_text(ffmpeg_filter, encoding="utf-8")
        self._write_audio_levels(timeline, pause_events)

        # V3 extended output
        if mix_profile.get("adaptive_mixing", False):
            self._write_json(
                "state_timeline.json",
                self._build_state_timeline(timeline, pause_events, mix_profile),
            )
            self._write_json(
                "bgm-mix-report.json",
                self._build_mix_report(timeline, pause_events, mix_profile),
            )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_ducking_events(
        self,
        timeline: SpeechTimeline,
        pause_events: list[PauseEvent],
    ) -> dict:
        events: list[dict] = []
        for seg in timeline.segments:
            events.append(
                {"time": round(seg.start, 3), "state": "duck", "energy": round(seg.energy, 3)}
            )
            events.append({"time": round(seg.end, 3), "state": "restore"})
        # Annotate events with pause type where available
        pause_map = {round(p.start, 3): p.pause_type.value for p in pause_events}
        for ev in events:
            if ev["state"] == "restore":
                ev["pause_type"] = pause_map.get(ev["time"], "unknown")
        return {"event_count": len(events), "events": events}

    def _build_state_timeline(
        self,
        timeline: SpeechTimeline,
        pause_events: list[PauseEvent],
        mix_profile: dict,
    ) -> dict:
        """Build a full state machine trace.

        States:
            FULL          — music at full volume (intro/outro/long silence)
            NARRATION_ACTIVE — music ducked (speech or short pause hold)
            MUSIC_FEATURE — music recovering after long silence begins
        """
        bgm_vol = mix_profile.get("bgm_volume", 0.30)
        duck_floor = mix_profile.get("duck_floor", 0.04)
        hold_ms = mix_profile.get("hold_after_speech_ms", 2200)
        release_ms = mix_profile.get("duck_release_ms", 1800)

        entries: list[dict] = []

        def _append(t: float, state: str, bgm_level: float, note: str = "") -> None:
            entry: dict = {
                "time": round(t, 3),
                "state": state,
                "bgm_level_approx": round(bgm_level, 3),
            }
            if note:
                entry["note"] = note
            entries.append(entry)

        # Start in FULL state (intro)
        _append(0.0, "FULL", bgm_vol, "intro fade-in")

        segs = timeline.segments
        for i, seg in enumerate(segs):
            # Narration starts → duck
            _append(seg.start, "NARRATION_ACTIVE", duck_floor, "speech onset — duck")
            # Narration ends
            seg_end = seg.end

            if i < len(pause_events):
                pe = pause_events[i]
                if pe.pause_type == PauseType.LONG_SILENCE:
                    # Hold still ducked for hold_ms then begin recovery
                    hold_end = seg_end + hold_ms / 1000.0
                    _append(
                        hold_end,
                        "MUSIC_FEATURE",
                        duck_floor,
                        f"hold expired ({hold_ms} ms) — begin recovery",
                    )
                    recover_end = hold_end + release_ms / 1000.0
                    _append(
                        recover_end,
                        "FULL",
                        bgm_vol,
                        f"recovery complete ({release_ms} ms release)",
                    )
                else:
                    _append(
                        seg_end,
                        "NARRATION_ACTIVE",
                        duck_floor,
                        f"hold active — {pe.pause_type.value} ({pe.duration * 1000:.0f} ms)",
                    )
            else:
                # Last segment — outro
                _append(
                    seg_end + hold_ms / 1000.0,
                    "FULL",
                    bgm_vol,
                    "outro — hold expired",
                )

        total_dur = timeline.total_duration
        _append(total_dur, "FULL", 0.0, "outro fade-out complete")

        return {
            "total_duration": round(total_dur, 3),
            "entry_count": len(entries),
            "entries": entries,
        }

    def _build_mix_report(
        self,
        timeline: SpeechTimeline,
        pause_events: list[PauseEvent],
        mix_profile: dict,
    ) -> dict:
        """Build bgm-mix-report.json quality summary."""
        pause_counts: dict[str, int] = {}
        long_silences: list[dict] = []
        for pe in pause_events:
            pause_counts[pe.pause_type.value] = pause_counts.get(pe.pause_type.value, 0) + 1
            if pe.pause_type == PauseType.LONG_SILENCE:
                long_silences.append(pe.to_dict())

        speech_ratio = timeline.speech_ratio
        pumping_risk = "low" if mix_profile.get("adaptive_mixing", False) else "medium"

        return {
            "version": "v3",
            "adaptive_mixing": mix_profile.get("adaptive_mixing", False),
            "hold_after_speech_ms": mix_profile.get("hold_after_speech_ms", 2200),
            "duck_attack_ms": mix_profile.get("duck_attack_ms", 180),
            "duck_release_ms": mix_profile.get("duck_release_ms", 1800),
            "long_silence_threshold_ms": mix_profile.get("long_silence_threshold_ms", 2500),
            "speech_ratio": round(speech_ratio, 3),
            "segment_count": len(timeline.segments),
            "pause_classifications": pause_counts,
            "long_silence_windows": long_silences,
            "long_silence_count": len(long_silences),
            "pumping_risk": pumping_risk,
            "quality_notes": self._quality_notes(pause_events, speech_ratio),
        }

    def _quality_notes(self, pause_events: list[PauseEvent], speech_ratio: float) -> list[str]:
        notes: list[str] = []
        breath_count = sum(1 for p in pause_events if p.pause_type == PauseType.BREATH)
        comma_count = sum(1 for p in pause_events if p.pause_type == PauseType.COMMA)
        if breath_count > 0:
            notes.append(
                f"{breath_count} breath pause(s) detected — music held ducked (no pumping)"
            )
        if comma_count > 0:
            notes.append(
                f"{comma_count} comma pause(s) detected — music held ducked (no pumping)"
            )
        if speech_ratio > 0.85:
            notes.append(
                "High narration density — BGM will remain ducked for most of the video"
            )
        if speech_ratio < 0.30:
            notes.append(
                "Low narration density — BGM will feature prominently in silences"
            )
        return notes

    def _write_audio_levels(
        self, timeline: SpeechTimeline, pause_events: list[PauseEvent]
    ) -> None:
        rows: list[list[str]] = [["time_s", "event", "bgm_state", "pause_type"]]
        for i, seg in enumerate(timeline.segments):
            rows.append([f"{seg.start:.3f}", "speech_start", "ducked", ""])
            pause_type = pause_events[i].pause_type.value if i < len(pause_events) else ""
            rows.append([f"{seg.end:.3f}", "speech_end", "restoring", pause_type])
        path = self._out / "audio_levels.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)

    def _write_json(self, name: str, data: dict) -> None:
        (self._out / name).write_text(json.dumps(data, indent=2), encoding="utf-8")
