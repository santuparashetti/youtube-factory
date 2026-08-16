"""Tests for the YouTube Shorts Phase 1A pipeline.

All LLM calls are mocked. No live API calls.
WORKSPACE_DIR is patched in each consuming module.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.shorts.models import (
    CrossShortQAResult,
    LongFormBridge,
    OpportunityExtractionResult,
    ShortOpportunity,
    ShortsImageManifest,
    ShortsImageManifestItem,
    ShortsScene,
    ShortsScenePlan,
    ShortsScript,
    ShortsScriptQAReport,
    ValidationReport,
    ValidationScores,
    VideoResolution,
)
from ytfactory.shorts.repository import ShortsRepository


# ── Fixtures ────────────────────────────────────────────────────────────────

def _make_opportunity(
    opportunity_id: str = "opportunity-a",
    angle: str = "paradox",
    hook_strength: float = 8.0,
    source_sections: list[str] | None = None,
    primary_mechanism: str = "story",
    primary_evidence: str = "pebble_gathering_story",
) -> ShortOpportunity:
    return ShortOpportunity(
        opportunity_id=opportunity_id,
        angle=angle,
        surprising_idea="The mind keeps wanting more even after getting everything.",
        emotional_tension="Recognition of something deeply familiar.",
        curiosity_potential="Why does more never feel like enough?",
        connection_to_long_video="Central mechanism of the parent video.",
        unresolved_question="Why does the finish line keep moving?",
        estimated_hook_strength=hook_strength,
        source_sections=source_sections or ["Section A"],
        primary_mechanism=primary_mechanism,  # type: ignore[arg-type]
        primary_evidence=primary_evidence,
    )


def _make_script(
    short_id: str = "short-001",
    parent_video_id: str = "test-project",
    validation_passed: bool = True,
    word_count: int = 110,
    open_loop: str = "But why does the mind keep wanting more even after it gets everything?",
    scores: ValidationScores | None = None,
    hook: str | None = None,
    setup: str | None = None,
    story: str | None = None,
    revelation: str | None = None,
) -> ShortsScript:
    hook = hook or "Imagine waking up tomorrow with everything you ever wanted."
    setup = setup or "More money. More freedom. More success."
    story = story or "Here is the strange part. Research and ancient philosophy point to the same uncomfortable truth."
    revelation = revelation or "The problem is not that you do not have enough. It is that the mind keeps moving the finish line."
    full = "\n\n".join([hook, setup, story, revelation, open_loop])
    bridge = LongFormBridge(
        source_video=parent_video_id,
        relationship="opens_question",
        bridge_type="open_question",
        unresolved_question="Why does the finish line keep moving?",
        continuation_value="The full video explains the mechanism.",
    )
    return ShortsScript(
        short_id=short_id,
        parent_video_id=parent_video_id,
        angle="paradox",
        source_opportunity_id="opportunity-a",
        title="Why More Never Feels Like Enough",
        hook=hook,
        setup=setup,
        story=story,
        revelation=revelation,
        open_loop=open_loop,
        full_script=full,
        long_form_bridge=bridge,
        target_duration_seconds=52.0,
        estimated_word_count=word_count,
        validation_passed=validation_passed,
        scores=scores,
    )


def _make_scores(**overrides) -> ValidationScores:
    defaults = {
        "hook_strength": 8.0,
        "retention_potential": 7.5,
        "clarity": 9.0,
        "emotional_intensity": 7.0,
        "philosophical_depth": 7.0,
        "standalone_value": 7.0,
        "curiosity_gap": 8.5,
        "long_form_bridge": 8.0,
        "spoiler_risk": 2.0,
        "naturalness": 8.0,
        "specificity": 7.5,
        "generic_ai_language": 1.0,
        "advertising_feel": 0.5,
        "cliche_density": 1.0,
        "overall": 7.5,
    }
    defaults.update(overrides)
    return ValidationScores(**defaults)


def _make_scene_plan(short_id: str = "short-001", scene_count: int = 7) -> ShortsScenePlan:
    scenes = [
        ShortsScene(
            index=i,
            section="hook" if i == 0 else ("open_loop" if i == scene_count - 1 else "story"),
            narration=f"Narration for scene {i}.",
            visual_prompt=f"VERTICAL PORTRAIT COMPOSITION visual prompt {i}",
            duration_seconds=4.5,
            is_hook_scene=(i == 0),
            first_frame_priority="maximum" if i == 0 else "normal",
            shot_type="portrait_close_up" if i == 0 else "portrait_medium",
        )
        for i in range(scene_count)
    ]
    return ShortsScenePlan(
        short_id=short_id,
        parent_video_id="test-project",
        aspect_ratio="9:16",
        resolution=VideoResolution(width=1080, height=1920),
        target_duration_seconds=52.0,
        total_estimated_duration=sum(s.duration_seconds for s in scenes),
        scene_count=scene_count,
        scenes=scenes,
        visual_hook_description="A person waking to perfect surroundings, expression shifting to emptiness.",
        provenance={
            "parent_video": "test-project",
            "short_id": short_id,
            "source_opportunity": "opportunity-a",
        },
    )


# ── Repository tests ─────────────────────────────────────────────────────────

class TestShortsRepository:
    def test_repository_save_and_load_opportunities_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))
        repo = ShortsRepository()
        opp = _make_opportunity()
        result = OpportunityExtractionResult(
            parent_video_id="test-project",
            parent_video_title="Test Video",
            parent_core_thesis="A thesis.",
            opportunities=[opp],
            selected=["opportunity-a"],
            extraction_rationale="Best opportunity.",
        )
        repo.save_opportunities("test-project", result)
        loaded = repo.load_opportunities("test-project")
        assert loaded is not None
        assert loaded.parent_video_id == "test-project"
        assert loaded.selected == ["opportunity-a"]
        assert len(loaded.opportunities) == 1

    def test_repository_save_and_load_script_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))
        repo = ShortsRepository()
        script = _make_script()
        repo.save_script("test-project", "short-001", script)
        loaded = repo.load_script("test-project", "short-001")
        assert loaded is not None
        assert loaded.short_id == "short-001"
        assert loaded.parent_video_id == "test-project"
        assert loaded.angle == "paradox"

    def test_repository_save_and_load_validation_report_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))
        repo = ShortsRepository()
        report = ValidationReport(
            short_id="short-001",
            validation_passed=True,
            attempts=1,
            regenerated=False,
            rule_checks={"word_count_passed": True},
            scores=_make_scores(),
            failure_reasons=[],
        )
        repo.save_validation_report("test-project", "short-001", report)
        loaded = repo.load_validation_report("test-project", "short-001")
        assert loaded is not None
        assert loaded.validation_passed is True
        assert loaded.scores is not None
        assert loaded.scores.hook_strength == 8.0

    def test_repository_save_and_load_scene_plan_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))
        repo = ShortsRepository()
        plan = _make_scene_plan()
        repo.save_scene_plan("test-project", "short-001", plan)
        loaded = repo.load_scene_plan("test-project", "short-001")
        assert loaded is not None
        assert loaded.short_id == "short-001"
        assert loaded.aspect_ratio == "9:16"
        assert loaded.resolution.width == 1080
        assert loaded.scene_count == 7

    def test_repository_save_and_load_image_manifest_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))
        repo = ShortsRepository()
        manifest = ShortsImageManifest(
            short_id="short-001",
            parent_video_id="test-project",
            aspect_ratio="9:16",
            resolution=VideoResolution(width=1080, height=1920),
            ready_for_image_generation=True,
            images=[
                ShortsImageManifestItem(scene_index=0, filename="scene-000.png", prompt="VERTICAL ..."),
            ],
        )
        repo.save_image_manifest("test-project", "short-001", manifest)
        loaded = repo.load_image_manifest("test-project", "short-001")
        assert loaded is not None
        assert loaded.ready_for_image_generation is True
        assert loaded.images[0].filename == "scene-000.png"

    def test_repository_short_dir_resolves_from_workspace(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))
        repo = ShortsRepository()
        d = repo.short_dir("test-project", "short-001")
        assert str(tmp_path) in str(d)
        assert "shorts" in str(d)
        assert "short-001" in str(d)


# ── Opportunity Extractor tests ───────────────────────────────────────────────

class TestShortOpportunityExtractor:
    def _mock_llm_response(self, opportunities: list[dict]) -> MagicMock:
        response = MagicMock()
        response.text = json.dumps({
            "parent_video_title": "Test Video",
            "parent_core_thesis": "A core thesis.",
            "opportunities": opportunities,
            "extraction_rationale": "These are compelling.",
        })
        return response

    def test_extract_returns_two_selected_opportunities(self, tmp_path, monkeypatch):
        from ytfactory.shorts.extractor import ShortOpportunityExtractor
        from ytfactory.config.settings import Settings

        opps = [
            {"opportunity_id": "opportunity-a", "angle": "paradox", "surprising_idea": "X",
             "emotional_tension": "Y", "curiosity_potential": "Z", "connection_to_long_video": "W",
             "unresolved_question": "Q1?", "estimated_hook_strength": 8.5, "source_sections": ["Sec A"]},
            {"opportunity_id": "opportunity-b", "angle": "story", "surprising_idea": "X2",
             "emotional_tension": "Y2", "curiosity_potential": "Z2", "connection_to_long_video": "W2",
             "unresolved_question": "Q2?", "estimated_hook_strength": 7.0, "source_sections": ["Sec B"]},
            {"opportunity_id": "opportunity-c", "angle": "counterintuitive", "surprising_idea": "X3",
             "emotional_tension": "Y3", "curiosity_potential": "Z3", "connection_to_long_video": "W3",
             "unresolved_question": "Q3?", "estimated_hook_strength": 6.5, "source_sections": ["Sec C"]},
        ]
        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_llm_response(opps)

        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm):
            extractor = ShortOpportunityExtractor(Settings())
            result = extractor.extract("A long script.", "Test Video", "test-project")

        assert len(result.selected) == 2

    def test_extract_selects_diverse_angles(self, tmp_path, monkeypatch):
        from ytfactory.shorts.extractor import ShortOpportunityExtractor
        from ytfactory.config.settings import Settings

        opps = [
            {"opportunity_id": "opportunity-a", "angle": "paradox", "surprising_idea": "X",
             "emotional_tension": "Y", "curiosity_potential": "Z", "connection_to_long_video": "W",
             "unresolved_question": "Q?", "estimated_hook_strength": 9.0, "source_sections": ["Sec A"]},
            {"opportunity_id": "opportunity-b", "angle": "story", "surprising_idea": "X2",
             "emotional_tension": "Y2", "curiosity_potential": "Z2", "connection_to_long_video": "W2",
             "unresolved_question": "Q2?", "estimated_hook_strength": 8.0, "source_sections": ["Sec B"]},
        ]
        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_llm_response(opps)

        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm):
            extractor = ShortOpportunityExtractor(Settings())
            result = extractor.extract("A long script.", "Test Video", "test-project")

        opp_map = {o.opportunity_id: o for o in result.opportunities}
        selected_angles = [opp_map[s].angle for s in result.selected]
        assert len(set(selected_angles)) == 2, "Selected opportunities must have different angles"

    def test_extract_warns_when_angles_are_same(self, tmp_path, capsys):
        from ytfactory.shorts.extractor import ShortOpportunityExtractor
        from ytfactory.config.settings import Settings

        opps = [
            {"opportunity_id": "opportunity-a", "angle": "paradox", "surprising_idea": "X",
             "emotional_tension": "Y", "curiosity_potential": "Z", "connection_to_long_video": "W",
             "unresolved_question": "Q?", "estimated_hook_strength": 9.0, "source_sections": ["Sec A"]},
            {"opportunity_id": "opportunity-b", "angle": "paradox", "surprising_idea": "X2",
             "emotional_tension": "Y2", "curiosity_potential": "Z2", "connection_to_long_video": "W2",
             "unresolved_question": "Q2?", "estimated_hook_strength": 8.0, "source_sections": ["Sec B"]},
        ]
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "parent_video_title": "Test", "parent_core_thesis": "Thesis",
            "opportunities": opps, "extraction_rationale": "..."
        })
        mock_llm = MagicMock()
        mock_llm.generate.return_value = mock_response

        warning_messages: list[str] = []
        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm):
            with patch("ytfactory.shorts.extractor.logger") as mock_logger:
                mock_logger.warning.side_effect = lambda msg, *a, **kw: warning_messages.append(msg)
                extractor = ShortOpportunityExtractor(Settings())
                result = extractor.extract("Script.", "Title", "proj")

        assert len(result.selected) == 2
        assert any("angle" in m.lower() for m in warning_messages)

    def test_extract_selection_is_deterministic(self):
        from ytfactory.shorts.extractor import _select_two

        opps = [
            _make_opportunity("opp-a", "paradox", 9.0, ["Sec A"]),
            _make_opportunity("opp-b", "story", 8.0, ["Sec B"]),
            _make_opportunity("opp-c", "question", 7.5, ["Sec C"]),
        ]
        result1 = _select_two(opps)
        result2 = _select_two(opps)
        assert result1 == result2

    def test_extract_prefers_different_source_sections(self):
        from ytfactory.shorts.extractor import _select_two

        opps = [
            _make_opportunity("opp-a", "paradox", 9.0, ["Sec A"]),
            _make_opportunity("opp-b", "story", 8.5, ["Sec A"]),  # same section
            _make_opportunity("opp-c", "story", 8.0, ["Sec B"]),  # different section
        ]
        selected = _select_two(opps)
        assert "opp-a" in selected
        # opp-c preferred over opp-b because it comes from a different source section
        assert "opp-c" in selected


# ── Script Generator tests ───────────────────────────────────────────────────

class TestShortScriptGenerator:
    def _mock_llm_for_generator(self, word_count_target: int = 110) -> MagicMock:
        # Build a response with enough words
        words = "word " * (word_count_target // 5)
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "title": "Test Short Title",
            "hook": words,
            "setup": words,
            "story": words,
            "revelation": words,
            "open_loop": words,
            "long_form_bridge": {
                "relationship": "opens_question",
                "bridge_type": "open_question",
                "unresolved_question": "Why?",
                "continuation_value": "The full video explains.",
            },
        })
        return mock_response

    def test_generate_assembles_full_script_from_sections(self):
        from ytfactory.shorts.generator import ShortScriptGenerator
        from ytfactory.config.settings import Settings

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "title": "Title",
            "hook": "Hook text.",
            "setup": "Setup text.",
            "story": "Story text.",
            "revelation": "Revelation text.",
            "open_loop": "Open loop text.",
            "long_form_bridge": {
                "relationship": "opens_question",
                "bridge_type": "open_question",
                "unresolved_question": "Q?",
                "continuation_value": "CV.",
            },
        })
        mock_llm = MagicMock()
        mock_llm.generate.return_value = mock_response

        with patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm):
            gen = ShortScriptGenerator(Settings())
            script = gen.generate(
                _make_opportunity(), "Title", "Script content", "proj", 1
            )

        assert "Hook text." in script.full_script
        assert "Setup text." in script.full_script
        assert "Story text." in script.full_script
        assert "Revelation text." in script.full_script
        assert "Open loop text." in script.full_script

    def test_generate_does_not_depend_on_llm_full_script(self):
        from ytfactory.shorts.generator import ShortScriptGenerator
        from ytfactory.config.settings import Settings

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "title": "Title",
            "hook": "A.",
            "setup": "B.",
            "story": "C.",
            "revelation": "D.",
            "open_loop": "E.",
            "full_script": "This should be ignored by Python.",
            "long_form_bridge": {
                "relationship": "opens_question",
                "bridge_type": "open_question",
                "unresolved_question": "Q?",
                "continuation_value": "CV.",
            },
        })
        mock_llm = MagicMock()
        mock_llm.generate.return_value = mock_response

        with patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm):
            gen = ShortScriptGenerator(Settings())
            script = gen.generate(_make_opportunity(), "Title", "Script", "proj", 1)

        # full_script should be assembled from sections, not from LLM's full_script field
        assert "This should be ignored" not in script.full_script
        assert "A." in script.full_script

    def test_generate_calculates_duration_from_word_count(self):
        from ytfactory.shorts.generator import ShortScriptGenerator
        from ytfactory.config.settings import Settings

        # exactly 26 words across five sections
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "title": "Title",
            "hook": "one two three four five",
            "setup": "six seven eight nine ten",
            "story": "eleven twelve thirteen fourteen fifteen",
            "revelation": "sixteen seventeen eighteen nineteen twenty",
            "open_loop": "twenty one twenty two twenty three twenty four",
            "long_form_bridge": {
                "relationship": "opens_question",
                "bridge_type": "open_question",
                "unresolved_question": "Q?",
                "continuation_value": "CV.",
            },
        })
        mock_llm = MagicMock()
        mock_llm.generate.return_value = mock_response

        settings = Settings()
        with patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm):
            gen = ShortScriptGenerator(settings)
            script = gen.generate(_make_opportunity(), "Title", "Script", "proj", 1)

        expected_duration = (script.estimated_word_count / settings.shorts_narration_wpm) * 60
        assert abs(expected_duration - (script.estimated_word_count / 130) * 60) < 0.01

    def test_generate_duration_within_60_seconds(self):
        from ytfactory.shorts.generator import ShortScriptGenerator
        from ytfactory.config.settings import Settings

        # 120 words exactly (hard max)
        words_per_section = "word " * 24  # 24 × 5 = 120
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "title": "Title",
            "hook": words_per_section,
            "setup": words_per_section,
            "story": words_per_section,
            "revelation": words_per_section,
            "open_loop": words_per_section,
            "long_form_bridge": {
                "relationship": "opens_question",
                "bridge_type": "open_question",
                "unresolved_question": "Q?",
                "continuation_value": "CV.",
            },
        })
        mock_llm = MagicMock()
        mock_llm.generate.return_value = mock_response

        settings = Settings()
        with patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm):
            gen = ShortScriptGenerator(settings)
            script = gen.generate(_make_opportunity(), "Title", "Script", "proj", 1)

        duration = (script.estimated_word_count / settings.shorts_narration_wpm) * 60
        assert duration <= settings.shorts_max_duration_seconds

    def test_generate_preserves_provenance(self):
        from ytfactory.shorts.generator import ShortScriptGenerator
        from ytfactory.config.settings import Settings

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "title": "Title",
            "hook": "A.", "setup": "B.", "story": "C.", "revelation": "D.", "open_loop": "E.",
            "long_form_bridge": {
                "relationship": "opens_question", "bridge_type": "open_question",
                "unresolved_question": "Q?", "continuation_value": "CV.",
            },
        })
        mock_llm = MagicMock()
        mock_llm.generate.return_value = mock_response
        opp = _make_opportunity("opportunity-x")

        with patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm):
            gen = ShortScriptGenerator(Settings())
            script = gen.generate(opp, "Title", "Script", "my-project", 2)

        assert script.short_id == "short-002"
        assert script.parent_video_id == "my-project"
        assert script.source_opportunity_id == "opportunity-x"
        assert script.long_form_bridge.source_video == "my-project"


# ── Validator tests ───────────────────────────────────────────────────────────

class TestShortScriptValidator:
    def test_validate_passes_good_script(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        good_scores = _make_scores()
        mock_response = MagicMock()
        mock_response.text = json.dumps(good_scores.model_dump())
        mock_llm = MagicMock()
        mock_llm.generate.return_value = mock_response

        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            script = _make_script(word_count=110)
            updated, report = v.validate(script, "short-001")

        assert report.validation_passed is True
        assert updated.validation_passed is True
        assert report.scores is not None

    def test_validate_fails_on_low_hook_strength(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        bad_scores = _make_scores(hook_strength=3.0)
        mock_response = MagicMock()
        mock_response.text = json.dumps(bad_scores.model_dump())
        mock_llm = MagicMock()
        mock_llm.generate.return_value = mock_response

        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            script = _make_script(word_count=110)
            _, report = v.validate(script, "short-001")

        assert report.validation_passed is False
        assert any("hook_strength" in r for r in report.failure_reasons)

    def test_validate_fails_on_high_spoiler_risk(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        bad_scores = _make_scores(spoiler_risk=8.5)
        mock_response = MagicMock()
        mock_response.text = json.dumps(bad_scores.model_dump())
        mock_llm = MagicMock()
        mock_llm.generate.return_value = mock_response

        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            script = _make_script(word_count=110)
            _, report = v.validate(script, "short-001")

        assert report.validation_passed is False
        assert any("spoiler_risk" in r for r in report.failure_reasons)

    def test_validate_fails_on_watch_full_video_phrase(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        mock_llm = MagicMock()
        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            script = _make_script(
                word_count=110,
                open_loop="Watch the full video to find out more.",
            )
            _, report = v.validate(script, "short-001")

        assert report.validation_passed is False
        assert any("banned" in r.lower() for r in report.failure_reasons)
        # LLM should NOT have been called
        mock_llm.generate.assert_not_called()

    def test_validate_fails_on_subscribe_phrase(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        mock_llm = MagicMock()
        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            script = _make_script(
                word_count=110,
                open_loop="Subscribe for more philosophical content.",
            )
            _, report = v.validate(script, "short-001")

        assert report.validation_passed is False
        mock_llm.generate.assert_not_called()

    def test_validate_fails_on_excessive_word_count(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        mock_llm = MagicMock()
        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            script = _make_script(word_count=135)  # over 120 hard max
            _, report = v.validate(script, "short-001")

        assert report.validation_passed is False
        assert any("word_count" in r for r in report.failure_reasons)
        mock_llm.generate.assert_not_called()

    def test_validate_fails_on_too_short_word_count(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        mock_llm = MagicMock()
        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            script = _make_script(word_count=80)  # under 90 minimum
            _, report = v.validate(script, "short-001")

        assert report.validation_passed is False
        assert any("word_count" in r or "minimum" in r for r in report.failure_reasons)
        mock_llm.generate.assert_not_called()

    def test_validate_skips_llm_if_rule_check_fails(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        mock_llm = MagicMock()
        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            script = _make_script(word_count=200)  # way over limit
            _, report = v.validate(script, "short-001")

        assert report.scores is None
        mock_llm.generate.assert_not_called()


# ── Scene Planner tests ───────────────────────────────────────────────────────

class TestShortsScenePlanner:
    def _mock_planner_response(self, scene_count: int = 7) -> MagicMock:
        scenes = []
        for i in range(scene_count):
            section = "hook" if i == 0 else ("open_loop" if i == scene_count - 1 else "story")
            narration = "word " * 10  # 10 words per scene
            scenes.append({
                "index": i,
                "section": section,
                "narration": narration.strip(),
                "visual_prompt": f"Portrait visual {i}",
                "duration_seconds": 4.5,  # this will be overridden by word-count calculation
                "is_hook_scene": (i == 0),
                "first_frame_priority": "maximum" if i == 0 else "normal",
                "shot_type": "portrait_close_up" if i == 0 else "portrait_medium",
            })
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "visual_hook_description": "A striking first frame.",
            "scenes": scenes,
        })
        return mock_response

    def test_plan_produces_5_to_9_scenes(self):
        from ytfactory.shorts.scene_planner import ShortsScenePlanner
        from ytfactory.config.settings import Settings

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_planner_response(7)

        with patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm):
            planner = ShortsScenePlanner(Settings())
            plan = planner.plan(_make_script())

        assert 5 <= plan.scene_count <= 9

    def test_plan_scene_0_is_hook(self):
        from ytfactory.shorts.scene_planner import ShortsScenePlanner
        from ytfactory.config.settings import Settings

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_planner_response(6)

        with patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm):
            planner = ShortsScenePlanner(Settings())
            plan = planner.plan(_make_script())

        assert plan.scenes[0].is_hook_scene is True
        assert plan.scenes[0].first_frame_priority == "maximum"

    def test_plan_last_scene_is_open_loop(self):
        from ytfactory.shorts.scene_planner import ShortsScenePlanner
        from ytfactory.config.settings import Settings

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_planner_response(6)

        with patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm):
            planner = ShortsScenePlanner(Settings())
            plan = planner.plan(_make_script())

        assert plan.scenes[-1].section == "open_loop"

    def test_plan_durations_derived_from_word_count(self):
        from ytfactory.shorts.scene_planner import _compute_duration

        narration = "one two three four five six seven eight nine ten"  # 10 words
        duration = _compute_duration(narration, wpm=130)
        expected = (10 / 130) * 60
        assert abs(duration - expected) < 0.01

    def test_plan_durations_are_not_hardcoded(self):
        from ytfactory.shorts.scene_planner import ShortsScenePlanner
        from ytfactory.config.settings import Settings

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_planner_response(5)

        with patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm):
            planner = ShortsScenePlanner(Settings())
            plan = planner.plan(_make_script())

        # All scene durations must match the word-count formula
        wpm = Settings().shorts_narration_wpm
        for scene in plan.scenes:
            expected = round((len(scene.narration.split()) / wpm) * 60, 2)
            assert scene.duration_seconds == expected, (
                f"Scene {scene.index} duration {scene.duration_seconds} "
                f"does not match word-count formula {expected}"
            )

    def test_plan_is_9x16(self):
        from ytfactory.shorts.scene_planner import ShortsScenePlanner
        from ytfactory.config.settings import Settings

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_planner_response(5)

        with patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm):
            planner = ShortsScenePlanner(Settings())
            plan = planner.plan(_make_script())

        assert plan.aspect_ratio == "9:16"
        assert plan.resolution.width == 1080
        assert plan.resolution.height == 1920

    def test_plan_contains_visual_hook_description(self):
        from ytfactory.shorts.scene_planner import ShortsScenePlanner
        from ytfactory.config.settings import Settings

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_planner_response(5)

        with patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm):
            planner = ShortsScenePlanner(Settings())
            plan = planner.plan(_make_script())

        assert plan.visual_hook_description != ""

    def test_plan_preserves_provenance(self):
        from ytfactory.shorts.scene_planner import ShortsScenePlanner
        from ytfactory.config.settings import Settings

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_planner_response(5)

        with patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm):
            planner = ShortsScenePlanner(Settings())
            plan = planner.plan(_make_script())

        assert plan.provenance.get("parent_video") == "test-project"
        assert plan.provenance.get("short_id") == "short-001"

    def test_plan_does_not_include_motion_type(self):
        from ytfactory.shorts.models import ShortsScene
        # Phase 1A spec explicitly excludes motion_type from ShortsScene
        fields = ShortsScene.model_fields
        assert "motion_type" not in fields


# ── Image Prompt Engine tests ─────────────────────────────────────────────────

class TestShortsImagePromptEngine:
    def test_image_prompts_prepend_vertical_preamble(self, tmp_path, monkeypatch):
        from ytfactory.shorts.image_prompts import ShortsImagePromptEngine, _VERTICAL_PREAMBLE

        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))
        engine = ShortsImagePromptEngine()
        plan = _make_scene_plan()
        manifest = engine.generate(plan, "test-project", "short-001")
        for item in manifest.images:
            assert _VERTICAL_PREAMBLE in item.prompt

    def test_image_prompts_hook_scene_gets_extra_preamble(self, tmp_path, monkeypatch):
        from ytfactory.shorts.image_prompts import ShortsImagePromptEngine, _HOOK_PREAMBLE

        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))
        engine = ShortsImagePromptEngine()
        plan = _make_scene_plan()
        manifest = engine.generate(plan, "test-project", "short-001")
        hook_item = next(i for i in manifest.images if i.scene_index == 0)
        assert _HOOK_PREAMBLE in hook_item.prompt

    def test_image_prompts_creates_images_dir(self, tmp_path, monkeypatch):
        from ytfactory.shorts.image_prompts import ShortsImagePromptEngine

        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))
        engine = ShortsImagePromptEngine()
        plan = _make_scene_plan()
        engine.generate(plan, "test-project", "short-001")
        images_dir = tmp_path / "test-project" / "shorts" / "short-001" / "images"
        assert images_dir.exists()

    def test_image_prompts_writes_manifest_json(self, tmp_path, monkeypatch):
        from ytfactory.shorts.image_prompts import ShortsImagePromptEngine

        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))
        engine = ShortsImagePromptEngine()
        plan = _make_scene_plan()
        engine.generate(plan, "test-project", "short-001")
        manifest_path = (
            tmp_path / "test-project" / "shorts" / "short-001" / "images" / "image-prompts.json"
        )
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["ready_for_image_generation"] is True

    def test_image_prompts_all_prompts_are_vertical(self, tmp_path, monkeypatch):
        from ytfactory.shorts.image_prompts import ShortsImagePromptEngine

        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))
        engine = ShortsImagePromptEngine()
        plan = _make_scene_plan()
        manifest = engine.generate(plan, "test-project", "short-001")
        for item in manifest.images:
            assert "9:16" in item.prompt or "VERTICAL" in item.prompt

    def test_image_prompts_expected_filenames(self, tmp_path, monkeypatch):
        from ytfactory.shorts.image_prompts import ShortsImagePromptEngine

        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))
        engine = ShortsImagePromptEngine()
        plan = _make_scene_plan(scene_count=5)
        manifest = engine.generate(plan, "test-project", "short-001")
        filenames = [item.filename for item in manifest.images]
        assert filenames == [f"scene-{i:03d}.png" for i in range(5)]


# ── Pipeline tests ────────────────────────────────────────────────────────────

class TestShortsPipeline:
    def _setup_workspace(self, tmp_path: Path, project_id: str = "test-project") -> Path:
        """Create the minimum workspace structure for pipeline tests."""
        script_dir = tmp_path / project_id / "script"
        script_dir.mkdir(parents=True)
        script_path = script_dir / "script.md"
        script_path.write_text(
            "# Test Script\n\nThis is a test long-form script with enough content "
            "to generate two compelling philosophical YouTube Shorts.",
            encoding="utf-8",
        )
        return tmp_path

    def _mock_project(self, project_id: str = "test-project"):
        from unittest.mock import MagicMock
        project = MagicMock()
        project.id = project_id
        project.title = "Test Video"
        return project

    def test_pipeline_requires_script_md_exists(self, tmp_path, monkeypatch):
        from ytfactory.shorts.pipeline import ShortsPipeline
        from ytfactory.config.settings import Settings

        monkeypatch.setattr("ytfactory.shorts.pipeline.WORKSPACE_DIR", str(tmp_path))
        mock_projects = MagicMock()
        mock_projects.load.return_value = self._mock_project()

        mock_llm = MagicMock()
        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.pipeline.ProjectRepository", return_value=mock_projects):
            pipeline = ShortsPipeline(Settings())
            with pytest.raises(FileNotFoundError):
                pipeline.run("test-project")

    def test_pipeline_creates_expected_folder_structure(self, tmp_path, monkeypatch):
        from ytfactory.shorts.pipeline import ShortsPipeline
        from ytfactory.config.settings import Settings

        self._setup_workspace(tmp_path)
        monkeypatch.setattr("ytfactory.shorts.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))

        good_scores = _make_scores()
        opp_data = {
            "parent_video_title": "Test Video",
            "parent_core_thesis": "A thesis.",
            "opportunities": [
                {"opportunity_id": "opportunity-a", "angle": "paradox", "surprising_idea": "X",
                 "emotional_tension": "Y", "curiosity_potential": "Z", "connection_to_long_video": "W",
                 "unresolved_question": "Q?", "estimated_hook_strength": 9.0, "source_sections": ["A"]},
                {"opportunity_id": "opportunity-b", "angle": "story", "surprising_idea": "X2",
                 "emotional_tension": "Y2", "curiosity_potential": "Z2", "connection_to_long_video": "W2",
                 "unresolved_question": "Q2?", "estimated_hook_strength": 8.0, "source_sections": ["B"]},
            ],
            "extraction_rationale": "Good.",
        }
        script_data = {
            "title": "Title", "hook": "A.", "setup": "B.", "story": "C.",
            "revelation": "D.", "open_loop": "E.",
            "long_form_bridge": {
                "relationship": "opens_question", "bridge_type": "open_question",
                "unresolved_question": "Q?", "continuation_value": "CV.",
            },
        }
        # Build a 110-word script response
        words = " ".join(["word"] * 22)
        script_data_110 = {**script_data,
                           "hook": words, "setup": words, "story": words,
                           "revelation": words, "open_loop": words}
        plan_data = {
            "visual_hook_description": "Hook frame.",
            "scenes": [
                {"index": i, "section": "hook" if i == 0 else ("open_loop" if i == 6 else "story"),
                 "narration": "word word word word word", "visual_prompt": "Portrait visual.",
                 "duration_seconds": 2.3, "is_hook_scene": (i == 0),
                 "first_frame_priority": "maximum" if i == 0 else "normal",
                 "shot_type": "portrait_close_up" if i == 0 else "portrait_medium"}
                for i in range(7)
            ],
        }

        cross_no_problem = {
            "similarity_problem": False, "overlap_reason": "none",
            "failed_dimensions": [], "preserve_sections": [],
            "rewrite_sections": [], "specific_instruction": "",
        }
        mock_llm = MagicMock()
        # New pipeline order: S2(001) → S2b(001) → S2(002) → S2b(002) → cross-QA → S3(001) → S3(002)
        mock_llm.generate.side_effect = [
            MagicMock(text=json.dumps(opp_data)),                    # S1
            MagicMock(text=json.dumps(script_data_110)),             # S2 short-001
            MagicMock(text=json.dumps(good_scores.model_dump())),    # S2b scoring short-001
            MagicMock(text=json.dumps(script_data_110)),             # S2 short-002
            MagicMock(text=json.dumps(good_scores.model_dump())),    # S2b scoring short-002
            MagicMock(text=json.dumps(cross_no_problem)),            # cross-short QA
            MagicMock(text=json.dumps(plan_data)),                   # S3 short-001
            MagicMock(text=json.dumps(plan_data)),                   # S3 short-002
        ]

        mock_projects = MagicMock()
        mock_projects.load.return_value = self._mock_project()

        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.pipeline.ProjectRepository", return_value=mock_projects):
            pipeline = ShortsPipeline(Settings())
            pipeline.run("test-project")

        shorts_dir = tmp_path / "test-project" / "shorts"
        assert (shorts_dir / "opportunities.json").exists()
        assert (shorts_dir / "short-001").is_dir()
        assert (shorts_dir / "short-002").is_dir()

    def test_pipeline_run_idempotent_when_artifacts_exist(self, tmp_path, monkeypatch):
        from ytfactory.shorts.pipeline import ShortsPipeline
        from ytfactory.config.settings import Settings

        self._setup_workspace(tmp_path)
        monkeypatch.setattr("ytfactory.shorts.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))

        # Pre-populate opportunities.json
        repo = ShortsRepository()
        opp = _make_opportunity()
        opp2 = _make_opportunity("opportunity-b", "story", 8.0, ["Sec B"])
        extraction = OpportunityExtractionResult(
            parent_video_id="test-project",
            parent_video_title="Test Video",
            parent_core_thesis="Thesis.",
            opportunities=[opp, opp2],
            selected=["opportunity-a", "opportunity-b"],
            extraction_rationale="Good.",
        )
        repo.save_opportunities("test-project", extraction)

        # Pre-populate scripts
        script1 = _make_script("short-001", word_count=110)
        script2 = _make_script("short-002", word_count=112)
        repo.save_script("test-project", "short-001", script1)
        repo.save_script("test-project", "short-002", script2)

        # Pre-populate validation reports
        report = ValidationReport(
            short_id="short-001", validation_passed=True, attempts=1,
            regenerated=False, rule_checks={"word_count_passed": True},
            scores=_make_scores(), failure_reasons=[],
        )
        repo.save_validation_report("test-project", "short-001", report)
        report2 = report.model_copy(update={"short_id": "short-002"})
        repo.save_validation_report("test-project", "short-002", report2)

        # Pre-populate scene plans
        plan = _make_scene_plan("short-001")
        plan2 = _make_scene_plan("short-002")
        repo.save_scene_plan("test-project", "short-001", plan)
        repo.save_scene_plan("test-project", "short-002", plan2)

        # Pre-populate image manifests
        manifest = ShortsImageManifest(
            short_id="short-001", parent_video_id="test-project",
            aspect_ratio="9:16", resolution=VideoResolution(width=1080, height=1920),
            ready_for_image_generation=True, images=[],
        )
        repo.save_image_manifest("test-project", "short-001", manifest)
        manifest2 = manifest.model_copy(update={"short_id": "short-002"})
        repo.save_image_manifest("test-project", "short-002", manifest2)

        mock_llm = MagicMock()
        mock_projects = MagicMock()
        mock_projects.load.return_value = self._mock_project()

        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.pipeline.ProjectRepository", return_value=mock_projects):
            pipeline = ShortsPipeline(Settings())
            pipeline.run("test-project", force=False)

        # No LLM calls should have been made — all artifacts exist
        mock_llm.generate.assert_not_called()

    def test_pipeline_continues_short_002_if_short_001_validation_fails(
        self, tmp_path, monkeypatch
    ):
        from ytfactory.shorts.pipeline import ShortsPipeline
        from ytfactory.config.settings import Settings

        self._setup_workspace(tmp_path)
        monkeypatch.setattr("ytfactory.shorts.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))

        # Pre-populate opportunities with two options
        repo = ShortsRepository()
        opp1 = _make_opportunity("opportunity-a", "paradox", 9.0)
        opp2 = _make_opportunity("opportunity-b", "story", 8.0, ["Sec B"])
        extraction = OpportunityExtractionResult(
            parent_video_id="test-project",
            parent_video_title="Test Video",
            parent_core_thesis="Thesis.",
            opportunities=[opp1, opp2],
            selected=["opportunity-a", "opportunity-b"],
            extraction_rationale="Good.",
        )
        repo.save_opportunities("test-project", extraction)

        # Script data with 110 words (within limits)
        words = " ".join(["word"] * 22)
        script_data = {
            "title": "Title", "hook": words, "setup": words, "story": words,
            "revelation": words, "open_loop": words,
            "long_form_bridge": {
                "relationship": "opens_question", "bridge_type": "open_question",
                "unresolved_question": "Q?", "continuation_value": "CV.",
            },
        }

        # Fail short-001 but pass short-002
        failing_scores = _make_scores(hook_strength=2.0, overall=3.0)
        passing_scores = _make_scores()
        plan_data = {
            "visual_hook_description": "Hook frame.",
            "scenes": [
                {"index": i, "section": "hook" if i == 0 else ("open_loop" if i == 4 else "story"),
                 "narration": "word word word word word", "visual_prompt": "Portrait visual.",
                 "duration_seconds": 2.3, "is_hook_scene": (i == 0),
                 "first_frame_priority": "maximum" if i == 0 else "normal",
                 "shot_type": "portrait_close_up" if i == 0 else "portrait_medium"}
                for i in range(5)
            ],
        }

        # New pipeline: recomposition instead of regeneration
        # short-001: S2 → S2b(FAIL) → recompose → re-QA(FAIL) → skip S3
        # short-002: S2 → S2b(PASS) → (no cross-QA since 001 failed) → S3
        recomposed_sections = {
            "hook": "Rewritten hook.", "setup": script_data["setup"],
            "story": script_data["story"], "revelation": script_data["revelation"],
            "open_loop": script_data["open_loop"],
        }
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = [
            MagicMock(text=json.dumps(script_data)),                      # S2 short-001
            MagicMock(text=json.dumps(failing_scores.model_dump())),      # S2b short-001 → FAIL
            MagicMock(text=json.dumps(recomposed_sections)),              # recomposer
            MagicMock(text=json.dumps(failing_scores.model_dump())),      # re-QA → still FAIL
            MagicMock(text=json.dumps(script_data)),                      # S2 short-002
            MagicMock(text=json.dumps(passing_scores.model_dump())),      # S2b short-002 → PASS
            MagicMock(text=json.dumps(plan_data)),                        # S3 short-002
        ]

        mock_projects = MagicMock()
        mock_projects.load.return_value = self._mock_project()

        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.pipeline.ProjectRepository", return_value=mock_projects):
            pipeline = ShortsPipeline(Settings())
            pipeline.run("test-project")

        # short-001 should exist (script saved even if failed)
        s1_script = repo.load_script("test-project", "short-001")
        assert s1_script is not None
        assert s1_script.validation_passed is False

        # short-002 should have a scene plan (it passed)
        s2_plan = repo.load_scene_plan("test-project", "short-002")
        assert s2_plan is not None

        # short-001 should NOT have a scene plan (failed validation)
        s1_plan = repo.load_scene_plan("test-project", "short-001")
        assert s1_plan is None

    def test_pipeline_does_not_scene_plan_failed_short(self, tmp_path, monkeypatch):
        """A failed short must not proceed to S3/S4."""
        from ytfactory.shorts.pipeline import ShortsPipeline
        from ytfactory.config.settings import Settings

        self._setup_workspace(tmp_path)
        monkeypatch.setattr("ytfactory.shorts.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))

        # Pre-populate one opportunity
        repo = ShortsRepository()
        opp = _make_opportunity()
        opp2 = _make_opportunity("opportunity-b", "story")
        extraction = OpportunityExtractionResult(
            parent_video_id="test-project",
            parent_video_title="Test",
            parent_core_thesis="Thesis.",
            opportunities=[opp, opp2],
            selected=["opportunity-a", "opportunity-b"],
            extraction_rationale="Good.",
        )
        repo.save_opportunities("test-project", extraction)

        words = " ".join(["word"] * 22)
        script_data = {
            "title": "Title", "hook": words, "setup": words, "story": words,
            "revelation": words, "open_loop": words,
            "long_form_bridge": {
                "relationship": "opens_question", "bridge_type": "open_question",
                "unresolved_question": "Q?", "continuation_value": "CV.",
            },
        }
        fail_scores = _make_scores(hook_strength=1.0, overall=2.0)
        pass_scores = _make_scores()
        plan_data = {
            "visual_hook_description": "Hook.",
            "scenes": [
                {"index": i, "section": "hook" if i == 0 else "story",
                 "narration": "word word word", "visual_prompt": "Portrait.",
                 "duration_seconds": 1.4, "is_hook_scene": (i == 0),
                 "first_frame_priority": "maximum" if i == 0 else "normal",
                 "shot_type": "portrait_medium"}
                for i in range(5)
            ],
        }

        recomposed_sections = {
            "hook": "Rewritten hook.", "setup": words, "story": words,
            "revelation": words, "open_loop": words,
        }
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = [
            MagicMock(text=json.dumps(script_data)),                   # S2 short-001
            MagicMock(text=json.dumps(fail_scores.model_dump())),      # S2b → FAIL
            MagicMock(text=json.dumps(recomposed_sections)),           # recomposer
            MagicMock(text=json.dumps(fail_scores.model_dump())),      # re-QA → FAIL
            MagicMock(text=json.dumps(script_data)),                   # S2 short-002
            MagicMock(text=json.dumps(pass_scores.model_dump())),      # S2b short-002 → PASS
            MagicMock(text=json.dumps(plan_data)),                     # S3 short-002
        ]

        mock_projects = MagicMock()
        mock_projects.load.return_value = self._mock_project()

        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.pipeline.ProjectRepository", return_value=mock_projects):
            pipeline = ShortsPipeline(Settings())
            pipeline.run("test-project")

        assert not (tmp_path / "test-project" / "shorts" / "short-001" / "scene-plan.json").exists()
        assert not (tmp_path / "test-project" / "shorts" / "short-001" / "images").exists()


# ── Diversity selection tests ─────────────────────────────────────────────────

class TestOpportunityDiversitySelection:
    """Tests for pairwise diversity-aware selection in _select_two()."""

    def test_extract_selects_different_primary_mechanisms(self):
        from ytfactory.shorts.extractor import _select_two

        opps = [
            _make_opportunity("opp-a", "story", 8.5, ["Sec A"],
                              primary_mechanism="story", primary_evidence="pebble_story"),
            _make_opportunity("opp-b", "question", 8.0, ["Sec B"],
                              primary_mechanism="psychological_mechanism", primary_evidence="hedonic_treadmill"),
            _make_opportunity("opp-c", "paradox", 7.5, ["Sec C"],
                              primary_mechanism="story", primary_evidence="pebble_story"),
        ]
        selected = _select_two(opps)
        opp_map = {o.opportunity_id: o for o in opps}
        mechs = {opp_map[sid].primary_mechanism for sid in selected}
        assert len(mechs) == 2, "Selected pair must have different primary mechanisms"
        assert "opp-a" in selected  # highest hook
        assert "opp-b" in selected  # different mechanism

    def test_extract_penalizes_same_story_overlap(self):
        """The pebble-story + pebble-question pair should lose to pebble-story + chair-contrast."""
        from ytfactory.shorts.extractor import _select_two

        # A: story about pebbles (9.0)
        opp_a = _make_opportunity("opp-a", "story", 9.0, ["Sec A"],
                                  primary_mechanism="story", primary_evidence="pebble_gathering_story")
        # B: question angle, but STILL about pebbles — same evidence
        opp_b = _make_opportunity("opp-b", "question", 8.0, ["Sec A"],
                                  primary_mechanism="psychological_mechanism", primary_evidence="pebble_gathering_story")
        # C: contrast with genuinely different evidence
        opp_c = _make_opportunity("opp-c", "contrast", 7.5, ["Sec B"],
                                  primary_mechanism="contrast", primary_evidence="chair_comparison_example")
        selected = _select_two([opp_a, opp_b, opp_c])
        # A+C preferred over A+B because A+B share the same evidence
        assert "opp-a" in selected
        assert "opp-c" in selected, "Should prefer opp-c (different evidence) over opp-b (same evidence)"

    def test_extract_penalizes_same_primary_evidence(self):
        from ytfactory.shorts.extractor import _pair_score

        opp_same_ev_a = _make_opportunity("a", "story", 8.0, primary_evidence="pebble_gathering")
        opp_same_ev_b = _make_opportunity("b", "question", 8.0, primary_evidence="pebble_gathering")
        opp_diff_ev = _make_opportunity("c", "contrast", 7.5, primary_evidence="chair_comparison")

        score_same = _pair_score(opp_same_ev_a, opp_same_ev_b)
        score_diff = _pair_score(opp_same_ev_a, opp_diff_ev)
        assert score_diff > score_same, (
            f"Pair with different evidence ({score_diff:.2f}) should outscore "
            f"pair with same evidence ({score_same:.2f})"
        )

    def test_extract_prefers_story_and_psychological_mechanism(self):
        from ytfactory.shorts.extractor import _select_two

        opps = [
            _make_opportunity("opp-a", "story", 8.0, ["Sec A"],
                              primary_mechanism="story", primary_evidence="pebble_story"),
            _make_opportunity("opp-b", "question", 7.8, ["Sec B"],
                              primary_mechanism="psychological_mechanism", primary_evidence="hedonic_treadmill"),
            _make_opportunity("opp-c", "paradox", 7.9, ["Sec A"],
                              primary_mechanism="story", primary_evidence="pebble_story"),
        ]
        selected = _select_two(opps)
        # opp-a + opp-b preferred: story + psychological_mechanism pair
        assert "opp-a" in selected
        assert "opp-b" in selected

    def test_extract_does_not_force_diversity_when_second_opportunity_is_weak(self):
        """When the only alternative is below minimum quality, fall back to top-2."""
        from ytfactory.shorts.extractor import _select_two

        opps = [
            _make_opportunity("opp-a", "story", 8.5, primary_mechanism="story",
                              primary_evidence="pebble_story"),
            _make_opportunity("opp-b", "paradox", 8.0, primary_mechanism="paradox",
                              primary_evidence="same_evidence"),
            # third option has very different evidence but below minimum quality
            _make_opportunity("opp-c", "contrast", 2.0, primary_mechanism="contrast",
                              primary_evidence="chair_comparison"),
        ]
        selected = _select_two(opps)
        assert len(selected) == 2
        # opp-c (score 2.0) should NOT be selected despite evidence diversity
        assert "opp-c" not in selected

    def test_pair_score_mechanism_bonus(self):
        """Mechanism diversity bonus is 3.0 points."""
        from ytfactory.shorts.extractor import _pair_score

        a = _make_opportunity("a", "story", 8.0, primary_mechanism="story",
                              primary_evidence="unique_evidence_a")
        b_same_mech = _make_opportunity("b", "question", 7.0, primary_mechanism="story",
                                        primary_evidence="unique_evidence_b")
        # Use "contrast" — not in conceptual_mechs — to isolate just the mech_bonus (3.0)
        # without triggering the conceptual_pairing_bonus (1.5)
        b_diff_mech = _make_opportunity("c", "question", 7.0,
                                        primary_mechanism="contrast",
                                        primary_evidence="unique_evidence_b")

        score_same = _pair_score(a, b_same_mech)
        score_diff = _pair_score(a, b_diff_mech)
        assert score_diff - score_same == pytest.approx(3.0, abs=0.01)

    def test_selection_is_deterministic_with_new_fields(self):
        from ytfactory.shorts.extractor import _select_two

        opps = [
            _make_opportunity("a", "story", 9.0, primary_mechanism="story",
                              primary_evidence="pebble_story"),
            _make_opportunity("b", "question", 8.0, primary_mechanism="psychological_mechanism",
                              primary_evidence="hedonic_treadmill"),
            _make_opportunity("c", "contrast", 7.5, primary_mechanism="contrast",
                              primary_evidence="chair_comparison"),
        ]
        result1 = _select_two(opps)
        result2 = _select_two(opps)
        assert result1 == result2


# ── Individual QA tests ───────────────────────────────────────────────────────

class TestShortsScriptQA:
    """Tests for the 3-outcome QA system (PASS / PASS_WITH_WARNING / FAIL)."""

    def _make_good_scores_dict(self) -> dict:
        # overall=9.0 keeps it above the warning zone (threshold 6.5 + margin 1.5 = 8.0)
        return {
            "hook_strength": 8.0, "retention_potential": 7.5, "clarity": 9.0,
            "emotional_intensity": 7.0, "philosophical_depth": 8.0,
            "standalone_value": 7.5, "curiosity_gap": 8.0, "long_form_bridge": 8.0,
            "spoiler_risk": 2.0, "naturalness": 8.0, "specificity": 7.5,
            "generic_ai_language": 1.0, "advertising_feel": 0.5, "cliche_density": 1.0,
            "narrative_coherence": 8.0, "progression": 7.5, "ending_strength": 7.5,
            "overall": 9.0,
        }

    def _make_warn_scores_dict(self) -> dict:
        """Scores that are above hard threshold but within warning margin."""
        base = self._make_good_scores_dict()
        # hook_strength threshold is 5.0; warning is 5.0–6.5
        base["hook_strength"] = 5.8
        return base

    def _make_fail_scores_dict(self) -> dict:
        base = self._make_good_scores_dict()
        base["hook_strength"] = 3.0  # below threshold 5.0
        return base

    def test_short_qa_passes_strong_script(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        scores = self._make_good_scores_dict()
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(scores))

        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            _, _, qa = v.evaluate_with_qa(_make_script(word_count=110), "short-001")

        assert qa.status == "PASS"
        assert qa.failed_dimensions == []

    def test_short_qa_returns_warning_for_minor_issue(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        scores = self._make_warn_scores_dict()
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(scores))

        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            updated, report, qa = v.evaluate_with_qa(_make_script(word_count=110), "short-001")

        assert qa.status == "PASS_WITH_WARNING"
        assert "hook_strength" in qa.warning_dimensions
        # PASS_WITH_WARNING still counts as passed
        assert report.validation_passed is True
        assert updated.validation_passed is True

    def test_short_qa_fails_critical_issue(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        scores = self._make_fail_scores_dict()
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(scores))

        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            _, report, qa = v.evaluate_with_qa(_make_script(word_count=110), "short-001")

        assert qa.status == "FAIL"
        assert report.validation_passed is False

    def test_short_qa_identifies_specific_failed_dimensions(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        scores = self._make_good_scores_dict()
        scores["hook_strength"] = 2.0
        scores["naturalness"] = 3.0
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(scores))

        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            _, _, qa = v.evaluate_with_qa(_make_script(word_count=110), "short-001")

        assert "hook_strength" in qa.failed_dimensions
        assert "naturalness" in qa.failed_dimensions

    def test_short_qa_identifies_sections_to_preserve(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        # Only advertising_feel fails (open_loop problem)
        scores = self._make_good_scores_dict()
        scores["advertising_feel"] = 5.0  # above threshold 3.0
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(scores))

        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            _, _, qa = v.evaluate_with_qa(_make_script(word_count=110), "short-001")

        # open_loop should be in rewrite, hook should be in preserve
        assert "open_loop" in qa.rewrite_sections
        assert "hook" in qa.preserve_sections

    def test_short_qa_identifies_sections_to_rewrite(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        # hook_strength fails → hook should be in rewrite
        scores = self._make_good_scores_dict()
        scores["hook_strength"] = 2.0
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(scores))

        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            _, _, qa = v.evaluate_with_qa(_make_script(word_count=110), "short-001")

        assert "hook" in qa.rewrite_sections

    def test_short_qa_includes_new_scoring_dimensions(self):
        """ValidationScores now includes narrative_coherence, progression, ending_strength."""
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        scores = self._make_good_scores_dict()
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(scores))

        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            _, report, _ = v.evaluate_with_qa(_make_script(word_count=110), "short-001")

        assert report.scores is not None
        assert hasattr(report.scores, "narrative_coherence")
        assert hasattr(report.scores, "progression")
        assert hasattr(report.scores, "ending_strength")

    def test_pass_with_warning_does_not_trigger_recomposition_in_pipeline(
        self, tmp_path, monkeypatch
    ):
        """PASS_WITH_WARNING should go straight to S3, not recompose."""
        from ytfactory.shorts.pipeline import ShortsPipeline
        from ytfactory.config.settings import Settings

        _setup_workspace_simple(tmp_path)
        monkeypatch.setattr("ytfactory.shorts.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))

        repo = ShortsRepository()
        opp1 = _make_opportunity("opportunity-a", "paradox", 9.0, ["Sec A"],
                                 primary_mechanism="story", primary_evidence="pebble")
        opp2 = _make_opportunity("opportunity-b", "story", 8.0, ["Sec B"],
                                 primary_mechanism="psychological_mechanism", primary_evidence="hedonic")
        extraction = OpportunityExtractionResult(
            parent_video_id="test-project", parent_video_title="Test",
            parent_core_thesis="Thesis.", opportunities=[opp1, opp2],
            selected=["opportunity-a", "opportunity-b"], extraction_rationale="Good.",
        )
        repo.save_opportunities("test-project", extraction)

        warn_scores = {
            "hook_strength": 5.8,  # in warning zone (5.0–6.5)
            "retention_potential": 7.5, "clarity": 9.0, "emotional_intensity": 7.0,
            "philosophical_depth": 8.0, "standalone_value": 7.5, "curiosity_gap": 7.0,
            "long_form_bridge": 7.0, "spoiler_risk": 2.0, "naturalness": 8.0,
            "specificity": 7.5, "generic_ai_language": 1.0, "advertising_feel": 0.5,
            "cliche_density": 1.0, "narrative_coherence": 8.0, "progression": 7.5,
            "ending_strength": 7.5, "overall": 7.0,
        }
        pass_scores = {**warn_scores, "hook_strength": 8.0}
        words = " ".join(["word"] * 22)
        script_data = {
            "title": "Title", "hook": words, "setup": words, "story": words,
            "revelation": words, "open_loop": words,
            "long_form_bridge": {"relationship": "opens_question", "bridge_type": "open_question",
                                 "unresolved_question": "Q?", "continuation_value": "CV."},
        }
        plan_data = _make_plan_data()

        cross_result = {"similarity_problem": False, "overlap_reason": "none",
                        "failed_dimensions": [], "preserve_sections": [],
                        "rewrite_sections": [], "specific_instruction": ""}

        mock_llm = MagicMock()
        mock_llm.generate.side_effect = [
            MagicMock(text=json.dumps(script_data)),    # S2 short-001
            MagicMock(text=json.dumps(warn_scores)),    # S2b score short-001 (WARNING)
            MagicMock(text=json.dumps(script_data)),    # S2 short-002
            MagicMock(text=json.dumps(pass_scores)),    # S2b score short-002 (PASS)
            MagicMock(text=json.dumps(cross_result)),   # cross-short QA
            MagicMock(text=json.dumps(plan_data)),      # S3 short-001
            MagicMock(text=json.dumps(plan_data)),      # S3 short-002
        ]
        mock_projects = MagicMock()
        mock_projects.load.return_value = _mock_project()

        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.pipeline.ProjectRepository", return_value=mock_projects):
            ShortsPipeline(Settings()).run("test-project")

        # Both scene plans exist (no recomposition stale-artifact cleanup happened)
        assert (tmp_path / "test-project" / "shorts" / "short-001" / "scene-plan.json").exists()
        assert (tmp_path / "test-project" / "shorts" / "short-002" / "scene-plan.json").exists()


# ── Cross-short QA tests ──────────────────────────────────────────────────────

class TestCrossShortQA:
    """Tests for cross-Short similarity detection via evaluate_cross_short()."""

    def test_cross_short_qa_detects_same_story(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        script_a = _make_script("short-001", open_loop="Why does it keep moving?")
        script_b = _make_script("short-002", open_loop="But why does the pebble count keep rising?")

        mock_result = {
            "similarity_problem": True,
            "overlap_reason": "Both Shorts retell the pebble gathering story with the sage.",
            "failed_dimensions": ["same_story", "same_characters", "same_evidence"],
            "preserve_sections": ["hook", "revelation"],
            "rewrite_sections": ["story", "open_loop"],
            "specific_instruction": "Remove the pebble gathering narrative from short-002.",
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(mock_result))

        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            result = v.evaluate_cross_short(script_a, script_b)

        assert result.similarity_problem is True
        assert "pebble" in result.overlap_reason.lower() or result.overlap_reason

    def test_cross_short_qa_allows_different_mechanisms(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        script_a = _make_script("short-001")
        # script_b has same theme but different mechanism (no story overlap)
        script_b = _make_script("short-002",
            open_loop="But what makes the salary number feel wrong the moment you achieve it?")

        mock_result = {
            "similarity_problem": False,
            "overlap_reason": "none",
            "failed_dimensions": [],
            "preserve_sections": [],
            "rewrite_sections": [],
            "specific_instruction": "",
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(mock_result))

        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            result = v.evaluate_cross_short(script_a, script_b)

        assert result.similarity_problem is False

    def test_cross_short_qa_detects_same_evidence(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        # Both scripts explicitly reference the same evidence
        hook = "A wealthy man sat with a sage."
        script_a = _make_script("short-001")
        script_b = _make_script("short-002", open_loop="Why did the sage only add one more pebble?")

        mock_result = {
            "similarity_problem": True,
            "overlap_reason": "Both use the sage/pebble story as primary evidence.",
            "failed_dimensions": ["same_evidence", "same_characters"],
            "preserve_sections": ["hook", "setup"],
            "rewrite_sections": ["story", "revelation", "open_loop"],
            "specific_instruction": "Use a different example that avoids the sage and pebbles.",
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(mock_result))

        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            result = v.evaluate_cross_short(script_a, script_b)

        assert result.similarity_problem is True
        assert "story" in result.rewrite_sections

    def test_cross_short_qa_does_not_penalize_shared_theme_alone(self):
        """Sharing the same broad theme is acceptable — the LLM decides."""
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        script_a = _make_script("short-001")
        # script_b shares theme "more never feels like enough" but uses different mechanism
        script_b = _make_script("short-002",
            story="Psychologists call this the hedonic treadmill. When income doubles, "
                  "satisfaction rises briefly, then returns to baseline. "
                  "The number changes but the feeling does not.")

        mock_result = {
            "similarity_problem": False,
            "overlap_reason": "Shared theme of desire/satisfaction but different mechanism and evidence.",
            "failed_dimensions": [],
            "preserve_sections": [],
            "rewrite_sections": [],
            "specific_instruction": "",
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(mock_result))

        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            result = v.evaluate_cross_short(script_a, script_b)

        assert result.similarity_problem is False

    def test_cross_short_qa_gracefully_handles_llm_parse_error(self):
        from ytfactory.shorts.validator import ShortScriptValidator
        from ytfactory.config.settings import Settings

        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text="this is not json {{{")

        with patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm):
            v = ShortScriptValidator(Settings())
            result = v.evaluate_cross_short(_make_script("short-001"), _make_script("short-002"))

        # Should not raise — should return no similarity
        assert result.similarity_problem is False


# ── Recomposer tests ──────────────────────────────────────────────────────────

class TestShortScriptRecomposer:
    def _make_qa_report(
        self,
        status: str = "FAIL",
        failed: list[str] | None = None,
        preserve: list[str] | None = None,
        rewrite: list[str] | None = None,
        instruction: str = "Fix the failing dimensions.",
    ) -> ShortsScriptQAReport:
        return ShortsScriptQAReport(
            short_id="short-001",
            status=status,  # type: ignore[arg-type]
            failed_dimensions=failed if failed is not None else ["hook_strength"],
            warning_dimensions=[],
            preserve_sections=preserve if preserve is not None else ["setup", "story", "revelation"],
            rewrite_sections=rewrite if rewrite is not None else ["hook", "open_loop"],
            specific_instruction=instruction,
        )

    def test_recomposer_preserves_strong_sections(self):
        from ytfactory.shorts.recomposer import ShortScriptRecomposer
        from ytfactory.config.settings import Settings

        original = _make_script()
        qa = self._make_qa_report(preserve=["setup", "story", "revelation"], rewrite=["hook", "open_loop"])

        llm_response = {
            "hook": "REWRITTEN HOOK HERE.",
            "setup": "SHOULD BE IGNORED — preserve applies",
            "story": "SHOULD BE IGNORED — preserve applies",
            "revelation": "SHOULD BE IGNORED — preserve applies",
            "open_loop": "REWRITTEN OPEN LOOP HERE.",
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(llm_response))

        with patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm):
            r = ShortScriptRecomposer(Settings())
            result = r.recompose(original, qa, [], "parent script")

        # Preserved sections must be verbatim from original
        assert result.setup == original.setup
        assert result.story == original.story
        assert result.revelation == original.revelation
        # Rewritten sections come from LLM
        assert result.hook == "REWRITTEN HOOK HERE."
        assert result.open_loop == "REWRITTEN OPEN LOOP HERE."

    def test_recomposer_rewrites_only_requested_sections(self):
        from ytfactory.shorts.recomposer import ShortScriptRecomposer
        from ytfactory.config.settings import Settings

        original = _make_script()
        qa = self._make_qa_report(preserve=["hook", "setup", "story", "revelation"],
                                   rewrite=["open_loop"])

        llm_response = {
            "hook": "Different hook text",
            "setup": "Different setup text",
            "story": "Different story text",
            "revelation": "Different revelation text",
            "open_loop": "NEW OPEN LOOP.",
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(llm_response))

        with patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm):
            r = ShortScriptRecomposer(Settings())
            result = r.recompose(original, qa, [], "parent")

        assert result.hook == original.hook
        assert result.setup == original.setup
        assert result.story == original.story
        assert result.revelation == original.revelation
        assert result.open_loop == "NEW OPEN LOOP."

    def test_recomposer_reassembles_full_script_in_python(self):
        from ytfactory.shorts.recomposer import ShortScriptRecomposer
        from ytfactory.config.settings import Settings

        original = _make_script()
        qa = self._make_qa_report(preserve=[], rewrite=["hook", "setup", "story", "revelation", "open_loop"])

        llm_response = {
            "hook": "Hook.",
            "setup": "Setup.",
            "story": "Story.",
            "revelation": "Revelation.",
            "open_loop": "Open loop.",
            "full_script": "LLM FULL SCRIPT THAT MUST BE IGNORED",
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(llm_response))

        with patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm):
            r = ShortScriptRecomposer(Settings())
            result = r.recompose(original, qa, [], "parent")

        # full_script must be assembled from sections, not from LLM
        assert "LLM FULL SCRIPT THAT MUST BE IGNORED" not in result.full_script
        expected = "\n\n".join(["Hook.", "Setup.", "Story.", "Revelation.", "Open loop."])
        assert result.full_script == expected

    def test_recomposer_recalculates_word_count(self):
        from ytfactory.shorts.recomposer import ShortScriptRecomposer
        from ytfactory.config.settings import Settings

        original = _make_script()
        qa = self._make_qa_report(preserve=[], rewrite=["hook", "setup", "story", "revelation", "open_loop"])

        new_hook = "one two three"
        new_setup = "four five six"
        new_story = "seven eight nine"
        new_revelation = "ten eleven twelve"
        new_open_loop = "thirteen fourteen"
        total_words = 14  # 3+3+3+3+2

        llm_response = {
            "hook": new_hook, "setup": new_setup, "story": new_story,
            "revelation": new_revelation, "open_loop": new_open_loop,
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(llm_response))

        with patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm):
            r = ShortScriptRecomposer(Settings())
            result = r.recompose(original, qa, [], "parent")

        assert result.estimated_word_count == total_words

    def test_recomposer_recalculates_duration(self):
        from ytfactory.shorts.recomposer import ShortScriptRecomposer
        from ytfactory.config.settings import Settings

        settings = Settings()
        original = _make_script()
        qa = self._make_qa_report(preserve=[], rewrite=["hook", "setup", "story", "revelation", "open_loop"])

        # exactly 13 words
        llm_response = {
            "hook": "one two three", "setup": "four five six",
            "story": "seven eight nine", "revelation": "ten eleven",
            "open_loop": "twelve thirteen",
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(llm_response))

        with patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm):
            r = ShortScriptRecomposer(settings)
            result = r.recompose(original, qa, [], "parent")

        expected_duration = (13 / settings.shorts_narration_wpm) * 60
        assert abs(result.target_duration_seconds - expected_duration) < 0.01

    def test_recomposer_output_validation_passed_is_false(self):
        """Recomposer never sets validation_passed — that is the validator's job."""
        from ytfactory.shorts.recomposer import ShortScriptRecomposer
        from ytfactory.config.settings import Settings

        original = _make_script(validation_passed=True)
        qa = self._make_qa_report(rewrite=["open_loop"])

        llm_response = {
            "hook": original.hook, "setup": original.setup, "story": original.story,
            "revelation": original.revelation, "open_loop": "New open loop.",
        }
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(text=json.dumps(llm_response))

        with patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm):
            r = ShortScriptRecomposer(Settings())
            result = r.recompose(original, qa, [], "parent")

        # Must be False — re-validation by validator is caller's responsibility
        assert result.validation_passed is False

    def test_recomposer_returns_original_if_no_rewrite_sections(self):
        from ytfactory.shorts.recomposer import ShortScriptRecomposer
        from ytfactory.config.settings import Settings

        original = _make_script()
        qa = self._make_qa_report(rewrite=[])  # nothing to rewrite

        mock_llm = MagicMock()

        with patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm):
            r = ShortScriptRecomposer(Settings())
            result = r.recompose(original, qa, [], "parent")

        # Should return original unchanged, no LLM call needed
        assert result.full_script == original.full_script
        mock_llm.generate.assert_not_called()


