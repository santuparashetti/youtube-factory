# IMAGE_PROMPT_GENERATION_V3.md

# Part 8 --- Claude Implementation Guide & Engineering Specification

> **Status:** Part 8 of the V3 specification
>
> **Scope:** Implementation guidance for Claude Code. This section
> defines how to integrate all previous parts into the existing
> `scene_planner` without changing the pipeline architecture.

------------------------------------------------------------------------

# Objective

This document is **not** asking for a new pipeline.

It is asking for a smarter reasoning process inside the existing visual
prompt generation stage.

The following components must remain untouched:

-   LangGraph graph
-   Python scene splitter
-   Batch processing
-   Scene JSON schema
-   Node interfaces
-   Workspace layout
-   CLI
-   Image providers
-   Video renderer

Only the intelligence behind `image_prompt` generation should change.

------------------------------------------------------------------------

# Implementation Philosophy

Think of the current implementation as:

    Narration
        ↓
    Image Prompt

Replace only the internal reasoning with:

    Narration
          ↓
    Core Meaning
          ↓
    Dominant Emotion
          ↓
    Storytelling Strategy
          ↓
    Visual Metaphor Selection
          ↓
    Storyboard Planning
          ↓
    Cinematography Decisions
          ↓
    Prompt Generation
          ↓
    Self Critique
          ↓
    Final Image Prompt

The external interface remains exactly the same.

------------------------------------------------------------------------

# Internal Execution Order

For each batch:

1.  Read every narration.
2.  Build a storyboard.
3.  Assign emotional progression.
4.  Plan shot diversity.
5.  Choose recurring motifs.
6.  Generate prompts.
7.  Review prompts.
8.  Improve weak prompts.
9.  Return final output.

Never generate prompts sequentially without first understanding the
batch.

------------------------------------------------------------------------

# Recommended Prompt Architecture

The system prompt used by the visual generation LLM should instruct it
to behave as:

-   Documentary Director
-   Storyboard Artist
-   Cinematographer
-   Concept Artist
-   Visual Storyteller

It should **not** identify itself as an "AI prompt generator."

------------------------------------------------------------------------

# Internal Planning (Not Output)

Before writing any prompt, Claude should internally determine:

-   What is the central idea?
-   What emotion should dominate?
-   Literal or symbolic?
-   Which metaphor communicates it best?
-   Which camera best supports the emotion?
-   Which environment reinforces the story?
-   Does this repeat a previous scene?
-   How does this transition from the previous scene?
-   What makes this frame memorable?

These questions are for reasoning only.

They must never appear in the output.

------------------------------------------------------------------------

# Prompt Writing Rules

The final prompt should:

-   Read naturally.
-   Be concise.
-   Avoid keyword spam.
-   Avoid provider-specific syntax.
-   Work across Pollinations, Flux, Leonardo, Firefly, Midjourney,
    Imagen and Gemini.

Use descriptive language rather than comma-separated keyword lists
whenever possible.

------------------------------------------------------------------------

# Performance Considerations

The reasoning process should increase quality without dramatically
increasing token usage.

Guidelines:

-   Keep reasoning internal.
-   Keep output prompt approximately the current length.
-   Avoid generating unnecessary prose.
-   Reuse style instructions efficiently.

------------------------------------------------------------------------

# Determinism

When the same narration and style are provided:

The resulting prompt should remain stylistically consistent.

Minor creative variation is acceptable.

Large random shifts in artistic direction are not.

------------------------------------------------------------------------

# Error Handling

If a narration is too abstract:

Prefer symbolic imagery.

If symbolism feels forced:

Prefer documentary realism.

If both approaches are weak:

Use environmental storytelling.

Never fall back to generic placeholders.

------------------------------------------------------------------------

# Style Adaptation

Different styles should influence metaphor selection and cinematography.

Examples:

## Spiritual

Quiet pacing.

Nature.

Temples.

Silence.

Warm practical lighting.

Contemplative imagery.

------------------------------------------------------------------------

## Documentary

Authentic environments.

Human activity.

Realistic composition.

Observational framing.

------------------------------------------------------------------------

## Educational

Clear storytelling.

Recognizable environments.

Balanced symbolism.

Readable visual hierarchy.

------------------------------------------------------------------------

## History

Period-appropriate architecture.

Historical clothing.

Weathered textures.

Authentic lighting.

------------------------------------------------------------------------

# Acceptance Tests

The implementation should satisfy the following scenarios.

## Test 1

Narration:

"Desire never ends."

Reject:

Person holding money.

Accept:

Traveler pursuing an endlessly receding oasis.

------------------------------------------------------------------------

## Test 2

Narration:

"Inner peace."

Reject:

Person meditating.

Accept:

Still lake reflecting dawn beneath ancient mountains.

------------------------------------------------------------------------

## Test 3

Narration:

"The passage of time."

Reject:

Clock.

Accept:

Stone staircase worn smooth through generations.

------------------------------------------------------------------------

## Test 4

Across seven scenes:

Verify:

-   no repeated camera framing
-   no repeated symbolic imagery
-   no repeated locations without purpose
-   emotional progression exists

------------------------------------------------------------------------

# Final Quality Gate

The implementation is successful if reviewers consistently observe:

-   stronger symbolism
-   greater visual diversity
-   better emotional communication
-   fewer generic prompts
-   improved continuity
-   memorable documentary-style imagery

without requiring any pipeline redesign.

------------------------------------------------------------------------

# Final Instruction to Claude Code

Refactor only the visual prompt generation logic and prompt template
used by `scene_planner`.

Do **not** redesign the architecture.

Do **not** introduce new nodes.

Do **not** change public interfaces.

Do **not** modify batching or scene splitting.

Your goal is to make the existing Scene Planner think like a world-class
documentary director while preserving every existing integration point.

This specification (Parts 1--8) should become the long-term design
reference for image prompt generation inside YouTube Factory.

------------------------------------------------------------------------

**End of Part 8**

**End of IMAGE_PROMPT_GENERATION_V3**
