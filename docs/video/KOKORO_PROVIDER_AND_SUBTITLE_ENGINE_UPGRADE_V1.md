# KOKORO_PROVIDER_AND_SUBTITLE_ENGINE_UPGRADE_V1

> Implementation Specification for Claude Code
>
> **Prerequisite:** Read `MASTER_CONTEXT_V4.md` completely before making
> any code changes.
>
> **Purpose:** Extend the existing architecture. Do **not** redesign it.

# Objectives

Implement:

1.  Kokoro as an additional TTS provider.
2.  WhisperX forced alignment.
3.  Upgrade Subtitle Intelligence Engine V2 with semantic segmentation.
4.  Preserve all existing architecture, providers, pipelines, review
    layers and incremental build support.

------------------------------------------------------------------------

# Non-Negotiable Rules

-   Do not create parallel pipelines.
-   Do not replace existing VoicePipeline.
-   Do not replace SubtitleEngine.
-   Do not replace Subtitle Intelligence Engine V2.
-   Reuse provider factories.
-   Preserve backward compatibility.
-   Keep changes localized.
-   Prefer extension over refactoring.

------------------------------------------------------------------------

# Existing Components To Extend

-   providers/tts/
-   VoicePipeline
-   SubtitleEngine
-   Subtitle Intelligence Engine V2
-   BuildPipeline
-   ReviewPipeline
-   ValidationRunner
-   AutoRemediation
-   IncrementalBuildEngine
-   Settings
-   CLI commands

Inspect these before writing code.

------------------------------------------------------------------------

# Part A --- Kokoro Provider

Implement a new provider beside Edge and ElevenLabs.

Requirements

-   Provider factory registration
-   Retry support
-   Timeouts
-   Diagnostics
-   Provider capability metadata
-   Respect Settings
-   No hardcoded credentials

Defaults

-   voice = am_michael
-   language = en-US
-   sample_rate = 24000
-   speed = 1.0

Artifacts remain compatible with existing VoicePipeline.

No workflow changes should be required when switching providers.

------------------------------------------------------------------------

# Part B --- VoicePipeline Integration

Keep existing scene-based generation.

Current output:

audio/ scene-001.mp3 scene-001.timing.json

Maintain this structure.

Support provider selection via Settings only.

------------------------------------------------------------------------

# Part C --- WhisperX Alignment

After narration generation, optionally perform WhisperX forced
alignment.

Do NOT perform full transcription when original narration text is
available.

Input

-   narration text
-   generated audio

Output

scene-001.alignment.json

Store

-   word timestamps
-   sentence timestamps
-   confidence

Support incremental builds.

If narration is unchanged, alignment should be skipped.

------------------------------------------------------------------------

# Part D --- Subtitle Intelligence Upgrade

Upgrade Subtitle Intelligence Engine V2.

Do NOT create a second subtitle engine.

Improve segmentation.

Priority

1 Sentence completion

2 Clause completion

3 Natural pause

4 Reading speed

5 Character limits

Character limits are safety constraints only.

Never split because a line reaches 40 characters.

Preserve complete thoughts.

Example

Bad

To be seen more. From childhood.

Good

To be seen more.

From childhood, we are taught how to earn.

Never split

-   names
-   numbers
-   quotations
-   idioms

Avoid orphan words.

Balance two-line subtitles.

------------------------------------------------------------------------

# Part E --- Timing Improvements

Use WhisperX timing.

Prefer subtitle changes

-   after pauses
-   after sentence endings
-   after dramatic statements

Avoid subtitle changes exactly on scene cuts.

Support emotion-aware timing.

------------------------------------------------------------------------

# Part F --- Validation

Extend existing SubtitleValidator.

Add checks

-   semantic boundary quality
-   CPS
-   balanced lines
-   overlap
-   orphan words
-   duration
-   duplicate cues

Existing reports should continue to work.

------------------------------------------------------------------------

# Part G --- Review Integration

Integrate into ReviewPipeline.

Failures should appear naturally inside existing review reports.

Do not invent new review systems.

Reuse RCA and Engine Feedback.

------------------------------------------------------------------------

# Part H --- Auto Remediation

Allow remediation to regenerate

-   alignment
-   subtitles

without regenerating narration.

Respect locked scenes.

Respect incremental manifests.

------------------------------------------------------------------------

# Part I --- Incremental Builds

Update manifest dependencies.

Changes

Script -\> Narration -\> Alignment -\> Subtitles -\> Video

If alignment changes

rebuild subtitles

rebuild affected scene video

rebuild final render

Do not rebuild images.

------------------------------------------------------------------------

# Part J --- Debug Artifacts

When debug enabled

subtitle-debug/

store

original alignment

segmented output

edited subtitles

validation report

timing report

Never enable by default.

------------------------------------------------------------------------

# Part K --- Configuration

Add only required settings.

KOKORO_API_KEY

KOKORO_VOICE

WHISPERX_ENABLED

WHISPERX_MODEL

SUBTITLE_SEGMENTATION_MODE=semantic

SUBTITLE_TARGET_CPS

Defaults must preserve existing behavior.

------------------------------------------------------------------------

# Part L --- Tests

Add tests for

-   Kokoro provider
-   Provider factory
-   VoicePipeline integration
-   WhisperX wrapper
-   Semantic segmentation
-   Incremental rebuild behavior
-   Validator
-   Review integration
-   Remediation integration

Run

ruff

mypy

pytest

until green.

------------------------------------------------------------------------

# Files Likely To Change

Review current implementation before modifying.

-   providers/tts/\*
-   providers/factory\*
-   voice/\*
-   subtitles/\*
-   subtitles/editor/\*
-   build/\*
-   review/\*
-   remediation/\*
-   config/settings.py
-   CLI registration
-   tests/\*

Modify only where necessary.

------------------------------------------------------------------------

# Deliverables

-   Kokoro provider
-   WhisperX integration
-   Subtitle Intelligence Engine V2 upgrade
-   Validator enhancements
-   Incremental build integration
-   Review integration
-   Auto remediation integration
-   Configuration updates
-   Tests
-   Documentation

At completion provide:

1.  Files changed
2.  Architectural decisions
3.  Backward compatibility notes
4.  Remaining future improvements
