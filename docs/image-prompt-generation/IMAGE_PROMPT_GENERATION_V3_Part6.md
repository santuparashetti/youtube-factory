# IMAGE_PROMPT_GENERATION_V3.md

# Part 6 --- Prompt Generation Engine

> **Status:** Part 6 of the V3 specification
>
> **Scope:** Defines how the Scene Planner converts its internal
> reasoning into high-quality, model-agnostic image prompts.

------------------------------------------------------------------------

# Objective

The Prompt Generation Engine is the final stage of the Scene Planner.

It receives the completed internal reasoning from Parts 1--5 and
transforms it into a single, concise, cinematic image prompt.

It must not invent new narrative ideas.

Its job is to faithfully translate the planned visual into language that
modern image models understand.

------------------------------------------------------------------------

# Inputs

The Prompt Generation Engine receives:

-   Scene narration
-   Core idea
-   Dominant emotion
-   Storytelling strategy
-   Selected metaphor (if applicable)
-   Subject
-   Environment
-   Camera decisions
-   Composition
-   Lighting
-   Color palette
-   Continuity context
-   Previous scene context
-   Style guide

These are internal only.

------------------------------------------------------------------------

# Outputs

Continue producing exactly the existing output:

-   image_prompt

No new JSON fields.

No pipeline changes.

------------------------------------------------------------------------

# Prompt Construction Order

Always build prompts using the following order:

1.  Primary subject
2.  Action or state
3.  Environment
4.  Emotional context
5.  Camera language
6.  Composition
7.  Lighting
8.  Atmosphere
9.  Visual style
10. Quality modifiers
11. Negative prompt

This order improves consistency across models.

------------------------------------------------------------------------

# Subject Rules

Lead with the most important visual element.

Good:

"A weary middle-aged man..."

"An ancient temple corridor..."

"A lone lighthouse..."

Poor:

"Cinematic photorealistic..."

Never begin with quality modifiers.

------------------------------------------------------------------------

# Action Rules

Describe natural actions.

Examples:

walking

watching

climbing

standing in silence

holding worn prayer beads

looking toward the horizon

Avoid static descriptions when movement can improve storytelling.

------------------------------------------------------------------------

# Environment Rules

Environments should support emotion.

Include meaningful details.

Examples:

rain on windows

weathered stone

morning mist

dust particles

ancient wood

soft incense smoke

Avoid empty backgrounds.

------------------------------------------------------------------------

# Camera Language

Mention only the camera choices that matter.

Do not overload prompts.

Good:

wide establishing shot

low-angle portrait

macro detail

overhead view

Avoid listing every cinematic keyword.

------------------------------------------------------------------------

# Lighting Rules

Lighting should reinforce the emotional objective.

Examples:

soft morning light

warm candlelight

storm clouds with diffused sunlight

volumetric rays through forest

Avoid decorative lighting that serves no purpose.

------------------------------------------------------------------------

# Style Language

Append a concise visual style.

Example:

cinematic documentary, photorealistic, realistic textures, natural
colors, subtle film grain

Avoid excessive keyword stuffing.

------------------------------------------------------------------------

# Negative Prompt

Append a short model-agnostic negative prompt.

Example:

No text, logo, watermark, blurry, low quality, deformed anatomy,
duplicate subjects, cartoon, CGI, oversaturated colors.

Keep it concise.

------------------------------------------------------------------------

# Length Guidelines

Target:

80--150 words.

Enough detail for high-quality generation.

Avoid unnecessarily long prompts.

Every sentence should contribute visual information.

------------------------------------------------------------------------

# Repetition Filter

Before finalizing:

Compare against prompts already generated in the current batch.

If the same:

-   location
-   metaphor
-   framing
-   lighting
-   weather
-   subject pose

appears too frequently,

rewrite.

------------------------------------------------------------------------

# Quality Checklist

Silently verify:

✓ Strong focal point

✓ Clear emotion

✓ Memorable imagery

✓ Cinematic framing

✓ Environmental storytelling

✓ Diversity from neighboring scenes

✓ Consistency with style

Only then produce the prompt.

------------------------------------------------------------------------

# Prompt Skeleton (Internal)

\[Subject\]

\[Action\]

\[Environment\]

\[Emotional context\]

\[Camera\]

\[Lighting\]

\[Composition\]

\[Atmosphere\]

\[Style\]

[Negative prompt](#negative-prompt)

The skeleton is internal.

Output only a natural, fluent image prompt.

------------------------------------------------------------------------

# Example

Weak:

"A man sitting beside a lake at sunset."

Improved:

"A weary middle-aged man sits quietly on a weathered wooden dock
overlooking a perfectly still mountain lake before sunrise, thin mist
drifting across the water, subtle ripples reflecting pale golden light,
captured in a wide cinematic composition that emphasizes solitude and
inner peace, photorealistic documentary style, realistic textures,
natural color grading, subtle film grain. No text, logo, watermark,
blurry, cartoon, CGI."

------------------------------------------------------------------------

# Acceptance Criteria (Part 6)

A successful implementation will:

-   Generate concise but information-rich prompts.
-   Preserve internal reasoning from earlier stages.
-   Produce model-agnostic prompts.
-   Minimize repetition.
-   Avoid keyword stuffing.
-   Improve image quality without changing pipeline architecture.

------------------------------------------------------------------------

**End of Part 6**
