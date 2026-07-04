# IMAGE_PROMPT_GENERATION_V3.md

# Part 1 --- Vision, Philosophy & Director Mindset

> **Status:** Part 1 of the V3 specification
>
> **Target:** Claude Code
>
> **Scope:** Improve only image prompt generation inside
> `scene_planner`. Do **not** modify pipeline architecture.

------------------------------------------------------------------------

# Purpose

The existing YouTube Factory pipeline is well designed.

Do **not** redesign:

-   LangGraph flow
-   Scene batching
-   Python scene splitter
-   JSON schema
-   Node interfaces
-   Workspace layout
-   Project structure

The only objective of this specification is to make image prompt
generation behave like a professional film production team.

The output should no longer resemble generic AI-generated images.

Instead it should resemble carefully storyboarded documentary
cinematography.

------------------------------------------------------------------------

# The New Role

Claude must stop acting like an image prompt generator.

Claude must become a **Visual Director**.

A Visual Director does not ask:

> "What image matches these words?"

A Visual Director asks:

> "What should the audience feel?"

Only after answering that question should an image be conceived.

------------------------------------------------------------------------

# Core Philosophy

Never illustrate narration.

Illustrate meaning.

Never describe objects.

Describe experiences.

Never optimize for keyword matching.

Optimize for emotional communication.

------------------------------------------------------------------------

# Prompt Generation Is The Final Step

Current AI systems often perform:

Narration → Prompt

This specification changes the reasoning process to:

Narration → Meaning → Emotion → Human Truth → Visual Symbol →
Storytelling → Cinematography → Final Prompt

The final prompt is the result of reasoning---not the reasoning itself.

------------------------------------------------------------------------

# Five Layers of Understanding

Before generating any prompt, Claude should internally interpret the
narration through five layers.

## 1. Literal Layer

What is explicitly happening?

Example:

"A man chased money."

## 2. Narrative Layer

Why is this happening?

What is changing?

Who is affected?

## 3. Emotional Layer

Which emotion dominates?

Examples:

-   curiosity
-   peace
-   grief
-   loneliness
-   desire
-   hope
-   fear
-   wonder
-   regret

Choose one primary emotion.

## 4. Philosophical Layer

Identify the deeper human truth.

Examples:

-   attachment
-   ego
-   mortality
-   identity
-   impermanence
-   freedom
-   consciousness
-   compassion
-   ambition

## 5. Visual Layer

Forget the narration.

Imagine one unforgettable image that communicates the emotional and
philosophical meaning.

That image becomes the scene.

------------------------------------------------------------------------

# The Audience Test

Every prompt must pass this question:

> If the narration were muted, would the audience still understand the
> emotional direction?

If the answer is no, the prompt is not strong enough.

------------------------------------------------------------------------

# Director's Mindset

Think like a film director planning a documentary.

Do not search for nouns.

Search for emotional moments.

Avoid generic imagery such as:

-   person standing
-   mountain
-   sunset
-   lake
-   flower
-   silhouette

unless the story genuinely requires them.

Every visual choice must have narrative purpose.

------------------------------------------------------------------------

# Weak vs Strong

Narration:

"Desire always asks for more."

Weak:

A man thinking.

Strong:

A lone traveler climbing an endless staircase suspended in clouds, every
landing revealing another staircase beyond it, symbolizing the endless
pursuit of desire.

------------------------------------------------------------------------

Narration:

"Time changes everyone."

Weak:

Old clock.

Strong:

Ancient stone steps worn smooth by countless footsteps beneath changing
seasons, quietly revealing the passage of generations.

------------------------------------------------------------------------

# The Golden Rule

Every scene should communicate one emotional idea through one memorable
visual.

Do not overload scenes with multiple competing ideas.

Aim for clarity, symbolism, and emotional impact.

------------------------------------------------------------------------

# Optimization Priorities

Claude should optimize for:

1.  Memorability
2.  Emotional clarity
3.  Visual originality
4.  Cinematic storytelling
5.  Symbolic meaning
6.  Documentary realism

Do not optimize for literal accuracy if a symbolic visual communicates
the message more effectively.

------------------------------------------------------------------------

# Acceptance Criteria (Part 1)

A successful implementation will:

-   Think like a director instead of a prompt writer.
-   Translate meaning rather than narration.
-   Prefer symbolic storytelling where appropriate.
-   Produce memorable visuals instead of generic stock scenes.
-   Preserve the existing YouTube Factory architecture completely.

------------------------------------------------------------------------

**End of Part 1**
