# VIDEO_REVIEW_DEBUG_MODE_V1

## Purpose

Provide complete observability into the Video Quality Review pipeline by
capturing every decision, artifact and diagnostic needed to reproduce
and understand review outcomes.

## Objectives

-   Capture every review step
-   Explain every decision
-   Enable reproducible debugging
-   Store intermediate artifacts
-   Support regression analysis

## Pipeline

Video Review → Debug Collector → Artifact Storage → Diagnostics → Debug
Reports

## Debug Levels

-   OFF
-   BASIC
-   DETAILED
-   VERBOSE

## Captured Artifacts

### Validation

-   Rule execution
-   Passed/failed rules
-   Validation metadata

### Root Cause

-   RCA decisions
-   Confidence
-   Evidence

### Quality Scoring

-   Category scores
-   Weight calculations
-   PASS/FAIL reasoning

### Engine Feedback

-   Assigned engine
-   Priority
-   Permanent fix recommendations

### Per Scene

-   Scene number
-   Timestamp
-   Image
-   Narration
-   Subtitle
-   Motion metadata
-   Validation summary
-   Quality score

## Outputs

workspace/review/debug/

-   debug-report.md
-   debug-summary.json
-   scene-debug.json
-   validation-debug.json
-   scoring-debug.json
-   feedback-debug.json
-   execution-timeline.json

## Diagnostics

-   Stage timings
-   Processing time
-   Memory usage
-   Errors
-   Warnings
-   Missing artifacts

## Future

Support a visual debug dashboard with timeline navigation and scene
inspection.

## Success Criteria

Every review decision is traceable, reproducible and backed by evidence.
