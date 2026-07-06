from __future__ import annotations

from typing import Annotated, Optional, TypedDict


def _merge_dicts(a: dict, b: dict) -> dict:
    return {**a, **b}


def _append_list(a: list, b: list) -> list:
    return a + b


class VideoState(TypedDict, total=False):
    # ── Project metadata ──────────────────────────────────────────────────
    project_id: str
    topic: str
    language: str  # BCP-47 code, e.g. "en", "hi", "mr"
    topic_category: str  # history | tech | science | finance | health | other
    style: Optional[str]  # visual style hint: "spiritual" | "documentary" | None
    target_minutes: int  # target narration duration (5-10); drives enhancer word count
    auto_mode: bool  # True → skip all human-review gates
    skip_images: bool  # True → skip image generation (for manual-image workflow)

    # ── Stage text outputs ────────────────────────────────────────────────
    research_md: str
    script_md: str
    scene_plan: list[dict]  # validated JSON list from scene planner

    # ── Per-scene current pointer (set by Send during parallel fan-out) ───
    current_scene: Optional[dict]

    # ── Parallel stage outputs (reducers merge partial updates) ───────────
    image_paths: Annotated[dict[int, str], _merge_dicts]
    audio_paths: Annotated[dict[int, str], _merge_dicts]
    srt_paths: Annotated[dict[int, str], _merge_dicts]
    scene_video_paths: Annotated[dict[int, str], _merge_dicts]

    # ── Final output ──────────────────────────────────────────────────────
    final_video_path: Optional[str]

    # ── Quality review (populated by quality_review_node) ─────────────────
    review_result: Optional[dict]  # {"verdict": "PASS"|"FAIL", "errors": [...], ...}

    # ── Remediation (populated by remediation_node) ────────────────────────
    remediation_result: Optional[dict]  # {"final_verdict": "PASS"|"FAIL", "stopped_reason": str, ...}

    # ── Non-fatal error accumulation ──────────────────────────────────────
    stage_errors: Annotated[list[str], _append_list]