# ── Extended pipeline tests ───────────────────────────────────────────────────

def _setup_workspace_simple(tmp_path: Path, project_id: str = "test-project") -> Path:
    """Helper: create minimum workspace."""
    script_dir = tmp_path / project_id / "script"
    script_dir.mkdir(parents=True)
    (script_dir / "script.md").write_text(
        "# Test Script\n\nA philosophical long-form script.", encoding="utf-8"
    )
    return tmp_path


def _mock_project(project_id: str = "test-project"):
    p = MagicMock()
    p.id = project_id
    p.title = "Test Video"
    return p


def _make_plan_data(scene_count: int = 5) -> dict:
    return {
        "visual_hook_description": "Hook frame.",
        "scenes": [
            {
                "index": i,
                "section": "hook" if i == 0 else ("open_loop" if i == scene_count - 1 else "story"),
                "narration": "word word word word word",
                "visual_prompt": "Portrait visual.",
                "duration_seconds": 2.3,
                "is_hook_scene": (i == 0),
                "first_frame_priority": "maximum" if i == 0 else "normal",
                "shot_type": "portrait_close_up" if i == 0 else "portrait_medium",
            }
            for i in range(scene_count)
        ],
    }


class TestShortsPipelineExtended:

    def _script_data(self, word_count: int = 110) -> dict:
        n = word_count // 5
        words = " ".join(["word"] * n)
        return {
            "title": "Title",
            "hook": words, "setup": words, "story": words,
            "revelation": words, "open_loop": words,
            "long_form_bridge": {
                "relationship": "opens_question", "bridge_type": "open_question",
                "unresolved_question": "Q?", "continuation_value": "CV.",
            },
        }

    def _good_scores(self) -> dict:
        return {
            "hook_strength": 8.0, "retention_potential": 7.5, "clarity": 9.0,
            "emotional_intensity": 7.0, "philosophical_depth": 8.0,
            "standalone_value": 7.5, "curiosity_gap": 8.0, "long_form_bridge": 8.0,
            "spoiler_risk": 2.0, "naturalness": 8.0, "specificity": 7.5,
            "generic_ai_language": 1.0, "advertising_feel": 0.5, "cliche_density": 1.0,
            "narrative_coherence": 8.0, "progression": 7.5, "ending_strength": 7.5,
            "overall": 7.5,
        }

    def _fail_scores(self) -> dict:
        s = self._good_scores()
        s["hook_strength"] = 2.0
        s["overall"] = 3.0
        return s

    def _cross_no_problem(self) -> dict:
        return {
            "similarity_problem": False, "overlap_reason": "none",
            "failed_dimensions": [], "preserve_sections": [],
            "rewrite_sections": [], "specific_instruction": "",
        }

    def _cross_problem(self) -> dict:
        return {
            "similarity_problem": True,
            "overlap_reason": "Both use the same pebble gathering story.",
            "failed_dimensions": ["same_story"],
            "preserve_sections": ["hook", "revelation"],
            "rewrite_sections": ["story", "open_loop"],
            "specific_instruction": "Replace pebble story with a different example.",
        }

    def test_pipeline_recomposes_failed_short(self, tmp_path, monkeypatch):
        """A short that fails individual QA should be recomposed, not regenerated."""
        from ytfactory.shorts.pipeline import ShortsPipeline
        from ytfactory.config.settings import Settings

        _setup_workspace_simple(tmp_path)
        monkeypatch.setattr("ytfactory.shorts.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))

        repo = ShortsRepository()
        opp1 = _make_opportunity("opportunity-a", "paradox", 9.0, ["A"],
                                 primary_mechanism="story", primary_evidence="pebble")
        opp2 = _make_opportunity("opportunity-b", "story", 8.0, ["B"],
                                 primary_mechanism="psychological_mechanism", primary_evidence="hedonic")
        extraction = OpportunityExtractionResult(
            parent_video_id="test-project", parent_video_title="Test",
            parent_core_thesis="Thesis.", opportunities=[opp1, opp2],
            selected=["opportunity-a", "opportunity-b"], extraction_rationale="Good.",
        )
        repo.save_opportunities("test-project", extraction)

        sd = self._script_data()
        good = self._good_scores()
        fail = self._fail_scores()
        recomposed_sections = {
            "hook": "REWRITTEN HOOK.", "setup": sd["setup"],
            "story": sd["story"], "revelation": sd["revelation"],
            "open_loop": sd["open_loop"],
        }
        plan = _make_plan_data()
        no_problem = self._cross_no_problem()

        mock_llm = MagicMock()
        mock_llm.generate.side_effect = [
            MagicMock(text=json.dumps(sd)),             # S2 short-001
            MagicMock(text=json.dumps(fail)),           # S2b score short-001 → FAIL
            MagicMock(text=json.dumps(recomposed_sections)),  # recomposer output
            MagicMock(text=json.dumps(good)),           # re-QA → PASS
            MagicMock(text=json.dumps(sd)),             # S2 short-002
            MagicMock(text=json.dumps(good)),           # S2b score short-002 → PASS
            MagicMock(text=json.dumps(no_problem)),     # cross-short QA
            MagicMock(text=json.dumps(plan)),           # S3 short-001
            MagicMock(text=json.dumps(plan)),           # S3 short-002
        ]
        mock_projects = MagicMock()
        mock_projects.load.return_value = _mock_project()

        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.pipeline.ProjectRepository", return_value=mock_projects):
            ShortsPipeline(Settings()).run("test-project")

        # Both shorts should have scene plans (recomposition succeeded)
        assert (tmp_path / "test-project" / "shorts" / "short-001" / "scene-plan.json").exists()
        assert (tmp_path / "test-project" / "shorts" / "short-002" / "scene-plan.json").exists()

        # Validation report must record that recomposition happened
        report_001 = repo.load_validation_report("test-project", "short-001")
        assert report_001 is not None
        assert report_001.recomposed is True

    def test_pipeline_sends_passed_short_directly_to_s3(self, tmp_path, monkeypatch):
        """A short that passes QA on first attempt must not call the recomposer."""
        from ytfactory.shorts.pipeline import ShortsPipeline
        from ytfactory.config.settings import Settings

        _setup_workspace_simple(tmp_path)
        monkeypatch.setattr("ytfactory.shorts.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))

        repo = ShortsRepository()
        opp1 = _make_opportunity("opportunity-a", "paradox", 9.0, ["A"],
                                 primary_mechanism="story", primary_evidence="pebble")
        opp2 = _make_opportunity("opportunity-b", "story", 8.0, ["B"],
                                 primary_mechanism="psychological_mechanism", primary_evidence="hedonic")
        extraction = OpportunityExtractionResult(
            parent_video_id="test-project", parent_video_title="Test",
            parent_core_thesis="Thesis.", opportunities=[opp1, opp2],
            selected=["opportunity-a", "opportunity-b"], extraction_rationale="Good.",
        )
        repo.save_opportunities("test-project", extraction)

        sd = self._script_data()
        good = self._good_scores()
        plan = _make_plan_data()
        no_problem = self._cross_no_problem()

        mock_llm = MagicMock()
        mock_llm.generate.side_effect = [
            MagicMock(text=json.dumps(sd)),        # S2 short-001
            MagicMock(text=json.dumps(good)),      # S2b score → PASS
            MagicMock(text=json.dumps(sd)),        # S2 short-002
            MagicMock(text=json.dumps(good)),      # S2b score → PASS
            MagicMock(text=json.dumps(no_problem)),# cross-short QA
            MagicMock(text=json.dumps(plan)),      # S3 short-001
            MagicMock(text=json.dumps(plan)),      # S3 short-002
        ]
        mock_projects = MagicMock()
        mock_projects.load.return_value = _mock_project()
        recomposer_mock = MagicMock()

        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=recomposer_mock), \
             patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.pipeline.ProjectRepository", return_value=mock_projects):
            ShortsPipeline(Settings()).run("test-project")

        # Recomposer LLM should NOT have been called
        recomposer_mock.generate.assert_not_called()

    def test_pipeline_continues_other_short_after_recomposition_failure(
        self, tmp_path, monkeypatch
    ):
        """If short-001 fails even after recomposition, short-002 must still be processed."""
        from ytfactory.shorts.pipeline import ShortsPipeline
        from ytfactory.config.settings import Settings

        _setup_workspace_simple(tmp_path)
        monkeypatch.setattr("ytfactory.shorts.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))

        repo = ShortsRepository()
        opp1 = _make_opportunity("opportunity-a", "paradox", 9.0, ["A"],
                                 primary_mechanism="story", primary_evidence="pebble")
        opp2 = _make_opportunity("opportunity-b", "story", 8.0, ["B"],
                                 primary_mechanism="psychological_mechanism", primary_evidence="hedonic")
        extraction = OpportunityExtractionResult(
            parent_video_id="test-project", parent_video_title="Test",
            parent_core_thesis="Thesis.", opportunities=[opp1, opp2],
            selected=["opportunity-a", "opportunity-b"], extraction_rationale="Good.",
        )
        repo.save_opportunities("test-project", extraction)

        sd = self._script_data()
        good = self._good_scores()
        fail = self._fail_scores()
        plan = _make_plan_data()
        no_problem = self._cross_no_problem()

        # short-001 fails and recomposition also fails
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = [
            MagicMock(text=json.dumps(sd)),        # S2 short-001
            MagicMock(text=json.dumps(fail)),      # S2b score → FAIL
            MagicMock(text=json.dumps(sd)),        # recomposer output
            MagicMock(text=json.dumps(fail)),      # re-QA → still FAIL
            MagicMock(text=json.dumps(sd)),        # S2 short-002
            MagicMock(text=json.dumps(good)),      # S2b score short-002 → PASS
            # No cross-short QA (short-001 failed, only short-002 passed)
            MagicMock(text=json.dumps(plan)),      # S3 short-002
        ]
        mock_projects = MagicMock()
        mock_projects.load.return_value = _mock_project()

        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.pipeline.ProjectRepository", return_value=mock_projects):
            ShortsPipeline(Settings()).run("test-project")

        # short-001: no scene plan (failed)
        assert not (tmp_path / "test-project" / "shorts" / "short-001" / "scene-plan.json").exists()
        # short-002: has scene plan (passed)
        assert (tmp_path / "test-project" / "shorts" / "short-002" / "scene-plan.json").exists()

    def test_pipeline_does_not_run_s3_after_final_qa_failure(self, tmp_path, monkeypatch):
        """A short that fails final QA (after recomposition) must NOT proceed to S3."""
        from ytfactory.shorts.pipeline import ShortsPipeline
        from ytfactory.config.settings import Settings

        _setup_workspace_simple(tmp_path)
        monkeypatch.setattr("ytfactory.shorts.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))

        repo = ShortsRepository()
        opp1 = _make_opportunity("opportunity-a", "paradox", 9.0, ["A"],
                                 primary_mechanism="story", primary_evidence="pebble")
        opp2 = _make_opportunity("opportunity-b", "story", 8.0, ["B"],
                                 primary_mechanism="psychological_mechanism", primary_evidence="hedonic")
        extraction = OpportunityExtractionResult(
            parent_video_id="test-project", parent_video_title="Test",
            parent_core_thesis="Thesis.", opportunities=[opp1, opp2],
            selected=["opportunity-a", "opportunity-b"], extraction_rationale="Good.",
        )
        repo.save_opportunities("test-project", extraction)

        sd = self._script_data()
        good = self._good_scores()
        fail = self._fail_scores()
        plan = _make_plan_data()
        no_problem = self._cross_no_problem()

        mock_llm = MagicMock()
        mock_llm.generate.side_effect = [
            MagicMock(text=json.dumps(sd)),    # S2 short-001
            MagicMock(text=json.dumps(fail)),  # S2b → FAIL
            MagicMock(text=json.dumps(sd)),    # recomposer
            MagicMock(text=json.dumps(fail)),  # re-QA → FAIL (final)
            MagicMock(text=json.dumps(sd)),    # S2 short-002
            MagicMock(text=json.dumps(good)),  # S2b → PASS
            MagicMock(text=json.dumps(plan)),  # S3 short-002 (only)
        ]
        mock_projects = MagicMock()
        mock_projects.load.return_value = _mock_project()

        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.pipeline.ProjectRepository", return_value=mock_projects):
            ShortsPipeline(Settings()).run("test-project")

        assert not (tmp_path / "test-project" / "shorts" / "short-001" / "scene-plan.json").exists()

    def test_pipeline_cross_short_qa_runs_before_s3(self, tmp_path, monkeypatch):
        """Cross-short QA should run before S3 when both scripts pass individually."""
        from ytfactory.shorts.pipeline import ShortsPipeline
        from ytfactory.config.settings import Settings

        _setup_workspace_simple(tmp_path)
        monkeypatch.setattr("ytfactory.shorts.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))

        repo = ShortsRepository()
        opp1 = _make_opportunity("opportunity-a", "paradox", 9.0, ["A"],
                                 primary_mechanism="story", primary_evidence="pebble")
        opp2 = _make_opportunity("opportunity-b", "story", 8.0, ["B"],
                                 primary_mechanism="psychological_mechanism", primary_evidence="hedonic")
        extraction = OpportunityExtractionResult(
            parent_video_id="test-project", parent_video_title="Test",
            parent_core_thesis="Thesis.", opportunities=[opp1, opp2],
            selected=["opportunity-a", "opportunity-b"], extraction_rationale="Good.",
        )
        repo.save_opportunities("test-project", extraction)

        sd = self._script_data()
        good = self._good_scores()
        plan = _make_plan_data()
        no_problem = self._cross_no_problem()

        call_order: list[str] = []

        def side_effect_with_tracking(*args, **kwargs):
            prompt = args[0] if args else kwargs.get("prompt", "")
            system_prompt = str(kwargs.get("system_prompt", ""))
            if "similarity" in system_prompt.lower() or "similarity_problem" in prompt:
                call_order.append("cross_short_qa")
                return MagicMock(text=json.dumps(no_problem))
            if "scenes" in prompt or "visual_hook" in str(prompt):
                call_order.append("s3")
                return MagicMock(text=json.dumps(plan))
            call_order.append("other")
            # Scoring calls have hook_strength in the system_prompt, not user prompt
            if "hook_strength" in system_prompt or "Script to evaluate" in str(prompt):
                return MagicMock(text=json.dumps(good))
            return MagicMock(text=json.dumps(sd))

        mock_llm = MagicMock()
        mock_llm.generate.side_effect = side_effect_with_tracking
        mock_projects = MagicMock()
        mock_projects.load.return_value = _mock_project()

        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.pipeline.ProjectRepository", return_value=mock_projects):
            ShortsPipeline(Settings()).run("test-project")

        # cross_short_qa should appear before any s3 call in call_order
        if "cross_short_qa" in call_order and "s3" in call_order:
            assert call_order.index("cross_short_qa") < call_order.index("s3"), \
                "Cross-short QA must run before S3"

    def test_pipeline_does_not_leave_stale_scene_plan_after_recomposition(
        self, tmp_path, monkeypatch
    ):
        """If recomposition succeeds, any pre-existing scene-plan.json must be deleted."""
        from ytfactory.shorts.pipeline import ShortsPipeline
        from ytfactory.config.settings import Settings

        _setup_workspace_simple(tmp_path)
        monkeypatch.setattr("ytfactory.shorts.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))

        repo = ShortsRepository()
        opp1 = _make_opportunity("opportunity-a", "paradox", 9.0, ["A"],
                                 primary_mechanism="story", primary_evidence="pebble")
        opp2 = _make_opportunity("opportunity-b", "story", 8.0, ["B"],
                                 primary_mechanism="psychological_mechanism", primary_evidence="hedonic")
        extraction = OpportunityExtractionResult(
            parent_video_id="test-project", parent_video_title="Test",
            parent_core_thesis="Thesis.", opportunities=[opp1, opp2],
            selected=["opportunity-a", "opportunity-b"], extraction_rationale="Good.",
        )
        repo.save_opportunities("test-project", extraction)

        # Pre-plant a stale scene-plan.json for short-001
        stale_plan = _make_scene_plan("short-001")
        repo.save_scene_plan("test-project", "short-001", stale_plan)
        assert (tmp_path / "test-project" / "shorts" / "short-001" / "scene-plan.json").exists()

        sd = self._script_data()
        good = self._good_scores()
        fail = self._fail_scores()
        plan = _make_plan_data()
        no_problem = self._cross_no_problem()
        recomposed_sections = {
            "hook": "REWRITTEN HOOK.", "setup": sd["setup"],
            "story": sd["story"], "revelation": sd["revelation"], "open_loop": sd["open_loop"],
        }

        mock_llm = MagicMock()
        mock_llm.generate.side_effect = [
            MagicMock(text=json.dumps(sd)),                 # S2 short-001
            MagicMock(text=json.dumps(fail)),               # S2b → FAIL
            MagicMock(text=json.dumps(recomposed_sections)),# recomposer
            MagicMock(text=json.dumps(good)),               # re-QA → PASS
            MagicMock(text=json.dumps(sd)),                 # S2 short-002
            MagicMock(text=json.dumps(good)),               # S2b → PASS
            MagicMock(text=json.dumps(no_problem)),         # cross-short QA
            MagicMock(text=json.dumps(plan)),               # S3 short-001 (fresh)
            MagicMock(text=json.dumps(plan)),               # S3 short-002
        ]
        mock_projects = MagicMock()
        mock_projects.load.return_value = _mock_project()

        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.pipeline.ProjectRepository", return_value=mock_projects):
            ShortsPipeline(Settings()).run("test-project")

        # Scene plan should exist and be the fresh one (S3 re-ran after recomposition)
        plan_path = tmp_path / "test-project" / "shorts" / "short-001" / "scene-plan.json"
        assert plan_path.exists()
        # The content should come from S3, not the stale pre-planted one
        import json as _json
        plan_data = _json.loads(plan_path.read_text())
        # The fresh plan has 5 scenes from _make_plan_data(); stale has 7 from _make_scene_plan()
        assert plan_data["scene_count"] == 5, "Stale plan (7 scenes) must have been replaced by fresh plan (5 scenes)"

    def test_pipeline_force_regenerates_qa_and_recomposition(self, tmp_path, monkeypatch):
        """With force=True, existing scripts must be deleted and re-generated."""
        from ytfactory.shorts.pipeline import ShortsPipeline
        from ytfactory.config.settings import Settings

        _setup_workspace_simple(tmp_path)
        monkeypatch.setattr("ytfactory.shorts.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))

        repo = ShortsRepository()
        opp1 = _make_opportunity("opportunity-a", "paradox", 9.0, ["A"],
                                 primary_mechanism="story", primary_evidence="pebble")
        opp2 = _make_opportunity("opportunity-b", "story", 8.0, ["B"],
                                 primary_mechanism="psychological_mechanism", primary_evidence="hedonic")
        extraction = OpportunityExtractionResult(
            parent_video_id="test-project", parent_video_title="Test",
            parent_core_thesis="Thesis.", opportunities=[opp1, opp2],
            selected=["opportunity-a", "opportunity-b"], extraction_rationale="Good.",
        )
        repo.save_opportunities("test-project", extraction)

        # Pre-plant scripts (should be ignored with force=True)
        repo.save_script("test-project", "short-001", _make_script("short-001"))
        repo.save_script("test-project", "short-002", _make_script("short-002"))

        sd = self._script_data()
        good = self._good_scores()
        plan = _make_plan_data()
        no_problem = self._cross_no_problem()
        # S1 (force=True re-runs extraction) needs an extraction-shaped response
        extraction_json = {
            "parent_video_title": "Test Video",
            "parent_core_thesis": "Thesis.",
            "extraction_rationale": "Good.",
            "opportunities": [
                {
                    "opportunity_id": "opportunity-a", "angle": "paradox",
                    "surprising_idea": "Paradox.", "emotional_tension": "Tension.",
                    "curiosity_potential": "Curiosity.", "connection_to_long_video": "Connection.",
                    "unresolved_question": "Question?", "estimated_hook_strength": 9.0,
                    "source_sections": ["A"], "primary_mechanism": "story",
                    "primary_evidence": "pebble",
                },
                {
                    "opportunity_id": "opportunity-b", "angle": "story",
                    "surprising_idea": "Story idea.", "emotional_tension": "Tension.",
                    "curiosity_potential": "Curiosity.", "connection_to_long_video": "Connection.",
                    "unresolved_question": "Question?", "estimated_hook_strength": 8.0,
                    "source_sections": ["B"], "primary_mechanism": "psychological_mechanism",
                    "primary_evidence": "hedonic",
                },
            ],
        }

        mock_llm = MagicMock()
        mock_llm.generate.side_effect = [
            MagicMock(text=json.dumps(extraction_json)),  # S1 re-extraction (force=True)
            MagicMock(text=json.dumps(sd)),        # S2 short-001 (force regenerated)
            MagicMock(text=json.dumps(good)),      # S2b → PASS
            MagicMock(text=json.dumps(sd)),        # S2 short-002 (force regenerated)
            MagicMock(text=json.dumps(good)),      # S2b → PASS
            MagicMock(text=json.dumps(no_problem)),# cross-short QA
            MagicMock(text=json.dumps(plan)),      # S3 short-001
            MagicMock(text=json.dumps(plan)),      # S3 short-002
        ]
        mock_projects = MagicMock()
        mock_projects.load.return_value = _mock_project()

        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.pipeline.ProjectRepository", return_value=mock_projects):
            ShortsPipeline(Settings()).run("test-project", force=True)

        # Both scene plans written (full pipeline ran)
        assert (tmp_path / "test-project" / "shorts" / "short-001" / "scene-plan.json").exists()
        assert (tmp_path / "test-project" / "shorts" / "short-002" / "scene-plan.json").exists()

    def test_pipeline_runs_recomposer_only_once_per_short(self, tmp_path, monkeypatch):
        """Recomposition must happen at most once per Short (spec: maximum 1 cycle)."""
        from ytfactory.shorts.pipeline import ShortsPipeline
        from ytfactory.config.settings import Settings

        _setup_workspace_simple(tmp_path)
        monkeypatch.setattr("ytfactory.shorts.pipeline.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.shorts.repository.WORKSPACE_DIR", str(tmp_path))

        repo = ShortsRepository()
        opp1 = _make_opportunity("opportunity-a", "paradox", 9.0, ["A"],
                                 primary_mechanism="story", primary_evidence="pebble")
        opp2 = _make_opportunity("opportunity-b", "story", 8.0, ["B"],
                                 primary_mechanism="psychological_mechanism", primary_evidence="hedonic")
        extraction = OpportunityExtractionResult(
            parent_video_id="test-project", parent_video_title="Test",
            parent_core_thesis="Thesis.", opportunities=[opp1, opp2],
            selected=["opportunity-a", "opportunity-b"], extraction_rationale="Good.",
        )
        repo.save_opportunities("test-project", extraction)

        sd = self._script_data()
        good = self._good_scores()
        fail = self._fail_scores()
        plan = _make_plan_data()

        recomposer_call_count = 0

        def counting_llm_side_effect(*args, **kwargs):
            nonlocal recomposer_call_count
            system = kwargs.get("system_prompt", "")
            if "editorial recomposer" in system:
                recomposer_call_count += 1
                return MagicMock(text=json.dumps({
                    "hook": "Rewritten.", "setup": sd["setup"],
                    "story": sd["story"], "revelation": sd["revelation"],
                    "open_loop": sd["open_loop"],
                }))
            prompt = args[0] if args else ""
            if "hook_strength" in prompt:
                return MagicMock(text=json.dumps(good))
            if "similarity_problem" in prompt or "similarity" in system:
                return MagicMock(text=json.dumps({
                    "similarity_problem": False, "overlap_reason": "none",
                    "failed_dimensions": [], "preserve_sections": [],
                    "rewrite_sections": [], "specific_instruction": "",
                }))
            if "visual_hook" in str(prompt):
                return MagicMock(text=json.dumps(plan))
            return MagicMock(text=json.dumps(sd))

        # Make the validator return fail on first score, pass on second
        score_calls = 0

        def score_side_effect(*args, **kwargs):
            nonlocal score_calls
            system = kwargs.get("system_prompt", "")
            if "editorial recomposer" in system:
                return counting_llm_side_effect(*args, **kwargs)
            if "hook_strength" in system:
                score_calls += 1
                if score_calls in (1, 3, 5):  # short-001 first, recomposed, short-002
                    return MagicMock(text=json.dumps(fail if score_calls == 1 else good))
            return counting_llm_side_effect(*args, **kwargs)

        # Hook needs enough words so recomposed total >= 90: sd sections are 22 words each (110//5),
        # so 4×22 + hook_words >= 90 → hook_words >= 2. Use 2 words minimum.
        recomposed_hook = "Rewritten hook."  # 2 words → total = 2 + 4×22 = 90 ≥ 90

        mock_llm = MagicMock()
        # Note: recomposer calls are handled by recomposer_llm — no recomposer entry here
        mock_llm.generate.side_effect = [
            MagicMock(text=json.dumps(sd)),    # S2 short-001
            MagicMock(text=json.dumps(fail)),  # S2b score → FAIL
            MagicMock(text=json.dumps(good)),  # re-QA after recomposition → PASS
            MagicMock(text=json.dumps(sd)),    # S2 short-002
            MagicMock(text=json.dumps(good)),  # S2b score short-002
            MagicMock(text=json.dumps({"similarity_problem": False, "overlap_reason": "none",
                                       "failed_dimensions": [], "preserve_sections": [],
                                       "rewrite_sections": [], "specific_instruction": ""})),
            MagicMock(text=json.dumps(plan)),  # S3 short-001
            MagicMock(text=json.dumps(plan)),  # S3 short-002
        ]
        mock_projects = MagicMock()
        mock_projects.load.return_value = _mock_project()

        recomposer_llm = MagicMock()
        recomposer_call_count_list = []

        def track_recompose(*args, **kwargs):
            recomposer_call_count_list.append(1)
            return MagicMock(text=json.dumps({
                "hook": recomposed_hook, "setup": sd["setup"],
                "story": sd["story"], "revelation": sd["revelation"],
                "open_loop": sd["open_loop"],
            }))

        recomposer_llm.generate.side_effect = track_recompose

        with patch("ytfactory.shorts.extractor.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.generator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.validator.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.recomposer.get_llm_for_role", return_value=recomposer_llm), \
             patch("ytfactory.shorts.scene_planner.get_llm_for_role", return_value=mock_llm), \
             patch("ytfactory.shorts.pipeline.ProjectRepository", return_value=mock_projects):
            ShortsPipeline(Settings()).run("test-project")

        # Recomposer should have been called exactly once for short-001
        assert len(recomposer_call_count_list) <= 1, (
            f"Recomposer called {len(recomposer_call_count_list)} times, expected at most 1"
        )
