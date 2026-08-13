"""ContinuityValidator — post-prompt validation of visual prompts against story state.

Reports WARNINGS and ERRORS; never blocks the pipeline.
"""

from __future__ import annotations

import re
from typing import Any

from .models import (
    ContinuityFinding,
    SceneMode,
    StoryState,
    ValidationLevel,
    is_symbolic_mode,
    scene_mode_from_narrative_role,
)


def _get_prompt(scene: Any) -> str:
    """Extract the visual prompt string from a scene object."""
    if hasattr(scene, "visual_prompt"):
        return scene.visual_prompt or ""
    if isinstance(scene, dict):
        return scene.get("visual_prompt", "")
    return ""


def _get_narration(scene: Any) -> str:
    if hasattr(scene, "narration"):
        return scene.narration or ""
    if isinstance(scene, dict):
        return scene.get("narration", "")
    return ""


def _get_narrative_role(scene: Any) -> str:
    if hasattr(scene, "visual_metadata") and scene.visual_metadata:
        return getattr(scene.visual_metadata, "narrative_role", "STORY") or "STORY"
    if isinstance(scene, dict):
        vm = scene.get("visual_metadata") or {}
        return vm.get("narrative_role", "STORY") or "STORY"
    return "STORY"


def _get_allowed_characters(scene: Any, scene_analysis: Any | None) -> list[str]:
    if scene_analysis is not None:
        raw = getattr(scene_analysis, "allowed_characters", None) or []
        return [c for c in raw if c]
    return []


def _get_forbidden_characters(scene: Any, scene_analysis: Any | None) -> list[str]:
    if scene_analysis is not None:
        raw = getattr(scene_analysis, "forbidden_characters", None) or []
        return [c for c in raw if c]
    return []


def _name_appears_in_prompt(name: str, prompt: str) -> bool:
    """Case-insensitive word-boundary check for a character name in a prompt."""
    # Handle multi-word names: check all words together and key nouns
    words = name.lower().split()
    prompt_lower = prompt.lower()
    # Full name match
    if name.lower() in prompt_lower:
        return True
    # Last significant word match (for "the Traveler" → "traveler")
    for word in words:
        if len(word) > 3:
            if re.search(r"\b" + re.escape(word) + r"\b", prompt_lower):
                return True
    return False


