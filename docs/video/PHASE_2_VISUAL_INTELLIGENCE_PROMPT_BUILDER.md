# Phase 2 -- Visual Intelligence Prompt Builder

Version: 1.0

## Goal

Implement **Phase 2** of the Visual Intelligence Layer. The objective is
to make the **Prompt Builder** consume `VisualMetadata` and
automatically construct provider-ready image prompts.

### Out of Scope

Do **NOT** modify:

-   Vision QA
-   Prompt Remediation
-   Image Providers
-   Scene Planner

The Scene Planner already produces `VisualMetadata`.

------------------------------------------------------------------------

# Design Principle

The Scene Planner describes:

**WHAT happens**

VisualMetadata describes:

**WHAT the image represents**

The Prompt Builder determines:

**HOW it should look**

The Scene Planner should never explicitly include negative prompts such
as:

-   No drones
-   No helicopters
-   No smartphones

These constraints belong in the Prompt Builder.

------------------------------------------------------------------------

# Step 1 -- Prompt Builder

Create:

`video_core/visual_intelligence/prompt_builder.py`

Input:

-   Scene
-   VisualMetadata

Output:

-   PromptPackage

The Prompt Builder becomes the only component responsible for prompt
assembly.

------------------------------------------------------------------------

# Step 2 -- Visual Profiles

Create:

`video_core/visual_intelligence/profiles/`

Profiles:

-   ancient_documentary.py
-   historical_documentary.py
-   modern_documentary.py
-   symbolic_documentary.py
-   transitional_documentary.py

Each profile should expose:

-   Positive prompt fragments
-   Negative prompt fragments
-   Lighting hints
-   Architecture hints
-   Materials
-   Atmosphere
-   Camera hints
-   Color palette hints

The Prompt Builder composes these automatically.

------------------------------------------------------------------------

# Step 3 -- Era Behaviour

## Ancient

Automatically inject:

-   historically authentic
-   ancient architecture
-   stone temples
-   natural materials
-   traditional clothing
-   cinematic documentary realism

Negative constraints:

-   drones
-   aircraft
-   helicopters
-   cars
-   roads
-   smartphones
-   cameras
-   power lines
-   glass buildings
-   modern clothing
-   plastic
-   electronics

## Historical

Historically authentic.

## Modern

Allow:

-   smartphones
-   laptops
-   cars
-   roads
-   offices
-   apartments
-   coffee shops
-   airports

## Symbolic

Use:

-   timeless
-   dreamlike
-   ethereal
-   abstract
-   metaphorical

## Transitional

Allow intentional coexistence of ancient and modern elements.

------------------------------------------------------------------------

# Step 4 -- Narrative Role

Narrative roles influence prompts.

-   STORY → literal documentary
-   ANALOGY → blend concept and reality
-   METAPHOR → symbolic imagery
-   EXPLANATION → educational clarity
-   ESTABLISHING → wide cinematic composition
-   CTA → clean composition with overlay space

------------------------------------------------------------------------

# Step 5 -- Mood

Mood influences:

-   Lighting
-   Weather
-   Atmosphere
-   Color palette

Examples:

-   PEACEFUL → warm golden light
-   FEARFUL → stormy contrast
-   REFLECTIVE → soft evening light
-   MYSTERIOUS → fog and moonlight

------------------------------------------------------------------------

# Step 6 -- Environment

Environment enriches prompts automatically.

Examples:

-   TEMPLE
-   FOREST
-   KINGDOM
-   OFFICE
-   CITY
-   MOUNTAIN
-   ABSTRACT
-   COSMIC

------------------------------------------------------------------------

# Step 7 -- Prompt Assembly

Prompt is assembled in layers:

1.  Scene Description
2.  Visual Profile
3.  Era Rules
4.  Environment
5.  Narrative Role
6.  Mood
7.  Provider formatting

Providers remain provider-agnostic.

------------------------------------------------------------------------

# Step 8 -- PromptPackage

Create a first-class PromptPackage object.

Fields:

-   final_prompt
-   negative_prompt
-   visual_profile
-   prompt_fingerprint
-   metadata_snapshot

Future stages consume PromptPackage instead of raw prompt strings.

------------------------------------------------------------------------

# Step 8.5 -- Prompt Assembly Report (Debug)

Generate a structured report.

Include:

-   Scene Description
-   Visual Metadata
-   Applied Profile
-   Positive Constraints
-   Negative Constraints
-   Environment Enhancements
-   Mood Enhancements
-   Narrative Role Enhancements
-   Prompt Statistics
-   Final Prompt (optional)

Configuration:

``` env
PROMPT_DEBUG_REPORT=true
PROMPT_LOG_FULL_TEXT=false
PROMPT_LOG_METADATA=true
```

------------------------------------------------------------------------

# Step 8.6 -- Prompt Fingerprinting

Generate deterministic SHA256 fingerprint.

Store with:

-   Scene Number
-   Metadata
-   Provider
-   Prompt Length
-   Timestamp

Purpose:

-   Compare regenerations
-   Debug prompt evolution
-   Track prompt stability

------------------------------------------------------------------------

# Step 8.7 -- Prompt Diff

When remediation regenerates an image:

Generate structured diff.

Show:

-   Added constraints
-   Removed constraints
-   Changed constraints

Log the diff.

------------------------------------------------------------------------

# Step 9 -- Backward Compatibility

If VisualMetadata is absent:

Fall back to current prompt generation.

No existing pipeline should break.

------------------------------------------------------------------------

# Step 10 -- Tests

Verify:

-   Ancient prompts include historical constraints.
-   Modern prompts allow technology.
-   Symbolic prompts remain timeless.
-   Transitional prompts intentionally mix eras.
-   NarrativeRole changes prompt construction.
-   Mood changes atmosphere.
-   Existing providers require zero changes.
-   Existing pipelines continue working.

------------------------------------------------------------------------

# Deliverables

-   Prompt Builder
-   Visual Profiles
-   PromptPackage
-   Prompt Assembly Report
-   Prompt Fingerprinting
-   Prompt Diff
-   Full test coverage

Stop after Phase 2 implementation and provide a summary before Phase 3.
