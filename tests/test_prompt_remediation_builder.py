"""Unit tests for PromptRemediationBuilder."""

from __future__ import annotations

import pytest

from ytfactory.prompts.prompt_remediation_builder import (
    CATEGORY_PROMPT_LIBRARY,
    RULE_PROMPT_LIBRARY,
    PromptRemediationBuilder,
    RemediationInput,
    _CORRECTION_HEADER,
    _FALLBACK_INSTRUCTION,
)
from ytfactory.providers.vision.models import IssueSeverity, VisionIssue, VisionReviewResult


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _result(issues: list[VisionIssue] | None = None, score: float = 40.0) -> VisionReviewResult:
    return VisionReviewResult(
        status="FAIL",
        score=score,
        confidence=80.0,
        issues=issues or [],
        recommend_regeneration=True,
    )


def _input(
    prompt: str = "Ancient Greek philosopher walking along a stone road.",
    issues: list[VisionIssue] | None = None,
    detected_rules: list[str] | None = None,
    cinematic_score: float = 90.0,
    attempt: int = 1,
) -> RemediationInput:
    return RemediationInput(
        original_prompt=prompt,
        scene={"index": 1, "visual_prompt": prompt},
        result=_result(issues),
        cinematic_score=cinematic_score,
        detected_rules=detected_rules or [],
        attempt=attempt,
    )


def _issue(cat: str, desc: str, sev: IssueSeverity = IssueSeverity.HIGH) -> VisionIssue:
    return VisionIssue(category=cat, description=desc, severity=sev)


# ── PromptRemediationBuilder.build() ─────────────────────────────────────────


class TestBuildPreservesOriginalPrompt:
    def test_output_starts_with_original(self) -> None:
        builder = PromptRemediationBuilder()
        original = "Ancient Greek philosopher walking along a stone road."
        result = builder.build(_input(prompt=original, detected_rules=["hands_invalid"]))
        assert result.startswith(original)

    def test_never_replaces_original(self) -> None:
        builder = PromptRemediationBuilder()
        original = "Cinematic portrait of a bearded elder, golden hour, stone archway."
        result = builder.build(_input(prompt=original, detected_rules=["face_distorted"]))
        assert original in result

    def test_output_longer_than_original(self) -> None:
        builder = PromptRemediationBuilder()
        original = "Short prompt."
        result = builder.build(_input(prompt=original, detected_rules=["hands_invalid"]))
        assert len(result) > len(original)

    def test_correction_header_present(self) -> None:
        builder = PromptRemediationBuilder()
        result = builder.build(_input(detected_rules=["hands_invalid"]))
        assert _CORRECTION_HEADER in result


class TestBuildFromNamedRules:
    def test_hands_invalid_rule_adds_hand_instruction(self) -> None:
        builder = PromptRemediationBuilder()
        result = builder.build(_input(detected_rules=["hands_invalid"]))
        assert RULE_PROMPT_LIBRARY["hands_invalid"] in result

    def test_face_distorted_rule_adds_face_instruction(self) -> None:
        builder = PromptRemediationBuilder()
        result = builder.build(_input(detected_rules=["face_distorted"]))
        assert RULE_PROMPT_LIBRARY["face_distorted"] in result

    def test_impossible_walk_rule_adds_gait_instruction(self) -> None:
        builder = PromptRemediationBuilder()
        result = builder.build(_input(detected_rules=["impossible_walk_cycle"]))
        assert RULE_PROMPT_LIBRARY["impossible_walk_cycle"] in result

    def test_multiple_rules_all_included(self) -> None:
        builder = PromptRemediationBuilder()
        result = builder.build(_input(detected_rules=["hands_invalid", "impossible_walk_cycle"]))
        assert RULE_PROMPT_LIBRARY["hands_invalid"] in result
        assert RULE_PROMPT_LIBRARY["impossible_walk_cycle"] in result

    def test_instructions_formatted_as_bullets(self) -> None:
        builder = PromptRemediationBuilder()
        result = builder.build(_input(detected_rules=["hands_invalid"]))
        assert "- " in result