class ContinuityValidator:
    """Validate visual prompts against accumulated story state.

    Usage:
        validator = ContinuityValidator(story_state)
        findings = validator.validate_all(scenes, scene_analysis_map)
        for f in findings:
            logger.warning(str(f))
    """

    def __init__(self, story_state: StoryState) -> None:
        self._state = story_state

    def validate_all(
        self,
        scenes: list[Any],
        scene_analysis_map: dict[int, Any] | None = None,
    ) -> list[ContinuityFinding]:
        """Validate all scenes; return list of ContinuityFindings."""
        from .tracker import (
            _get_scene_idx,
        )  # local to avoid circular import at module load

        findings: list[ContinuityFinding] = []
        analysis_map = scene_analysis_map or {}
        for enum_idx, scene in enumerate(scenes):
            scene_idx = _get_scene_idx(enum_idx, scene)
            findings.extend(
                self.validate_scene(scene_idx, scene, analysis_map.get(scene_idx))
            )
        return findings

    def validate_scene(
        self,
        scene_idx: int,
        scene: Any,
        scene_analysis: Any | None,
    ) -> list[ContinuityFinding]:
        findings: list[ContinuityFinding] = []
        narrative_role = _get_narrative_role(scene)
        mode = scene_mode_from_narrative_role(narrative_role)

        # Symbolic/metaphorical scenes: only flag gross violations
        if is_symbolic_mode(mode):
            findings.extend(self._check_cta_scene(scene_idx, scene, mode))
            return findings

        prompt = _get_prompt(scene)
        narration = _get_narration(scene)

        findings.extend(self._check_dead_characters(scene_idx, prompt, mode))
        findings.extend(
            self._check_forbidden_characters(scene_idx, scene, scene_analysis, prompt)
        )
        findings.extend(
            self._check_prop_state_continuity(scene_idx, prompt, narration, mode)
        )
        findings.extend(self._check_narration_coverage(scene_idx, prompt, narration))
        return findings

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_dead_characters(
        self, scene_idx: int, prompt: str, mode: SceneMode
    ) -> list[ContinuityFinding]:
        findings: list[ContinuityFinding] = []
        char_states, _ = self._state.get_state_before_scene(scene_idx)
        for cid, char_state in char_states.items():
            if not char_state.alive and _name_appears_in_prompt(
                char_state.name, prompt
            ):
                findings.append(
                    ContinuityFinding(
                        scene_id=scene_idx,
                        level=ValidationLevel.ERROR,
                        category="CHARACTER_CONTINUITY",
                        message=(
                            f"'{char_state.name}' appears in prompt but died before scene {scene_idx}. "
                            f"Last seen at scene {char_state.scene_last_seen}."
                        ),
                        suggested_fix=(
                            f"Remove '{char_state.name}' from the visual prompt, or mark this scene SYMBOLIC "
                            "if it's a flashback/memory."
                        ),
                    )
                )
        return findings

    def _check_forbidden_characters(
        self,
        scene_idx: int,
        scene: Any,
        scene_analysis: Any | None,
        prompt: str,
    ) -> list[ContinuityFinding]:
        findings: list[ContinuityFinding] = []
        forbidden = _get_forbidden_characters(scene, scene_analysis)
        for char_name in forbidden:
            if _name_appears_in_prompt(char_name, prompt):
                findings.append(
                    ContinuityFinding(
                        scene_id=scene_idx,
                        level=ValidationLevel.ERROR,
                        category="EXTRA_CHARACTER",
                        message=f"Forbidden character '{char_name}' appears in prompt for scene {scene_idx}.",
                        suggested_fix=f"Remove '{char_name}' from the prompt. Only allowed characters: "
                        + ", ".join(
                            _get_allowed_characters(scene, scene_analysis)
                            or ["(none specified)"]
                        ),
                    )
                )
        return findings

    def _check_prop_state_continuity(
        self,
        scene_idx: int,
        prompt: str,
        narration: str,
        mode: SceneMode,
    ) -> list[ContinuityFinding]:
        findings: list[ContinuityFinding] = []
        _, prop_states = self._state.get_state_before_scene(scene_idx)

        for prop_cid, prop_state in prop_states.items():
            if not prop_state.current_state:
                continue
            # Look for contradictory state keywords in the prompt
            _LIT_WORDS = {"lit", "burning", "glowing", "illuminated", "aflame"}
            _UNLIT_WORDS = {"unlit", "dark", "extinguished", "cold", "dead", "dim"}
            _FULL_WORDS = {"full", "filled"}
            _EMPTY_WORDS = {"empty", "empty", "depleted", "spent", "drained"}

            prompt_lower = prompt.lower()
            # Only check prompts that mention the prop at all
            if not _name_appears_in_prompt(prop_state.name, prompt_lower):
                continue

            proposed: str | None = None
            if any(w in prompt_lower for w in _LIT_WORDS):
                proposed = "lit"
            elif any(w in prompt_lower for w in _UNLIT_WORDS):
                proposed = "unlit"
            elif any(w in prompt_lower for w in _FULL_WORDS):
                proposed = "full"
            elif any(w in prompt_lower for w in _EMPTY_WORDS):
                proposed = "empty"

            if proposed:
                ok, reason = prop_state.can_be_in_state(proposed)
                if not ok:
                    findings.append(
                        ContinuityFinding(
                            scene_id=scene_idx,
                            level=ValidationLevel.WARNING,
                            category="PROP_STATE",
                            message=(
                                f"Prop '{prop_state.name}' shown as '{proposed}' in scene {scene_idx} "
                                f"but {reason}."
                            ),
                            suggested_fix=(
                                f"Either narration should explain the state change, or update the prompt "
                                f"to show the prop as '{prop_state.current_state}'."
                            ),
                        )
                    )
        return findings

    def _check_narration_coverage(
        self, scene_idx: int, prompt: str, narration: str
    ) -> list[ContinuityFinding]:
        """Warn when prompt seems completely disconnected from narration content."""
        findings: list[ContinuityFinding] = []
        if not narration or not prompt:
            return findings

        # Extract significant words from narration (>4 chars, skip stopwords)
        _STOPWORDS = frozenset(
            {
                "there",
                "their",
                "about",
                "would",
                "could",
                "which",
                "after",
                "before",
                "while",
                "where",
                "being",
                "these",
                "those",
                "other",
                "every",
                "some",
                "have",
                "from",
                "with",
                "that",
                "this",
                "when",
            }
        )
        narration_words = {
            w.lower()
            for w in re.findall(r"\b\w+\b", narration)
            if len(w) > 4 and w.lower() not in _STOPWORDS
        }
        prompt_lower = prompt.lower()

        # Count how many narration words appear in prompt
        if len(narration_words) < 3:
            return findings

        matches = sum(1 for w in narration_words if w in prompt_lower)
        coverage = matches / len(narration_words)
        if coverage < 0.08:  # Less than 8% overlap — very likely a disconnected prompt
            findings.append(
                ContinuityFinding(
                    scene_id=scene_idx,
                    level=ValidationLevel.WARNING,
                    category="NARRATION_COVERAGE",
                    message=(
                        f"Scene {scene_idx} prompt shares very few words with narration "
                        f"({matches}/{len(narration_words)} key words). "
                        "Prompt may be disconnected from what is being said."
                    ),
                    suggested_fix="Ensure the visual prompt represents what the narration describes.",
                )
            )
        return findings

    def _check_cta_scene(
        self, scene_idx: int, scene: Any, mode: SceneMode
    ) -> list[ContinuityFinding]:
        """For CTA / brand card scenes, just verify they don't use story character names."""
        findings: list[ContinuityFinding] = []
        prompt = _get_prompt(scene)
        for cid, char_state in self._state.characters.items():
            if char_state.role in {"protagonist", "main"} and _name_appears_in_prompt(
                char_state.name, prompt
            ):
                findings.append(
                    ContinuityFinding(
                        scene_id=scene_idx,
                        level=ValidationLevel.WARNING,
                        category="CTA_STORY_LEAK",
                        message=(
                            f"CTA/symbolic scene {scene_idx} includes story character '{char_state.name}'. "
                            "Brand cards should be story-neutral."
                        ),
                        suggested_fix="Remove story character references from brand/CTA scene prompts.",
                    )
                )
        return findings
