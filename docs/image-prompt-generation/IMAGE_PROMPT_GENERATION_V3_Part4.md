# IMAGE_PROMPT_GENERATION_V3.md

# Part 4 --- Visual Metaphor Library

> **Status:** Part 4 of the V3 specification
>
> **Scope:** Teach the Scene Planner to translate abstract ideas into
> memorable cinematic imagery.

------------------------------------------------------------------------

# Objective

The greatest weakness of AI-generated prompts is literal thinking.

Humans remember symbols.

Not descriptions.

This library teaches Claude to convert abstract concepts into visual
metaphors before writing image prompts.

------------------------------------------------------------------------

# Golden Rule

Never ask:

"What object was mentioned?"

Always ask:

"What image would make the audience feel this idea?"

------------------------------------------------------------------------

# Choosing a Metaphor

For every scene:

1.  Identify the philosophical concept.
2.  Search for symbolic imagery.
3.  Compare multiple visual ideas.
4.  Choose the strongest one.
5.  Reject clichés unless the narration explicitly requires them.

Do not always choose the first idea.

------------------------------------------------------------------------

# Concept Library

## Desire

Possible imagery:

-   Endless staircase
-   Moving oasis
-   Moth flying into flame
-   Overflowing treasure room
-   Maze with no exit
-   Ocean tide that never reaches shore
-   Climber chasing a summit hidden by clouds
-   Endless shopping street
-   River flowing toward an unreachable horizon

Avoid:

Person holding money.

------------------------------------------------------------------------

## Ego

Possible imagery:

-   Giant mirror maze
-   Golden throne standing alone
-   Crown becoming heavier
-   Tower built on fragile sand
-   Balloon expanding until bursting
-   Statue worshipping itself
-   Endless applause from faceless crowd

Avoid:

Businessman smiling.

------------------------------------------------------------------------

## Peace

Possible imagery:

-   Still mountain lake
-   Snow-covered valley
-   Silent monastery
-   Temple corridor at dawn
-   Candle in complete darkness
-   Mist over forest
-   Bird resting after a storm

Avoid:

Person meditating unless the narration specifically requires it.

------------------------------------------------------------------------

## Fear

Possible imagery:

-   Narrow bridge over darkness
-   Shadow growing larger
-   Endless corridor
-   Storm approaching lighthouse
-   Child alone in fog
-   Cracked ice beneath footsteps
-   Forest disappearing into darkness

------------------------------------------------------------------------

## Hope

Possible imagery:

-   Sunrise after rain
-   First flower through stone
-   Lighthouse in storm
-   Open doorway with warm light
-   Bird taking flight
-   Mountain peak after clouds clear
-   Bridge reaching sunlight

------------------------------------------------------------------------

## Time

Possible imagery:

-   Weathered stone stairs
-   Tree rings
-   Eroding coastline
-   Autumn leaves
-   Ancient clock tower
-   Rusted railway
-   Desert ruins

Avoid:

Generic clock close-up.

------------------------------------------------------------------------

## Mortality

Possible imagery:

-   Empty chair
-   Fallen autumn leaves
-   Extinguished candle
-   Ancient cemetery beneath stars
-   River disappearing into mist
-   Weathered footprints
-   Last light before night

Avoid horror imagery.

------------------------------------------------------------------------

## Wisdom

Possible imagery:

-   Ancient library
-   Monk beneath tree
-   Weathered mountain path
-   Quiet temple bell
-   Open book illuminated by morning light
-   Elder watching sunrise

------------------------------------------------------------------------

## Attachment

Possible imagery:

-   Vine wrapping around tree
-   Hands gripping sand
-   Bird trapped inside open cage
-   Heavy chain made of gold
-   Anchor preventing a boat from sailing

------------------------------------------------------------------------

## Freedom

Possible imagery:

-   Open sky
-   Bird leaving cage
-   Cliff overlooking ocean
-   Boat released from anchor
-   Mountain summit after difficult climb

------------------------------------------------------------------------

## Consciousness

Possible imagery:

-   Calm water reflecting stars
-   Infinite night sky
-   Spiral galaxy
-   Mirror reflecting endless reflections
-   Light entering cave
-   Silent observatory

------------------------------------------------------------------------

## Compassion

Possible imagery:

-   Stranger helping another climb
-   Shared umbrella
-   Candle lighting another candle
-   Hands supporting fragile branch
-   Warm fire in cold landscape

------------------------------------------------------------------------

## Loneliness

Possible imagery:

-   Empty apartment
-   Single chair
-   Train platform at night
-   Lone lighthouse
-   Small cabin in snow
-   Boat drifting on calm sea

------------------------------------------------------------------------

## Ambition

Possible imagery:

-   Towering skyscrapers
-   Endless staircase
-   Marathon runners
-   Construction cranes
-   Mountain expedition

------------------------------------------------------------------------

## Transformation

Possible imagery:

-   Butterfly emerging
-   Forest after wildfire
-   Ice melting into river
-   Sunrise over ruins
-   Broken chain
-   Blooming desert

------------------------------------------------------------------------

# Metaphor Selection Rules

Choose metaphors that are:

-   universally understood
-   emotionally powerful
-   visually rich
-   easy for image models to render
-   suitable for documentary storytelling

Avoid symbols that require specialist cultural knowledge unless the
narration explicitly references them.

------------------------------------------------------------------------

# Freshness Rule

If the same metaphor has appeared recently, search for another equally
strong alternative.

Example:

Do not use "endless staircase" three times in one video.

Maintain novelty while preserving meaning.

------------------------------------------------------------------------

# Combining Metaphors

Use a maximum of two complementary symbols in one scene.

Good:

Lonely road + sunrise

Poor:

Road + temple + mountain + candle + mirror + bird + ocean

Simplicity is more memorable.

------------------------------------------------------------------------

# Acceptance Criteria (Part 4)

A compliant implementation will:

-   Prefer metaphor over literal illustration.
-   Maintain a diverse symbolic vocabulary.
-   Avoid repetitive clichés.
-   Select imagery that reinforces the narration emotionally.
-   Produce prompts that viewers remember long after watching.

------------------------------------------------------------------------

**End of Part 4**
