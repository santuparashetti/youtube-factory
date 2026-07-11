"""Tests for SpeechOptimizer edge cases."""

from __future__ import annotations

import pytest

from video_core.providers.tts.optimizer import SpeechOptimizer


@pytest.fixture()
def opt() -> SpeechOptimizer:
    return SpeechOptimizer()


class TestBasicOptimization:
    def test_returns_string(self, opt):
        result = opt.optimize("Hello world.", style=None, scene_position=0.5)
        assert isinstance(result, str)

    def test_non_empty_input_non_empty_output(self, opt):
        result = opt.optimize(
            "Some narration text here.", style=None, scene_position=0.5
        )
        assert result.strip() != ""

    def test_empty_input_does_not_crash(self, opt):
        result = opt.optimize("", style=None, scene_position=0.5)
        assert isinstance(result, str)


class TestScenePosition:
    def test_beginning_position(self, opt):
        text = "The story begins with a question about the universe."
        result = opt.optimize(text, style="spiritual", scene_position=0.0)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_middle_position(self, opt):
        text = "In the depths of time, civilizations rose and fell."
        result = opt.optimize(text, style="spiritual", scene_position=0.5)
        assert isinstance(result, str)

    def test_end_position(self, opt):
        text = "And so the journey ends where it began."
        result = opt.optimize(text, style="spiritual", scene_position=1.0)
        assert isinstance(result, str)


class TestOutputStructure:
    def test_optimizer_does_not_crash_on_markdown_input(self, opt):
        # Markdown stripping is the formatter's responsibility, not the optimizer's.
        # The optimizer receives raw narration (which may contain markdown) and
        # restructures phrasing for spoken delivery. The formatter cleans it later.
        text = "**Bold** and *italic* narration."
        result = opt.optimize(text, style="spiritual", scene_position=0.5)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_output_has_no_double_period(self, opt):
        """
        Critical regression guard: optimizer output fed into formatter
        must not produce ".." after formatter's paragraph normalization.
        """
        text = "First sentence ends here.\n\nSecond sentence begins."
        result = opt.optimize(text, style="spiritual", scene_position=0.5)
        # The optimizer can output phrases with \n\n — that is expected.
        # What matters is there is no ".." already in the optimized output.
        assert ".." not in result

    def test_long_narration_handled(self, opt):
        text = " ".join(["This is sentence number one."] * 20)
        result = opt.optimize(text, style="spiritual", scene_position=0.3)
        assert isinstance(result, str)
        assert len(result) > 0


class TestStyleVariants:
    def test_spiritual_style(self, opt):
        text = "The sacred mountain stands eternal."
        result = opt.optimize(text, style="spiritual", scene_position=0.5)
        assert isinstance(result, str)

    def test_none_style(self, opt):
        text = "The product launched in 2024."
        result = opt.optimize(text, style=None, scene_position=0.5)
        assert isinstance(result, str)

    def test_documentary_style(self, opt):
        text = "In 1969, humans first walked on the moon."
        result = opt.optimize(text, style="documentary", scene_position=0.5)
        assert isinstance(result, str)
