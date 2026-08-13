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
    LightingState,
    LocationState,
    PropState,
    SceneMode,
    SceneState,
    StoryState,
    TemporalMode,
    is_symbolic_mode,
    scene_mode_from_narrative_role,
)
from .normalization import (
    canonical_entity_id,
    detect_transfer_language,
    extract_transfer_target,
    normalize_location,
    normalize_time,
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

    _extinguish_pat = (
        r"\bextinguish"
        r"|\bblows? out\b"
        r"|\bgoes? out\b"
        r"|\bwent out\b"
        r"|\bdies? out\b"
        r"|\burned out\b"
        r"|\bflickered out\b"
        r"|\bgave out\b"
    )
    _lamp_obj_pat = r"\b(lamp|lantern|flame|torch|wick)\b"

    # Oil lamp / lamp patterns (oil mentioned explicitly)
    if re.search(r"\b(oil|fuel|fills|refills|pours oil)\b", text) and re.search(
        _lamp_obj_pat, text
    ):
        if re.search(r"\bpours?\b|\bfills?\b|\brefills?\b|\breplenish", text):
            result["oil_lamp"] = "full"
        if re.search(
            r"\blights?\b|\blights? (up|the|a)\b|\bkindles?\b|\bignites?\b", text
        ):
            result["oil_lamp"] = "lit"
        if re.search(_extinguish_pat, text):
            result["oil_lamp"] = "unlit"
    # Lamp/flame extinguished — even without "oil" keyword
    if re.search(_lamp_obj_pat, text) and re.search(_extinguish_pat, text):
        result["oil_lamp"] = "unlit"
    # Runs out of oil: "ran/runs out of oil", "out of oil", "no more oil", "last drop of oil"
    if re.search(r"\b(runs? out|out of|no more|last drop)\b.{0,20}\boil\b", text):
        result["oil_lamp"] = "empty"
    # Oil exhausted with reversed word order: "oil was gone", "oil had run out", "oil is gone"
    if re.search(r"\boil\b.{0,25}\b(was gone|had run out|is gone|ran out)\b", text):
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
        # Possessive name + life ended: "traveler's life ended"
        r"(\w[\w ]+?'s)\s+life\s+(?:ended|was\s+over|came\s+to\s+an\s+end|ran\s+out)",
        # Third-person death statements: "death of X"
        r"(?:death|murder|execution|sacrifice)\s+of\s+(\w[\w ]+)",
        # Consumption by danger: "consumed by the forest" / "taken by" (animals)
        r"(\w[\w ]+?)\s+(?:was\s+consumed|was\s+taken|was\s+lost)\s+(?:in|by|to)\s+the\s+(?:forest|darkness|animals)",
        # "lost his/her/their life"
        r"(\w[\w ]+?)\s+lost\s+(?:his|her|their)\s+life",
        # "was slain / was killed / was murdered"
        r"(\w[\w ]+?)\s+(?:was\s+slain|was\s+killed|was\s+murdered)",
        # "met his/her/their end" / "met his/her/their death"
        r"(\w[\w ]+?)\s+met\s+(?:his|her|their)\s+(?:end|death)",
    ]

    for pat in death_patterns:
        for m in re.finditer(pat, text):
            # For patterns with a capture group, use it; otherwise mark implicit death
            if m.lastindex and m.lastindex >= 1:
                raw = m.group(1).strip()
                # Strip possessive 's from name tokens (e.g. "traveler's" → "traveler")
                if raw.lower().endswith("'s"):
                    raw = raw[:-2].strip()
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
        scene_analysis: Any | None,  # SceneAnalysis or None
        narrative_role: str = "STORY",
        scene_metadata: dict | None = None,
    ) -> None:
        """Update story state from one scene's narration + analysis."""
        mode = scene_mode_from_narrative_role(narrative_role)
        self.story_state.scene_modes[scene_idx] = mode

        # Determine temporal mode from metadata or narrative_role
        temporal_mode = TemporalMode.LITERAL
        effective_mode = mode
        if scene_metadata:
            raw_temporal = scene_metadata.get("temporal_mode", "")
            if raw_temporal:
                try:
                    temporal_mode = TemporalMode(raw_temporal.upper())
                except ValueError:
                    temporal_mode = TemporalMode.LITERAL
            if temporal_mode == TemporalMode.SYMBOLIC_RECONSTRUCTION:
                effective_mode = SceneMode.SYMBOLIC

        # In symbolic scenes: don't update character/prop states — they're
        # conceptual appearances, not story events.
        if is_symbolic_mode(effective_mode):
            snapshot = self._snapshot(
                scene_idx,
                effective_mode,
                temporal_mode,
                [],
                [],
                scene_metadata=scene_metadata,
            )
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
                    if (
                        hasattr(scene_analysis, "primary_subject")
                        and scene_analysis.primary_subject
                    ):
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
            cid = canonical_entity_id(name_token)
            # Match by canonical_id prefix to handle e.g. "the traveler" → "the_traveler" / "traveler"
            for existing_cid, char_state in self.story_state.characters.items():
                if (
                    existing_cid == cid
                    or existing_cid.endswith(cid)
                    or cid.endswith(existing_cid)
                ):
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

        # Detect ownership transfers from narration
        if detect_transfer_language(narration):
            for prop_cid, prop in self.story_state.props.items():
                target_char = extract_transfer_target(narration, prop.name)
                if target_char is None:
                    # Fallback: try canonical_id tokens
                    target_char = extract_transfer_target(
                        narration, prop.canonical_id.replace("_", " ")
                    )
                if target_char and target_char in self.story_state.characters:
                    old_owner = prop.owner
                    if old_owner != target_char:
                        prop.transfer_history.append(
                            {
                                "from": old_owner,
                                "to": target_char,
                                "scene": scene_idx,
                                "narration_snippet": narration[:100],
                            }
                        )
                        prop.owner = target_char
                        target_char_state = self.story_state.characters.get(target_char)
                        if target_char_state and prop.canonical_id not in target_char_state.possessions:
                            target_char_state.possessions.append(prop.canonical_id)

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

        # Update canonical temporal/location/lighting state from scene_metadata
        if scene_metadata:
            raw_time = scene_metadata.get("time_of_day", "")
            if raw_time:
                self.story_state.current_time_of_day = normalize_time(raw_time)

            raw_loc = scene_metadata.get("location", "")
            if raw_loc:
                loc_id = normalize_location(raw_loc)
                if not self.story_state.current_location.location_id:
                    self.story_state.current_location = LocationState(
                        location_id=loc_id,
                        canonical_name=raw_loc,
                    )
                else:
                    self.story_state.current_location.location_id = loc_id
                    self.story_state.current_location.canonical_name = raw_loc

            raw_lighting = scene_metadata.get("lighting", "")
            if raw_lighting:
                self.story_state.current_lighting = LightingState(
                    time_of_day=self.story_state.current_time_of_day,
                    derived_description=raw_lighting,
                )
            elif self.story_state.current_time_of_day:
                self.story_state.current_lighting.update(
                    self.story_state.current_time_of_day
                )

        snapshot = self._snapshot(
            scene_idx,
            effective_mode,
            temporal_mode,
            allowed,
            list(self.story_state.props),
            scene_metadata=scene_metadata,
        )
        self.story_state.scene_history[scene_idx] = snapshot

    def _snapshot(
        self,
        scene_idx: int,
        mode: SceneMode,
        temporal_mode: TemporalMode,
        chars_present: list[str],
        props_present: list[str],
        scene_metadata: dict | None = None,
    ) -> SceneState:
        location = LocationState()
        lighting = LightingState()
        time_of_day = ""
        if scene_metadata:
            raw_loc = scene_metadata.get("location", "")
            if raw_loc:
                location = LocationState(
                    location_id=normalize_location(raw_loc),
                    canonical_name=raw_loc,
                )
            raw_time = scene_metadata.get("time_of_day", "")
            if raw_time:
                time_of_day = normalize_time(raw_time)
                lighting = LightingState(time_of_day=time_of_day)
                raw_light_desc = scene_metadata.get("lighting", "")
                if raw_light_desc:
                    lighting.derived_description = raw_light_desc
                else:
                    from .normalization import derive_lighting

                    lighting.derived_description = derive_lighting(time_of_day)
        return SceneState(
            scene_id=scene_idx,
            mode=mode,
            characters_present=chars_present,
            props_present=props_present,
            character_states={
                k: copy.deepcopy(v) for k, v in self.story_state.characters.items()
            },
            prop_states={
                k: copy.deepcopy(v) for k, v in self.story_state.props.items()
            },
            temporal_mode=temporal_mode,
            time_of_day=time_of_day or self.story_state.current_time_of_day,
            lighting=lighting if lighting.derived_description else self.story_state.current_lighting,
            location=location if location.location_id else self.story_state.current_location,
            environment=(scene_metadata or {}).get("environment", ""),
            weather=(scene_metadata or {}).get("weather", ""),
        )


