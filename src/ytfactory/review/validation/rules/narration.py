"""Narration validation rules (category B).

Rules:
  NARR_001 [critical] — Narration present for every scene
  NARR_002 [high]     — Word count per scene within configured bounds
  NARR_003 [medium]   — No single narration block exceeds configured limit
  NARR_004 [low]      — Natural pacing proxy (average words per scene)
"""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult


class NarrationValidator(BaseValidator):
    category = "narration"
    responsible_engine = "ScriptWriter"

    def validate(
        self,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> list[ValidationResult]:
        results: list[ValidationResult] = []

        if not scenes:
            for rule_id in ("NARR_001", "NARR_002", "NARR_003", "NARR_004"):
                if self._config.is_enabled(rule_id):
                    results.append(self._skip(rule_id, "no scenes available"))
            return results

        for scene in scenes:
            idx = scene.get("index", 0)
            narration = scene.get("narration", "")
            words = narration.split() if narration else []

            # NARR_001: Narration present for every scene
            if self._config.is_enabled("NARR_001"):
                if not narration or not narration.strip():
                    results.append(
                        self._fail(
                            "NARR_001",
                            f"Scene {idx} has no narration",
                            f"scene_index={idx}, narration=empty",
                            "critical",
                            scene_index=idx,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "NARR_001",
                            f"Scene {idx} has narration",
                            f"{len(words)} words",
                            scene_index=idx,
                        )
                    )

            if not narration.strip():
                continue

            # NARR_002: Word count within bounds
            if self._config.is_enabled("NARR_002"):
                min_w = self._config.narration_min_words
                max_w = self._config.narration_max_words
                wc = len(words)
                if wc < min_w:
                    results.append(
                        self._fail(
                            "NARR_002",
                            f"Scene {idx} narration too short: {wc} words (minimum: {min_w})",
                            f"word_count={wc}, min={min_w}",
                            "high",
                            scene_index=idx,
                            word_count=wc,
                        )
                    )
                elif wc > max_w:
                    results.append(
                        self._warn(
                            "NARR_002",
                            f"Scene {idx} narration very long: {wc} words (maximum: {max_w})",
                            f"word_count={wc}, max={max_w}",
                            "medium",
                            scene_index=idx,
                            word_count=wc,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "NARR_002",
                            f"Scene {idx} narration word count OK",
                            f"{wc} words",
                            scene_index=idx,
                        )
                    )

            # NARR_003: No single block exceeds the configured limit
            if self._config.is_enabled("NARR_003"):
                max_block = self._config.narration_max_single_block_words
                wc = len(words)
                if wc > max_block:
                    results.append(
                        self._warn(
                            "NARR_003",
                            f"Scene {idx} narration is a very long block: {wc} words",
                            f"word_count={wc}, max_block={max_block}",
                            "medium",
                            scene_index=idx,
                            word_count=wc,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "NARR_003",
                            f"Scene {idx} narration block length OK",
                            f"{wc} words",
                            scene_index=idx,
                        )
                    )

        # NARR_004: Natural pacing proxy (average words per scene)
        if self._config.is_enabled("NARR_004"):
            narrations = [
                s.get("narration", "").strip()
                for s in scenes
                if s.get("narration", "").strip()
            ]
            if narrations:
                avg_words = sum(len(n.split()) for n in narrations) / len(narrations)
                if avg_words < 10:
                    results.append(
                        self._warn(
                            "NARR_004",
                            f"Average narration length is very short: {avg_words:.0f} words/scene",
                            f"avg_words_per_scene={avg_words:.1f}",
                            "low",
                            avg_words_per_scene=round(avg_words, 1),
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "NARR_004",
                            "Natural pacing proxy OK",
                            f"avg {avg_words:.0f} words/scene",
                            avg_words_per_scene=round(avg_words, 1),
                        )
                    )
            else:
                results.append(self._skip("NARR_004", "no narration content to assess"))

        return results
