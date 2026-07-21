"""Story validation rules (category H).

Rules:
  STOR_001 [high]   — Scene indices are sequential starting from 1
  STOR_002 [medium] — Scene count within configured bounds
  STOR_003 [medium] — Scene titles are unique
  STOR_004 [low]    — Narration shows variation across scenes
  STOR_005 [low]    — First scene has substantial opening narration
  STOR_006 [critical] — Frame label does not appear before first rehook (post-render safety net)
  STOR_007 [medium]  — Bridge line exists between story resolution and frame label
  STOR_008 [medium]  — Rehook gap does not exceed 45 seconds
  STOR_009 [medium]  — PEAK emotional moment has sufficient hold before scene cut
  STOR_010 [medium]  — Text overlay blocks do not exceed 5 seconds
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult
from ytfactory.shared.pipeline_status import PipelineAbort
from ytfactory.retention.pre_render_gate import check_frame_naming_gate, check_bridge_requirement, parse_script_to_segments


class StoryValidator(BaseValidator):
    category = "story"
    responsible_engine = "ScenePlanner"

    def validate(
        self,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> list[ValidationResult]:
        results: list[ValidationResult] = []

        if not scenes:
            for rule_id in (
                "STOR_001", "STOR_002", "STOR_003", "STOR_004", "STOR_005",
                "STOR_006", "STOR_007", "STOR_008", "STOR_009", "STOR_010",
            ):
                if self._config.is_enabled(rule_id):
                    results.append(self._skip(rule_id, "no scenes available"))
            return results

        indices = [s.get("index", 0) for s in scenes]

        # STOR_001: Sequential indices starting from 1
        if self._config.is_enabled("STOR_001"):
            expected = list(range(1, len(scenes) + 1))
            if sorted(indices) != expected:
                results.append(
                    self._fail(
                        "STOR_001",
                        f"Scene indices not sequential: got {sorted(indices)}, expected {expected}",
                        f"indices={sorted(indices)}",
                        "high",
                        indices=sorted(indices),
                    )
                )
            else:
                results.append(
                    self._pass(
                        "STOR_001",
                        "Scene indices are sequential",
                        f"1..{len(scenes)}",
                    )
                )

        # STOR_002: Scene count within bounds
        if self._config.is_enabled("STOR_002"):
            count = len(scenes)
            min_s = self._config.story_min_scenes
            max_s = self._config.story_max_scenes
            if count < min_s:
                results.append(
                    self._fail(
                        "STOR_002",
                        f"Too few scenes: {count} (minimum: {min_s})",
                        f"scene_count={count}",
                        "medium",
                        scene_count=count,
                    )
                )
            elif count > max_s:
                results.append(
                    self._warn(
                        "STOR_002",
                        f"Very many scenes: {count} (maximum: {max_s})",
                        f"scene_count={count}",
                        "medium",
                        scene_count=count,
                    )
                )
            else:
                results.append(
                    self._pass(
                        "STOR_002",
                        "Scene count within bounds",
                        f"{count} scenes",
                    )
                )

        # STOR_003: Scene titles are unique
        if self._config.is_enabled("STOR_003"):
            titles = [
                s.get("title", "").strip() for s in scenes if s.get("title", "").strip()
            ]
            if not titles:
                results.append(self._skip("STOR_003", "no scene titles present"))
            else:
                seen: set[str] = set()
                dupes = [t for t in titles if t in seen or seen.add(t)]  # type: ignore[func-returns-value]
                unique_dupes = list(dict.fromkeys(dupes))  # preserve first-seen order
                if unique_dupes:
                    results.append(
                        self._warn(
                            "STOR_003",
                            f"Duplicate scene titles: {unique_dupes[:3]}",
                            f"duplicate_count={len(unique_dupes)}",
                            "medium",
                            duplicate_titles=unique_dupes[:5],
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "STOR_003",
                            "Scene titles are unique",
                            f"{len(titles)} unique titles",
                        )
                    )

        # STOR_004: Narration shows variation across scenes
        if self._config.is_enabled("STOR_004"):
            narrations = [
                s.get("narration", "").strip()
                for s in scenes
                if s.get("narration", "").strip()
            ]
            if len(narrations) < 2:
                results.append(
                    self._skip("STOR_004", "fewer than 2 scenes with narration")
                )
            else:
                unique_narrations = set(narrations)
                if len(unique_narrations) == 1:
                    results.append(
                        self._warn(
                            "STOR_004",
                            "All scenes have identical narration — no story progression",
                            f"unique_narrations=1 out of {len(narrations)} scenes",
                            "low",
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "STOR_004",
                            "Narration shows variation across scenes",
                            f"{len(unique_narrations)} unique narrations across {len(narrations)} scenes",
                        )
                    )

        # STOR_005: First scene has substantial opening narration
        if self._config.is_enabled("STOR_005"):
            first = next((s for s in scenes if s.get("index") == 1), None)
            if first is None:
                results.append(self._skip("STOR_005", "no scene with index=1 found"))
            else:
                words = len(first.get("narration", "").split())
                if words < 10:
                    results.append(
                        self._warn(
                            "STOR_005",
                            f"First scene narration very short: {words} words",
                            f"first_scene_word_count={words}",
                            "low",
                            scene_index=1,
                            word_count=words,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "STOR_005",
                            "First scene has substantial opening narration",
                            f"{words} words",
                            scene_index=1,
                        )
                    )

        # ── Pipeline QA post-render rules ─────────────────────────────────

        # STOR_006: Frame naming gate — post-render safety net
        if self._config.is_enabled("STOR_006"):
            script_path = Path(context.get("script_md_path", ""))
            if script_path.is_file():
                script_md = script_path.read_text(encoding="utf-8")
                segments = parse_script_to_segments(script_md)
                first_rehook = next((i for i, s in enumerate(segments) if s.is_rehook), None)
                if first_rehook is not None:
                    violations = check_frame_naming_gate(segments)
                    if violations:
                        results.append(
                            self._fail(
                                "STOR_006",
                                f"Frame label appears before first rehook: {violations[0]}",
                                f"frame_label_before_rehook={len(violations)}",
                                "critical",
                                scene_index=0,
                            )
                        )
                        raise PipelineAbort(
                            stage="quality_review",
                            reason=f"STOR_006: Frame naming gate failed — {len(violations)} frame label(s) before first rehook",
                        )
                    else:
                        results.append(self._pass("STOR_006", "Frame naming gate passed", ""))
                else:
                    results.append(self._skip("STOR_006", "no rehook found in script"))
            else:
                results.append(self._skip("STOR_006", "script.md not found"))

        # STOR_007: Bridge requirement — post-render safety net
        if self._config.is_enabled("STOR_007"):
            script_path = Path(context.get("script_md_path", ""))
            if script_path.is_file():
                script_md = script_path.read_text(encoding="utf-8")
                segments = parse_script_to_segments(script_md)
                violations = check_bridge_requirement(segments)
                if violations:
                    results.append(
                        self._warn(
                            "STOR_007",
                            f"Bridge requirement violated: {violations[0]}",
                            f"bridge_violations={len(violations)}",
                            "medium",
                        )
                    )
                else:
                    results.append(self._pass("STOR_007", "Bridge requirement satisfied", ""))
            else:
                results.append(self._skip("STOR_007", "script.md not found"))

        # STOR_008: Rehook gap > 45s
        if self._config.is_enabled("STOR_008"):
            audio_dir = Path(context.get("audio_dir", ""))
            rehook_times: list[float] = []
            if audio_dir.is_dir():
                for timing_file in sorted(audio_dir.glob("scene-*.timing.json")):
                    try:
                        data = json.loads(timing_file.read_text(encoding="utf-8"))
                        if data and isinstance(data, list) and len(data) > 0:
                            last_word = data[-1]
                            rehook_times.append(float(last_word.get("end", 0)))
                    except (json.JSONDecodeError, OSError, KeyError):
                        continue
            if len(rehook_times) >= 2:
                gaps = [
                    rehook_times[i + 1] - rehook_times[i] for i in range(len(rehook_times) - 1)
                ]
                max_gap = max(gaps) if gaps else 0
                if max_gap > 45.0:
                    gap_idx = gaps.index(max_gap)
                    results.append(
                        self._warn(
                            "STOR_008",
                            f"Rehook gap exceeds 45s: {max_gap:.1f}s between rehooks {gap_idx}→{gap_idx + 1}",
                            f"max_gap={max_gap:.1f}s",
                            "medium",
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "STOR_008",
                            f"Rehook gaps within bounds (max {max_gap:.1f}s)",
                            f"max_gap={max_gap:.1f}s",
                        )
                    )
            else:
                results.append(self._skip("STOR_008", "insufficient rehook timing data"))

        # STOR_009: Missing holds — PEAK moment cut within 1.5s
        if self._config.is_enabled("STOR_009"):
            violations = self._check_missing_holds(project_dir, scenes, context)
            if violations:
                results.append(
                    self._warn(
                        "STOR_009",
                        f"Missing hold at {violations[0]}",
                        f"missing_hold_count={len(violations)}",
                        "medium",
                    )
                )
            else:
                results.append(self._pass("STOR_009", "All PEAK moments have sufficient holds", ""))

        # STOR_010: Text overlay duration > 5s
        if self._config.is_enabled("STOR_010"):
            violations = self._check_text_overlay_duration(context)
            if violations:
                results.append(
                    self._warn(
                        "STOR_010",
                        f"Text overlay held too long: {violations[0][2]} ({violations[0][1] - violations[0][0]:.1f}s)",
                        f"overlay_violations={len(violations)}",
                        "medium",
                    )
                )
            else:
                results.append(self._pass("STOR_010", "Text overlay durations within bounds", ""))

        return results

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _check_missing_holds(
        self,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> list[tuple[float, float]]:
        """
        Cross-reference scenes where linked_segment.emotional_intensity == PEAK
        against actual scene cut timestamps in the rendered video.
        Flag if a scene cut occurs within 1.5s of a peak line ending.
        """
        violations: list[tuple[float, float]] = []
        peak_segments = []
        for scene in scenes:
            seg_data = scene.get("linked_segment")
            if seg_data and seg_data.get("emotional_intensity") == "peak":
                peak_segments.append((scene.get("index", 0), seg_data))

        if not peak_segments:
            return violations

        final_video = Path(context.get("final_video_path", ""))
        if not final_video.is_file():
            return violations

        import subprocess

        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "frame=pkt_pts_time",
                    "-of", "csv=p=0",
                    str(final_video),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            scene_cuts = [
                float(line.strip())
                for line in probe.stdout.strip().splitlines()
                if line.strip()
            ]
        except (subprocess.SubprocessError, OSError, ValueError):
            return violations

        for scene_idx, seg_data in peak_segments:
            end_time = seg_data.get("end_time")
            if end_time is None:
                continue
            for cut_time in scene_cuts:
                if 0 < abs(cut_time - float(end_time)) < 1.5:
                    violations.append((float(end_time), cut_time))
                    break

        return violations

    def _check_text_overlay_duration(self, context: dict) -> list[tuple[float, float, str]]:
        """
        Read cta-timing.json timing_metadata. Flag any single overlay block active > 5s.
        """
        violations: list[tuple[float, float, str]] = []
        cta_path = Path(context.get("cta_timing_path", ""))
        if not cta_path.is_file():
            return violations

        try:
            data = json.loads(cta_path.read_text(encoding="utf-8"))
            timing = data.get("timing_metadata")
            if not timing:
                return violations
            duration = float(timing.get("duration", 0))
            timestamp = float(timing.get("timestamp", 0))
            if duration > 5.0:
                violations.append((timestamp, timestamp + duration, timing.get("variant", "cta")))
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            pass

        return violations
