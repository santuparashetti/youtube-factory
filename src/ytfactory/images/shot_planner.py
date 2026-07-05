"""Shot planner — assigns shot types to scenes with balanced distribution.

V4 Image Prompt Engine: shot variety is the primary lever for visual diversity.
The planner ensures no two adjacent scenes share the same shot type and that
all shot types appear roughly equally across a full video.
"""

from __future__ import annotations

SHOT_TYPES: list[str] = [
    "establishing shot",
    "wide shot",
    "medium shot",
    "close-up",
    "extreme close-up",
    "macro",
    "POV",
    "over-the-shoulder",
    "low angle",
    "high angle",
    "drone",
    "tracking shot",
    "static",
    "handheld",
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
        # Rotate the starting point by i so every scene gets a fresh candidate
        # that isn't the previous shot type.
        for offset in range(n):
            candidate = SHOT_TYPES[(i + offset) % n]
            if not result or candidate != result[-1]:
                result.append(candidate)
                break
        else:
            # Safety fallback: if all types equal prev (only possible with 1-type list)
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

    # Consecutive repeats
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
