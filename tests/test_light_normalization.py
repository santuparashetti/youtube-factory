"""Tests for the Light Normalization stage (ADR-0010).

Coverage:
  - Scripture span extraction and placeholder round-trip
  - NormalizationValidator: each of the four automated checks
  - LightNormalizationPipeline: happy path, validation-failure fallback, scripture preservation
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.light_normalization.pipeline import LightNormalizationPipeline
from ytfactory.shared.scripture import (
    extract_scripture_spans as _extract_scripture_spans,
    restore_scripture_spans as _restore_scripture_spans,
)
from ytfactory.light_normalization.validator import NormalizationValidator


# ── Scripture extraction ───────────────────────────────────────────────────────


class TestScriptureExtraction:
    def test_no_scripture_returns_unchanged(self):
        text = "This is a plain English transcript with no sacred text."
        result, placeholders = _extract_scripture_spans(text)
        assert result == text
        assert placeholders == {}

    def test_devanagari_is_extracted(self):
        text = "The verse says सर्वे भवन्तु सुखिनः and we continue."
        result, placeholders = _extract_scripture_spans(text)
        assert len(placeholders) >= 1
        assert "सर्वे भवन्तु सुखिनः" not in result
        assert "{{SCRIPTURE_1}}" in result

    def test_explicit_marker_is_extracted(self):
        text = "He quoted <scripture>OM SHANTI OM</scripture> at the end."
        result, placeholders = _extract_scripture_spans(text)
        assert len(placeholders) == 1
        original_span = next(iter(placeholders.values()))
        assert "OM SHANTI OM" in original_span
        assert "<scripture>" not in result

    def test_restore_round_trips_exactly(self):
        text = "First <scripture>Shanti Path</scripture> then ಕನ್ನಡ ಭಾಷೆ done."
        placeholder_text, placeholders = _extract_scripture_spans(text)
        restored = _restore_scripture_spans(placeholder_text, placeholders)
        assert restored == text

    def test_multiple_spans_numbered_sequentially(self):
        text = "Verse one: ॐ नमः शिवाय then verse two: ಓಂ ನಮಃ"
        _, placeholders = _extract_scripture_spans(text)
        keys = sorted(placeholders.keys())
        assert keys[0] == "SCRIPTURE_1"
        assert len(keys) >= 2


# ── NormalizationValidator ─────────────────────────────────────────────────────


class TestChangeRatioBound:
    def test_identical_passes(self):
        v = NormalizationValidator(change_ratio_threshold=0.15)
        result = v.validate("hello world", "hello world", [])
        assert result.checks["change_ratio_bound"] is True

    def test_minor_change_passes(self):
        original = "a " * 100  # 200 chars
        # Remove 10 chars (5% change)
        normalized = "a " * 95
        v = NormalizationValidator(change_ratio_threshold=0.15)
        result = v.validate(original, normalized, [])
        assert result.checks["change_ratio_bound"] is True

    def test_large_change_fails(self):
        original = "The full transcript is here with many words and sentences."
        normalized = "Short."  # > 15% reduction
        v = NormalizationValidator(change_ratio_threshold=0.15)
        result = v.validate(original, normalized, [])
        assert result.checks["change_ratio_bound"] is False
        assert not result.passed


class TestScripturePlaceholderMatch:
    def test_preserved_placeholder_passes(self):
        original = "Text {{SCRIPTURE_1}} more text."
        normalized = "Text {{SCRIPTURE_1}} more text."
        v = NormalizationValidator()
        result = v.validate(original, normalized, ["Sacred verse here"])
        assert result.checks["scripture_placeholder_match"] is True

    def test_missing_placeholder_fails(self):
        original = "Text {{SCRIPTURE_1}} more text."
        normalized = "Text  more text."  # placeholder removed
        v = NormalizationValidator()
        result = v.validate(original, normalized, [])
        assert result.checks["scripture_placeholder_match"] is False
        assert not result.passed

    def test_modified_placeholder_fails(self):
        original = "Text {{SCRIPTURE_1}} end."
        normalized = "Text [SCRIPTURE_1] end."  # brackets instead of braces
        v = NormalizationValidator()
        result = v.validate(original, normalized, [])
        assert result.checks["scripture_placeholder_match"] is False


class TestParagraphOrder:
    def test_same_order_passes(self):
        original = "First paragraph content here.\n\nSecond paragraph content here."
        normalized = "First paragraph content here.\n\nSecond paragraph content here."
        v = NormalizationValidator()
        result = v.validate(original, normalized, [])
        assert result.checks["paragraph_order"] is True

    def test_single_paragraph_passes(self):
        original = "Just one paragraph, no newlines."
        normalized = "Just one paragraph, no newlines."
        v = NormalizationValidator()
        result = v.validate(original, normalized, [])
        assert result.checks["paragraph_order"] is True


class TestNoNewContent:
    def test_no_new_content_passes(self):
        original = "The teacher spoke about dharma and the path to liberation."
        normalized = "The teacher spoke about dharma and the path to liberation."
        v = NormalizationValidator(min_sentence_overlap=0.30)
        result = v.validate(original, normalized, [])
        assert result.checks["no_new_content"] is True

    def test_clearly_new_sentence_fails(self):
        original = "The teacher spoke about dharma."
        normalized = (
            "The teacher spoke about dharma. "
            "Furthermore quantum mechanics explains consciousness through entanglement."
        )
        v = NormalizationValidator(min_sentence_overlap=0.30)
        result = v.validate(original, normalized, [])
        assert result.checks["no_new_content"] is False

    def test_short_sentences_skipped(self):
        original = "The teacher spoke."
        normalized = "The teacher spoke. Yes."
        v = NormalizationValidator(min_sentence_overlap=0.30)
        result = v.validate(original, normalized, [])
        # "Yes." is < 6 words so it's skipped by the check
        assert result.checks["no_new_content"] is True


# ── LightNormalizationPipeline ─────────────────────────────────────────────────


class TestLightNormalizationPipeline:
    @pytest.fixture
    def settings(self):
        s = MagicMock()
        return s

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        response = MagicMock()
        response.text = "Cleaned transcript text here, no changes needed."
        llm.generate.return_value = response
        return llm

    def _make_pipeline(self, settings, mock_llm):
        with patch(
            "ytfactory.light_normalization.pipeline.get_llm_provider",
            return_value=mock_llm,
        ):
            return LightNormalizationPipeline(settings)

    def test_happy_path_writes_files(self, tmp_path, settings, mock_llm):
        project_id = "test-project"
        script_dir = tmp_path / project_id / "script"
        script_dir.mkdir(parents=True)
        raw = "Cleaned transcript text here, no changes needed."
        (script_dir / "script.md").write_text(raw, encoding="utf-8")

        pipeline = self._make_pipeline(settings, mock_llm)

        with patch(
            "ytfactory.light_normalization.pipeline.WORKSPACE_DIR", str(tmp_path)
        ):
            result = pipeline.run(project_id)

        assert (script_dir / "script.md").exists()
        assert (script_dir / "script_pre_normalize.md").exists()
        assert (script_dir / "normalization-report.json").exists()
        assert result  # non-empty

    def test_backup_contains_original(self, tmp_path, settings, mock_llm):
        project_id = "test-project"
        script_dir = tmp_path / project_id / "script"
        script_dir.mkdir(parents=True)
        raw = "Cleaned transcript text here, no changes needed."
        (script_dir / "script.md").write_text(raw, encoding="utf-8")

        pipeline = self._make_pipeline(settings, mock_llm)

        with patch(
            "ytfactory.light_normalization.pipeline.WORKSPACE_DIR", str(tmp_path)
        ):
            pipeline.run(project_id)

        backup = (script_dir / "script_pre_normalize.md").read_text(encoding="utf-8")
        assert backup == raw

    def test_validation_failure_uses_fallback(self, tmp_path, settings):
        project_id = "test-project"
        script_dir = tmp_path / project_id / "script"
        script_dir.mkdir(parents=True)
        raw = "The teacher spoke about dharma and enlightenment in great detail here."
        (script_dir / "script.md").write_text(raw, encoding="utf-8")

        # LLM returns drastically shortened text → change_ratio > threshold
        llm = MagicMock()
        response = MagicMock()
        response.text = "Short."
        llm.generate.return_value = response

        pipeline = self._make_pipeline(settings, llm)

        with patch(
            "ytfactory.light_normalization.pipeline.WORKSPACE_DIR", str(tmp_path)
        ):
            result = pipeline.run(project_id)

        # Fallback: original is preserved
        assert result == raw

        import json
        report = json.loads((script_dir / "normalization-report.json").read_text())
        assert report["fallback_used"] is True

    def test_scripture_spans_preserved_in_output(self, tmp_path, settings):
        project_id = "test-project"
        script_dir = tmp_path / project_id / "script"
        script_dir.mkdir(parents=True)
        sacred = "सर्वे भवन्तु सुखिनः"
        raw = f"The verse {sacred} is important."
        (script_dir / "script.md").write_text(raw, encoding="utf-8")

        # LLM returns the placeholder version correctly
        llm = MagicMock()
        response = MagicMock()
        response.text = "The verse {{SCRIPTURE_1}} is important."
        llm.generate.return_value = response

        pipeline = self._make_pipeline(settings, llm)

        with patch(
            "ytfactory.light_normalization.pipeline.WORKSPACE_DIR", str(tmp_path)
        ):
            result = pipeline.run(project_id)

        assert sacred in result

    def test_missing_script_raises(self, tmp_path, settings, mock_llm):
        pipeline = self._make_pipeline(settings, mock_llm)
        # tmp_path has no project dir, so script.md won't exist
        with patch("ytfactory.light_normalization.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with pytest.raises(FileNotFoundError):
                pipeline.run("nonexistent-project")

    def test_accepts_script_text_directly(self, tmp_path, settings, mock_llm):
        project_id = "test-direct"
        script_dir = tmp_path / project_id / "script"
        script_dir.mkdir(parents=True)

        pipeline = self._make_pipeline(settings, mock_llm)

        with patch(
            "ytfactory.light_normalization.pipeline.WORKSPACE_DIR", str(tmp_path)
        ):
            result = pipeline.run(
                project_id,
                script_text="Cleaned transcript text here, no changes needed.",
            )

        assert result


# ── Rename backward compat ─────────────────────────────────────────────────────


class TestRenameBackwardCompat:
    def test_script_enhancer_alias_resolves(self):
        from ytfactory.script_enhancer.pipeline import (
            DocumentaryScriptEnhancerPipeline,
            ScriptEnhancerPipeline,
        )

        assert ScriptEnhancerPipeline is DocumentaryScriptEnhancerPipeline

    def test_build_pipeline_has_backward_compat_attribute(self):
        with patch("ytfactory.build.pipeline.Settings"):
            with patch("ytfactory.build.pipeline.LightNormalizationPipeline"):
                with patch("ytfactory.build.pipeline.DocumentaryScriptEnhancerPipeline"):
                    with patch("ytfactory.build.pipeline.ScenePipeline"):
                        with patch("ytfactory.build.pipeline.ImagePipeline"):
                            with patch("ytfactory.build.pipeline.VoicePipeline"):
                                with patch("ytfactory.build.pipeline.CaptionPipeline"):
                                    with patch("ytfactory.build.pipeline.VideoPipeline"):
                                        with patch("ytfactory.build.pipeline.CTAPipeline"):
                                            with patch("ytfactory.build.pipeline.ReviewPipeline"):
                                                with patch("ytfactory.build.pipeline.PublishPipeline"):
                                                    from ytfactory.build.pipeline import BuildPipeline
                                                    bp = BuildPipeline()
                                                    # Both names should resolve to the same object
                                                    assert bp.script_enhancer is bp.documentary_script_enhancer
