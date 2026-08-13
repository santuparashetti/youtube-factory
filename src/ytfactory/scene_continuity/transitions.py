"""State transition validation for continuity enforcement.

Provides:
- ObjectStateTransitionRule: configurable allowed transitions per object type
- validate_scene_transition: generic scene-to-scene state transition validator
- ContinuityViolation: structured violation result
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import (
    ContinuityFinding,
    SceneMode,
    StoryState,
    ValidationLevel,
    is_symbolic_mode,
)
from .normalization import (
    detect_transfer_language,
    normalize_state,
    time_progression_allowed,
)


# ---------------------------------------------------------------------------
# ContinuityViolation
# ---------------------------------------------------------------------------


@dataclass
class ContinuityViolation:
    """Structured continuity violation from state transition validation."""

    code: str  # e.g. "CONT_001", "CONT_DEATH_001"
    severity: ValidationLevel  # WARNING | ERROR | CRITICAL
    scene_index: int
    entity: str  # entity id that violated continuity
    previous_state: str = ""
    proposed_state: str = ""
    reason: str = ""
    suggested_fix: str = ""
    category: str = "STATE_TRANSITION"

    def to_finding(self) -> ContinuityFinding:
        """Convert to a ContinuityFinding for the existing validator interface."""
        return ContinuityFinding(
            scene_id=self.scene_index,
            level=self.severity,
            category=self.category,
            message=f"[{self.code}] {self.reason}",
            suggested_fix=self.suggested_fix,
        )


# ---------------------------------------------------------------------------
# Object state transition rules
# ---------------------------------------------------------------------------


@dataclass
class ObjectStateTransitionRule:
    """Configurable allowed transitions for a class of objects."""

    object_type: str = "generic"
    allowed_transitions: list[tuple[str, str]] = field(default_factory=list)
    terminal_states: list[str] = field(default_factory=list)
    initial_state: str = ""

    def can_transition(self, from_state: str, to_state: str) -> tuple[bool, str]:
        """Return (allowed, reason)."""
        from_norm = normalize_state(from_state) if from_state else self.initial_state
        to_norm = normalize_state(to_state) if to_state else ""
        if not from_norm or not to_norm:
            return True, ""
        if from_norm == to_norm:
            return True, ""
        if from_norm in self.terminal_states:
            return (
                False,
                f"Object in terminal state '{from_norm}' cannot transition to '{to_norm}'.",
            )
        if self.allowed_transitions:
            if (from_norm, to_norm) not in self.allowed_transitions:
                return (
                    False,
                    f"Transition '{from_norm}' → '{to_norm}' not in allowed transitions "
                    f"for {self.object_type}.",
                )
        return True, ""


# Default transition rules for common object types
_DEFAULT_RULES: dict[str, ObjectStateTransitionRule] = {
    "container": ObjectStateTransitionRule(
        object_type="container",
        allowed_transitions=[
            ("empty", "full"),
            ("full", "empty"),
            ("closed", "open"),
            ("open", "closed"),
        ],
        terminal_states=["destroyed", "lost"],
        initial_state="closed",
    ),
    "light_source": ObjectStateTransitionRule(
        object_type="light_source",
        allowed_transitions=[
            ("unlit", "lit"),
            ("lit", "unlit"),
        ],
        terminal_states=["destroyed", "exhausted", "lost"],
        initial_state="unlit",
    ),
    "consumable": ObjectStateTransitionRule(
        object_type="consumable",
        allowed_transitions=[
            ("full", "empty"),
            ("empty", "full"),
        ],
        terminal_states=["consumed", "exhausted", "lost"],
        initial_state="full",
    ),
    "weapon": ObjectStateTransitionRule(
        object_type="weapon",
        allowed_transitions=[],
        terminal_states=["destroyed", "lost"],
        initial_state="",
    ),
    "document": ObjectStateTransitionRule(
        object_type="document",
        allowed_transitions=[
            ("unread", "read"),
            ("sealed", "opened"),
            ("opened", "sealed"),
        ],
        terminal_states=["destroyed", "lost", "burned"],
        initial_state="unread",
    ),
}


def get_default_rule(object_type: str) -> ObjectStateTransitionRule:
    """Get a default transition rule by object type, or return a generic one."""
    key = object_type.lower().replace(" ", "_")
    return _DEFAULT_RULES.get(key, ObjectStateTransitionRule(object_type=object_type))


# ---------------------------------------------------------------------------
# Scene transition validation
# ---------------------------------------------------------------------------


def validate_scene_transition(
    previous_state: StoryState,
    proposed_state: StoryState,
    scene_index: int,
    scene_mode: SceneMode = SceneMode.LITERAL,
    narration: str = "",
    scene_analysis: Any = None,
) -> list[ContinuityViolation]:
    """Validate a scene-to-scene state transition.

    Args:
        previous_state: accumulated StoryState BEFORE this scene
        proposed_state: StoryState proposed for AFTER this scene
        scene_index: current scene index
        scene_mode: LITERAL or symbolic
        narration: current scene narration
        scene_analysis: optional scene analysis with allowed_characters etc.

    Returns:
        List of ContinuityViolation instances (empty = no violations)
    """
    violations: list[ContinuityViolation] = []

    if is_symbolic_mode(scene_mode):
        return violations

    char_states_before, prop_states_before = previous_state.get_state_before_scene(
        scene_index
    )
    char_states_after = proposed_state.characters
    prop_states_after = proposed_state.props

    # Gather known character IDs
    # (reserved for future entity-resolution checks)
    set(char_states_before.keys()) | set(char_states_after.keys())

    # ── Character death guard ─────────────────────────────────────────────
    for cid, after_state in char_states_after.items():
        before_state = char_states_before.get(cid)
        if before_state is None:
            continue
        if before_state.alive and not after_state.alive:
            violations.append(
                ContinuityViolation(
                    code="CONT_DEATH_001",
                    severity=ValidationLevel.ERROR,
                    scene_index=scene_index,
                    entity=cid,
                    previous_state="ALIVE",
                    proposed_state="DEAD",
                    reason=f"Character '{before_state.name}' died in scene {scene_index}.",
                    suggested_fix="Ensure narration explicitly describes the death event.",
                    category="CHARACTER_DEATH",
                )
            )
        if not before_state.alive and after_state.alive:
            violations.append(
                ContinuityViolation(
                    code="CONT_DEATH_002",
                    severity=ValidationLevel.CRITICAL,
                    scene_index=scene_index,
                    entity=cid,
                    previous_state="DEAD",
                    proposed_state="ALIVE",
                    reason=(
                        f"Character '{before_state.name}' resurrected in scene {scene_index}. "
                        f"Dead characters cannot return alive in LITERAL scenes."
                    ),
                    suggested_fix=(
                        "Remove the character from the prompt, or mark this scene "
                        "SYMBOLIC_RECONSTRUCTION if it is a memory/flashback."
                    ),
                    category="CHARACTER_RESURRECTION",
                )
            )

    # ── Character presence guard ─────────────────────────────────────────
    if scene_analysis is not None:
        raw = getattr(scene_analysis, "allowed_characters", None) or []
        [c for c in raw if c]  # reserved for future presence checks

    for cid, after_state in char_states_after.items():
        before_state = char_states_before.get(cid)
        if before_state is None:
            continue
        if before_state.present_in_story and not after_state.present_in_story:
            if after_state.alive:
                violations.append(
                    ContinuityViolation(
                        code="CONT_PRESENCE_001",
                        severity=ValidationLevel.ERROR,
                        scene_index=scene_index,
                        entity=cid,
                        previous_state="PRESENT",
                        proposed_state="ABSENT",
                        reason=(
                            f"Character '{before_state.name}' became absent without "
                            f"narration support in scene {scene_index}."
                        ),
                        suggested_fix="Ensure narration establishes why the character left.",
                        category="CHARACTER_PRESENCE",
                    )
                )

    # ── Object ownership guard ────────────────────────────────────────────
    has_transfer_language = detect_transfer_language(narration or "")
    for prop_cid, after_prop in prop_states_after.items():
        before_prop = prop_states_before.get(prop_cid)
        if before_prop is None:
            if after_prop.owner and not has_transfer_language:
                violations.append(
                    ContinuityViolation(
                        code="CONT_OWN_001",
                        severity=ValidationLevel.ERROR,
                        scene_index=scene_index,
                        entity=prop_cid,
                        previous_state="NOT_OWNED",
                        proposed_state=f"OWNED_BY_{after_prop.owner}",
                        reason=(
                            f"Object '{after_prop.name}' suddenly owned by "
                            f"'{after_prop.owner}' without prior acquisition in scene {scene_index}."
                        ),
                        suggested_fix=(
                            "Establish a transfer event in narration, or set owner to empty."
                        ),
                        category="OBJECT_OWNERSHIP",
                    )
                )
            continue
        if before_prop.owner != after_prop.owner and after_prop.owner:
            if not has_transfer_language:
                violations.append(
                    ContinuityViolation(
                        code="CONT_OWN_002",
                        severity=ValidationLevel.ERROR,
                        scene_index=scene_index,
                        entity=prop_cid,
                        previous_state=f"OWNED_BY_{before_prop.owner or 'NONE'}",
                        proposed_state=f"OWNED_BY_{after_prop.owner}",
                        reason=(
                            f"Object '{after_prop.name}' changed owner from "
                            f"'{before_prop.owner}' to '{after_prop.owner}' without "
                            f"explicit transfer language in narration for scene {scene_index}."
                        ),
                        suggested_fix=(
                            "Add transfer language (gives, hands, receives, takes, etc.) "
                            "to the narration, or revert ownership."
                        ),
                        category="OBJECT_OWNERSHIP",
                    )
                )
    # ── Object state monotonicity ────────────────────────────────────────
    for prop_cid, after_prop in prop_states_after.items():
        before_prop = prop_states_before.get(prop_cid)
        if before_prop is None:
            continue
        if not before_prop.current_state or not after_prop.current_state:
            continue
        from_norm = normalize_state(before_prop.current_state)
        to_norm = normalize_state(after_prop.current_state)
        if from_norm == to_norm:
            continue
        rule = get_default_rule(prop_cid)
        ok, reason = rule.can_transition(from_norm, to_norm)
        if not ok:
            violations.append(
                ContinuityViolation(
                    code="CONT_PROP_001",
                    severity=ValidationLevel.ERROR,
                    scene_index=scene_index,
                    entity=prop_cid,
                    previous_state=from_norm,
                    proposed_state=to_norm,
                    reason=(
                        f"Object '{after_prop.name}' changed state from "
                        f"'{from_norm}' to '{to_norm}' without valid transition: {reason}"
                    ),
                    suggested_fix=(
                        "Ensure narration describes a valid state transition, "
                        "or revert to previous state."
                    ),
                    category="PROP_STATE_MONOTONICITY",
                )
            )

    # ── Temporal continuity ──────────────────────────────────────────────
    prev_time = ""
    if previous_state.scene_history:
        last_scene_id = max(k for k in previous_state.scene_history if k < scene_index)
        snap = previous_state.scene_history[last_scene_id]
        prev_time = getattr(snap, "time_of_day", "") or ""

    proposed_time = ""
    for snap in proposed_state.scene_history.values():
        if snap.scene_id == scene_index:
            proposed_time = getattr(snap, "time_of_day", "") or ""
            break

    if prev_time and proposed_time:
        ok, reason = time_progression_allowed(prev_time, proposed_time, narration or "")
        if not ok:
            violations.append(
                ContinuityViolation(
                    code="CONT_TEMPORAL_001",
                    severity=ValidationLevel.ERROR,
                    scene_index=scene_index,
                    entity="time_of_day",
                    previous_state=prev_time,
                    proposed_state=proposed_time,
                    reason=reason,
                    suggested_fix=(
                        "Add explicit time-jump narration, or adjust the time to "
                        "follow naturally from the previous scene."
                    ),
                    category="TEMPORAL_CONTINUITY",
                )
            )

    # ── Location continuity ──────────────────────────────────────────────
    prev_location = ""
    if previous_state.scene_history:
        last_scene_id = max(k for k in previous_state.scene_history if k < scene_index)
        snap = previous_state.scene_history[last_scene_id]
        loc = getattr(snap, "location", None)
        if loc is not None:
            prev_location = getattr(loc, "location_id", "") or ""

    proposed_location = ""
    for snap in proposed_state.scene_history.values():
        if snap.scene_id == scene_index:
            loc = getattr(snap, "location", None)
            if loc is not None:
                proposed_location = getattr(loc, "location_id", "") or ""
            break

    if prev_location and proposed_location:
        if prev_location != proposed_location:
            parent_prev = _get_parent_location(prev_location)
            parent_prop = _get_parent_location(proposed_location)
            if parent_prev and parent_prop and parent_prev != parent_prop:
                if not _detects_travel(narration or ""):
                    violations.append(
                        ContinuityViolation(
                            code="CONT_LOC_001",
                            severity=ValidationLevel.WARNING,
                            scene_index=scene_index,
                            entity="location",
                            previous_state=prev_location,
                            proposed_state=proposed_location,
                            reason=(
                                f"Location jumped from '{prev_location}' to "
                                f"'{proposed_location}' without travel narrative."
                            ),
                            suggested_fix=(
                                "Add travel/transition narration between these locations, "
                                "or confirm they are connected sub-locations."
                            ),
                            category="LOCATION_CONTINUITY",
                        )
                    )

    return violations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_parent_location(location_id: str) -> str:
    """Extract the parent location from a normalized location ID."""
    parts = location_id.split("_")
    if len(parts) > 1:
        return parts[0]
    return ""


def _detects_travel(narration: str) -> bool:
    """True if narration contains travel/transition language."""
    travel_terms = [
        r"\bwalked?\b",
        r"\bjourney(?:ed)?\b",
        r"\btravel(?:ed|s)?\b",
        r"\bmoved?\b",
        r"\bhead(?:ed)?\s+(?:to|toward|towards)\b",
        r"\bwent\s+(?:to|toward|towards|into|through|across)\b",
        r"\bcrossed?\b",
        r"\bpassed?\s+(?:through|by|into)\b",
        r"\bentered?\b",
        r"\bleft\b",
        r"\bdeparted?\b",
        r"\barrived?\b",
        r"\breached?\b",
        r"\bapproached?\b",
        r"\b rode\b",
        r"\briding\b",
        r"\btransition(?:ed)?\b",
        r"\bmade\s+(?:his|her|their)\s+way\b",
        r"\bset\s+out\b",
        r"\bcontinued?\s+(?:on|toward|towards)\b",
        r"\bproceeded?\b",
        r"\bventured?\b",
        r"\bstepped?\s+(?:into|through|outside|inside)\b",
        r"\bclimbed?\b",
        r"\bdescended?\b",
        r"\bcrossed?\s+(?:the|a)\b",
    ]
    lower = narration.lower()
    return any(re.search(pat, lower) for pat in travel_terms)
