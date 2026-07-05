"""Script validation rules (category A).

Rules:
  SCRIPT_001 [critical] — Script file exists and is non-empty
  SCRIPT_002 [high]     — Word count within configured range
  SCRIPT_003 [medium]   — No repeated paragraphs (Jaccard similarity)
  SCRIPT_004 [medium]   — Minimum sentence count
  SCRIPT_005 [low]      — Script has sufficient content lines
"""

from __future__ import annotations

import re
from pathlib import Path

from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult


def _jaccard(a: str, b: str) -> float:
    sa = set(a.lower().split())
    sb = set(b.lower().split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


class ScriptValidator(BaseValidator):
    category = "script"
    responsible_engine = "ScriptWriter"

    def validate(
        self,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        script_file = project_dir / "script" / "script.md"

        # SCRIPT_001: Script file exists and is non-empty
        if self._config.is_enabled("SCRIPT_001"):
            exists_and_nonempty = script_file.exists() and script_file.stat().st_size > 0
            if not exists_and_nonempty:
                results.append(
                    self._fail(
                        "SCRIPT_001",
                        "Script file is missing or empty",
                        f"Expected: {script_file}",
                        "critical",
                    )
                )
                for rule_id in ("SCRIPT_002", "SCRIPT_003", "SCRIPT_004", "SCRIPT_005"):
                    if self._config.is_enabled(rule_id):
                        results.append(self._skip(rule_id, "script file unavailable"))
                return results
            results.append(
                self._pass(
                    "SCRIPT_001",
                    "Script file exists and is non-empty",
                    str(script_file),
                )
            )

        if not script_file.exists():
            return results

        text = script_file.read_text(encoding="utf-8", errors="replace")
        words = text.split()

        # SCRIPT_002: Word count within range
        if self._config.is_enabled("SCRIPT_002"):
            min_w = self._config.script_min_words
            max_w = self._config.script_max_words
            wc = len(words)
            if wc < min_w:
                results.append(
                    self._fail(
                        "SCRIPT_002",
                        f"Script is too short: {wc} words (minimum: {min_w})",
                        f"word_count={wc}, min={min_w}",
                        "high",
                        word_count=wc,
                    )
                )
            elif wc > max_w:
                results.append(
                    self._warn(
                        "SCRIPT_002",
                        f"Script is very long: {wc} words (maximum: {max_w})",
                        f"word_count={wc}, max={max_w}",
                        "medium",
                        word_count=wc,
                    )
                )
            else:
                results.append(
                    self._pass(
                        "SCRIPT_002",
                        "Script word count within range",
                        f"{wc} words",
                        word_count=wc,
                    )
                )

        # SCRIPT_003: No repeated paragraphs
        if self._config.is_enabled("SCRIPT_003"):
            paragraphs = [
                p.strip()
                for p in re.split(r"\n{2,}", text)
                if len(p.split()) > 5
            ]
            threshold = self._config.script_paragraph_similarity_threshold
            repeated: list[tuple[int, int, float]] = []
            for i in range(len(paragraphs)):
                for j in range(i + 1, len(paragraphs)):
                    sim = _jaccard(paragraphs[i], paragraphs[j])
                    if sim >= threshold:
                        repeated.append((i + 1, j + 1, round(sim, 2)))
            if repeated:
                evidence = "; ".join(
                    f"paragraphs {a}&{b} sim={s}" for a, b, s in repeated[:3]
                )
                results.append(
                    self._warn(
                        "SCRIPT_003",
                        f"Script contains {len(repeated)} highly similar paragraph pair(s)",
                        evidence,
                        "medium",
                        repeated_pair_count=len(repeated),
                    )
                )
            else:
                results.append(self._pass("SCRIPT_003", "No repeated paragraphs detected"))

        # SCRIPT_004: Minimum sentence count
        if self._config.is_enabled("SCRIPT_004"):
            sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
            min_s = self._config.script_min_sentences
            if len(sentences) < min_s:
                results.append(
                    self._fail(
                        "SCRIPT_004",
                        f"Script has too few sentences: {len(sentences)} (minimum: {min_s})",
                        f"sentence_count={len(sentences)}",
                        "medium",
                        sentence_count=len(sentences),
                    )
                )
            else:
                results.append(
                    self._pass(
                        "SCRIPT_004",
                        "Script has sufficient sentences",
                        f"{len(sentences)} sentences",
                    )
                )

        # SCRIPT_005: Script has multiple content lines
        if self._config.is_enabled("SCRIPT_005"):
            content_lines = [line.strip() for line in text.splitlines() if line.strip()]
            if len(content_lines) < 3:
                results.append(
                    self._warn(
                        "SCRIPT_005",
                        "Script has very few content lines — may lack structure",
                        f"content_line_count={len(content_lines)}",
                        "low",
                        content_line_count=len(content_lines),
                    )
                )
            else:
                results.append(
                    self._pass(
                        "SCRIPT_005",
                        "Script has sufficient content lines",
                        f"{len(content_lines)} lines",
                    )
                )

        return results
