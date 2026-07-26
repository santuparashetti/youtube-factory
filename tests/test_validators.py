"""Regression tests for story fidelity validators."""

from __future__ import annotations

from ytfactory.images.validators import (
    HumanClassification,
    RealismValidator,
    RetryCoordinator,
    StoryFidelityValidator,
    SymbolismValidator,
    ValidationError,
    ValidationResult,
    run_validators,
)


# ── StoryFidelityValidator ─────────────────────────────────────────────────────


class TestStoryFidelityValidator:
    def test_rejects_invented_generic_human(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["eaglet", "eagle"]},
            prompt="A lean man stands at the edge of a cliff.",
            narration="The chick rose a little. Came down. Tried again.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert not result.passed
        codes = [e.code for e in result.errors]
        assert "UNSUPPORTED_CHARACTER" in codes

    def test_passes_when_characters_match(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["eaglet", "eagle"]},
            prompt="A young eaglet tests its wings on a cliff edge, wide cinematic.",
            narration="The eaglet tests its wings.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert result.passed

    def test_primary_subject_missing_no_longer_flagged(self):
        """Task 2.3 Fix 1: PRIMARY_SUBJECT_MISSING removed — semantic checks
        can't judge whether cinematic imagery embodies a concept."""
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"primary_subject": "eaglet", "allowed_characters": ["eaglet"]},
            prompt="A cliff edge at sunset, golden hour light, wide cinematic.",
            narration="The eaglet tests its wings.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert not any(e.code == "PRIMARY_SUBJECT_MISSING" for e in result.errors)

    def test_primary_action_missing_no_longer_flagged(self):
        """Task 2.3 Fix 1: PRIMARY_ACTION_MISSING removed."""
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"primary_action": "testing wings", "allowed_characters": ["eaglet"]},
            prompt="A young eaglet perched on a cliff, wide cinematic.",
            narration="The eaglet tests its wings.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert not any(e.code == "PRIMARY_ACTION_MISSING" for e in result.errors)

    def test_narration_not_represented_no_longer_flagged(self):
        """Task 2.3 Fix 1: NARRATION_NOT_REPRESENTED removed."""
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["eaglet"], "primary_action": "testing wings"},
            prompt="A vast ocean, golden sunset, cinematic wide shot.",
            narration="The eaglet tests its wings on the cliff.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert not any(e.code == "NARRATION_NOT_REPRESENTED" for e in result.errors)

    def test_detects_environment_mismatch(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"environment": "ocean", "allowed_characters": ["eaglet"]},
            prompt="A young eaglet tests its wings on a cliff edge.",
            narration="The eaglet tests its wings on the cliff.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert not result.passed
        assert any(e.code == "ENVIRONMENT_MISMATCH" for e in result.errors)

    def test_detects_missing_camera(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["eaglet"]},
            prompt="A young eaglet tests its wings on a cliff edge.",
            narration="The eaglet tests its wings.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert not result.passed
        assert any(e.code == "CAMERA_MISSING" for e in result.errors)

    def test_no_human_allowed_enforcement(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["eaglet"]},
            prompt="A young eaglet tests its wings, face visible, golden hour.",
            narration="The eaglet tests its wings.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert not result.passed
        assert any(e.code == "HUMAN_CLASSIFICATION_VIOLATED" for e in result.errors)

    def test_human_required_enforcement(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["Bhagiratha"]},
            prompt="A vast mountain landscape.",
            narration="Bhagiratha walked up the mountain.",
            human_classification=HumanClassification.HUMAN_REQUIRED,
        )
        assert not result.passed
        assert any(e.code == "HUMAN_CLASSIFICATION_VIOLATED" for e in result.errors)

    def test_named_person_required_enforcement(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"named_person": "Bhagiratha", "allowed_characters": ["Bhagiratha"]},
            prompt="A sage meditating in the mountains.",
            narration="Bhagiratha went to the Himalayan peaks.",
            human_classification=HumanClassification.NAMED_PERSON_REQUIRED,
        )
        assert not result.passed
        assert any(e.code == "NAMED_PERSON_MISSING" for e in result.errors)

    def test_human_optional_allows_no_human(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["Bhagiratha"]},
            prompt="Bhagiratha ascended the Himalayan peaks, wide cinematic.",
            narration="Bhagiratha went to the Himalayan peaks.",
            human_classification=HumanClassification.HUMAN_OPTIONAL,
        )
        assert result.passed

    def test_emotional_beat_missing_no_longer_flagged(self):
        """Task 2.3 Fix 1: EMOTIONAL_BEAT_MISSING removed."""
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={"allowed_characters": ["eaglet"], "emotional_beat": "wonder"},
            prompt="A young eaglet tests its wings on a cliff edge, wide cinematic.",
            narration="The eaglet tests its wings.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert not any(e.code == "EMOTIONAL_BEAT_MISSING" for e in result.errors)


