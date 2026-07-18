# ADR-0014: Pipeline Progress Reporting & Status Tracking

## Status

Proposed

## Priority

Medium

## Owner

YouTube Factory

## Relates to

-   ADR-0011
-   ADR-0012
-   Image Generation Pipeline
-   Video Rendering Pipeline

## Background

The YouTube Factory is now a long-running, multi-stage pipeline. Users
currently have little visibility until a job completes or fails.

Goals: - Provide accurate, real-time progress. - Never display fake
percentages. - Show the current stage. - Surface retries and
iterations. - Persist status for external monitoring. - Use one data
source for CLI and future UI.

## Progress Types

### Determinate

Use counters for measurable work.

Examples: - Image Generation (18/32) - TTS (25/41) - Scene Rendering
(12/32)

### Indeterminate

Use a spinner for unknown-duration operations.

Examples: - Light Normalization - Documentary Enhancement Pass 1 -
Research

### Iterative

Show retry count and score.

Example:

Pass 2 Attempt 2/3 Narrative Score: 8.3/10 Retrying...

## Pipeline Stages

Research → Light Normalization → Documentary Enhancer Pass 1 →
Documentary Enhancer Pass 2 → Scene Planning → Image Generation → Image
QA → Image Regeneration → TTS → Subtitle Generation → Subtitle Editing →
Background Music → Scene Rendering → Video Merge → CTA Overlay → Final
Packaging

Each stage reports: - pending - running - retrying - completed - failed

## Pipeline Status File

Maintain:

`pipeline-status.json`

This is the single source of truth and is consumed by both CLI and
future UI.

## Status Model

-   job_id
-   current_stage
-   stage_state
-   started_at
-   updated_at
-   elapsed_seconds
-   retry_count
-   progress
-   total
-   message
-   error

Example:

``` json
{
  "current_stage": "image_generation",
  "stage_state": "running",
  "progress": 18,
  "total": 32,
  "retry_count": 1,
  "message": "Generating image 18 of 32"
}
```

## CLI Rendering

Display the current stage using the status file.

Example:

✓ Research

✓ Light Normalization

⟳ Narrative Review Attempt 2/3 Narrative Score: 8.1/10 Retrying...

Images 18/32

▶ Rendering Scene 12/32

## Failure Reporting

Show: - stage - reason - retry count - stack trace location - elapsed
time

## Validation

-   Never fake progress.
-   Report every stage transition.
-   Show retries.
-   Keep CLI synchronized with `pipeline-status.json`.
-   Allow external monitoring without parsing logs.

## Success Criteria

Users should always know: - What stage is running. - Whether work is
progressing. - Whether retries are occurring. - Remaining measurable
work. - Failure reason and location.
