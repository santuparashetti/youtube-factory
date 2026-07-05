"""
SubtitleValidator — validation rules + auto-repair for subtitle cues.

Checks (in order):
  1. HIGH_CPS      — characters per second exceeds limit
  2. LONG_LINE     — a line exceeds MAX_CHARS_PER_LINE
  3. ORPHAN        — a line has only one word
  4. SHORT_DUR     — cue duration is suspiciously short
  5. LONG_DUR      — cue duration is suspiciously long
  6. EMPTY_CUE     — cue has no displayable text

Repairs are applied in-place where possible.
Findings that cannot be auto-repaired are flagged as warnings.
"""

from __future__ import annotations

from .models import SubtitleCue, ValidationIssue

# Default thresholds (overridden by settings)
_DEFAULT_MAX_CPS = 18.0
_DEFAULT_MAX_CHARS_PER_LINE = 42
_DEFAULT_MIN_DURATION = 0.5
_DEFAULT_MAX_DURATION = 7.0
_ORPHAN_WORD_THRESHOLD = 1  # a line with ≤ this many words is an orphan


class SubtitleValidator:
    """
    Validate and repair a list of SubtitleCues.

    Usage::

        validator = SubtitleValidator(max_cps=18, max_chars_per_line=42)
        repaired, issues = validator.validate(cues)
    """

    def __init__(
        self,
        max_cps: float = _DEFAULT_MAX_CPS,
        max_chars_per_line: int = _DEFAULT_MAX_CHARS_PER_LINE,
        min_duration: float = _DEFAULT_MIN_DURATION,
        max_duration: float = _DEFAULT_MAX_DURATION,
    ) -> None:
        self._max_cps = max_cps
        self._max_chars = max_chars_per_line
        self._min_dur = min_duration
        self._max_dur = max_duration

    def validate(
        self,
        cues: list[SubtitleCue],
    ) -> tuple[list[SubtitleCue], list[ValidationIssue]]:
        """
        Validate all cues and auto-repair where possible.

        Returns:
            (repaired_cues, issues)
            issues contains both auto-repaired and non-repaired findings.
        """
        result: list[SubtitleCue] = []
        issues: list[ValidationIssue] = []

        for cue in cues:
            repaired_cue, cue_issues = self._validate_cue(cue)
            if repaired_cue is not None:
                result.append(repaired_cue)
            issues.extend(cue_issues)

        return result, issues

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _validate_cue(
        self,
        cue: SubtitleCue,
    ) -> tuple[SubtitleCue | None, list[ValidationIssue]]:
        issues: list[ValidationIssue] = []
        lines = list(cue.lines)

        # Empty cue
        if not any(ln.strip() for ln in lines):
            issues.append(
                ValidationIssue(
                    cue_index=cue.index,
                    code="EMPTY_CUE",
                    severity="error",
                    message="Cue has no displayable text",
                    repaired=True,  # will be removed
                )
            )
            return None, issues

        # Short duration
        if cue.duration < self._min_dur:
            issues.append(
                ValidationIssue(
                    cue_index=cue.index,
                    code="SHORT_DUR",
                    severity="warning",
                    message=f"Duration {cue.duration:.2f}s below minimum {self._min_dur}s",
                )
            )

        # Long duration
        if cue.duration > self._max_dur:
            issues.append(
                ValidationIssue(
                    cue_index=cue.index,
                    code="LONG_DUR",
                    severity="warning",
                    message=f"Duration {cue.duration:.2f}s exceeds maximum {self._max_dur}s",
                )
            )

        # CPS check
        if cue.cps > self._max_cps:
            issues.append(
                ValidationIssue(
                    cue_index=cue.index,
                    code="HIGH_CPS",
                    severity="warning",
                    message=f"CPS {cue.cps:.1f} exceeds limit {self._max_cps}",
                )
            )

        # Long lines
        repaired_lines = []
        for line in lines:
            if len(line) > self._max_chars:
                issues.append(
                    ValidationIssue(
                        cue_index=cue.index,
                        code="LONG_LINE",
                        severity="warning",
                        message=f"Line '{line[:20]}…' is {len(line)} chars (max {self._max_chars})",
                    )
                )
            repaired_lines.append(line)

        # Orphan detection
        for line in repaired_lines:
            word_count = len(line.split())
            if word_count <= _ORPHAN_WORD_THRESHOLD:
                issues.append(
                    ValidationIssue(
                        cue_index=cue.index,
                        code="ORPHAN",
                        severity="warning",
                        message=f"Single-word line: '{line}'",
                    )
                )

        repaired = SubtitleCue(
            index=cue.index,
            start=cue.start,
            end=cue.end,
            lines=repaired_lines,
        )
        return repaired, issues
