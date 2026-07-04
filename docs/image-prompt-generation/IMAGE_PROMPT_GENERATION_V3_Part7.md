# IMAGE_PROMPT_GENERATION_V3.md

# Part 7 --- Self-Critique Engine & Quality Assurance

> **Status:** Part 7 of the V3 specification
>
> **Scope:** Teach the Scene Planner to review and improve its own work
> before returning image prompts.

------------------------------------------------------------------------

# Objective

A professional director never accepts the first storyboard.

The Scene Planner should adopt the same discipline.

Before returning an image prompt, it must critique, refine and improve
its own output.

This review is entirely internal.

The pipeline output remains unchanged.

------------------------------------------------------------------------

# Principle

Generate.

Review.

Improve.

Then return the final prompt.

Never return the first acceptable prompt.

Return the best prompt within the allotted reasoning budget.

------------------------------------------------------------------------

# Two-Pass Generation

## Pass 1

Generate the initial cinematic concept using Parts 1--6.

Do not output it yet.

## Pass 2

Critically evaluate the concept using the checklist below.

Rewrite if improvements are found.

Only then emit the final prompt.

------------------------------------------------------------------------

# Self-Review Questions

Silently ask:

1.  Does this image communicate the central idea?
2.  Is the dominant emotion immediately obvious?
3.  Would this frame still work without narration?
4.  Is the visual memorable?
5.  Is there a stronger metaphor?
6.  Have I recently used a similar environment?
7.  Have I repeated the same framing?
8.  Does the lighting reinforce emotion?
9.  Does the composition guide the viewer's eye?
10. Would a documentary cinematographer approve this shot?

If multiple answers are "no", revise.

------------------------------------------------------------------------

# Genericity Detector

Reject prompts that rely on vague defaults.

Examples to avoid:

-   person standing
-   person thinking
-   beautiful landscape
-   mountain at sunset
-   lake at sunrise
-   cinematic shot

Replace them with specific, meaningful imagery.

------------------------------------------------------------------------

# Repetition Detector

Compare with recent prompts in the batch.

Avoid repeating:

-   locations
-   symbols
-   weather
-   color palette
-   camera angle
-   emotional tone
-   subject pose

If repetition exists without narrative purpose, regenerate.

------------------------------------------------------------------------

# Memorability Score

Internally score each prompt from 1--5.

## 1

Forgettable stock imagery.

## 2

Generic AI art.

## 3

Visually good but common.

## 4

Strong documentary frame.

## 5

Iconic, emotionally memorable, suitable for promotional artwork.

Target 4--5.

------------------------------------------------------------------------

# Emotional Clarity Score

Ask:

"What single emotion will the viewer feel first?"

If more than one primary emotion competes, simplify the scene.

------------------------------------------------------------------------

# Storytelling Score

The frame should answer:

What changed?

What matters?

Why should the audience care?

If none are clear, strengthen the visual narrative.

------------------------------------------------------------------------

# Thumbnail Test

Imagine the image is used as the YouTube thumbnail.

Would someone pause scrolling?

If not:

Increase visual focus.

Reduce clutter.

Strengthen contrast.

Clarify the subject.

------------------------------------------------------------------------

# Silence Test

Imagine the entire video is muted.

Can the audience still follow the emotional progression through the
sequence?

If not, strengthen visual storytelling.

------------------------------------------------------------------------

# Batch Review

After generating every prompt in the batch, perform a final review.

Verify:

-   visual rhythm
-   emotional progression
-   diversity
-   continuity
-   hero frame presence

If the batch feels repetitive, improve the weakest prompts.

------------------------------------------------------------------------

# Prompt Refinement Rules

When rewriting:

Increase specificity.

Prefer stronger symbolism.

Reduce unnecessary adjectives.

Remove decorative keywords.

Preserve readability.

Do not inflate prompt length.

------------------------------------------------------------------------

# Failure Recovery

If no compelling metaphor exists:

Prefer authentic documentary realism.

If realism is weak:

Prefer environmental storytelling.

Never invent surreal imagery simply to appear creative.

The metaphor must support the narration.

------------------------------------------------------------------------

# Quality Gate

A prompt should only be returned if it satisfies all of the following:

✓ Emotion is clear.

✓ Composition is intentional.

✓ Environment supports meaning.

✓ Visual is memorable.

✓ Distinct from neighboring scenes.

✓ Consistent with overall style.

✓ Free of unnecessary repetition.

------------------------------------------------------------------------

# Acceptance Criteria (Part 7)

A successful implementation will:

-   Critique prompts before returning them.
-   Detect generic imagery.
-   Reduce repetition across batches.
-   Improve emotional clarity.
-   Produce consistently stronger cinematic prompts without changing the
    existing pipeline.

------------------------------------------------------------------------

**End of Part 7**
