"""Scene continuity — story state tracking and visual prompt validation.

Pipeline position:
  narration → scene_analysis → build_story_state()
  → inject story context → visual_prompt generation
  → ContinuityValidator.validate_all() → log findings
"""

from .action_grounding import (
    ActionConstraint,
    build_action_constraints_block,
    extract_action_constraints,
)
from .diagnostics import (
    ContinuityReport,
    SceneContinuityStatus,
)
from .models import (
    CharacterState,
    ContinuityFinding,
    LocationState,
    LightingState,
    PropState,
    SceneMode,
    SceneState,
    StoryState,
    TemporalMode,
    ValidationLevel,
    scene_mode_from_narrative_role,
)
from .normalization import (
    canonical_entity_id,
    detect_time_jump,
    detect_transfer_language,
    derive_lighting,
    extract_transfer_target,
    is_terminal_state,
    normalize_location,
    normalize_state,
    normalize_time,
    state_family,
    time_progression_allowed,
)
from .prompt_validator import (
    validate_prompt_against_state,
)
from .tracker import StoryStateTracker, build_story_state
from .transitions import (
    ContinuityViolation,
    ObjectStateTransitionRule,
    get_default_rule,
    validate_scene_transition,
)
from .validator import ContinuityValidator

__all__ = [
    "ActionConstraint",
    "build_action_constraints_block",
    "build_story_state",
    "canonical_entity_id",
    "CharacterState",
    "ContinuityFinding",
    "ContinuityReport",
    "ContinuityViolation",
    "ContinuityValidator",
    "detect_time_jump",
    "detect_transfer_language",
    "derive_lighting",
    "extract_action_constraints",
    "extract_transfer_target",
    "get_default_rule",
    "is_terminal_state",
    "LightingState",
    "LocationState",
    "normalize_location",
    "normalize_state",
    "normalize_time",
    "ObjectStateTransitionRule",
    "PropState",
    "SceneContinuityStatus",
    "SceneMode",
    "SceneState",
    "state_family",
    "StoryState",
    "StoryStateTracker",
    "TemporalMode",
    "time_progression_allowed",
    "validate_prompt_against_state",
    "validate_scene_transition",
    "ValidationLevel",
    "scene_mode_from_narrative_role",
]
