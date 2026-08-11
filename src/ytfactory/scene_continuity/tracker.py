"""StoryStateTracker — builds StoryState from scenes + scene_analysis_map.

Usage (in scene_planner_node, after analysis map is built):
    from ytfactory.scene_continuity import build_story_state
    story_state = build_story_state(scenes, scene_analysis_map)
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from .models import (
    CharacterState,
    PropState,
    SceneMode,
    SceneState,
    StoryState,
    is_symbolic_mode,
    scene_mode_from_narrative_role,
)


def _slugify(name: str) -> str:
    """Normalize a character/prop name to a canonical_id slug."""
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")


def _extract_prop_state_from_narration(narration: str) -> dict[str, str]:
    """Heuristic extraction of prop state changes from narration text.

    Returns {canonical_prop_id: new_state}. Only triggers on obvious patterns
    to avoid false positives.
    """
    result: dict[str, str] = {}
    text = narration.lower()

    _extinguish_pat = r"\bextinguish|\bblows? out\b|\bgoes out\b|\bdies? out\b"
    _lamp_obj_pat = r"\b(lamp|lantern|flame|torch|wick)\b"

    # Oil lamp / lamp patterns (oil mentioned explicitly)
    if re.search(r"\b(oil|fuel|fills|refills|pours oil)\b", text) and re.search(_lamp_obj_pat, text):
        if re.search(r"\bpours?\b|\bfills?\b|\brefills?\b|\breplenish", text):
            result["oil_lamp"] = "full"
        if re.search(r"\blights?\b|\blights? (up|the|a)\b|\bkindles?\b|\bignites?\b", text):
            result["oil_lamp"] = "lit"
        if re.search(_extinguish_pat, text):
            result["oil_lamp"] = "unlit"
    # Lamp/flame extinguished — even without "oil" keyword
    if re.search(_lamp_obj_pat, text) and re.search(_extinguish_pat, text):
        result["oil_lamp"] = "unlit"
    # Runs out of oil
    if re.search(r"\b(runs? out|out of|no more|last drop)\b.{0,20}\boil\b", text):
        result["oil_lamp"] = "empty"

    # Flask / container patterns
    if re.search(r"\bflask\b|\bcanteen\b|\bpouch\b", text):
        if re.search(r"\bempties?\b|\bdrains?\b|\bexhausts?\b|\bused up\b", text):
            result["flask"] = "empty"
        if re.search(r"\bfills?\b|\breplenish\b", text):
            result["flask"] = "full"

    return result


def _infer_death_from_narration(narration: str) -> list[str]:
    """Heuristic detection of character death/departure in narration.

    Returns list of lowercased name tokens that appear to die/disappear.
    Very conservative — only obvious explicit patterns.
    """
    departed: list[str] = []
    text = narration.lower()
    death_patterns = [
        # Explicit death verbs
        r"(\w[\w ]+?)\s+(?:dies?|died|falls?\s+dead|is\s+killed|perishes?|breathes?\s+his\s+last|breathes?\s+her\s+last|passes?\s+away|collapses?\s+dead)",
        # Ownership/life-ending euphemisms: "his life ended", "her life was over"
        r"(?:his|her|their)\s+life\s+(?:ended|was\s+over|came\s+to\s+an\s+end|ran\s+out)",
        # Third-person death statements: "death of X"
        r"(?:death|murder|execution|sacrifice)\s+of\s+(\w[\w ]+)",
        # Consumption by danger: "consumed by the forest" / "taken by" (animals)
        r"(\w[\w ]+?)\s+(?:was\s+consumed|was\s+taken|was\s+lost)\s+(?:in|by|to)\s+the\s+(?:forest|darkness|animals)",
    ]

    for pat in death_patterns:
        for m in re.finditer(pat, text):
            # For patterns with a capture group, use it; otherwise mark implicit death
            if m.lastindex and m.lastindex >= 1:
                raw = m.group(1).strip()
                if len(raw) > 2:
                    departed.append(raw)
            else:
                # Implicit death (pronoun-based) — mark with sentinel to let caller
                # resolve which characters are "he/she/they" in context
                departed.append("__implicit__")

    return departed


@dataclass
class StoryStateTracker:
    """Incrementally builds StoryState scene by scene.

    Call `process_scene()` for each scene in order, then access `.story_state`.
    """

    story_state: StoryState = field(default_factory=StoryState)

    def process_scene(
        self,
        scene_idx: int,
        narration: str,
        scene_analysis: Any | None,   # SceneAnalysis or None
        narrative_role: str = "STORY",
    ) -> None:
        """Update story state from one scene's narration + analysis."""
        mode = scene_mode_from_narrative_role(narrative_role)
        self.story_state.scene_modes[scene_idx] = mode

        # In symbolic scenes: don't update character/prop states — they're
        # conceptual appearances, not story events.
        if is_symbolic_mode(mode):
            snapshot = self._snapshot(scene_idx, mode, [], [])
            self.story_state.scene_history[scene_idx] = snapshot
            return

        allowed: list[str] = []
        if scene_analysis is not None:
            # scene_analysis.allowed_characters may be a list or None
            raw_allowed = getattr(scene_analysis, "allowed_characters", None) or []
            allowed = [c for c in raw_allowed if c]

        # Introduce new characters
        for char_name in allowed:
            cid = _slugify(char_name)
            if cid not in self.story_state.characters:
                role = ""
                if scene_analysis is not None:
                    if hasattr(scene_analysis, "primary_subject") and scene_analysis.primary_subject:
                        if _slugify(scene_analysis.primary_subject) == cid:
                            role = "protagonist"
                self.story_state.characters[cid] = CharacterState(
                    name=char_name,
                    canonical_id=cid,
                    role=role,
                    alive=True,
                    present_in_story=True,
                    scene_introduced=scene_idx,
                    scene_last_seen=scene_idx,
                )
            else:
                state = self.story_state.characters[cid]
                state.scene_last_seen = scene_idx

        # Detect deaths
        for name_token in _infer_death_from_narration(narration):
            if name_token == "__implicit__":
                # Pronoun-based death: mark the most recently active alive protagonist
                # (the character last seen in a STORY scene and still alive)
                protagonist = None
                for char_state in sorted(
                    self.story_state.characters.values(),
                    key=lambda c: c.scene_last_seen,
                    reverse=True,
                ):
                    if char_state.alive and char_state.present_in_story:
                        protagonist = char_state
                        break
                if protagonist is not None:
                    protagonist.alive = False
                    protagonist.present_in_story = False
                continue
            cid = _slugify(name_token)
            # Match by canonical_id prefix to handle e.g. "the traveler" → "the_traveler" / "traveler"
            for existing_cid, char_state in self.story_state.characters.items():
                if existing_cid == cid or existing_cid.endswith(cid) or cid.endswith(existing_cid):
                    char_state.alive = False
                    char_state.present_in_story = False
                    break

        # Update prop states from narration
        prop_changes = _extract_prop_state_from_narration(narration)
        for prop_cid, new_state in prop_changes.items():
            if prop_cid not in self.story_state.props:
                # Extract display name from prop_cid
                display_name = prop_cid.replace("_", " ")
                self.story_state.props[prop_cid] = PropState(
                    name=display_name,
                    canonical_id=prop_cid,
                    current_state=new_state,
                    scene_introduced=scene_idx,
                    scene_last_modified=scene_idx,
                )
            else:
                existing = self.story_state.props[prop_cid]
                existing.current_state = new_state
                existing.scene_last_modified = scene_idx

        # Also pick up scene_objects from analysis for prop tracking
        if scene_analysis is not None:
            scene_objects = getattr(scene_analysis, "scene_objects", None) or []
            for obj in scene_objects:
                obj_cid = _slugify(obj)
                if obj_cid and obj_cid not in self.story_state.props:
                    self.story_state.props[obj_cid] = PropState(
                        name=obj,
                        canonical_id=obj_cid,
                        scene_introduced=scene_idx,
                        scene_last_modified=scene_idx,
                    )

        snapshot = self._snapshot(scene_idx, mode, allowed, list(self.story_state.props))
        self.story_state.scene_history[scene_idx] = snapshot

    def _snapshot(
        self,
        scene_idx: int,
        mode: SceneMode,
        chars_present: list[str],
        props_present: list[str],
    ) -> SceneState:
        return SceneState(
            scene_id=scene_idx,
            mode=mode,
            characters_present=chars_present,
            props_present=props_present,
            character_states={k: copy.deepcopy(v) for k, v in self.story_state.characters.items()},
            prop_states={k: copy.deepcopy(v) for k, v in self.story_state.props.items()},
        )


def build_story_state(
    scenes: list[Any],
    scene_analysis_map: dict[int, Any],
) -> StoryState:
    """Build StoryState for all scenes.

    Args:
        scenes: list of Scene (or dict-like) objects with narration field
        scene_analysis_map: mapping from 0-based scene index to SceneAnalysis

    Returns:
        Populated StoryState with scene_history and character/prop states.
    """
    tracker = StoryStateTracker()
    for idx, scene in enumerate(scenes):
        # Support both Pydantic Scene and plain dicts
        if hasattr(scene, "narration"):
            narration = scene.narration or ""
        else:
            narration = scene.get("narration", "")

        # narrative_role lives in visual_metadata
        narrative_role = "STORY"
        if hasattr(scene, "visual_metadata") and scene.visual_metadata:
            narrative_role = getattr(scene.visual_metadata, "narrative_role", "STORY") or "STORY"
        elif isinstance(scene, dict):
            vm = scene.get("visual_metadata") or {}
            narrative_role = vm.get("narrative_role", "STORY") or "STORY"

        analysis = scene_analysis_map.get(idx)
        tracker.process_scene(idx, narration, analysis, narrative_role)

    return tracker.story_state
