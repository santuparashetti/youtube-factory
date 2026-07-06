"""Shot planner — assigns safe, documentary-appropriate shot types to scenes.

V5 Image Prompt Engine:
  • Removed unsafe defaults: extreme close-up, macro, POV (first-person).
  • Added safe cinematic alternatives: environmental portrait, profile shot,
    wide cinematic.
  • Shot variety remains the primary lever for visual diversity.
  • No two adjacent scenes share the same shot type.
  • All shot types appear roughly equally across a full video.
"""

from __future__ import annotations

# Safe composition defaults for documentary-quality images.
# Unsafe types (extreme close-up, macro, POV/first-person) are excluded.
# Override via the LLM prompt when the narration absolutely requires them.
SHOT_TYPES: list[str] = [
    "establishing shot",
    "wide shot",
    "medium shot",
    "close-up",
    "over-the-shoulder",
    "low angle",
    "high angle",
    "drone",
    "tracking shot",
    "static",
    "handheld",
    "environmental portrait",
    "profile shot",
    "wide cinematic",
]


def plan_shots(num_scenes: int) -> list[str]:
    """
    Assign one shot type per scene.

    Algorithm: round-robin through the full SHOT_TYPES list with consecutive-
    repeat avoidance.  Deterministic — same num_scenes always produces the
    same sequence.  Balanced — each type appears at most once more than any
    other type across the full list.

    Returns an empty list when num_scenes == 0.
    """
    if num_scenes == 0:
        return []
    if num_scenes == 1:
        return [SHOT_TYPES[0]]

    n = len(SHOT_TYPES)
    result: list[str] = []

    for i in range(num_scenes):
        for offset in range(n):
            candidate = SHOT_TYPES[(i + offset) % n]
            if not result or candidate != result[-1]:
                result.append(candidate)
                break
        else:
            result.append(SHOT_TYPES[i % n])

    return result


def validate_shot_diversity(shots: list[str]) -> list[str]:
    """
    Return a list of human-readable issues with the given shot plan.

    Issues reported:
    - Consecutive repeats (should never occur after plan_shots)
    - Any shot type appearing more than 3× the minimum count (heavy imbalance)
    - Fewer than 3 distinct shot types for plans with 5+ scenes
    """
    issues: list[str] = []

    if not shots:
        return issues

    for i in range(1, len(shots)):
        if shots[i] == shots[i - 1]:
            issues.append(f"Consecutive repeat at position {i + 1}: '{shots[i]}'")

    if len(shots) >= 5:
        from collections import Counter

        counts = Counter(shots)
        distinct = len(counts)
        if distinct < 3:
            issues.append(
                f"Low shot diversity: only {distinct} distinct shot types used"
            )

        min_count = min(counts.values())
        for shot, count in counts.items():
            if min_count > 0 and count > min_count * 3:
                issues.append(
                    f"Shot type '{shot}' appears {count}× (imbalanced distribution)"
                )

    return issues
