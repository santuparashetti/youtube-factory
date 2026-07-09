"""Pipeline dependency graph.

Defines which stages produce which output file patterns, and which stages
depend on which other stages.  Used by ChangeDetector to propagate
invalidations downstream.
"""

from __future__ import annotations

# Ordered list of all pipeline stages.
PIPELINE_STAGES: list[str] = [
    "research",
    "script",
    "scenes",
    "images",
    "voice",
    "captions",
    "video",
    "cta",
    "review",
    "publish",
]

# stage → list of stages it directly depends on.
# Transitively: when stage X is invalidated, every stage that depends on X
# (directly or indirectly) is also invalidated.
STAGE_DEPENDENCIES: dict[str, list[str]] = {
    "research": [],
    "script": ["research"],
    "scenes": ["script"],
    "images": ["scenes"],
    "voice": ["scenes"],
    "captions": ["voice"],
    "video": ["images", "voice", "captions"],
    "cta": ["video"],
    "review": ["cta"],
    "publish": ["review"],
}

# Relative-path glob patterns produced by each stage (relative to project_dir).
# Patterns with "*" are expanded via Path.glob(); others are checked directly.
STAGE_OUTPUT_PATTERNS: dict[str, list[str]] = {
    "research": ["research/research.md", "research/research.json"],
    "script": ["script/script.md"],
    "scenes": ["scenes/scene-plan.json"],
    "images": ["images/scene-*.png"],
    "voice": [
        "audio/scene-*.mp3",
        "audio/scene-*.timing.json",
        "audio/scene-*.alignment.json",
    ],
    "captions": ["subtitles/scene-*.srt", "subtitles/scene-*.ass"],
    "video": ["video/scene-*.mp4", "video/final.mp4"],
    "cta": ["cta/cta-timing.json"],
    "review": ["review/review-report.md"],
    "publish": ["publish/youtube-metadata.json"],
}

# Map force-flag name → stage to invalidate.
FORCE_FLAG_TO_STAGE: dict[str, str] = {
    "images": "images",
    "image": "images",
    "narration": "voice",
    "voice": "voice",
    "subtitles": "captions",
    "captions": "captions",
    "motion": "video",
    "video": "video",
    "alignment": "voice",  # force re-alignment → re-run voice stage (incl. alignment)
    "bgm": "video",
    "cta": "cta",
    "review": "review",
    "publish": "publish",
}


def downstream_stages(changed: set[str]) -> set[str]:
    """Return all stages that transitively depend on any stage in ``changed``."""
    result: set[str] = set()

    def _recurse(stage: str) -> None:
        for s, deps in STAGE_DEPENDENCIES.items():
            if stage in deps and s not in result:
                result.add(s)
                _recurse(s)

    for stage in changed:
        _recurse(stage)
    return result


def stages_to_run(invalidated: set[str]) -> list[str]:
    """Return ordered list of stages that need to run (respects PIPELINE_STAGES order)."""
    return [s for s in PIPELINE_STAGES if s in invalidated]
