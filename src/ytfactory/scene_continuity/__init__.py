"""Scene continuity — story state tracking and visual prompt validation.

Pipeline position:
  narration → scene_analysis → build_story_state()
  → inject story context → visual_prompt generation
  → ContinuityValidator.validate_all() → log findings
"""

from .action_grounding import ActionConstraint, build_action_constraints_block, extract_action_constraints
from .models import (
    CharacterState,
    ContinuityFinding,
    PropState,
    SceneMode,
    SceneState,
    StoryState,
    ValidationLevel,
    scene_mode_from_narrative_role,
)
from .tracker import StoryStateTracker, build_story_state
from .validator import ContinuityValidator

__all__ = [
    "ActionConstraint",
    "build_action_constraints_block",
    "build_story_state",
    "CharacterState",
    "ContinuityFinding",
    "ContinuityValidator",
    "extract_action_constraints",
    "PropState",
    "SceneMode",
    "SceneState",
    "StoryState",
    "StoryStateTracker",
    "ValidationLevel",
    "scene_mode_from_narrative_role",
]
