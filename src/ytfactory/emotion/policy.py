"""Centralized emotional progression policy for the YouTube Factory pipeline.

Defines:
  NarrativePhase  — pipeline phases (HOOK … MEMORABLE_FINAL_LINE)
  EmotionPolicy   — phase→emotion map, families, rarity rules, diversity check

This is the single source of truth. Composer prompts, the SSML enhancer,
and the scene-level validator all read from here — nothing is duplicated.
"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from typing import FrozenSet


# ── Narrative phases ──────────────────────────────────────────────────────────

class NarrativePhase(str, Enum):
    HOOK = "HOOK"
    STORY = "STORY"
    TENSION = "TENSION"
    REVELATION = "REVELATION"
    HUMAN_PARALLEL = "HUMAN_PARALLEL"
    DEEPER_INSIGHT = "DEEPER_INSIGHT"
    PRACTICE = "PRACTICE"
    PHILOSOPHICAL_QUESTION = "PHILOSOPHICAL_QUESTION"
    CALLBACK = "CALLBACK"
    MEMORABLE_FINAL_LINE = "MEMORABLE_FINAL_LINE"
    UNKNOWN = "UNKNOWN"  # fallback when LLM does not classify


# ── Emotion vocabulary (Speechify SSML) ───────────────────────────────────────

# Core vocabulary — valid emotions for <speechify:style emotion="...">
CORE_EMOTIONS: FrozenSet[str] = frozenset({
    "curious", "direct", "warm", "calm", "reflective",
    "concerned", "uneasy", "sad", "assertive", "bright",
    "surprised", "realization", "empathetic", "relaxed",
    "encouraging", "hopeful",
    # Speechify built-ins also used here
    "cheerful", "energetic",
})

# High-intensity / rare emotions — require explicit narrative evidence
RARE_EMOTIONS: FrozenSet[str] = frozenset({
    "terrified", "fearful", "furious", "enraged", "panicked", "shocked",
    # Speechify native high-intensity
    "angry",
})

ALL_EMOTIONS: FrozenSet[str] = CORE_EMOTIONS | RARE_EMOTIONS


# ── Emotion families for diversity counting ───────────────────────────────────
#
# Synonyms map to one family so the script-level "5 distinct states" check
# cannot be gamed by selecting calm + relaxed + peaceful as "three states".

EMOTION_FAMILIES: dict[str, str] = {
    # CALM family
    "calm":        "CALM",
    "relaxed":     "CALM",
    "peaceful":    "CALM",
    # WARM family
    "warm":        "WARM",
    "empathetic":  "WARM",
    "encouraging": "WARM",
    "hopeful":     "WARM",
    "cheerful":    "WARM",
    # DIRECT family
    "direct":      "DIRECT",
    "assertive":   "DIRECT",
    "energetic":   "DIRECT",
    # REFLECTION family
    "reflective":  "REFLECTION",
    "realization": "REFLECTION",
    "curious":     "REFLECTION",
    # BRIGHT family
    "bright":      "BRIGHT",
    "surprised":   "BRIGHT",
    # TENSION family
    "concerned":   "TENSION",
    "uneasy":      "TENSION",
    "sad":         "TENSION",
    # RARE/HIGH-INTENSITY — each its own family
    "terrified":   "TERRIFIED",
    "fearful":     "FEARFUL",
    "furious":     "FURIOUS",
    "enraged":     "ENRAGED",
    "panicked":    "PANICKED",
    "shocked":     "SHOCKED",
    "angry":       "ANGER",
}

MINIMUM_DISTINCT_EMOTIONS: int = 5


# ── Phase → emotion map ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class PhaseEmotionTarget:
    primary: str
    allowed: tuple[str, ...]  # primary + allowed secondaries; primary is always valid

    def all_valid(self) -> tuple[str, ...]:
        return (self.primary,) + self.allowed


_PHASE_MAP: dict[NarrativePhase, PhaseEmotionTarget] = {
    NarrativePhase.HOOK: PhaseEmotionTarget(
        primary="direct",
        allowed=("warm", "curious"),
    ),
    NarrativePhase.STORY: PhaseEmotionTarget(
        primary="calm",
        allowed=("warm", "reflective"),
    ),
    NarrativePhase.TENSION: PhaseEmotionTarget(
        primary="assertive",
        allowed=("sad", "uneasy", "concerned"),
    ),
    NarrativePhase.REVELATION: PhaseEmotionTarget(
        primary="bright",
        allowed=("calm", "surprised", "realization"),
    ),
    NarrativePhase.HUMAN_PARALLEL: PhaseEmotionTarget(
        primary="warm",
        allowed=("empathetic", "reflective"),
    ),
    NarrativePhase.DEEPER_INSIGHT: PhaseEmotionTarget(
        primary="reflective",
        allowed=("calm", "relaxed"),
    ),
    NarrativePhase.PRACTICE: PhaseEmotionTarget(
        primary="direct",
        allowed=("assertive", "encouraging"),
    ),
    NarrativePhase.PHILOSOPHICAL_QUESTION: PhaseEmotionTarget(
        primary="calm",
        allowed=("relaxed", "curious"),
    ),
    NarrativePhase.CALLBACK: PhaseEmotionTarget(
        primary="warm",
        allowed=("reflective", "hopeful"),
    ),
    NarrativePhase.MEMORABLE_FINAL_LINE: PhaseEmotionTarget(
        primary="calm",
        allowed=("warm", "hopeful"),
    ),
    NarrativePhase.UNKNOWN: PhaseEmotionTarget(
        primary="calm",
        allowed=("warm", "reflective", "direct"),
    ),
}


# ── Public API ────────────────────────────────────────────────────────────────

class EmotionPolicy:
    """Single source of truth for emotional progression rules.

    Usage::

        policy = EmotionPolicy()
        target = policy.get_target(NarrativePhase.TENSION)
        # target.primary == "assertive"
        # target.allowed == ("sad", "uneasy", "concerned")

        families = policy.count_distinct_families(["calm", "relaxed", "warm", "assertive", "bright"])
        # 3  (calm+relaxed=CALM, warm=WARM, assertive=DIRECT, bright=BRIGHT) → 4
    """

    def get_target(self, phase: NarrativePhase | str) -> PhaseEmotionTarget:
        """Return primary + allowed emotions for a narrative phase."""
        if isinstance(phase, str):
            try:
                phase = NarrativePhase(phase.upper())
            except ValueError:
                phase = NarrativePhase.UNKNOWN
        return _PHASE_MAP.get(phase, _PHASE_MAP[NarrativePhase.UNKNOWN])

    def is_rare(self, emotion: str) -> bool:
        return emotion.lower() in RARE_EMOTIONS

    def is_valid(self, emotion: str) -> bool:
        return emotion.lower() in ALL_EMOTIONS

    def family_of(self, emotion: str) -> str:
        return EMOTION_FAMILIES.get(emotion.lower(), emotion.upper())

    def count_distinct_families(self, emotions: list[str]) -> int:
        """Count distinct emotion families across a list of emotion strings."""
        return len({self.family_of(e) for e in emotions if e})

    def is_phase_compatible(self, phase: NarrativePhase | str, emotion: str) -> bool:
        """True if emotion is primary or allowed for phase.

        Rare emotions are never 'phase-compatible' by the map alone — they
        require explicit narrative justification regardless of phase.
        """
        if self.is_rare(emotion):
            return False  # rare always requires evidence; never auto-compatible
        target = self.get_target(phase)
        return emotion.lower() in {e.lower() for e in target.all_valid()}

    def parse_phase(self, raw: str) -> NarrativePhase:
        """Parse a raw phase string → NarrativePhase, defaulting to UNKNOWN."""
        if not raw:
            return NarrativePhase.UNKNOWN
        try:
            return NarrativePhase(raw.upper().strip())
        except ValueError:
            return NarrativePhase.UNKNOWN

    def build_prompt_block(self, phase: NarrativePhase | str) -> str:
        """Return a structured SSML prompt constraint block for a given phase."""
        if isinstance(phase, str):
            phase = self.parse_phase(phase)
        target = self.get_target(phase)
        rare_list = ", ".join(sorted(RARE_EMOTIONS))
        allowed_list = ", ".join(target.allowed) if target.allowed else "—"
        return (
            f"NARRATIVE PHASE: {phase.value}\n"
            f"PRIMARY EMOTION: {target.primary}\n"
            f"ALLOWED SECONDARY EMOTIONS: {allowed_list}\n"
            f"RARE EMOTIONS (require explicit story evidence): {rare_list}\n"
            f"Open this scene with the primary emotion. You may transition to an allowed "
            f"secondary only at a sentence or paragraph boundary. Never use a rare emotion "
            f"unless the narration contains explicit evidence of danger, severe distress, "
            f"shock, or violent conflict."
        )

    def validate_script_diversity(
        self, phase_sequence: list[str]
    ) -> tuple[bool, int, list[str]]:
        """Check script-level diversity.

        Returns (passes, distinct_count, family_list).
        passes is True when distinct_count >= MINIMUM_DISTINCT_EMOTIONS.
        """
        emotions = [self.get_target(self.parse_phase(p)).primary for p in phase_sequence]
        families = [self.family_of(e) for e in emotions]
        distinct = list(dict.fromkeys(families))  # ordered unique
        return len(distinct) >= MINIMUM_DISTINCT_EMOTIONS, len(distinct), distinct

    def validate_adjacent_continuity(
        self, phases: list[str], emotions: list[str]
    ) -> list[tuple[int, str]]:
        """Detect emotionally jarring adjacent scene pairs.

        Returns a list of (scene_index, warning_message) for transitions where
        the emotion family changes AND both scenes belong to the same narrative phase
        (same-phase switches have no narrative boundary to justify the change).
        """
        warnings: list[tuple[int, str]] = []
        for i in range(1, len(phases)):
            if not emotions[i - 1] or not emotions[i]:
                continue
            fam_prev = self.family_of(emotions[i - 1])
            fam_curr = self.family_of(emotions[i])
            phase_prev = self.parse_phase(phases[i - 1])
            phase_curr = self.parse_phase(phases[i])
            if fam_prev != fam_curr and phase_prev == phase_curr:
                warnings.append((
                    i,
                    f"Scene {i}: emotion family changed ({fam_prev}→{fam_curr}) within "
                    f"the same narrative phase ({phase_curr.value}) — no boundary justifies this.",
                ))
        return warnings


# Module-level singleton — import and use directly.
emotion_policy = EmotionPolicy()