def _get_scene_metadata(scene: Any) -> dict:
    """Extract canonical state metadata from a scene object."""
    meta: dict[str, Any] = {}
    if hasattr(scene, "scene_state") and scene.scene_state:
        ss = scene.scene_state
        if hasattr(ss, "time_of_day"):
            meta["time_of_day"] = ss.time_of_day or ""
        if hasattr(ss, "location"):
            loc = ss.location
            if hasattr(loc, "canonical_name"):
                meta["location"] = loc.canonical_name or ""
            elif hasattr(loc, "location_id"):
                meta["location"] = loc.location_id or ""
        if hasattr(ss, "environment"):
            meta["environment"] = ss.environment or ""
        if hasattr(ss, "weather"):
            meta["weather"] = ss.weather or ""
        if hasattr(ss, "lighting"):
            lighting = ss.lighting
            if hasattr(lighting, "derived_description") and lighting.derived_description:
                meta["lighting"] = lighting.derived_description
        if hasattr(ss, "temporal_mode"):
            raw = ss.temporal_mode
            if isinstance(raw, str):
                meta["temporal_mode"] = raw
            elif hasattr(raw, "value"):
                meta["temporal_mode"] = raw.value
    elif isinstance(scene, dict):
        ss = scene.get("scene_state") or {}
        if isinstance(ss, dict):
            meta["time_of_day"] = ss.get("time_of_day", "") or ""
            loc = ss.get("location") or {}
            if isinstance(loc, dict):
                meta["location"] = loc.get("canonical_name", "") or loc.get("location_id", "") or ""
            meta["environment"] = ss.get("environment", "") or ""
            meta["weather"] = ss.get("weather", "") or ""
            lighting = ss.get("lighting") or {}
            if isinstance(lighting, dict):
                desc = lighting.get("derived_description") or lighting.get("time_of_day", "")
                if desc:
                    meta["lighting"] = desc
            raw_temporal = ss.get("temporal_mode", "")
            if raw_temporal:
                meta["temporal_mode"] = raw_temporal
    return meta


