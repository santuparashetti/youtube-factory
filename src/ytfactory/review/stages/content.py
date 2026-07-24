"""Stage 3 — Content Review.

Checks:
  - Script file exists and is non-empty
  - All scenes have non-empty narration
  - All generated_image scenes have non-empty visual prompts
  - Narration word counts are within a reasonable range
  - Scene count is within configured bounds
  - Scene titles are non-empty
  - Basic subtitle ↔ narration overlap (sanity check)
"""

from __future__ import annotations

import re
from pathlib import Path

from ytfactory.review.models import SceneReview
from ytfactory.review.stages.base import BaseReviewStage


class ContentReviewStage(BaseReviewStage):
    name = "content"

    def _run_checks(
        self,
        project_dir: Path,
        scenes: list[dict],
        scene_reviews: list[SceneReview],
        context: dict,
    ) -> None:
        # Script presence
        script_path = project_dir / "script" / "script.md"
        script_ok = self._check(
            script_path.exists() and script_path.stat().st_size > 0,
            "script/script.md is missing or empty",
        )
        if script_ok:
            context["script_word_count"] = len(
                script_path.read_text(encoding="utf-8").split()
            )

        # Scene count bounds
        n = len(scenes)
        self._check(
            n >= self._config.min_scenes,
            f"Too few scenes: {n} (minimum {self._config.min_scenes})",
        )
        self._check(
            n <= self._config.max_scenes,
            f"Too many scenes: {n} (maximum {self._config.max_scenes})",
        )

        # Per-scene content checks
        for scene in scenes:
            idx = scene.get("index", 0)
            sr = next((r for r in scene_reviews if r.index == idx), None)

            narration = scene.get("narration", "").strip()
            wc = len(narration.split()) if narration else 0
            scene_type = scene.get("scene_type", "generated_image")

            if sr:
                sr.narration_word_count = wc

            # Asset scenes (brand images, outro cards) carry intentionally short
            # taglines — exempt them from the minimum word-count check.
            if scene_type not in ("asset", "brand_card"):
                self._check(
                    wc >= self._config.min_narration_words,
                    f"Scene {idx}: narration missing or too short ({wc} words)",
                )
                if sr and wc < self._config.min_narration_words:
                    sr.issues.append(f"Narration too short ({wc} words)")

            # Title
            title = scene.get("title", "").strip()
            self._check(bool(title), f"Scene {idx}: title is empty")

            # Visual prompt (generated scenes only)
            if sr:
                sr.has_visual_prompt = bool(scene.get("visual_prompt", "").strip())
                sr.has_shot_type = bool(scene.get("shot_type", ""))

            if scene_type == "generated_image":
                prompt = scene.get("visual_prompt", "").strip()
                self._check(
                    bool(prompt),
                    f"Scene {idx}: visual_prompt is missing",
                )
                if sr and not prompt:
                    sr.issues.append("Missing visual prompt")

            # Light subtitle ↔ narration check
            if sr and sr.has_subtitle and wc > 0:
                srt_path = project_dir / "subtitles" / f"scene-{idx:03d}.srt"
                if srt_path.exists():
                    subtitle_text = _extract_srt_text(srt_path)
                    overlap = _word_overlap(narration, subtitle_text)
                    if overlap < 0.3 and wc > 10:
                        self._warn(
                            f"Scene {idx}: subtitle text has low overlap with narration "
                            f"({overlap:.0%}) — possible sync issue"
                        )
                    else:
                        self._ok()


# ── Helpers ───────────────────────────────────────────────────────────────────

_SRT_BLOCK_RE = re.compile(
    r"\d+\s*\n\d{2}:\d{2}:\d{2},\d{3}\s*-->.*?\n(.*?)(?=\n\n|\Z)", re.S
)


def _extract_srt_text(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return " ".join(
            m.group(1).replace("\n", " ") for m in _SRT_BLOCK_RE.finditer(text)
        )
    except OSError:
        return ""


def _word_overlap(a: str, b: str) -> float:
    def _words(s: str) -> set[str]:
        return set(re.findall(r"\b[a-z]{3,}\b", s.lower()))

    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)
