# ROOT_CAUSE_ANALYSIS_ENGINE_V1

## Purpose

The Root Cause Analysis Engine (RCAE) determines **why** a validation
failed---not just what failed.

It transforms validation failures into actionable engineering feedback
by identifying the most probable source of the problem and assigning
ownership to the correct pipeline engine.

------------------------------------------------------------------------

# Objectives

-   Identify the true cause of failures.
-   Avoid symptom-based reporting.
-   Prevent recurring defects.
-   Feed permanent improvements back into the pipeline.
-   Produce deterministic, explainable analysis.

------------------------------------------------------------------------

# Pipeline

Video Validation → Root Cause Analysis → Engine Ownership → Permanent
Fix Recommendation → Engine Feedback Loop

------------------------------------------------------------------------

# Inputs

-   Validation results
-   Review reports
-   Original script
-   Optimized script
-   Narration
-   ASS/SRT subtitles
-   Scene metadata
-   Image prompts
-   Motion plan
-   Final video
-   Diagnostics

------------------------------------------------------------------------

# Root Cause Categories

## Script

-   Padding
-   Weak flow
-   Wrong duration
-   Incorrect simplification

## Narration

-   Fast pace
-   Missing pauses
-   Pronunciation
-   Emotional mismatch

## Subtitle

-   Sync
-   Timing
-   Reading speed
-   Formatting
-   ASS rendering

## Image

-   Wrong subject
-   Weak prompt
-   Symbolic mismatch
-   Character inconsistency
-   Repeated imagery

## Motion

-   Wrong duration
-   Poor transition
-   Static scene
-   Black frame

## Audio

-   Clipping
-   Loudness
-   Music balance
-   Silence

## Rendering

-   Missing asset
-   Encoding
-   Resolution
-   Frame issues

------------------------------------------------------------------------

# Engine Ownership Mapping

Each root cause must map to exactly one primary engine.

Examples:

-   Script Pacing Engine
-   Image Prompt Engine
-   ASS Subtitle Engine
-   Scene Planner
-   Motion Engine
-   TTS Engine
-   Video Renderer

Secondary engines may also be listed with confidence.

------------------------------------------------------------------------

# RCA Output

For every issue generate:

-   Issue ID
-   Root Cause
-   Confidence (0--100)
-   Severity
-   Evidence
-   Timestamp / Scene
-   Primary Engine
-   Secondary Engines
-   Suggested Permanent Fix
-   Suggested Tests

------------------------------------------------------------------------

# Reports

workspace/review/

-   root-cause-report.md
-   root-cause.json
-   engine-owner-summary.json
-   recurring-issues.json

------------------------------------------------------------------------

# Design Principles

-   Explainable
-   Evidence-based
-   Deterministic where possible
-   AI-assisted when needed
-   No guessing without confidence
-   Extensible

------------------------------------------------------------------------

# Success Criteria

Every failed validation must either:

1.  Identify a probable root cause with confidence.

or

2.  Be marked as Unknown with evidence and investigation notes.

No validation failure should end without ownership and a recommended
permanent fix.
