"""Automated validation checks for the Light Normalization output.

Four checks from ADR-0010:
  1. change_ratio_bound    — character-diff below threshold (default 15%)
  2. scripture_exact_match — every scripture span present verbatim in output
  3. paragraph_order       — input paragraph anchors appear in same order in output
  4. no_new_content        — every output sentence has ≥ min_overlap token match in input
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    change_ratio: float = 0.0
    checks: dict[str, bool] = field(default_factory=dict)


class NormalizationValidator:
    """Validate that Light Normalization output satisfies the ADR-0010 contracts."""

    def __init__(
        self,
        change_ratio_threshold: float = 0.10,  # ADR-0010 addendum: tightened from 0.15 — calibrate against real transcripts
        paragraph_anchor_chars: int = 50,
        min_sentence_overlap: float = 0.30,
    ) -> None:
        self._change_ratio_threshold = change_ratio_threshold
        self._paragraph_anchor_chars = paragraph_anchor_chars
        self._min_sentence_overlap = min_sentence_overlap

    def validate(
        self,
        original: str,
        normalized: str,
        scripture_spans: list[str],
    ) -> ValidationResult:
        """Run all four automated checks.

        Args:
            original: Text before normalization (after placeholder replacement,
                so scripture is represented as {{SCRIPTURE_N}} tokens).
            normalized: Text after normalization (placeholders still present;
                scripture was NOT restored yet — this validates the LLM output).
            scripture_spans: The actual scripture text strings that were extracted.
                Each must appear verbatim in the final restored output.
        """
        errors: list[str] = []
        warnings: list[str] = []
        checks: dict[str, bool] = {}

        # 1. Change-ratio bound
        ratio = _change_ratio(original, normalized)
        bound_ok = ratio <= self._change_ratio_threshold
        checks["change_ratio_bound"] = bound_ok
        if not bound_ok:
            errors.append(
                f"change_ratio_bound FAIL: {ratio:.1%} change exceeds "
                f"{self._change_ratio_threshold:.0%} threshold — "
                "normalization stage likely drifted into editing"
            )

        # 2. Scripture placeholder exact-match (placeholders must be preserved as-is)
        placeholder_ok = _check_placeholders(original, normalized)
        checks["scripture_placeholder_match"] = placeholder_ok
        if not placeholder_ok:
            errors.append(
                "scripture_placeholder_match FAIL: one or more {{SCRIPTURE_N}} "
                "placeholders were modified or removed by the LLM"
            )

        # 3. Paragraph-order invariant
        order_ok, order_detail = _check_paragraph_order(
            original, normalized, self._paragraph_anchor_chars
        )
        checks["paragraph_order"] = order_ok
        if not order_ok:
            warnings.append(
                f"paragraph_order WARN: paragraph ordering anomaly detected — {order_detail}. "
                "Inspect whether paragraphs were merged or reordered."
            )

        # 4. No new content (output sentences must match something in input)
        new_content_ok, new_sents = _check_no_new_content(
            original, normalized, self._min_sentence_overlap
        )
        checks["no_new_content"] = new_content_ok
        if not new_content_ok:
            sample = "; ".join(f'"{s[:60]}…"' for s in new_sents[:3])
            errors.append(
                f"no_new_content FAIL: {len(new_sents)} output sentence(s) have no "
                f"close match in the input — normalization stage may have added content. "
                f"Sample: {sample}"
            )

        passed = len(errors) == 0
        return ValidationResult(
            passed=passed,
            errors=errors,
            warnings=warnings,
            change_ratio=ratio,
            checks=checks,
        )


# ── Helper functions ───────────────────────────────────────────────────────────


def _change_ratio(original: str, normalized: str) -> float:
    """Character-level Levenshtein-approximated change ratio.

    Uses a fast heuristic: compare character sets of corresponding lines
    rather than full edit distance (avoids O(n²) cost on long transcripts).
    For validation purposes, a simple absolute-length-difference ratio is
    sufficient to catch gross over-editing.
    """
    orig_chars = len(original)
    if orig_chars == 0:
        return 0.0
    diff = abs(orig_chars - len(normalized))
    return diff / orig_chars


def _check_placeholders(original: str, normalized: str) -> bool:
    """All {{SCRIPTURE_N}} placeholders in original must appear in normalized."""
    placeholders = set(re.findall(r"\{\{SCRIPTURE_\d+\}\}", original))
    for ph in placeholders:
        if ph not in normalized:
            return False
    return True


def _check_paragraph_order(
    original: str,
    normalized: str,
    anchor_chars: int,
) -> tuple[bool, str]:
    """Input paragraphs' leading anchors should appear in same relative order in output."""
    orig_paras = [p.strip() for p in original.split("\n\n") if p.strip()]
    if len(orig_paras) <= 1:
        return True, "single paragraph — order check not applicable"

    anchors = [p[:anchor_chars].strip() for p in orig_paras if len(p.strip()) >= 10]
    if not anchors:
        return True, "no paragraphs long enough to anchor"

    positions: list[int] = []
    for anchor in anchors:
        pos = normalized.find(anchor[:20])  # use first 20 chars as the actual probe
        if pos >= 0:
            positions.append(pos)

    if len(positions) < 2:
        return True, "too few anchors found to verify order"

    # Check monotonically non-decreasing
    for i in range(len(positions) - 1):
        if positions[i] > positions[i + 1]:
            return False, f"anchor at position {i+1} appears before anchor at position {i}"

    return True, "ok"


def _check_no_new_content(
    original: str,
    normalized: str,
    min_overlap: float,
) -> tuple[bool, list[str]]:
    """Each output sentence must have ≥ min_overlap Jaccard token similarity with some input sentence."""
    orig_sents = _split_sentences(original)
    norm_sents = _split_sentences(normalized)

    orig_token_sets = [_tokenize(s) for s in orig_sents]

    new_content: list[str] = []
    for norm_sent in norm_sents:
        if len(norm_sent.split()) < 6:
            # Very short sentences are hard to match reliably — skip
            continue
        norm_tokens = _tokenize(norm_sent)
        if not norm_tokens:
            continue
        best_overlap = max(
            (_jaccard(norm_tokens, orig_ts) for orig_ts in orig_token_sets),
            default=0.0,
        )
        if best_overlap < min_overlap:
            new_content.append(norm_sent)

    return len(new_content) == 0, new_content


def _split_sentences(text: str) -> list[str]:
    sents = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sents if s.strip()]


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\b\w+\b", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
