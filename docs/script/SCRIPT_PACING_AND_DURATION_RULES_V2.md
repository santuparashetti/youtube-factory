# SCRIPT_PACING_AND_DURATION_RULES_V2

## Purpose

Produce high-quality narration that respects the requested video
duration while preserving the original script's simplicity and meaning.

## Duration Rules

-   Requested duration is a hard target.
-   Maximum variance: ±1 minute.
-   Never exceed the requested duration by more than 1 minute.

## Preserve the Base Script

-   Treat the researched/base script as the source of truth.
-   Preserve structure, flow, tone and simplicity.
-   Only make minimal edits for clarity and narration.
-   Do not rewrite the script unnecessarily.

## Quality Over Quantity

-   Never add filler.
-   Never repeat ideas.
-   Every sentence must add value.
-   Prefer depth over volume.

## Pacing Instead of Padding

If the base script is shorter: - Slow narration naturally. - Insert
meaningful pauses. - Leave reflection gaps after important lines. - Give
viewers time to absorb each idea.

## Simplicity

-   Keep language as simple as the original.
-   Avoid complex vocabulary.
-   Sound natural and human.

## Narration Style

Narrate like a calm documentary storyteller. For spiritual content,
prioritize understanding over speed.

## Validation

-   Duration within ±1 minute.
-   No unnecessary padding.
-   Faithful to the original.
-   Prefer pauses over extra words.
-   Optimize for comprehension, not word count.

## Implementation Notes

-   Estimate duration after every revision.
-   Use pause markers where supported.
-   Include estimated duration in diagnostics.
-   Fail validation if duration exceeds tolerance.
