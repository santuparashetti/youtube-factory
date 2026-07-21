# BGM_MIXING_ENGINE_V2.md

> **Implementation Specification for Claude Code**

**Prerequisite:** Read `MASTER_CONTEXT.md` before implementation.

## Objective

Upgrade the existing BGM engine without redesigning the architecture.

Goals:

-   Duck music immediately when narration begins.
-   Restore music naturally during narration pauses.
-   Restore full music during long silence.
-   Eliminate pumping between words.
-   Preserve compatibility with existing VideoPipeline, ReviewPipeline,
    Incremental Build and FFmpeg renderer.

------------------------------------------------------------------------

## Components to Extend

-   bgm/
-   BGMPipeline
-   mixer.py
-   detector.py
-   VideoPipeline
-   FFmpeg renderer
-   Settings
-   ReviewPipeline
-   IncrementalBuildEngine

Reuse existing architecture.

------------------------------------------------------------------------

## Processing Flow

Narration ↓ Voice Activity Detection ↓ Speech Timeline ↓ Adaptive
Ducking ↓ FFmpeg Mix ↓ Final Audio

------------------------------------------------------------------------

## Voice Activity Detection

Prefer Silero VAD.

If another VAD already exists, reuse it.

Generate a speech timeline.

Example:

0.00--3.12 Speech 3.12--4.10 Silence 4.10--8.20 Speech

Use this timeline to automate music volume.

------------------------------------------------------------------------

## Adaptive Music States

Full: - Long silence - 100% configured BGM volume

Medium: - Short narration pause - 40--60% configured volume

Ducked: - Narration active - 10--20% configured volume

Transitions must be smooth.

------------------------------------------------------------------------

## Phrase Detection

Group nearby speech into one phrase.

Do not raise music between individual words.

Default phrase gap: 300 ms.

------------------------------------------------------------------------

## Dynamic Ducking

Ducking should depend on narration energy.

Quiet voice -\> lighter ducking

Normal voice -\> standard ducking

Loud voice -\> strongest ducking

------------------------------------------------------------------------

## Compressor Defaults

bgm_volume: 0.30

bgm_duck_floor: 0.04

bgm_duck_threshold: 0.008

bgm_duck_ratio: 8.0

bgm_duck_attack_ms: 15

bgm_duck_release_ms: 350

All configurable.

------------------------------------------------------------------------

## Long Silence

If narration silence exceeds 2 seconds:

Restore music to full configured volume.

Use smooth logarithmic recovery.

------------------------------------------------------------------------

## Incremental Build

Changing only BGM settings should rebuild only downstream audio/video.

Do not regenerate script, images, narration or subtitles.

------------------------------------------------------------------------

## Validation

Extend existing review.

Validate:

-   narration intelligibility
-   pumping
-   duck timing
-   recovery timing
-   clipping
-   silence detection

Reuse RCA and ReviewPipeline.

------------------------------------------------------------------------

## Debug Output

workspace/jobs/`<project>`{=html}/bgm-debug/

-   speech_timeline.json
-   ducking_events.json
-   mix_profile.json
-   ffmpeg_filter.txt
-   audio_levels.csv

------------------------------------------------------------------------

## Configuration

bgm_vad_enabled: true

bgm_vad_provider: silero

bgm_phrase_gap_ms: 300

bgm_long_silence_ms: 2000

bgm_dynamic_ducking: true

bgm_restore_curve: logarithmic

------------------------------------------------------------------------

## Tests

Add tests for:

-   VAD
-   phrase grouping
-   adaptive ducking
-   silence recovery
-   review integration
-   incremental builds

Run Ruff, MyPy and full pytest suite.

------------------------------------------------------------------------

## Deliverables

-   BGM Mixing Engine V2
-   VAD-assisted ducking
-   Adaptive music states
-   Phrase detection
-   Improved FFmpeg filter tuning
-   Configuration updates
-   Tests
-   Documentation

Provide a completion report listing modified files, new files,
configuration changes, architectural decisions and validation results.