class TestBuildFallbackBehaviour:
    def test_fallback_when_no_rules_and_no_issues(self) -> None:
        builder = PromptRemediationBuilder()
        result = builder.build(_input(detected_rules=[], issues=[]))
        assert _FALLBACK_INSTRUCTION in result

    def test_category_fallback_for_uncovered_issue(self) -> None:
        # lighting issue with no named rule → category fallback
        issues = [_issue("lighting", "harsh unnatural shadows", IssueSeverity.MEDIUM)]
        builder = PromptRemediationBuilder()
        result = builder.build(_input(issues=issues, detected_rules=[]))
        assert CATEGORY_PROMPT_LIBRARY["lighting"] in result

    def test_cinematic_boost_when_score_critically_low(self) -> None:
        builder = PromptRemediationBuilder()
        result = builder.build(_input(detected_rules=[], cinematic_score=50.0))
        assert (
            RULE_PROMPT_LIBRARY["weak_composition"] in result
            or CATEGORY_PROMPT_LIBRARY["cinematic"] in result
        )

    def test_no_cinematic_boost_when_already_covered(self) -> None:
        # weak_composition is already a named rule → no duplicate
        builder = PromptRemediationBuilder()
        result = builder.build(_input(detected_rules=["weak_composition"], cinematic_score=50.0))
        # instruction appears exactly once
        instr = RULE_PROMPT_LIBRARY["weak_composition"]
        assert result.count(instr) == 1

    def test_no_cinematic_boost_when_score_adequate(self) -> None:
        builder = PromptRemediationBuilder()
        # score=90 is above 70 threshold → no automatic cinematic boost
        result = builder.build(_input(detected_rules=[], issues=[], cinematic_score=90.0))
        assert RULE_PROMPT_LIBRARY["weak_composition"] not in result


class TestBuildDeduplication:
    def test_duplicate_rules_produce_one_instruction(self) -> None:
        builder = PromptRemediationBuilder()
        result = builder.build(_input(detected_rules=["hands_invalid", "hands_invalid"]))
        instr = RULE_PROMPT_LIBRARY["hands_invalid"]
        assert result.count(instr) == 1

    def test_category_fallback_not_added_when_rule_covers_category(self) -> None:
        # hands_invalid covers "anatomy" → anatomy category fallback should not appear
        builder = PromptRemediationBuilder()
        issues = [_issue("anatomy", "bad limb proportion", IssueSeverity.HIGH)]
        result = builder.build(_input(detected_rules=["hands_invalid"], issues=issues))
        # anatomy category fallback must NOT appear alongside the rule instruction
        assert CATEGORY_PROMPT_LIBRARY["anatomy"] not in result


# ── PromptRemediationBuilder.detect_rules() ──────────────────────────────────


class TestDetectRules:
    def test_anatomy_hand_keyword_detects_hands_invalid(self) -> None:
        builder = PromptRemediationBuilder()
        issues = [_issue("anatomy", "badly formed hand, extra finger", IssueSeverity.HIGH)]
        assert "hands_invalid" in builder.detect_rules(issues)

    def test_face_distort_keyword_detects_face_distorted(self) -> None:
        builder = PromptRemediationBuilder()
        issues = [_issue("face", "distorted jaw, asymmetric eye alignment", IssueSeverity.HIGH)]
        assert "face_distorted" in builder.detect_rules(issues)

    def test_below_min_severity_not_detected(self) -> None:
        # impossible_walk_cycle requires HIGH; LOW should not fire it
        builder = PromptRemediationBuilder()
        issues = [_issue("anatomy", "walk gait slightly off", IssueSeverity.LOW)]
        assert "impossible_walk_cycle" not in builder.detect_rules(issues)

    def test_no_issues_returns_empty_list(self) -> None:
        assert PromptRemediationBuilder().detect_rules([]) == []

    def test_each_rule_appears_at_most_once(self) -> None:
        builder = PromptRemediationBuilder()
        # Two issues both pointing to hands_invalid
        issues = [
            _issue("anatomy", "bad hand anatomy", IssueSeverity.HIGH),
            _issue("anatomy", "finger count wrong", IssueSeverity.HIGH),
        ]
        detected = builder.detect_rules(issues)
        assert detected.count("hands_invalid") == 1

    def test_build_auto_detects_rules_when_not_provided(self) -> None:
        # When detected_rules=[] (default), builder auto-detects from issues
        builder = PromptRemediationBuilder()
        issues = [_issue("anatomy", "bad hand fingers", IssueSeverity.HIGH)]
        result = builder.build(_input(issues=issues, detected_rules=[]))
        assert RULE_PROMPT_LIBRARY["hands_invalid"] in result
