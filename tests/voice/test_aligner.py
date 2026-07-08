"""Tests for WhisperX forced alignment helpers (ytfactory.voice.aligner).

Heavy dependencies (whisperx, numpy) are mocked throughout — these tests
run without a GPU or ML runtime installed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.voice.aligner import (
    boundaries_from_alignment,
    is_available,
    load_alignment,
    save_alignment,
)

# ── Sample data fixtures ───────────────────────────────────────────────────────

_ALIGNMENT_V1 = {
    "version": "whisperx_v1",
    "words": [
        {"word": "Hello", "start": 0.1, "end": 0.4, "score": 0.99},
        {"word": "world", "start": 0.5, "end": 0.8, "score": 0.97},
        {"word": "today", "start": 0.9, "end": 1.2, "score": 0.95},
    ],
    "sentences": [{"start": 0.1, "end": 1.2, "text": "Hello world today"}],
    "confidence": 0.97,
}


# ── is_available() ────────────────────────────────────────────────────────────


class TestIsAvailable:
    def test_returns_false_when_whisperx_missing(self):
        with patch.dict(sys.modules, {"whisperx": None}):
            assert is_available() is False

    def test_returns_true_when_whisperx_present(self):
        mock_wx = MagicMock()
        with patch.dict(sys.modules, {"whisperx": mock_wx}):
            assert is_available() is True


# ── save_alignment() / load_alignment() ───────────────────────────────────────


class TestSaveAndLoad:
    def test_save_creates_file(self, tmp_path):
        path = tmp_path / "scene-001.alignment.json"
        save_alignment(_ALIGNMENT_V1, path)
        assert path.exists()

    def test_save_writes_valid_json(self, tmp_path):
        path = tmp_path / "scene-001.alignment.json"
        save_alignment(_ALIGNMENT_V1, path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == "whisperx_v1"
        assert len(data["words"]) == 3

    def test_load_returns_dict_for_valid_file(self, tmp_path):
        path = tmp_path / "scene-001.alignment.json"
        save_alignment(_ALIGNMENT_V1, path)
        result = load_alignment(path)
        assert result is not None
        assert result["version"] == "whisperx_v1"

    def test_load_returns_none_for_missing_file(self, tmp_path):
        result = load_alignment(tmp_path / "nonexistent.alignment.json")
        assert result is None

    def test_load_returns_none_for_wrong_version(self, tmp_path):
        path = tmp_path / "bad.alignment.json"
        path.write_text(json.dumps({"version": "v0", "words": []}), encoding="utf-8")
        assert load_alignment(path) is None

    def test_load_returns_none_for_missing_words_key(self, tmp_path):
        path = tmp_path / "bad.alignment.json"
        path.write_text(json.dumps({"version": "whisperx_v1"}), encoding="utf-8")
        assert load_alignment(path) is None

    def test_load_returns_none_for_invalid_json(self, tmp_path):
        path = tmp_path / "corrupt.alignment.json"
        path.write_text("not json {{{{", encoding="utf-8")
        assert load_alignment(path) is None

    def test_roundtrip_preserves_all_words(self, tmp_path):
        path = tmp_path / "scene.alignment.json"
        save_alignment(_ALIGNMENT_V1, path)
        loaded = load_alignment(path)
        assert loaded is not None
        assert len(loaded["words"]) == len(_ALIGNMENT_V1["words"])


# ── boundaries_from_alignment() ───────────────────────────────────────────────


class TestBoundariesFromAlignment:
    def test_returns_correct_word_list(self):
        boundaries = boundaries_from_alignment(_ALIGNMENT_V1)
        words = [b["word"] for b in boundaries]
        assert words == ["Hello", "world", "today"]

    def test_strips_score_field(self):
        boundaries = boundaries_from_alignment(_ALIGNMENT_V1)
        for b in boundaries:
            assert "score" not in b

    def test_preserves_start_end(self):
        boundaries = boundaries_from_alignment(_ALIGNMENT_V1)
        assert boundaries[0]["start"] == pytest.approx(0.1)
        assert boundaries[0]["end"] == pytest.approx(0.4)

    def test_filters_words_with_missing_start(self):
        data = {
            "version": "whisperx_v1",
            "words": [
                {"word": "ok", "start": 0.0, "end": 0.5},
                {"word": "broken"},  # missing start/end
            ],
        }
        boundaries = boundaries_from_alignment(data)
        assert len(boundaries) == 1
        assert boundaries[0]["word"] == "ok"

    def test_empty_words_returns_empty_list(self):
        data = {"version": "whisperx_v1", "words": []}
        assert boundaries_from_alignment(data) == []

    def test_empty_word_string_is_filtered(self):
        data = {
            "version": "whisperx_v1",
            "words": [
                {"word": "", "start": 0.0, "end": 0.1},
                {"word": "real", "start": 0.2, "end": 0.5},
            ],
        }
        result = boundaries_from_alignment(data)
        assert len(result) == 1
        assert result[0]["word"] == "real"


# ── align() (full mocked integration) ─────────────────────────────────────────


class TestAlignFunction:
    def _make_mock_whisperx(self, word_list: list[dict]) -> MagicMock:
        """Build a whisperx-shaped mock that returns word_list from align()."""
        mock_wx = MagicMock()
        mock_wx.load_audio.return_value = [0.0] * 16000  # 1 second dummy audio

        mock_model = MagicMock()
        mock_metadata = MagicMock()
        mock_wx.load_align_model.return_value = (mock_model, mock_metadata)

        mock_wx.align.return_value = {
            "segments": [
                {
                    "start": 0.0,
                    "end": 1.0,
                    "text": "hello world",
                    "words": word_list,
                }
            ]
        }
        return mock_wx

    def test_returns_correct_version(self, tmp_path):
        from ytfactory.voice.aligner import align

        words = [
            {"word": "hello", "start": 0.1, "end": 0.4, "score": 0.98},
            {"word": "world", "start": 0.5, "end": 0.8, "score": 0.95},
        ]
        mock_wx = self._make_mock_whisperx(words)
        mock_np = MagicMock()
        mock_np.__version__ = "1.24"

        with patch.dict(sys.modules, {"whisperx": mock_wx, "numpy": mock_np}):
            result = align(
                "hello world",
                tmp_path / "audio.mp3",
                device="cpu",
                language="en",
            )

        assert result["version"] == "whisperx_v1"

    def test_returns_word_list(self, tmp_path):
        from ytfactory.voice.aligner import align

        words = [
            {"word": "hello", "start": 0.1, "end": 0.4, "score": 0.98},
            {"word": "world", "start": 0.5, "end": 0.8, "score": 0.95},
        ]
        mock_wx = self._make_mock_whisperx(words)
        mock_np = MagicMock()

        with patch.dict(sys.modules, {"whisperx": mock_wx, "numpy": mock_np}):
            result = align("hello world", tmp_path / "audio.mp3", language="en")

        assert len(result["words"]) == 2
        assert result["words"][0]["word"] == "hello"

    def test_confidence_is_average_of_scores(self, tmp_path):
        from ytfactory.voice.aligner import align

        words = [
            {"word": "a", "start": 0.0, "end": 0.2, "score": 0.8},
            {"word": "b", "start": 0.3, "end": 0.5, "score": 1.0},
        ]
        mock_wx = self._make_mock_whisperx(words)
        mock_np = MagicMock()

        with patch.dict(sys.modules, {"whisperx": mock_wx, "numpy": mock_np}):
            result = align("a b", tmp_path / "audio.mp3", language="en")

        assert result["confidence"] == pytest.approx(0.9, abs=0.01)

    def test_raises_runtime_error_without_whisperx(self, tmp_path):
        from ytfactory.voice.aligner import align

        with patch.dict(sys.modules, {"whisperx": None}):
            with pytest.raises(RuntimeError, match="whisperx"):
                align("hello", tmp_path / "audio.mp3")

    def test_bcp47_language_code_is_stripped(self, tmp_path):
        """'en-US' → 'en' is passed to load_align_model."""
        from ytfactory.voice.aligner import align

        words = [{"word": "hi", "start": 0.0, "end": 0.3, "score": 0.99}]
        mock_wx = self._make_mock_whisperx(words)
        mock_np = MagicMock()

        with patch.dict(sys.modules, {"whisperx": mock_wx, "numpy": mock_np}):
            align("hi", tmp_path / "audio.mp3", language="en-US")

        call_kwargs = mock_wx.load_align_model.call_args
        assert call_kwargs.kwargs.get("language_code") == "en"