# ── SymbolismValidator ────────────────────────────────────────────────────────


class TestSymbolismValidator:
    def test_flags_symbolic_replacement_not_in_narration(self):
        validator = SymbolismValidator()
        result = validator.validate(
            narration="The mother eagle encourages the chick to fly.",
            prompt="An old man points toward the horizon.",
        )
        assert not result.passed
        assert any(e.code == "SYMBOLIC_REPLACEMENT" for e in result.errors)

    def test_allows_symbolic_term_when_in_narration(self):
        validator = SymbolismValidator()
        result = validator.validate(
            narration="A silhouette of a man stood against the sky.",
            prompt="A silhouette of a man against the sky.",
        )
        assert result.passed


# ── RealismValidator ──────────────────────────────────────────────────────────


class TestRealismValidator:
    def test_flags_unrealistic_proportions(self):
        validator = RealismValidator()
        result = validator.validate(
            prompt="A tiny person the size of a mouse, cinematic wide shot."
        )
        assert not result.passed
        assert any(e.code == "UNREALISTIC_PROPORTIONS" for e in result.errors)

    def test_flags_giant_bird(self):
        validator = RealismValidator()
        result = validator.validate(
            prompt="A giant eagle with wings spanning the valley, cinematic wide shot."
        )
        assert not result.passed
        assert any(e.code == "UNREALISTIC_BIRD_SIZE" for e in result.errors)

    def test_flags_impossible_perspective(self):
        validator = RealismValidator()
        result = validator.validate(
            prompt="Camera view from inside the eagle, cinematic wide shot."
        )
        assert not result.passed
        assert any(e.code == "UNREALISTIC_PERSPECTIVE" for e in result.errors)

    def test_passes_realistic_prompt(self):
        validator = RealismValidator()
        result = validator.validate(
            prompt="A young eaglet tests its wings on a cliff edge, golden hour light, medium shot."
        )
        assert result.passed


# ── run_validators integration ────────────────────────────────────────────────


