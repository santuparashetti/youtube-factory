# IMAGE_PROMPT_GENERATION_V3.md

# Part 3 --- Storyboard Engine

> **Status:** Part 3 of the V3 specification
>
> **Scope:** Teach the Scene Planner to think like a storyboard artist
> while preserving the existing pipeline.

------------------------------------------------------------------------

# Objective

The Scene Planner must stop treating each scene as an isolated prompt.

Instead, every batch must be planned as a continuous visual sequence
from the same documentary.

The output format remains unchanged.

Only the internal reasoning changes.

------------------------------------------------------------------------

# The Storyboard Principle

A documentary is remembered because of the relationship between scenes.

A single beautiful image is valuable.

A sequence of intentionally connected images is unforgettable.

Claude should therefore design a sequence, not a collection.

------------------------------------------------------------------------

# Batch-Level Planning

Before writing any prompt, read every narration in the current batch.

Do not generate Scene 1 immediately.

First understand:

-   Where does the batch begin?
-   Where does it end?
-   How does the emotional tone evolve?
-   Which scene deserves the strongest visual impact?
-   Where should the viewer pause and breathe?

Only after this planning should prompts be generated.

------------------------------------------------------------------------

# Sequence Roles

Internally assign each scene a role.

Typical roles include:

-   Hook
-   Establishing
-   Discovery
-   Conflict
-   Escalation
-   Reflection
-   Symbolic transition
-   Emotional pause
-   Revelation
-   Resolution

Multiple scenes may share a role, but every scene should contribute
something unique.

------------------------------------------------------------------------

# Visual Rhythm

Avoid repeating the same visual energy.

Balance the sequence.

Example rhythm:

Scene 1 Wide establishing shot

↓

Scene 2 Close emotional portrait

↓

Scene 3 Symbolic metaphor

↓

Scene 4 Architectural environment

↓

Scene 5 Macro detail

↓

Scene 6 Landscape

↓

Scene 7 Quiet reflective image

The viewer should feel natural movement through the story.

------------------------------------------------------------------------

# Shot Diversity

Across every batch intentionally vary:

-   shot size
-   perspective
-   camera height
-   focal length
-   subject distance
-   movement implied
-   environment
-   weather
-   lighting
-   emotional intensity

Never produce consecutive scenes with nearly identical framing unless
intentionally emphasizing repetition.

------------------------------------------------------------------------

# Emotional Progression

Each scene should move the audience emotionally.

Example progression:

Curiosity

↓

Mystery

↓

Recognition

↓

Tension

↓

Reflection

↓

Acceptance

↓

Hope

The emotional flow should match the narration.

------------------------------------------------------------------------

# Scene Relationships

Every prompt should be aware of:

Previous scene

Current scene

Next scene

Ask:

Why is this image between those two?

If the order could be randomly shuffled without affecting the
experience, the storyboard is weak.

------------------------------------------------------------------------

# Callback Principle

Reusing imagery is encouraged only when it reinforces the narrative.

Example:

Early:

A lonely road disappearing into fog.

Later:

The same road at sunrise.

The callback communicates growth without explanation.

------------------------------------------------------------------------

# Transitions

Adjacent scenes should transition naturally.

Possible transitions:

-   Color
-   Shape
-   Direction
-   Subject
-   Architecture
-   Weather
-   Motion
-   Symbolism

Avoid abrupt unrelated changes unless they intentionally create
contrast.

------------------------------------------------------------------------

# Contrast

Documentaries become visually tiring when every scene has equal
intensity.

Alternate between:

Large ↔ Small

Dark ↔ Bright

Crowded ↔ Empty

Fast ↔ Still

Human ↔ Nature

Exterior ↔ Interior

Literal ↔ Symbolic

Contrast creates engagement.

------------------------------------------------------------------------

# Hero Moments

Every batch should contain at least one hero frame.

Characteristics:

-   emotionally powerful
-   visually iconic
-   suitable as a thumbnail
-   memorable without narration

Do not make every frame a hero frame.

Use them sparingly.

------------------------------------------------------------------------

# Continuity Rules

Maintain continuity in:

-   recurring characters
-   recurring locations
-   recurring symbols
-   color evolution
-   emotional progression

Break continuity only when the narration intentionally shifts.

------------------------------------------------------------------------

# Internal Storyboard Checklist

Before generating prompts, verify:

✓ Does every scene have a purpose?

✓ Does every scene differ from its neighbors?

✓ Is there visual rhythm?

✓ Is there emotional progression?

✓ Is there at least one unforgettable hero frame?

✓ Does the batch feel like one documentary instead of seven unrelated
images?

If not, revise the storyboard before writing prompts.

------------------------------------------------------------------------

# Acceptance Criteria (Part 3)

A successful implementation will:

-   Plan batches before generating prompts.
-   Produce coherent visual sequences.
-   Create emotional pacing.
-   Increase shot diversity.
-   Use callbacks intentionally.
-   Avoid repetitive compositions.
-   Preserve the existing Scene Planner interface and output format.

------------------------------------------------------------------------

**End of Part 3**
