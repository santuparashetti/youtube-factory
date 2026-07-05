# VIDEO_QUALITY_REVIEW_ENGINE_V1

## 1. Purpose

The Video Quality Review Engine (VQRE) is the final quality gate of
YouTube Factory.

Its responsibility is not only to detect defects, but to determine
**why** they occurred, identify the responsible engine, and produce
structured feedback that continuously improves the entire pipeline.

The renderer must never be considered the final step. The review engine
is the final authority before a video is approved.

------------------------------------------------------------------------

# 2. Objectives

-   Verify production quality.
-   Detect visual, audio and subtitle issues.
-   Compare output against the original intent.
-   Prevent low-quality videos from being published.
-   Generate structured feedback for upstream engines.
-   Enable future self-healing.

------------------------------------------------------------------------

# 3. Pipeline Position

Research → Script → Speech → Images → Motion → Rendering → **Video
Quality Review Engine** → Root Cause Analysis → Engine Feedback → PASS /
FAIL

------------------------------------------------------------------------

# 4. Responsibilities

The engine validates:

-   Script fidelity
-   Narration quality
-   Subtitle quality
-   Image relevance
-   Motion quality
-   Rendering quality
-   Audio quality
-   Scene continuity
-   Viewer experience
-   Production readiness

------------------------------------------------------------------------

# 5. Review Stages

## Stage 1

Asset Integrity - Missing images - Missing audio - Missing subtitles -
Corrupt files - Resolution checks

## Stage 2

Timeline Validation - Scene order - Scene duration - Timestamp
consistency - Sync accuracy

## Stage 3

Content Validation - Script vs narration - Narration vs visuals -
Visuals vs subtitles - Overall story flow

## Stage 4

Production Quality - Cinematic quality - Transition quality -
Readability - Audio quality - Final polish

------------------------------------------------------------------------

# 6. Review Inputs

-   Original script
-   Optimized script
-   Narration
-   ASS subtitles
-   SRT subtitles
-   Scene metadata
-   Image prompts
-   Generated images
-   Motion plan
-   Final rendered video

------------------------------------------------------------------------

# 7. Review Outputs

workspace/review/

-   review-report.md
-   quality-score.json
-   scene-review.json
-   review-debug.json
-   root-cause-report.json
-   engine-feedback.json

------------------------------------------------------------------------

# 8. Design Principles

-   Modular
-   Configurable
-   Explainable
-   Deterministic where possible
-   AI-assisted where beneficial
-   Backward compatible

------------------------------------------------------------------------

# 9. Pass / Fail

PASS only when:

-   Overall score exceeds configured threshold.
-   No critical failures exist.
-   All mandatory validations pass.

Otherwise FAIL and generate detailed root-cause reports.

------------------------------------------------------------------------

# 10. Future Integration

This engine is the foundation for:

-   Automatic remediation
-   Multi-pass AI review
-   Human review assistant
-   Continuous engine improvement
-   Self-healing pipeline

This document defines the architecture only. Validation rules, scoring,
root-cause analysis, and feedback loops are specified in dedicated V1
documents.