def _get_scene_idx(enum_idx: int, scene: Any) -> int:
    """Resolve a scene's natural index from the scene object.

    Production scene dicts carry scene["index"] (1-based); test FakeScene objects
    have no "index" attribute so the 0-based enumerate position is returned.
    Using scene["index"] aligns scene_history / scene_modes keys with the
    get_story_context_for_scene(scene["index"]) call in the planner, fixing
    the off-by-one that caused METAPHOR scenes to receive LITERAL context.
    """
    if isinstance(scene, dict):
        return scene.get("index", enum_idx)
    raw = getattr(scene, "index", None)
    if isinstance(raw, int):
        return raw
    return enum_idx


def build_story_state(
    scenes: list[Any],
    scene_analysis_map: dict[int, Any],
) -> StoryState:
    """Build StoryState for all scenes.

    Args:
        scenes: list of Scene (or dict-like) objects with narration field
        scene_analysis_map: mapping from scene index to SceneAnalysis.  The
            production call site uses 1-based keys (scene["index"]); unit tests
            use 0-based keys (FakeScene via enumerate).  _get_scene_idx picks
            the correct key for each scene automatically.

    Returns:
        Populated StoryState with scene_history and character/prop states.
    """
    tracker = StoryStateTracker()
    for enum_idx, scene in enumerate(scenes):
        scene_idx = _get_scene_idx(enum_idx, scene)

        # Support both Pydantic Scene and plain dicts
        if hasattr(scene, "narration"):
            narration = scene.narration or ""
        else:
            narration = scene.get("narration", "")

        # narrative_role lives in visual_metadata
        narrative_role = "STORY"
        if hasattr(scene, "visual_metadata") and scene.visual_metadata:
            narrative_role = (
                getattr(scene.visual_metadata, "narrative_role", "STORY") or "STORY"
            )
        elif isinstance(scene, dict):
            vm = scene.get("visual_metadata") or {}
            narrative_role = vm.get("narrative_role", "STORY") or "STORY"

        scene_metadata = _get_scene_metadata(scene)

        analysis = scene_analysis_map.get(scene_idx)
        tracker.process_scene(
            scene_idx,
            narration,
            analysis,
            narrative_role,
            scene_metadata=scene_metadata,
        )

    return tracker.story_state
