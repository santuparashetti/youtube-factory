"""Story validation rules (category H).

Rules:
  STOR_001 [high]   — Scene indices are sequential starting from 1
  STOR_002 [medium] — Scene count within configured bounds
  STOR_003 [medium] — Scene titles are unique
  STOR_004 [low]    — Narration shows variation across scenes
  STOR_005 [low]    — First scene has substantial opening narration
"""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult


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
            for rule_id in ("STOR_001", "STOR_002", "STOR_003", "STOR_004", "STOR_005"):
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

        return results
