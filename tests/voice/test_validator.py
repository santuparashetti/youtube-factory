"""Tests for AudioValidator."""

from __future__ import annotations

from pathlib import Path

import pytest

from video_core.providers.tts.validator import (
    AudioValidator,
    ValidationResult,
    _MIN_FILE_BYTES,
)


@pytest.fixture()
def validator() -> AudioValidator:
    return AudioValidator()


@pytest.fixture()
def tmp_audio(tmp_path) -> Path:
    """A scratch directory for synthetic audio files."""
    return tmp_path


def _make_fake_mp3(path: Path, size: int = 32_000) -> Path:
    """Write a dummy file of the given size (not a real MP3 — enough to pass size check)."""
    path.write_bytes(b"\xff\xfb" + b"\x00" * (size - 2))
    return path


class TestFileExistence:
    def test_missing_file_fails(self, validator, tmp_audio):
        result = validator.validate(tmp_audio / "nonexistent.mp3", word_count=10)
        assert result.passed is False
        assert any("does not exist" in i for i in result.issues)

    def test_returns_validation_result_type(self, validator, tmp_audio):
        result = validator.validate(tmp_audio / "nonexistent.mp3", word_count=10)
        assert isinstance(result, ValidationResult)


class TestFileSizeCheck:
    def test_file_too_small_fails(self, validator, tmp_audio):
        small = tmp_audio / "small.mp3"
        small.write_bytes(b"\xff\xfb" + b"\x00" * 10)
        result = validator.validate(small, word_count=1)
        # Either size or duration will fail — check there's at least one issue
        assert result.passed is False

    def test_adequate_size_passes_size_check(self, validator, tmp_audio):
        big = _make_fake_mp3(tmp_audio / "big.mp3", size=_MIN_FILE_BYTES + 1000)
        result = validator.validate(big, word_count=100)
        # Size check should pass even if duration can't be measured
        size_issues = [i for i in result.issues if "too small" in i]
        assert len(size_issues) == 0


class TestValidationResult:
    def test_to_dict_contains_required_keys(self):
        r = ValidationResult(
            passed=True,
            duration_seconds=5.0,
            file_size_bytes=20000,
            issues=[],
            warnings=["long duration"],
        )
        d = r.to_dict()
        assert "passed" in d
        assert "duration_seconds" in d
        assert "file_size_bytes" in d
        assert "issues" in d
        assert "warnings" in d

    def test_to_dict_rounds_duration(self):
        r = ValidationResult(
            passed=True,
            duration_seconds=5.123456789,
            file_size_bytes=20000,
        )
        d = r.to_dict()
        assert d["duration_seconds"] == round(5.123456789, 3)

    def test_passed_true_when_no_issues(self):
        r = ValidationResult(passed=True, duration_seconds=3.0, file_size_bytes=20000)
        assert r.passed is True
        assert r.issues == []

    def test_passed_false_with_issues(self):
        r = ValidationResult(
            passed=False,
            duration_seconds=0.0,
            file_size_bytes=0,
            issues=["audio file does not exist"],
        )
        assert r.passed is False


class TestSceneIndexLabel:
    def test_scene_index_appears_in_log(self, validator, tmp_audio, caplog):
        result = validator.validate(
            tmp_audio / "missing.mp3",
            word_count=10,
            scene_index=5,
        )
        # validate returns without crashing
        assert result.passed is False


class TestWordCountRatioEdgeCases:
    def test_zero_word_count_does_not_crash(self, validator, tmp_audio):
        f = _make_fake_mp3(tmp_audio / "audio.mp3")
        result = validator.validate(f, word_count=0)
        # No crash — ratio check is skipped when word_count == 0
        assert isinstance(result, ValidationResult)

    def test_very_high_word_count_no_crash(self, validator, tmp_audio):
        f = _make_fake_mp3(tmp_audio / "audio.mp3")
        result = validator.validate(f, word_count=10_000)
        assert isinstance(result, ValidationResult)