class TestRunValidators:
    def test_combined_pass(self):
        result = run_validators(
            scene_analysis={"allowed_characters": ["eaglet"], "primary_subject": "eaglet", "primary_action": "testing wings", "emotional_beat": "wonder", "environment": "cliff"},
            prompt="A young eaglet tests its wings on a cliff edge, golden hour light, wonder, wide cinematic.",
            narration="The eaglet tests its wings.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert result.passed

    def test_combined_failure(self):
        result = run_validators(
            scene_analysis={"allowed_characters": ["eaglet"]},
            prompt="A lean man stands at the edge of a cliff.",
            narration="The eaglet tests its wings.",
            human_classification=HumanClassification.NO_HUMAN_ALLOWED,
        )
        assert not result.passed


# ── New SceneAnalysis fields ──────────────────────────────────────────────────


class TestNewSceneAnalysisFields:
    def test_forbidden_character_detected(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={
                "allowed_characters": ["Mother Eagle", "Eagle Chick"],
                "scene_characters": ["Mother Eagle", "Eagle Chick"],
                "forbidden_characters": ["man", "woman", "child"],
            },
            prompt="A mother eagle watches over her chick on the nest, wide cinematic.",
            narration="The mother eagle encourages the chick to fly.",
        )
        assert result.passed

    def test_forbidden_object_detected(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={
                "allowed_characters": ["eaglet"],
                "forbidden_objects": ["candle"],
            },
            prompt="A candle flickers next to the eaglet on the cliff, wide cinematic.",
            narration="The eaglet tests its wings on the cliff.",
        )
        assert not result.passed
        assert any(e.code == "FORBIDDEN_OBJECT" for e in result.errors)

    def test_visual_focus_present(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={
                "allowed_characters": ["eaglet"],
                "visual_focus": "eaglet's wings",
            },
            prompt="Close-up on the eaglet's wings as they catch the updraft, golden hour.",
            narration="The eaglet tests its wings.",
        )
        assert result.passed

    def test_visual_focus_missing_no_longer_flagged(self):
        """Task 2.3 Fix 1: VISUAL_FOCUS_MISSING removed."""
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={
                "allowed_characters": ["eaglet"],
                "visual_focus": "eaglet's wings",
            },
            prompt="A vast cliff face at sunset, wide cinematic.",
            narration="The eaglet tests its wings.",
        )
        assert not any(e.code == "VISUAL_FOCUS_MISSING" for e in result.errors)

    def test_story_time_present(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={
                "allowed_characters": ["eaglet"],
                "story_time": "golden hour",
            },
            prompt="A young eaglet tests its wings at golden hour, wide cinematic.",
            narration="The eaglet tests its wings.",
        )
        assert result.passed

    def test_story_time_missing_no_longer_flagged(self):
        """Task 2.6 Fix 1B: STORY_TIME_MISSING removed — never part of any
        spec, and a semantic check the model can't reliably satisfy literally."""
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={
                "allowed_characters": ["eaglet"],
                "story_time": "golden hour",
            },
            prompt="A young eaglet tests its wings in the grey light of dawn, wide cinematic.",
            narration="The eaglet tests its wings.",
        )
        assert not any(e.code == "STORY_TIME_MISSING" for e in result.errors)

    def test_camera_constraints_respected(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={
                "allowed_characters": ["eaglet"],
                "camera_constraints": "wide shot, no close-up",
            },
            prompt="A young eaglet tests its wings on a cliff, wide shot, establishing shot.",
            narration="The eaglet tests its wings.",
        )
        assert result.passed

    def test_camera_constraints_violated(self):
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={
                "allowed_characters": ["eaglet"],
                "camera_constraints": "wide shot, no close-up",
            },
            prompt="Close-up of the eaglet's eye, intimate portrait.",
            narration="The eaglet tests its wings.",
        )
        assert not result.passed
        assert any(e.code == "CAMERA_CONSTRAINT_VIOLATED" for e in result.errors)

    def test_story_goal_missing_no_longer_flagged(self):
        """Task 2.3 Fix 1: STORY_GOAL_MISSING removed."""
        validator = StoryFidelityValidator()
        result = validator.validate(
            scene_analysis={
                "allowed_characters": ["eaglet"],
                "story_goal": "first step toward independence",
            },
            prompt="The eaglet tests its wings on a cliff, wide cinematic.",
            narration="The eaglet tests its wings.",
        )
        assert not any(e.code == "STORY_GOAL_MISSING" for e in result.errors)


# ── RetryCoordinator ──────────────────────────────────────────────────────────


class TestRetryCoordinator:
    def test_build_retry_request_contains_reasons(self):
        result = ValidationResult(
            passed=False,
            errors=[
                ValidationError(
                    code="UNSUPPORTED_CHARACTER",
                    message="Unsupported character detected: 'man'.",
                    severity="critical",
                    allowed_values=["Mother Eagle", "Eagle Chick"],
                ),
            ],
        )
        block = RetryCoordinator.build_retry_request(
            scene_index=5,
            scene_analysis={
                "allowed_characters": ["Mother Eagle", "Eagle Chick"],
                "primary_action": "chick attempting first flight",
            },
            narration="The mother eagle encourages the chick.",
            validation_result=result,
        )
        assert "FAILED" in block
        assert "UNSUPPORTED_CHARACTER" in block
        assert "Allowed:" in block
        assert "Mother Eagle" in block
        assert "Eagle Chick" in block
        assert "chick attempting first flight" in block
        assert "Return ONLY corrected JSON for this scene." in block

    def test_scene_needs_retry_true(self):
        result = ValidationResult(passed=False, errors=[])
        assert RetryCoordinator.scene_needs_retry(result) is True

    def test_scene_needs_retry_false(self):
        result = ValidationResult(passed=True, errors=[])
        assert RetryCoordinator.scene_needs_retry(result) is False
