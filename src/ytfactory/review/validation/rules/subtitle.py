"""Subtitle validation rules (category C).

Rules:
  SUBT_001 [critical] — SRT file exists for every scene
  SUBT_002 [high]     — No timestamp overlaps within a scene
  SUBT_003 [high]     — Reading speed within configured CPS limit
  SUBT_004 [medium]   — Characters per subtitle line within limit
  SUBT_005 [medium]   — No empty subtitle cues
  SUBT_006 [medium]   — Subtitle text overlaps with narration (Jaccard)
"""

from __future__ import annotations

import re
from pathlib import Path

from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult

_SRT_TS_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)


def _parse_srt_blocks(text: str) -> list[tuple[float, float, str]]:
    """Return list of (start_sec, end_sec, cue_text) from SRT content."""
    blocks: list[tuple[float, float, str]] = []
    for chunk in re.split(r"\n\s*\n", text.strip()):
        lines = chunk.strip().splitlines()
        ts_match = None
        for line in lines:
            m = _SRT_TS_RE.match(line.strip())
            if m:
                ts_match = m
                break
        if not ts_match:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(x) for x in ts_match.groups())
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        text_lines = [
            ln.strip()
            for ln in lines
            if ln.strip()
            and not _SRT_TS_RE.match(ln.strip())
            and not re.match(r"^\d+$", ln.strip())
        ]
        blocks.append((start, end, " ".join(text_lines)))
    return blocks


