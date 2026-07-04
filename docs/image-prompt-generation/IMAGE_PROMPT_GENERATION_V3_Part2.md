# IMAGE_PROMPT_GENERATION_V3.md

# Part 2 --- Visual Reasoning Engine

> **Status:** Part 2 of the V3 specification
>
> **Scope:** Defines how Claude should *think* before writing an image
> prompt.

------------------------------------------------------------------------

# Objective

The Scene Planner must stop converting narration directly into prompts.

Instead, every scene must pass through an internal **Visual Reasoning
Engine**.

This reasoning is internal only.

The external output remains exactly the same:

-   narration
-   image_prompt
-   duration
-   title

------------------------------------------------------------------------

# Principle

Do not ask:

> "What image matches this narration?"

Ask:

> "If this narration were a scene in a world-class documentary, what
> would the director choose to show?"

------------------------------------------------------------------------

# Internal Reasoning Pipeline

For every scene, internally execute the following steps.

## Step 1 --- Extract the Core Idea

Summarize the narration in one sentence.

Examples:

-   Desire is endless.
-   Time changes everyone.
-   Peace comes from within.
-   Ego seeks validation.

Do not include visual details.

------------------------------------------------------------------------

## Step 2 --- Identify the Emotional Target

Choose one dominant emotion.

Possible values include:

-   Curiosity
-   Wonder
-   Mystery
-   Hope
-   Fear
-   Grief
-   Peace
-   Joy
-   Isolation
-   Regret
-   Determination
-   Reverence

Avoid mixing multiple emotions unless intentionally transitioning.

------------------------------------------------------------------------

## Step 3 --- Determine the Storytelling Strategy

Choose the strongest visual approach.

Possible strategies:

-   Literal documentary
-   Symbolic metaphor
-   Emotional portrait
-   Environmental storytelling
-   Historical reenactment
-   Nature symbolism
-   Architectural symbolism
-   Macro detail
-   Object symbolism
-   Abstract visual concept
-   Human interaction
-   Landscape narrative

Prefer symbolism whenever it communicates the message more effectively.

------------------------------------------------------------------------

## Step 4 --- Select the Subject

Choose the primary subject.

Examples:

-   Main character
-   Child
-   Elder
-   Monk
-   Businessperson
-   Empty room
-   Temple
-   Forest
-   River
-   Desert
-   Lighthouse
-   Staircase
-   Candle
-   Mirror

The subject should serve the idea, not merely mirror the narration.

------------------------------------------------------------------------

## Step 5 --- Build the Environment

The environment must reinforce the emotional message.

Examples:

Peace

-   calm lake
-   quiet monastery
-   snowy valley

Isolation

-   abandoned station
-   empty apartment
-   foggy shoreline

Ambition

-   financial district
-   towering skyscrapers
-   endless staircase

Never use environments randomly.

------------------------------------------------------------------------

## Step 6 --- Decide the Scale

Select the best shot size.

Options:

-   Extreme wide
-   Wide
-   Medium
-   Close portrait
-   Extreme close-up
-   Macro

Alternate scale across neighboring scenes to create visual rhythm.

------------------------------------------------------------------------

## Step 7 --- Choose Camera Perspective

Possible choices:

-   Eye level
-   Low angle
-   High angle
-   Drone
-   Overhead
-   Side profile
-   Behind subject
-   Through foreground objects

Perspective must support emotion.

Example:

Power → low angle

Vulnerability → high angle

Reflection → behind subject

------------------------------------------------------------------------

## Step 8 --- Choose Lighting

Lighting communicates emotion.

Examples:

Golden hour

-   hope
-   peace

Blue hour

-   mystery
-   contemplation

Storm

-   conflict

Soft window light

-   introspection

Practical candlelight

-   spirituality

Lighting should never be decorative.

It should carry narrative meaning.

------------------------------------------------------------------------

## Step 9 --- Choose Color Language

Examples:

Gold → enlightenment

Blue → reflection

Green → renewal

Gray → uncertainty

Amber → nostalgia

White → transcendence

Black → the unknown

Choose a restrained palette.

Avoid oversaturated imagery.

------------------------------------------------------------------------

## Step 10 --- Search for a Stronger Metaphor

Before accepting the first idea, ask:

Can this become more memorable?

Example

Narration:

"The ego wants more."

Reject:

Businessman counting money.

Prefer:

An endless staircase vanishing into clouds.

Repeat this process until a memorable image is found.

------------------------------------------------------------------------

# Visual Memory Test

Imagine the viewer watched the video yesterday.

Ask:

Which image would they still remember today?

Generate that image.

Not the most literal one.

------------------------------------------------------------------------

# Continuity Awareness

The current batch is a sequence, not isolated prompts.

Internally remember:

-   previous environments
-   previous metaphors
-   previous camera angles
-   previous emotions
-   previous colors

Avoid accidental repetition.

Repetition is only allowed when it intentionally reinforces the story.

------------------------------------------------------------------------

# Diversity Rules

Across a batch, maximize diversity in:

-   shot size
-   perspective
-   location
-   weather
-   architecture
-   human presence
-   symbolism
-   visual texture
-   color palette
-   emotional tone

Never produce seven scenes that feel visually interchangeable.

------------------------------------------------------------------------

# Self-Question Checklist

Before finalizing each prompt, silently ask:

1.  Does this communicate the core idea?
2.  Does it evoke the intended emotion?
3.  Is there a stronger metaphor?
4.  Have I repeated a recent visual?
5.  Would a documentary director choose this shot?
6.  Is the environment meaningful?
7.  Would this frame be memorable without narration?

If any answer is "no", rethink the scene before writing the prompt.

------------------------------------------------------------------------

# Acceptance Criteria (Part 2)

A compliant implementation will:

-   Reason before generating.
-   Select visuals intentionally rather than literally.
-   Maintain continuity across the batch.
-   Balance symbolism and realism.
-   Produce prompts that feel storyboarded rather than randomly
    generated.
-   Preserve the existing YouTube Factory interfaces and outputs.

------------------------------------------------------------------------

**End of Part 2**
