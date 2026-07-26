# Task 1 - Story First Pipeline Refactor (Generation Only)

## Objective

Refactor the **generation pipeline only** so every generated visual
prompt faithfully represents the original story.

The objective is **story fidelity**, **not additional creativity**.

------------------------------------------------------------------------

# Scope

This task is responsible ONLY for improving generation.

This task MUST NOT:

-   Modify validation logic
-   Modify retry logic
-   Add regression tests
-   Redesign validator behaviour

Those belong to **Task 2**.

------------------------------------------------------------------------

# Phase 1 - Audit the Existing Pipeline

Inspect the current implementation and identify:

-   Script Enhancement
-   Scene Planning
-   Narration Generation
-   Entity Extraction
-   Visual Prompt Generation

For each stage document:

-   Purpose
-   Inputs
-   Outputs
-   Responsible files/classes/functions
-   Weaknesses

Produce a short audit report before changing code.

------------------------------------------------------------------------

# Phase 2 - Story First Architecture

Refactor the logical generation flow to:

Base Script

↓

Enhanced Script

↓

Scene Planning

↓

Scene Analysis (NEW)

↓

Visual Prompt Generation

Image generation must no longer rely only on narration.

------------------------------------------------------------------------

# Phase 3 - Implement Scene Analysis

Introduce a structured Scene Analysis object for every scene.

Suggested schema:

``` yaml
scene_id:

characters:

allowed_characters:

primary_subject:

secondary_subjects:

environment:

primary_action:

emotional_beat:

story_goal:

human_requirement:

named_person:

camera_focus:
```

Scene Analysis becomes the source of truth for prompt generation.

------------------------------------------------------------------------

# Phase 4 - Character Rules

Characters may ONLY come from:

-   Base Story
-   Enhanced Narration
-   Scene Analysis

Never invent:

-   man
-   woman
-   monk
-   traveller
-   sage
-   observer
-   narrator
-   silhouette
-   child

unless explicitly present.

Never replace animals with humans.

Example:

Story

-   Mother Eagle
-   Eagle Chick

Prompt

-   Mother Eagle
-   Eagle Chick

NOT

-   Old Man
-   Woman
-   Monk

------------------------------------------------------------------------

# Phase 5 - Narration Rules

Narration determines:

-   story beat
-   action
-   emotion
-   exact cinematic moment

Each scene should represent ONE narration moment.

Example

Narration

"The chick rose a little. Came down. Tried again."

Correct

-   chick struggling in flight
-   mother watching

Incorrect

-   human watching an eagle

------------------------------------------------------------------------

# Phase 6 - Visual Prompt Rules

Visual Prompt should describe ONLY:

-   composition
-   framing
-   camera
-   lens
-   lighting
-   environment
-   atmosphere
-   colours

It must never rewrite the story.

Priority:

1.  Story
2.  Narration
3.  Scene Analysis
4.  Camera
5.  Artistic enhancement

------------------------------------------------------------------------

# Phase 7 - Story First Prompt Templates

Review and refactor prompts used by:

-   Script Enhancement
-   Scene Planning
-   Entity Extraction
-   Visual Prompt Generation

Rewrite them to enforce:

-   Story fidelity
-   Narration-driven visuals
-   No invented characters
-   No invented events
-   Character continuity
-   Environmental continuity
-   Realistic proportions
-   Realistic perspective

The prompts should be deterministic rather than creative.

------------------------------------------------------------------------

# Phase 8 - Deliverables

Provide:

1.  Pipeline audit report.
2.  Updated generation architecture.
3.  Scene Analysis implementation.
4.  Refactored prompt templates.
5.  Summary of code changes.
6.  Backward compatibility notes.

Do NOT modify:

-   Validation
-   Retry logic
-   Validation rules
-   Regression tests

Those belong exclusively to Task 2.
