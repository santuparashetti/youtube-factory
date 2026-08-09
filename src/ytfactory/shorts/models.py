"""Data models for the YouTube Shorts pipeline (Phase 1A)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ShortAngle = Literal["paradox", "story", "counterintuitive", "question", "contrast"]

PrimaryMechanism = Literal[
    "story",
    "paradox",
    "psychological_mechanism",
    "modern_example",
    "contrast",
    "question",
    "metaphor",
]


class ShortOpportunity(BaseModel):
    opportunity_id: str
    angle: ShortAngle
    surprising_idea: str
    emotional_tension: str
    curiosity_potential: str
    connection_to_long_video: str
    unresolved_question: str
    estimated_hook_strength: float
    source_sections: list[str] = Field(default_factory=list)
    # Diversity fields — allow LLM to omit for backward-compat; default to safe values
    primary_mechanism: PrimaryMechanism = "story"
    primary_evidence: str = ""


class OpportunityExtractionResult(BaseModel):
    parent_video_id: str
    parent_video_title: str
    parent_core_thesis: str
    opportunities: list[ShortOpportunity]
    # selected is always written by Python selection logic, never trusted from LLM
    selected: list[str]
    extraction_rationale: str


class LongFormBridge(BaseModel):
    source_video: str
    relationship: Literal[
        "opens_question",
        "contradicts_assumption",
        "deepens_theme",
        "reveals_mechanism",
    ]
    bridge_type: Literal[
        "open_question",
        "incomplete_explanation",
        "surprising_consequence",
        "deeper_mechanism",
        "story_continuation",
    ]
    unresolved_question: str
    continuation_value: str


class ValidationScores(BaseModel):
    hook_strength: float
    retention_potential: float
    clarity: float
    emotional_intensity: float
    philosophical_depth: float
    standalone_value: float
    curiosity_gap: float
    long_form_bridge: float
    spoiler_risk: float
    naturalness: float
    specificity: float
    generic_ai_language: float
    advertising_feel: float
    cliche_density: float
    overall: float
    # Phase 1A quality improvements — default 0 so old data still loads
    narrative_coherence: float = 0.0
    progression: float = 0.0
    ending_strength: float = 0.0


class CrossShortQAResult(BaseModel):
    """Outcome of comparing two Shorts for cross-script similarity."""
    similarity_problem: bool
    overlap_reason: str
    failed_dimensions: list[str] = Field(default_factory=list)
    preserve_sections: list[str] = Field(default_factory=list)
    rewrite_sections: list[str] = Field(default_factory=list)
    specific_instruction: str = ""


class ShortsScriptQAReport(BaseModel):
    """Structured QA failure diagnosis used by the recomposer."""
    short_id: str
    status: Literal["PASS", "PASS_WITH_WARNING", "FAIL"]
    failed_dimensions: list[str] = Field(default_factory=list)
    warning_dimensions: list[str] = Field(default_factory=list)
    preserve_sections: list[str] = Field(default_factory=list)
    rewrite_sections: list[str] = Field(default_factory=list)
    specific_instruction: str = ""
    cross_short: CrossShortQAResult | None = None


class ValidationReport(BaseModel):
    short_id: str
    validation_passed: bool
    attempts: int
    regenerated: bool
    rule_checks: dict[str, bool]
    scores: ValidationScores | None
    failure_reasons: list[str]
    # Phase 1A quality improvements
    initial_status: str | None = None
    recomposed: bool = False
    recomposition_reason: str | None = None
    final_status: str | None = None


class ShortsScript(BaseModel):
    short_id: str
    parent_video_id: str
    angle: ShortAngle
    source_opportunity_id: str
    title: str
    hook: str
    setup: str
    story: str
    revelation: str
    open_loop: str
    full_script: str
    long_form_bridge: LongFormBridge
    target_duration_seconds: float
    estimated_word_count: int
    validation_passed: bool
    scores: ValidationScores | None = None


class VideoResolution(BaseModel):
    width: int
    height: int


class ShortsScene(BaseModel):
    index: int
    section: Literal["hook", "setup", "story", "revelation", "open_loop"]
    narration: str
    visual_prompt: str
    duration_seconds: float
    is_hook_scene: bool = False
    first_frame_priority: Literal["maximum", "high", "normal"] = "normal"
    shot_type: str
    # motion_type intentionally excluded — Phase 1A spec §8.8, §53


class ShortsScenePlan(BaseModel):
    short_id: str
    parent_video_id: str
    aspect_ratio: Literal["9:16"] = "9:16"
    resolution: VideoResolution = Field(
        default_factory=lambda: VideoResolution(width=1080, height=1920)
    )
    target_duration_seconds: float
    total_estimated_duration: float
    scene_count: int
    scenes: list[ShortsScene]
    visual_hook_description: str
    provenance: dict = Field(default_factory=dict)


class ShortsImageManifestItem(BaseModel):
    scene_index: int
    filename: str
    prompt: str


class ShortsImageManifest(BaseModel):
    short_id: str
    parent_video_id: str
    aspect_ratio: Literal["9:16"] = "9:16"
    resolution: VideoResolution = Field(
        default_factory=lambda: VideoResolution(width=1080, height=1920)
    )
    ready_for_image_generation: bool
    images: list[ShortsImageManifestItem]
