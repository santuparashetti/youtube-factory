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
    target_minutes: int  # target narration duration (1-10); drives enhancer word count
    auto_mode: bool  # True → skip all human-review gates
    ab_script_selection: bool  # True → composer generates 2 variants; user picks one (interactive)
    skip_images: bool  # True → skip image generation (for manual-image workflow)
    skip_thumbnail: bool  # True → skip thumbnail generation (Phase 2 resume)

    # ── Stage text outputs ────────────────────────────────────────────────
    research_md: str
    script_md: str
    original_source_transcript: Optional[str]
    enhancement_instructions: Optional[str]
    scene_plan: list[dict]  # validated JSON list from scene planner

    # ── Composer two-variant output + Script Selector + Polisher ──────────
    # composer_node (polisher path) writes both variants; script_selector_polisher
    # picks the stronger, lightly polishes it, and writes selected_script back
    # into script_md (the real backward-compat key every downstream stage reads).
    script_a: str  # composer variant A (temp composer_variant_temp_a)
    script_b: str  # composer variant B (temp composer_variant_temp_b)
    selected_script: str  # chosen + polished script, ready for scene_planner
    polisher_report: dict  # {chosen, selection_reason, changes_made, change_percentage, unchanged_note, [fallback]}

    # ── YouTube ingestion (alternate Phase 1 source: URL instead of a script
    # file or AI research). When set, routes START → acquire_audio instead of
    # research_agent / script_enhancer. See agents/nodes/youtube_ingest.py.
    source_url: Optional[str]

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
    pipeline_qa_score: Optional[dict]  # {"total": float, "breakdown": {...}, "violations": [...], "passed": bool}

    # ── Remediation (populated by remediation_node) ────────────────────────
    remediation_result: Optional[
        dict
    ]  # {"final_verdict": "PASS"|"FAIL", "stopped_reason": str, ...}

    # ── Non-fatal error accumulation ──────────────────────────────────────
    stage_errors: Annotated[list[str], _append_list]
