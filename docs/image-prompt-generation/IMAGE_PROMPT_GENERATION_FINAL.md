# IMAGE_PROMPT_GENERATION_FINAL.md

# Final Implementation Instructions for Claude Code

## Objective

Improve **only** the image prompt generation inside `scene_planner`.

Preserve:

-   LangGraph graph
-   Python scene splitter
-   Batch generation
-   JSON schema
-   Public interfaces
-   Downstream pipeline
-   Workspace layout

Only change how `image_prompt` is generated.

------------------------------------------------------------------------

# Read Before Coding

Before making any code changes:

1.  Read this document completely.
2.  Read `IMAGE_PROMPT_GENERATION_V3_Part1.md` through
    `IMAGE_PROMPT_GENERATION_V3_Part8.md`.
3.  Understand the existing implementation.
4.  Refactor only the visual prompt generation prompt/template and
    reasoning.

------------------------------------------------------------------------

# Replace Prompt Generation with Visual Direction

Do **not** think:

Narration → Prompt

Instead internally perform:

Narration → Core Meaning → Dominant Emotion → Storytelling Strategy →
Visual Metaphor → Storyboard Planning → Character Continuity → Camera
Planning → Lighting & Composition → Prompt Draft → Self Critique → Final
Prompt

This reasoning is internal only.

------------------------------------------------------------------------

# Treat Every Batch as One Film

Never generate prompts independently.

Before generating any prompt:

-   Read every narration in the batch.
-   Build a storyboard.
-   Decide emotional progression.
-   Decide hero moments.
-   Plan visual rhythm.
-   Plan callbacks.
-   Plan diversity.

Only then generate prompts.

------------------------------------------------------------------------

# Think Like a Director

Do not describe narration.

Direct scenes.

Always ask:

-   What should the audience feel?
-   What should they remember tomorrow?
-   What single image best communicates this idea?

------------------------------------------------------------------------

# Character Bible

If narration follows one protagonist:

Maintain:

-   same age
-   same ethnicity
-   same appearance
-   same clothing
-   same emotional progression

Never replace the protagonist with random people.

------------------------------------------------------------------------

# Style Bible

Maintain a consistent documentary identity.

Avoid random artistic shifts.

Use restrained cinematic language.

Natural colors.

Authentic environments.

Realistic textures.

Subtle film grain.

Photorealistic documentary.

------------------------------------------------------------------------

# Visual Storytelling Rules

Prefer:

-   symbolism
-   environmental storytelling
-   documentary realism
-   architecture
-   nature
-   object symbolism

Avoid simply illustrating words.

Example

Desire

❌ businessman holding money

✅ endless staircase disappearing into clouds

Peace

❌ person meditating

✅ still mountain lake before dawn

Time

❌ clock

✅ weathered stone staircase worn by generations

------------------------------------------------------------------------

# Scene Diversity

Across a batch vary:

-   shot size
-   perspective
-   environment
-   weather
-   lighting
-   architecture
-   symbolism
-   emotional intensity

Avoid repeating:

-   standing person
-   mountain
-   lake
-   flower
-   sunset
-   silhouette

unless intentionally used as a callback.

------------------------------------------------------------------------

# Continuity

Every prompt should know:

previous scene

current scene

next scene

If scenes can be randomly shuffled without affecting the experience,

the storyboard is weak.

------------------------------------------------------------------------

# Hero Frames

Every batch should contain at least one unforgettable frame suitable for
a thumbnail.

Not every scene should attempt to be a hero frame.

------------------------------------------------------------------------

# Environmental Storytelling

Avoid empty backgrounds.

The environment should reveal emotional context.

Instead of

"A man sitting."

Prefer

"A weary businessman sits alone in a luxury apartment overlooking a
rain-soaked city, untouched dinner growing cold beside him."

------------------------------------------------------------------------

# Prompt Structure

Internally think in this order:

Subject

Action

Environment

Emotion

Camera

Composition

Lighting

Atmosphere

Style

Negative prompt

Output one natural paragraph.

Never keyword spam.

------------------------------------------------------------------------

# Camera Language

Only include camera decisions that strengthen the story.

Examples:

wide establishing shot

macro detail

low angle

overhead

behind subject

shallow depth of field

volumetric light

Do not append identical cinematic keywords to every prompt.

------------------------------------------------------------------------

# Prompt Quality

Every prompt must answer:

-   What does this scene mean?
-   What emotion dominates?
-   Is the visual memorable?
-   Is there a stronger metaphor?
-   Does it repeat a previous prompt?
-   Would a documentary director shoot this?

If not,

rewrite before returning.

------------------------------------------------------------------------

# Anti-Template Rules

Never begin prompts with:

"A figure..."

"A person..."

"The camera is positioned..."

"The subject is shown..."

Write naturally.

Example:

"A weary middle-aged man walks alone through..."

instead of

"A figure is shown walking..."

------------------------------------------------------------------------

# Anti-Repetition

Track previous prompts.

Reject repetition of:

camera

environment

weather

metaphor

pose

composition

color

unless intentionally creating narrative continuity.

------------------------------------------------------------------------

# Acceptance Criteria

Implementation is successful when:

-   prompts feel storyboarded instead of generated
-   visuals communicate meaning without narration
-   metaphors are memorable
-   characters remain consistent
-   scenes flow like one documentary
-   prompts are concise and model agnostic
-   architecture remains unchanged

------------------------------------------------------------------------

# Final Instruction

Refactor only the visual prompt generation logic.

Do not redesign the pipeline.

Do not introduce new nodes.

Do not change interfaces.

The goal is to make the existing Scene Planner behave like a world-class
documentary director rather than an image prompt generator.
