"""LLM task identifiers for task-specific model selection."""

from __future__ import annotations

from enum import Enum


class LLMTask(str, Enum):
    SCRIPT_ANALYSIS = "script_analysis"
    SCRIPT_WRITING = "script_writing"
    SCRIPT_REFINEMENT = "script_refinement"
    SCENE_PLANNING = "scene_planning"
    VISUAL_PROMPTS = "visual_prompts"
    VISUAL_REFINEMENT = "visual_refinement"
    QA = "qa"
