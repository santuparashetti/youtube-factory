# ASS_SUBTITLE_ENGINE_V1

## Goal

Replace SRT as the primary subtitle format with ASS while keeping SRT
for compatibility/debug.

## Objectives

-   Production-quality subtitles
-   Config-driven styling
-   Better readability
-   Future-ready for animations and karaoke
-   Provider-independent architecture

## Pipeline

Speech Formatter → Subtitle Intelligence → ASS Subtitle Engine → ASS +
SRT Outputs → Video Renderer

## Features

### V1

-   ASS generation
-   SRT generation
-   Smart line breaking
-   Reading-speed validation
-   Default style/theme
-   Safe margins
-   Multi-style support
-   Scene-aware positioning
-   Validation
-   Debug mode

### Future

-   Word highlighting
-   Karaoke
-   Bounce/Fade animations
-   Multi-language themes
-   Dynamic positioning
-   Speaker styles

## Architecture

providers/ services/ models/ config/ validators/ tests/

## Configuration

-   font
-   size
-   colors
-   outline
-   shadow
-   margins
-   alignment
-   max chars/line
-   max reading speed
-   theme

## Outputs

workspace/subtitles/ - subtitles.ass - subtitles.srt -
subtitle-debug.json

## Validation

-   No overlap
-   Reading speed
-   Line length
-   Timing checks
-   Style validation

## Tests

-   Unit
-   Integration
-   Visual regression
-   Renderer compatibility

## Claude Implementation Prompt

Read MASTER_CONTEXT.md first.

Implement ASS_SUBTITLE_ENGINE_V1 following the existing architecture.

Requirements: - Preserve backward compatibility. - ASS is the primary
subtitle output. - Continue generating SRT for compatibility/debug. -
Build a clean, provider-independent module. - Add configuration,
validation, diagnostics and debug mode. - Integrate with Subtitle
Intelligence and Video Renderer. - Produce professional default
styling. - Keep the implementation extensible for karaoke, animations
and word highlighting. - Add comprehensive unit/integration tests. -
Update documentation. - Continue until production-ready. Do not stop at
partial implementation.
