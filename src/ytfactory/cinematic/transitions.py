"""
Transition Engine — emotion-aware transition selection for consecutive scenes.

Output: each scene dict gains 'transition_in' and 'transition_out' keys
containing a TransitionSpec dict. The renderer (Phase 3) reads these to
add FFmpeg fade filters to each scene clip.

This module does NO I/O and calls NO LLMs. Pure data transformation:
    list[scene_dict] → list[scene_dict with 'transition_in' and 'transition_out']

Transition types:
    hard_cut       — immediate cut, no filter (maximum energy / pace)
    match_cut      — compositional hard cut (semantic match between scenes)
    cross_dissolve — fade-through-black (standard documentary)
    luma_fade      — fade-through-black on dramatic reveal moments
    light_leak     — fade-through-white (warm emotional pivot, e.g. sadness→hope)
    blur_dissolve  — fade-through-black (blur overlay added in Phase 5)

Strategy A (current, Phase 3): transitions are baked per-clip using FFmpeg's
'fade' filter on each scene clip independently. Scene N gets fade=t=out;
Scene N+1 gets fade=t=in. These baked fades feed into render_continuous().

Strategy C (future, Phase 5): true overlapping cross-dissolves via a
filter_complex graph. Requires re-encoding but enables genuine overlap.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ytfactory.cinematic.profiles import RenderProfile
from ytfactory.providers.tts.emotion import classify_scene


@dataclass(frozen=True)
class TransitionSpec:
    """
    Transition metadata for entering OR exiting one scene.

    For hard_cut / match_cut: duration_frames = 0, no filter is applied.
    For fade-based transitions the renderer adds:
        fade=t=in:st=0:d=<seconds>:color=<color>           (transition_in)
        fade=t=out:st=<dur-d>:d=<seconds>:color=<color>    (transition_out)

    Attributes:
        transition_type:  hard_cut | match_cut | cross_dissolve |
                          luma_fade | light_leak | blur_dissolve
        duration_frames:  Fade length in frames. 0 = no fade filter.
        color:            Intermediate colour — "black" or "white".
        from_emotion:     Dominant emotion of the outgoing scene ("none" for opening).
        to_emotion:       Dominant emotion of the incoming scene ("none" for closing).
    """

    transition_type: str
    duration_frames: int
    color: str
    from_emotion: str
    to_emotion: str

    def to_dict(self) -> dict:
        return asdict(self)


# ── Profile → fade duration (frames at 30 fps) ────────────────────────────────

_PROFILE_DURATIONS: dict[str, int] = {
    RenderProfile.DRAFT: 0,  # hard cut everywhere — fastest render
    RenderProfile.BALANCED: 10,  # ~0.33 s — subtle, almost imperceptible
    RenderProfile.CINEMATIC: 15,  # ~0.50 s — noticeable but not slow
    RenderProfile.PREMIUM: 20,  # ~0.67 s — deliberate, cinematic weight
}

# Fixed durations for opening / closing regardless of interior profile
_OPENING_FRAMES: int = 10  # first scene: fade in from black
_CLOSING_FRAMES: int = 15  # last scene: fade out to black


# ── Emotion pair → transition type ───────────────────────────────────────────
#
# (from_emotion, to_emotion) → transition_type
# Pairs not in this table fall through to the same-emotion and default rules.

_PAIR_TRANSITIONS: dict[tuple[str, str], str] = {
    # Mystery → clarity
    ("mystery", "revelation"): "luma_fade",
    ("mystery", "wonder"): "cross_dissolve",
    ("mystery", "curiosity"): "cross_dissolve",
    # Darkness → light (emotional pivot)
    ("sadness", "hope"): "light_leak",
    ("sadness", "peace"): "cross_dissolve",
    ("sadness", "revelation"): "light_leak",
    # Reflection → insight
    ("reflection", "revelation"): "luma_fade",
    ("reflection", "wonder"): "cross_dissolve",
    ("reflection", "hope"): "cross_dissolve",
    # Urgency → calm
    ("urgency", "reflection"): "cross_dissolve",
    ("urgency", "peace"): "cross_dissolve",
    ("urgency", "sadness"): "cross_dissolve",
    # Awe and wonder arcs
    ("awe", "wonder"): "cross_dissolve",
    ("awe", "peace"): "cross_dissolve",
    ("wonder", "revelation"): "luma_fade",
    ("wonder", "peace"): "cross_dissolve",
    # Curiosity → discovery
    ("curiosity", "wonder"): "cross_dissolve",
    ("curiosity", "revelation"): "luma_fade",
    ("curiosity", "awe"): "cross_dissolve",
    # Compassion / hope arcs
    ("compassion", "hope"): "light_leak",
    ("compassion", "peace"): "cross_dissolve",
    ("hope", "peace"): "cross_dissolve",
    ("determination", "revelation"): "luma_fade",
}

# High-energy same-emotion continuity → hard cut keeps the pace
_HARD_CUT_EMOTIONS: frozenset[str] = frozenset(
    {
        "curiosity",
        "urgency",
        "determination",
    }
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_emotion(scene: dict, position: float) -> str:
    """Classify the dominant emotion for one scene."""
    if scene.get("scene_type") == "asset":
        return "asset"
    ep = classify_scene(scene.get("narration", ""), position)
    return ep.emotion.value


def _short_narration(scene: dict, threshold: int = 20) -> bool:
    return len(scene.get("narration", "").split()) < threshold


def _select_transition(
    from_emotion: str,
    to_emotion: str,
    to_scene: dict,
    profile: str,
    duration_frames: int,
) -> tuple[str, int, str]:
    """
    Return (transition_type, effective_frames, color) for one boundary.

    Priority order:
    1. Draft profile or zero duration → hard_cut.
    2. Incoming asset scene → cross_dissolve (brand card always soft entry).
    3. Match-cut heuristic (cinematic/premium + same high-energy emotion + short).
    4. Emotion pair table.
    5. Same emotion in hard-cut group → hard_cut.
    6. Default → cross_dissolve through black.
    """
    # 1. Draft / no-fade
    if profile == RenderProfile.DRAFT or duration_frames == 0:
        return "hard_cut", 0, "black"

    # 2. Asset scene: always dissolve for graceful brand card entry
    if to_scene.get("scene_type") == "asset":
        return "cross_dissolve", duration_frames, "black"

    # 3. Match-cut heuristic: rhythmic cuts during high-energy same-emotion runs
    if (
        from_emotion == to_emotion
        and from_emotion in _HARD_CUT_EMOTIONS
        and profile in (RenderProfile.CINEMATIC, RenderProfile.PREMIUM)
        and _short_narration(to_scene)
    ):
        return "match_cut", 0, "black"

    # 4. Emotion pair table
    ttype = _PAIR_TRANSITIONS.get((from_emotion, to_emotion))
    if ttype:
        color = "white" if ttype == "light_leak" else "black"
        return ttype, duration_frames, color

    # 5. Same high-energy emotion → hard cut (outside cinematic match-cut scope)
    if from_emotion == to_emotion and from_emotion in _HARD_CUT_EMOTIONS:
        return "hard_cut", 0, "black"

    # 6. Default: documentary cross-dissolve
    return "cross_dissolve", duration_frames, "black"


# ── Transition Planner ────────────────────────────────────────────────────────


class TransitionPlanner:
    """
    Assigns transition metadata to every scene boundary in a scene plan.

    After plan() each scene has two new keys:
        scene["transition_in"]  — TransitionSpec dict for how this scene enters
        scene["transition_out"] — TransitionSpec dict for how this scene exits

    Scene 0 → transition_in = fixed opening fade from black.
    Scene N → transition_out = fixed closing fade to black.
    Interior boundaries are chosen from the emotion-pair matrix.

    The TransitionPlanner is stateless; safe to reuse across projects.

    Usage:
        planner = TransitionPlanner()
        scenes = planner.plan(scenes, profile="cinematic")
    """

    def plan(
        self,
        scenes: list[dict],
        profile: str = "balanced",
    ) -> list[dict]:
        """
        Enrich each scene with 'transition_in' and 'transition_out'.

        Mutates in-place and returns the same list (consistent with
        MotionPlanner.plan() and _mark_asset_scenes() conventions).

        Args:
            scenes:  Scene dicts from scene-plan.json.
            profile: Rendering profile — draft | balanced | cinematic | premium.

        Returns:
            The same scene list with transition keys added to every scene.
        """
        if not scenes:
            return scenes

        total = len(scenes)
        duration_frames = _PROFILE_DURATIONS.get(
            profile, _PROFILE_DURATIONS[RenderProfile.BALANCED]
        )

        # Pre-classify emotions for all scenes in one pass
        positions = [
            (s["index"] - 1) / max(total - 1, 1) if total > 1 else 0.5 for s in scenes
        ]
        emotions = [_get_emotion(s, p) for s, p in zip(scenes, positions)]

        # ── Opening: first scene fades in from black ──────────────────────────
        open_frames = _OPENING_FRAMES if profile != RenderProfile.DRAFT else 0
        scenes[0]["transition_in"] = TransitionSpec(
            transition_type="cross_dissolve" if open_frames else "hard_cut",
            duration_frames=open_frames,
            color="black",
            from_emotion="none",
            to_emotion=emotions[0],
        ).to_dict()

        # ── Interior boundaries ───────────────────────────────────────────────
        for i in range(total - 1):
            from_scene = scenes[i]
            to_scene = scenes[i + 1]
            fe, te = emotions[i], emotions[i + 1]

            ttype, frames, color = _select_transition(
                fe, te, to_scene, profile, duration_frames
            )

            shared = dict(
                transition_type=ttype,
                duration_frames=frames,
                color=color,
                from_emotion=fe,
                to_emotion=te,
            )
            from_scene["transition_out"] = TransitionSpec(**shared).to_dict()
            to_scene["transition_in"] = TransitionSpec(**shared).to_dict()

        # ── Closing: last scene fades to black ───────────────────────────────
        close_frames = _CLOSING_FRAMES if profile != RenderProfile.DRAFT else 0
        scenes[-1]["transition_out"] = TransitionSpec(
            transition_type="cross_dissolve" if close_frames else "hard_cut",
            duration_frames=close_frames,
            color="black",
            from_emotion=emotions[-1],
            to_emotion="none",
        ).to_dict()

        # ── Safety net: ensure every scene has both keys ──────────────────────
        _null = TransitionSpec("hard_cut", 0, "black", "none", "none").to_dict()
        for scene in scenes:
            scene.setdefault("transition_in", _null)
            scene.setdefault("transition_out", _null)

        return scenes
