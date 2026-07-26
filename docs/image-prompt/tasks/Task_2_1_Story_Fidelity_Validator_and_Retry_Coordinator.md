# Task 2.1 - Story Fidelity Validator & Retry Coordinator

## Objective

Task 1 successfully introduced the Story-First generation pipeline.

This task builds the **enforcement layer**.

Do NOT modify generation prompts or Scene Analysis generation.

Instead, validate the outputs of Task 1 and coordinate targeted
regeneration.

------------------------------------------------------------------------

# Scope

This task is responsible ONLY for:

-   Story Fidelity Validator
-   Retry Coordinator
-   Validator integration
-   Regression tests

Do NOT modify:

-   Script Enhancement
-   Scene Planner
-   Scene Analysis generation
-   Visual Prompt prompt templates

------------------------------------------------------------------------

# Phase 1 - Expand Scene Analysis (Backward Compatible)

Extend the existing SceneAnalysis model.

Keep all existing fields.

Add the following OPTIONAL fields:

``` yaml
scene_characters:
scene_objects:
forbidden_characters:
forbidden_objects:
visual_focus:
continuity_reference:
story_time:
camera_constraints:
```

Rules:

-   Preserve backward compatibility.
-   Existing JSON should continue to work.
-   Default values should be empty.

These fields are intended for validation, not generation.

------------------------------------------------------------------------

# Phase 2 - Implement Story Fidelity Validator

Create a new validator.

Input:

-   Scene Analysis
-   Narration
-   Generated Visual Prompt

Output:

``` yaml
passed:
errors:
warnings:
score:
```

Validation checks:

## Characters

-   Only allowed characters appear.
-   Forbidden characters do not appear.
-   No invented humans.
-   No invented animals.
-   Named people preserved.

## Story

-   Primary action represented.
-   Story goal preserved.
-   Narration represented.
-   Emotional beat represented.

## Environment

-   Environment matches.
-   Story time consistent.
-   Visual focus respected.

## Continuity

-   Characters remain consistent.
-   Environment remains consistent.
-   Camera constraints respected.

------------------------------------------------------------------------

# Phase 3 - Symbolism Validator

Reject prompts that replace the literal story.

Example

Narration

"The mother eagle encourages the chick."

Reject

-   old man
-   woman
-   monk
-   traveller
-   weathered hand
-   candle

Accept

-   mother eagle encouraging the chick

Symbolism may enhance but never replace the story.

------------------------------------------------------------------------

# Phase 4 - Realism Validator

Validate:

-   realistic proportions
-   realistic anatomy
-   realistic bird sizes
-   realistic object sizes
-   realistic architecture
-   realistic perspective
-   realistic environmental scale

Reject unrealistic prompts.

------------------------------------------------------------------------

# Phase 5 - Retry Coordinator

Implement a dedicated Retry Coordinator.

Input:

-   Validation Result

Output:

-   Regeneration request for ONLY failed scene.

Never regenerate successful scenes.

Never regenerate an entire batch.

Construct structured retry instructions.

Example:

FAILED

Reason:

Unsupported character detected.

Allowed:

-   Mother Eagle
-   Eagle Chick

Primary Action:

Chick attempting first flight.

Please regenerate while preserving Story Analysis and Narration.

------------------------------------------------------------------------

# Phase 6 - Validation Integration

Execution order:

Generated Prompt

↓

Story Fidelity Validator

↓

If PASS

Accept

↓

If FAIL

Retry Coordinator

↓

Regenerate Failed Scene

↓

Revalidate

------------------------------------------------------------------------

# Phase 7 - Regression Tests

Add tests for:

-   Character validation
-   Forbidden characters
-   Story fidelity
-   Narration fidelity
-   Environment fidelity
-   Emotional beat
-   Continuity
-   Symbolism rejection
-   Realistic proportions
-   Retry Coordinator
-   Partial regeneration only

------------------------------------------------------------------------

# Deliverables

1.  Expanded SceneAnalysis (backward compatible).
2.  Story Fidelity Validator.
3.  Symbolism Validator.
4.  Realism Validator.
5.  Retry Coordinator.
6.  Validator integration.
7.  Regression tests.
8.  Documentation describing the validation workflow.

Do NOT modify generation prompts or generation architecture in this
task.
