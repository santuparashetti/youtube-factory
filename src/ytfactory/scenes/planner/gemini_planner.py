# Backward-compatibility shim — canonical class is LLMScenePlanner in llm_planner.py.
from ytfactory.scenes.planner.llm_planner import LLMScenePlanner as GeminiScenePlanner

__all__ = ["GeminiScenePlanner"]
