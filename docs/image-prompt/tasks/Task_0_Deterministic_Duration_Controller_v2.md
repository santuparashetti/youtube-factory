# Task 0 - Deterministic Duration Controller (Updated)

## Objective

Replace the current multi-pass duration correction with a deterministic
word-budget based controller.

The model should write **to a predefined word budget**, not guess the
duration.

------------------------------------------------------------------------

# Critical Requirement

The word budget MUST be enforced in the **system prompt**, not only the
user prompt.

Reason:

Large reasoning models (including DeepSeek V3.2) follow system-level
constraints more consistently than user-level reminders.

Every enhancement request should receive immutable constraints such as:

-   Target word count
-   Maximum allowed words
-   Minimum allowed words
-   Target speaking rate
-   Duration tolerance

These are generation constraints, not optional instructions.

------------------------------------------------------------------------

# System Prompt Requirements

Inject a dynamic system section before every enhancement request.

Example:

You are generating a narrated script.

Hard Constraints:

-   Target duration: {duration_minutes} minutes
-   Speaking rate: {speaking_rate_wpm} WPM
-   Target words: {target_words}
-   Allowed range: {min_words}-{max_words}
-   Never exceed the maximum.
-   Prefer removing repetition rather than compressing important ideas.
-   Preserve story, meaning, emotion and pacing.

These constraints have higher priority than writing style.

------------------------------------------------------------------------

# User Prompt

The user prompt should focus only on:

-   enhancing the script
-   improving storytelling
-   improving narration
-   preserving meaning

Avoid repeating duration rules already present in the system prompt.

------------------------------------------------------------------------

# Word Budget Planner

Calculate:

target_words = duration_minutes × speaking_rate

Generate:

minimum_words target_words maximum_words

using configurable tolerance.

------------------------------------------------------------------------

# Duration Optimizer

Only invoke when the generated script is outside tolerance.

Provide the optimizer with:

-   current word count
-   target word count
-   exact number of words to remove/add

Ask for exact adjustment instead of asking for a different duration.

------------------------------------------------------------------------

# Success Criteria

-   Scripts finish within configured tolerance in \>95% of runs.
-   Manual review becomes rare.
-   Fewer enhancement passes.
-   Lower API cost.
-   Stable narration quality.
-   System prompt becomes the single source of truth for duration
    constraints.