def _jaccard(a: str, b: str) -> float:
    sa = set(a.lower().split())
    sb = set(b.lower().split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


class SubtitleValidator(BaseValidator):
    category = "subtitle"
    responsible_engine = "CaptionGenerator"

    def validate(
        self,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> list[ValidationResult]:
        results: list[ValidationResult] = []

        if not scenes:
            for rule_id in ("SUBT_001", "SUBT_002", "SUBT_003", "SUBT_004", "SUBT_005", "SUBT_006"):
                if self._config.is_enabled(rule_id):
                    results.append(self._skip(rule_id, "no scenes available"))
            return results

        for scene in scenes:
            idx = scene.get("index", 0)
            srt_path = project_dir / "subtitles" / f"scene-{idx:03d}.srt"
            narration = scene.get("narration", "")

            # SUBT_001: SRT file exists
            if self._config.is_enabled("SUBT_001"):
                if not srt_path.exists():
                    results.append(
                        self._fail(
                            "SUBT_001",
                            f"Scene {idx}: subtitle file missing",
                            f"Expected: {srt_path.name}",
                            "critical",
                            scene_index=idx,
                        )
                    )
                    for rule_id in ("SUBT_002", "SUBT_003", "SUBT_004", "SUBT_005", "SUBT_006"):
                        if self._config.is_enabled(rule_id):
                            results.append(
                                self._skip(rule_id, "subtitle file unavailable", scene_index=idx)
                            )
                    continue
                results.append(
                    self._pass("SUBT_001", f"Scene {idx} subtitle exists", srt_path.name, scene_index=idx)
                )

            if not srt_path.exists():
                continue

            try:
                srt_text = srt_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                for rule_id in ("SUBT_002", "SUBT_003", "SUBT_004", "SUBT_005", "SUBT_006"):
                    if self._config.is_enabled(rule_id):
                        results.append(
                            self._skip(rule_id, "cannot read subtitle file", scene_index=idx)
                        )
                continue

            blocks = _parse_srt_blocks(srt_text)

            # SUBT_002: No timestamp overlaps
            if self._config.is_enabled("SUBT_002"):
                if not blocks:
                    results.append(
                        self._warn(
                            "SUBT_002",
                            f"Scene {idx}: no parseable SRT timestamp blocks found",
                            "empty or malformed SRT",
                            "high",
                            scene_index=idx,
                        )
                    )
                else:
                    overlaps: list[str] = []
                    prev_end = 0.0
                    for i, (start, end, _) in enumerate(blocks):
                        if end <= start:
                            overlaps.append(f"block {i+1}: end≤start ({start:.2f}→{end:.2f}s)")
                        if start < prev_end - 0.001:
                            overlaps.append(
                                f"block {i+1}: overlaps previous ({start:.2f}<{prev_end:.2f}s)"
                            )
                        prev_end = end
                    if overlaps:
                        results.append(
                            self._fail(
                                "SUBT_002",
                                f"Scene {idx} SRT has {len(overlaps)} timestamp issue(s)",
                                "; ".join(overlaps[:3]),
                                "high",
                                scene_index=idx,
                                overlap_count=len(overlaps),
                            )
                        )
                    else:
                        results.append(
                            self._pass(
                                "SUBT_002",
                                f"Scene {idx} SRT timestamps OK",
                                f"{len(blocks)} blocks",
                                scene_index=idx,
                            )
                        )

            # SUBT_003: Reading speed (CPS) per block
            if self._config.is_enabled("SUBT_003"):
                max_cps = self._config.subtitle_max_cps
                if not blocks:
                    results.append(self._skip("SUBT_003", "no SRT blocks to evaluate", scene_index=idx))
                else:
                    violations: list[str] = []
                    for i, (start, end, cue_text) in enumerate(blocks):
                        duration = end - start
                        if duration <= 0 or not cue_text:
                            continue
                        cps = len(cue_text) / duration
                        if cps > max_cps:
                            violations.append(f"block {i+1}: {cps:.1f} CPS")
                    if violations:
                        results.append(
                            self._warn(
                                "SUBT_003",
                                f"Scene {idx}: {len(violations)} block(s) exceed {max_cps} CPS",
                                "; ".join(violations[:3]),
                                "high",
                                scene_index=idx,
                                violation_count=len(violations),
                            )
                        )
                    else:
                        results.append(
                            self._pass(
                                "SUBT_003",
                                f"Scene {idx} reading speed within limit",
                                f"max {max_cps} CPS",
                                scene_index=idx,
                            )
                        )

            # SUBT_004: Characters per line
            if self._config.is_enabled("SUBT_004"):
                max_cpl = self._config.subtitle_max_chars_per_line
                long_lines = [
                    ln
                    for ln in srt_text.splitlines()
                    if ln.strip()
                    and not re.match(r"^\d+$", ln.strip())
                    and not _SRT_TS_RE.match(ln.strip())
                    and len(ln.strip()) > max_cpl
                ]
                if long_lines:
                    results.append(
                        self._warn(
                            "SUBT_004",
                            f"Scene {idx}: {len(long_lines)} line(s) exceed {max_cpl} chars",
                            f"example: '{long_lines[0].strip()[:50]}'",
                            "medium",
                            scene_index=idx,
                            long_line_count=len(long_lines),
                        )
                    )
                else:
                    results.append(
                        self._pass("SUBT_004", f"Scene {idx} line lengths OK", scene_index=idx)
                    )

            # SUBT_005: No empty cues
            if self._config.is_enabled("SUBT_005"):
                empty_cues = sum(1 for _, _, cue_text in blocks if not cue_text.strip())
                if empty_cues:
                    results.append(
                        self._warn(
                            "SUBT_005",
                            f"Scene {idx}: {empty_cues} empty subtitle cue(s) found",
                            f"empty_cue_count={empty_cues}",
                            "medium",
                            scene_index=idx,
                            empty_cue_count=empty_cues,
                        )
                    )
                else:
                    results.append(
                        self._pass("SUBT_005", f"Scene {idx} no empty cues", scene_index=idx)
                    )

            # SUBT_006: Subtitle text overlaps with narration (Jaccard)
            if self._config.is_enabled("SUBT_006"):
                narration_words = len(narration.split()) if narration else 0
                if narration_words <= 10:
                    results.append(
                        self._skip(
                            "SUBT_006",
                            "narration too short for meaningful overlap check",
                            scene_index=idx,
                        )
                    )
                else:
                    subtitle_text = " ".join(cue for _, _, cue in blocks)
                    threshold = self._config.subtitle_narration_overlap_threshold
                    sim = _jaccard(subtitle_text, narration)
                    if sim < threshold:
                        results.append(
                            self._warn(
                                "SUBT_006",
                                f"Scene {idx}: subtitle/narration overlap low ({sim:.2f})",
                                f"jaccard_similarity={sim:.2f}, threshold={threshold}",
                                "medium",
                                scene_index=idx,
                                jaccard_similarity=round(sim, 3),
                            )
                        )
                    else:
                        results.append(
                            self._pass(
                                "SUBT_006",
                                f"Scene {idx} subtitle/narration overlap OK",
                                f"jaccard={sim:.2f}",
                                scene_index=idx,
                            )
                        )

        return results
