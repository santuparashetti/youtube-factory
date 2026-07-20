# Phase 3 -- Era-Aware Vision QA

Version: 1.0

## Goal

Implement **Phase 3** of the Visual Intelligence Layer.

The objective is to make Vision QA consume `VisualMetadata` so image
validation becomes context-aware instead of relying on generic rules.

## Out of Scope

Do NOT modify:

-   Scene Planner
-   Prompt Builder
-   Image Providers
-   Prompt Remediation (Phase 4)

The Prompt Builder already assembles prompts using VisualMetadata.
Vision QA should now validate generated images against the same
metadata.

------------------------------------------------------------------------

# Design Principles

Vision QA should answer:

**"Is this image correct for this scene?"**

rather than

**"Is this a good image?"**

Validation depends on the scene context.

------------------------------------------------------------------------

# Step 1 -- Consume VisualMetadata

Update the VisionReview interface so every review receives:

-   Scene
-   VisualMetadata
-   PromptPackage
-   Image

No provider-specific logic.

All providers receive the same metadata.

------------------------------------------------------------------------

# Step 2 -- Era-Aware Validation

## Ancient

Reject:

-   drones
-   helicopters
-   aircraft
-   smartphones
-   cameras
-   roads
-   modern vehicles
-   glass buildings
-   concrete highways
-   power lines
-   LED lighting
-   plastic
-   modern clothing
-   laptops
-   televisions

Severity:

HIGH

Category:

Anachronism

recommend_regeneration=true

------------------------------------------------------------------------

## Historical

Same philosophy.

Require historical authenticity.

------------------------------------------------------------------------

## Modern

Allow:

-   smartphones
-   laptops
-   offices
-   traffic
-   apartments
-   airports
-   coffee shops
-   contemporary clothing

Do not reject modern technology unless it is inconsistent with the
narration.

------------------------------------------------------------------------

## Symbolic

Use relaxed validation.

Allow:

-   surreal imagery
-   floating objects
-   abstract light
-   dreamlike environments

Reject only obvious unintended artifacts.

------------------------------------------------------------------------

## Transitional

Allow intentional coexistence of:

-   Ancient
-   Historical
-   Modern

Only reject objects that contradict the intended comparison.

------------------------------------------------------------------------

# Step 3 -- Narrative Role Validation

Validate according to NarrativeRole.

STORY

-   Literal realism

ANALOGY

-   Conceptual consistency

METAPHOR

-   Symbolic imagery allowed

EXPLANATION

-   Educational clarity

ESTABLISHING

-   Strong environment

CTA

-   Clean composition
-   Room for text overlays

------------------------------------------------------------------------

# Step 4 -- Environment Validation

Verify scene environment matches metadata.

Examples:

TEMPLE

-   Temple architecture
-   Traditional materials

OFFICE

-   Modern workspace

FOREST

-   Natural vegetation

CITY

-   Urban environment

ABSTRACT

-   Avoid forcing realism

------------------------------------------------------------------------

# Step 5 -- Mood Validation

Validate atmosphere.

Examples:

PEACEFUL

-   Soft lighting

FEARFUL

-   Dark contrast

REFLECTIVE

-   Warm evening tones

MYSTERIOUS

-   Fog
-   Moonlight
-   Low visibility

Mood mismatches should be MEDIUM severity unless critical.

------------------------------------------------------------------------

# Step 6 -- VisionIssue Categories

Support structured issue types:

-   Anatomy
-   Artifact
-   Anachronism
-   Environment
-   Mood
-   Composition
-   Camera
-   Lighting
-   Text
-   Style
-   HistoricalAccuracy

Every issue includes:

-   Category
-   Severity
-   Description
-   Location
-   Confidence
-   Recommendation

------------------------------------------------------------------------

# Step 7 -- Quality Report

Produce a Vision Quality Report.

Include:

-   Overall Score
-   Historical Consistency
-   Environment Match
-   Mood Match
-   Narrative Alignment
-   Composition
-   Artifact Detection
-   Anatomy Detection

Output JSON only.

------------------------------------------------------------------------

# Step 8 -- Regeneration Hints

For failed reviews generate structured remediation hints.

Example:

Remove: - drone - helicopter

Increase: - historical authenticity - traditional architecture

Preserve: - composition - lighting

Do not regenerate automatically in this phase.

Only produce recommendations.

------------------------------------------------------------------------

# Step 9 -- Logging

Debug logs should include:

-   Scene Number
-   Era
-   Narrative Role
-   Environment
-   Mood
-   Validation Categories
-   Issues Found
-   Score
-   Regeneration Recommended

Production logs should remain concise.

------------------------------------------------------------------------

# Step 10 -- Metrics

Track:

-   Reviews by Era
-   Reviews by Narrative Role
-   Pass Rate by Era
-   Failure Rate by Era
-   Common Anachronisms
-   Common Anatomy Issues
-   Common Environment Issues
-   Average Score
-   Regeneration Recommendation Rate

------------------------------------------------------------------------

# Step 11 -- Backward Compatibility

If VisualMetadata is missing:

Use current generic Vision QA behaviour.

Do not break existing pipelines.

------------------------------------------------------------------------

# Step 12 -- Tests

Verify:

-   Ancient scenes reject drones.
-   Ancient scenes reject smartphones.
-   Historical scenes reject modern architecture.
-   Modern scenes allow phones and offices.
-   Symbolic scenes allow abstract imagery.
-   Transitional scenes allow intentional era mixing.
-   Existing providers require zero modification.
-   Existing pipelines continue working.

------------------------------------------------------------------------

# Deliverables

-   Era-aware Vision QA
-   Structured issue taxonomy
-   Vision Quality Report
-   Regeneration recommendations
-   Metrics
-   Full automated tests

Stop after Phase 3 implementation and provide a summary before Phase 4.
