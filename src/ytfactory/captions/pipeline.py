from __future__ import annotations

import json
from pathlib import Path

from .artifacts import subtitles_directory
from .models import CaptionArtifact
from .repository import CaptionRepository

_WORDS_PER_LINE = 5


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _boundaries_to_srt(boundaries: list[dict]) -> str:
    """Group word-level boundaries into subtitle lines, one cue per line."""
    cues: list[str] = []
    cue_index = 1

    for i in range(0, len(boundaries), _WORDS_PER_LINE):
        chunk = boundaries[i : i + _WORDS_PER_LINE]
        start = chunk[0]["start"]
        end = chunk[-1]["end"]
        text = " ".join(w["word"] for w in chunk)
        cues.append(f"{cue_index}\n{_ts(start)} --> {_ts(end)}\n{text}\n")
        cue_index += 1

    return "\n".join(cues)


def _fallback_srt(narration: str, duration: float) -> str:
    """Single-cue fallback when no timing data is available."""
    sentences = [s.strip() for s in narration.replace("\n", " ").split(".") if s.strip()]
    if not sentences:
        return f"1\n{_ts(0)} --> {_ts(duration)}\n{narration}\n"

    cues: list[str] = []
    per = duration / len(sentences)
    for idx, sent in enumerate(sentences):
        start = idx * per
        end = (idx + 1) * per
        cues.append(f"{idx + 1}\n{_ts(start)} --> {_ts(end)}\n{sent}.\n")
    return "\n".join(cues)


class CaptionPipeline:

    def __init__(self):
        self.repository = CaptionRepository()

    def run(
        self,
        project: str,
    ) -> None:

        project_dir = Path("workspace") / "jobs" / project

        scene_file = project_dir / "scenes" / "scene-plan.json"

        scenes = json.loads(
            scene_file.read_text(encoding="utf-8")
        )["scenes"]

        for scene in scenes:

            index = scene["index"]
            output = subtitles_directory(project) / f"scene-{index:03d}.srt"

            timing_file = project_dir / "audio" / f"scene-{index:03d}.timing.json"

            if timing_file.exists():
                boundaries = json.loads(timing_file.read_text(encoding="utf-8"))
                srt = _boundaries_to_srt(boundaries) if boundaries else _fallback_srt(
                    scene["narration"], float(scene["duration_seconds"])
                )
            else:
                srt = _fallback_srt(scene["narration"], float(scene["duration_seconds"]))

            output.write_text(srt, encoding="utf-8")

            self.repository.save(
                CaptionArtifact(
                    scene_id=index,
                    srt_path=output,
                )
            )