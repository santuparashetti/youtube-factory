# Phase 4 -- Intelligent Prompt Remediation Engine

Version: 1.0

## Goal

Implement **Phase 4** of the Visual Intelligence Layer.

The objective is to intelligently repair failed image generations using
the results from Vision QA and the existing PromptPackage instead of
blindly retrying with the same prompt.

## Out of Scope

Do NOT modify:

-   Scene Planner
-   VisualMetadata model
-   Prompt Builder (Phase 2)
-   Vision QA rules (Phase 3)
-   Image Providers

Use existing outputs from previous phases.

------------------------------------------------------------------------

# Design Principles

The remediation engine should answer:

**"What is the smallest change required to produce a correct image?"**

It should preserve everything that already works and modify only the
failed aspects.

Never rebuild prompts from scratch unless explicitly requested.

------------------------------------------------------------------------

# Step 1 -- Inputs

Consume:

-   Scene
-   VisualMetadata
-   PromptPackage
-   VisionReviewResult
-   VisionIssues
-   Original Image (optional reference)

Output:

-   RemediationPackage

------------------------------------------------------------------------

# Step 2 -- RemediationPackage

Create a first-class object.

Fields:

-   original_prompt
-   remediated_prompt
-   remediation_reason
-   issues_fixed
-   preserved_constraints
-   added_constraints
-   removed_constraints
-   prompt_diff
-   remediation_strategy
-   attempt_number

------------------------------------------------------------------------

# Step 3 -- Strategy Selection

Select a strategy based on VisionIssue categories.

Examples:

Anachronism → strengthen historical constraints

Anatomy → improve anatomy instructions

Artifacts → increase realism / remove artifacts

Lighting → adjust lighting guidance

Environment → reinforce environment description

Mood → reinforce atmosphere

Composition → improve framing guidance

Multiple issues → combine strategies without duplicating prompt
fragments.

------------------------------------------------------------------------

# Step 4 -- Minimal Prompt Editing

Never regenerate a completely new prompt.

Preserve:

-   subject
-   composition
-   environment
-   mood
-   narrative role

Only modify sections related to detected issues.

------------------------------------------------------------------------

# Step 5 -- Era-Aware Remediation

ANCIENT

Increase:

-   historical authenticity
-   traditional architecture
-   natural materials

Explicitly remove:

-   drones
-   aircraft
-   roads
-   phones
-   power lines
-   modern buildings

MODERN

Do not remove modern technology unless Vision QA identifies it as
inconsistent.

SYMBOLIC

Increase metaphorical guidance rather than historical constraints.

TRANSITIONAL

Preserve intentional mixing of eras.

------------------------------------------------------------------------

# Step 6 -- Confidence-Based Escalation

Low severity:

Adjust prompt only.

Medium severity:

Strengthen constraints.

High severity:

Significant remediation.

Critical:

Recommend full regeneration while preserving story intent.

------------------------------------------------------------------------

# Step 7 -- Retry Policy

Support configurable retry strategy.

Example:

MAX_REMEDIATION_ATTEMPTS=3

Attempt 1

Minimal edits.

Attempt 2

Stronger constraints.

Attempt 3

Aggressive remediation while preserving narrative.

After maximum attempts, return best result and report failure.

------------------------------------------------------------------------

# Step 8 -- Prompt Diff

Generate a structured diff.

Added

-   historical authenticity
-   traditional clothing

Removed

-   modern skyline
-   helicopter

Changed

-   lighting
-   camera angle
-   composition

Store for debugging and analytics.

------------------------------------------------------------------------

# Step 9 -- Logging

Debug logs:

Scene

Attempt

Strategy

Issues

Prompt diff

Constraints added

Constraints removed

Production logs:

Attempt number

Strategy

Result

Latency

------------------------------------------------------------------------

# Step 10 -- Metrics

Track:

-   remediation attempts
-   success rate
-   success by issue type
-   success by era
-   average retries
-   prompt growth
-   regeneration savings

------------------------------------------------------------------------

# Step 11 -- Learning Hooks

Persist anonymized remediation data for future analytics.

Store:

-   issue categories
-   remediation strategy
-   outcome
-   prompt fingerprint

No provider-specific information.

No user-specific information.

------------------------------------------------------------------------

# Step 12 -- Backward Compatibility

If VisualMetadata or PromptPackage is unavailable:

Fall back to the existing remediation behaviour.

Do not break existing pipelines.

------------------------------------------------------------------------

# Step 13 -- Tests

Verify:

-   Anachronisms strengthen historical constraints.
-   Anatomy issues preserve scene intent.
-   Mood issues only modify atmosphere.
-   Prompt diffs are correct.
-   Retry escalation behaves correctly.
-   Maximum retry limit respected.
-   Existing providers require zero changes.
-   Existing pipelines continue working.

------------------------------------------------------------------------

# Deliverables

-   RemediationPackage
-   Strategy Engine
-   Minimal Prompt Editing
-   Prompt Diff
-   Retry Escalation
-   Metrics
-   Full automated tests

Stop after Phase 4 implementation and provide a summary before Phase 5.
