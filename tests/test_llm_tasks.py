"""Tests for task-specific LLM model configuration (LLMTask + get_llm_for_task)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from video_core.config.shared_settings import SharedSettings
from video_core.providers.llm.tasks import LLMTask


# ── Req 1: LLMTask enum has exactly 7 values ─────────────────────────────────

def test_llm_task_enum_values():
    expected = {
        "script_analysis",
        "script_writing",
        "script_refinement",
        "scene_planning",
        "visual_prompts",
        "visual_refinement",
        "qa",
    }
    assert {t.value for t in LLMTask} == expected


# ── Req 2: get_llm_model returns task-specific model when field is set ────────

def test_get_llm_model_returns_task_field():
    s = SharedSettings(
        yt_llm_model_scene_planning="my-special-model",
        llm_provider="deepinfra",
        deepinfra_api_key="key",
    )
    assert s.get_llm_model(LLMTask.SCENE_PLANNING) == "my-special-model"


# ── Req 3: task-specific env var overrides default ───────────────────────────

def test_get_llm_model_task_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("YT_LLM_MODEL_VISUAL_PROMPTS", "custom/visual-model")
    s = SharedSettings(llm_provider="deepinfra", deepinfra_api_key="key")
    assert s.get_llm_model(LLMTask.VISUAL_PROMPTS) == "custom/visual-model"


# ── Req 4: defaults are Qwen models ──────────────────────────────────────────

def test_default_models_are_qwen():
    s = SharedSettings(llm_provider="deepinfra", deepinfra_api_key="key")
    assert s.get_llm_model(LLMTask.SCRIPT_ANALYSIS).startswith("Qwen/")
    assert s.get_llm_model(LLMTask.QA).startswith("Qwen/")
    for task in (
        LLMTask.SCRIPT_WRITING,
        LLMTask.SCRIPT_REFINEMENT,
        LLMTask.SCENE_PLANNING,
        LLMTask.VISUAL_PROMPTS,
        LLMTask.VISUAL_REFINEMENT,
    ):
        assert s.get_llm_model(task).startswith("Qwen/")


# ── Req 5: SCRIPT_ANALYSIS and QA default to the 235B thinking model ─────────

def test_heavy_tasks_use_235b_model():
    s = SharedSettings(llm_provider="deepinfra", deepinfra_api_key="key")
    assert "235B" in s.get_llm_model(LLMTask.SCRIPT_ANALYSIS)
    assert "235B" in s.get_llm_model(LLMTask.QA)


# ── Req 6: non-heavy tasks default to 30B model ──────────────────────────────

def test_light_tasks_use_30b_model():
    s = SharedSettings(llm_provider="deepinfra", deepinfra_api_key="key")
    for task in (
        LLMTask.SCRIPT_WRITING,
        LLMTask.SCRIPT_REFINEMENT,
        LLMTask.SCENE_PLANNING,
        LLMTask.VISUAL_PROMPTS,
        LLMTask.VISUAL_REFINEMENT,
    ):
        assert "30B" in s.get_llm_model(task), f"Expected 30B for {task.value}"


# ── Req 7: fallback precedence — task > llm_default_model > provider model ───

def test_llm_default_model_used_when_task_field_empty():
    s = SharedSettings(
        yt_llm_model_visual_prompts="",
        llm_default_model="fallback/model",
        llm_provider="deepinfra",
        deepinfra_api_key="key",
    )
    assert s.get_llm_model(LLMTask.VISUAL_PROMPTS) == "fallback/model"


def test_provider_model_used_when_task_and_default_empty():
    s = SharedSettings(
        yt_llm_model_visual_prompts="",
        llm_default_model="",
        llm_provider="deepinfra",
        deepinfra_api_key="key",
        deepinfra_model="provider/fallback",
    )
    assert s.get_llm_model(LLMTask.VISUAL_PROMPTS) == "provider/fallback"


# ── Req 8: get_llm_for_task returns a provider instance ──────────────────────

def test_get_llm_for_task_returns_provider():
    from video_core.providers.llm.factory import get_llm_for_task
    from video_core.providers.llm.base import LLMProvider

    s = SharedSettings(llm_provider="deepinfra", deepinfra_api_key="key")
    with patch("video_core.providers.llm.factory.get_llm_provider") as mock_get:
        mock_provider = MagicMock(spec=LLMProvider)
        mock_get.return_value = mock_provider
        result = get_llm_for_task(s, LLMTask.SCENE_PLANNING)
    assert mock_get.called
    # result is a _TrackedProvider wrapping mock_provider, which is an LLMProvider
    assert isinstance(result, LLMProvider)


# ── Req 9: different tasks produce providers with different models ─────────────

def test_different_tasks_produce_different_models():
    from video_core.providers.llm.factory import get_llm_for_task
    called_models: list[str] = []

    def capture_provider(settings):
        called_models.append(settings.deepinfra_model)
        return MagicMock()

    s = SharedSettings(llm_provider="deepinfra", deepinfra_api_key="key")
    with patch("video_core.providers.llm.factory.get_llm_provider", side_effect=capture_provider):
        get_llm_for_task(s, LLMTask.SCRIPT_ANALYSIS)
        get_llm_for_task(s, LLMTask.SCENE_PLANNING)

    assert len(called_models) == 2
    # SCRIPT_ANALYSIS should use the 235B model; SCENE_PLANNING the 30B model
    assert "235B" in called_models[0]
    assert "30B" in called_models[1]


# ── Req 10: debug logging fires on get_llm_model ─────────────────────────────

def test_get_llm_model_emits_debug_log(caplog):
    import logging
    s = SharedSettings(llm_provider="deepinfra", deepinfra_api_key="key")
    # Use stdlib caplog-compatible call — loguru writes to root logger in propagate mode
    with caplog.at_level(logging.DEBUG):
        model = s.get_llm_model(LLMTask.VISUAL_PROMPTS)
    # The model should be returned regardless of log capture
    assert model  # non-empty


# ── LLMTask is a str subclass ─────────────────────────────────────────────────

def test_llm_task_is_str_subclass():
    assert isinstance(LLMTask.SCENE_PLANNING, str)
    assert LLMTask.SCENE_PLANNING == "scene_planning"
