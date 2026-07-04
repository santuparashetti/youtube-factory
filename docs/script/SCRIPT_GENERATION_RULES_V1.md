# SCRIPT_GENERATION_RULES_V1.md

# Script Generation Rules V1

## Objective

Enhance only the Script Writer Agent so every generated script is
optimized for high-retention YouTube documentaries while preserving the
calm, cinematic, and reflective identity of Atma Theory.

------------------------------------------------------------------------

# Preserve Existing Architecture

Do NOT modify:

-   LangGraph workflow
-   Research pipeline
-   Scene Planner
-   Image Generation
-   Speech Optimizer
-   TTS
-   Subtitle Generation
-   Video Rendering
-   JSON schema
-   Public interfaces

Only improve script generation.

------------------------------------------------------------------------

# Primary Goals

Every script must:

-   Deliver maximum value per minute.
-   Feel like a professionally written documentary.
-   Maintain philosophical depth.
-   Flow naturally from hook to conclusion.
-   Be optimized for narration.

------------------------------------------------------------------------

# Video Duration Requirements

Target narration length:

-   Minimum: **5 minutes**
-   Ideal: **7--8 minutes**
-   Maximum: **10 minutes**

Estimate narration duration before returning the script.

If the estimated duration exceeds 10 minutes:

-   Compress the script automatically.
-   Remove redundant explanations.
-   Remove repeated examples.
-   Preserve only the strongest insights.

Never intentionally generate scripts longer than 10 minutes.

------------------------------------------------------------------------

# YouTube Retention Optimization

Every generated script should be automatically optimized for YouTube
retention.

The script must:

-   Start with a compelling hook in the first 15--20 seconds.
-   Maintain curiosity throughout.
-   Introduce meaningful insights regularly.
-   Build toward a strong emotional and philosophical payoff.
-   End with a memorable reflection.

Avoid long periods without introducing a new idea.

------------------------------------------------------------------------

# Information Density

Every sentence must contribute meaningful value.

Each sentence should provide at least one of the following:

-   a new insight
-   a philosophical perspective
-   a memorable analogy
-   a practical takeaway
-   emotional progression
-   narrative progression

Avoid:

-   filler
-   repetition
-   generic motivational language
-   unnecessary transitions
-   saying the same idea in different words

------------------------------------------------------------------------

# Quality Over Quantity

Never make the script longer simply to reach a target duration.

If the topic naturally fits within six minutes, produce an exceptional
six-minute script.

Prefer clarity over length.

------------------------------------------------------------------------

# Compression Strategy

When shortening a script, remove content in this order:

1.  Repeated examples
2.  Repeated explanations
3.  Weak analogies
4.  Generic transitions
5.  Redundant storytelling

Never remove:

-   Opening hook
-   Core philosophical insight
-   Emotional climax
-   Practical takeaway
-   Atma Theory welcome
-   Atma Theory closing

------------------------------------------------------------------------

# Story Flow

Every script should follow this structure:

1.  Hook
2.  Welcome
3.  Topic Introduction
4.  Build Curiosity
5.  Main Exploration
6.  Deep Insight
7.  Practical Reflection
8.  Closing Reflection
9.  Atma Theory Sign-off

------------------------------------------------------------------------

# Brand Voice

Maintain a voice that is:

-   calm
-   reflective
-   compassionate
-   intelligent
-   cinematic
-   conversational

Never sound:

-   preachy
-   repetitive
-   promotional
-   robotic

------------------------------------------------------------------------

# Internal Review Checklist

Before returning the final script verify:

✓ Estimated narration is between 5 and 10 minutes.

✓ Every sentence adds meaningful value.

✓ No repeated ideas.

✓ No filler.

✓ Strong opening hook.

✓ Smooth progression.

✓ Memorable ending.

✓ High information density.

If any check fails, rewrite the script before returning it.

------------------------------------------------------------------------

# Acceptance Criteria

A successful implementation will ensure:

-   Narration length stays between 5 and 10 minutes.
-   Scripts maximize information density.
-   Every sentence serves a purpose.
-   Redundant content is removed automatically.
-   Strong philosophical ideas are preserved.
-   The final script feels cinematic, emotionally engaging, and
    optimized for YouTube retention while remaining true to the Atma
    Theory brand.

------------------------------------------------------------------------

# Prompt for Claude Code

Read this document completely before making any code changes.

Enhance only the Script Writer Agent.

Do NOT modify the existing architecture or downstream pipeline.

Implement automatic optimization so every generated script:

-   Targets a narration length between **5 and 10 minutes** (ideal 7--8
    minutes).
-   Avoids filler, repetition, and unnecessary explanations.
-   Maximizes information density by ensuring every sentence contributes
    a meaningful insight, analogy, or progression of the narrative.
-   Preserves only the strongest examples and philosophical ideas when
    shortening a script.
-   Estimates narration duration before returning the final script and
    automatically compresses it if it exceeds 10 minutes.

Present an implementation plan first.

Wait for approval before coding.

After approval, explain every architectural decision and confirm full
backward compatibility with the existing YouTube Factory pipeline.
