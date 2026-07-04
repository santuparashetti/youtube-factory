# IMAGE_PROMPT_GENERATION_V3_MASTER.md

# YouTube Factory --- Image Prompt Generation V3 (Master Specification)

## Purpose

This is the **master entry point** for the V3 Image Prompt Generation
specification.

Do **NOT** implement changes based only on this document.

Instead, treat this document as the project index and implementation
guide.

------------------------------------------------------------------------

# Your Task

You are responsible for improving **only** the image prompt generation
logic inside the existing `scene_planner`.

## Non-Negotiable Constraints

Do NOT modify:

-   LangGraph architecture
-   Pipeline flow
-   Python scene splitter
-   Batch processing strategy
-   Scene JSON schema
-   Node interfaces
-   Workspace layout
-   CLI
-   Image providers
-   Video rendering
-   Existing downstream integrations

The architecture is already correct.

Your job is to significantly improve the intelligence and quality of
**image prompt generation only**.

------------------------------------------------------------------------

# IMPORTANT --- Read Every Specification Before Coding

Before writing or changing a single line of code, locate and read
**all** Markdown files in the same directory as this document.

They are part of one specification.

Read them in this exact order:

1.  IMAGE_PROMPT_GENERATION_V3_MASTER.md (this file)
2.  IMAGE_PROMPT_GENERATION_V3_Part1.md
3.  IMAGE_PROMPT_GENERATION_V3_Part2.md
4.  IMAGE_PROMPT_GENERATION_V3_Part3.md
5.  IMAGE_PROMPT_GENERATION_V3_Part4.md
6.  IMAGE_PROMPT_GENERATION_V3_Part5.md
7.  IMAGE_PROMPT_GENERATION_V3_Part6.md
8.  IMAGE_PROMPT_GENERATION_V3_Part7.md
9.  IMAGE_PROMPT_GENERATION_V3_Part8.md

Do not start implementation until every document has been read and
understood.

Treat all documents as a single engineering specification.

------------------------------------------------------------------------

# Implementation Workflow

1.  Read every specification document.
2.  Build a complete mental model.
3.  Review the current implementation in:
    -   scene_planner node
    -   prompt builder
    -   prompt templates
    -   batching logic (read only, preserve behavior)
4.  Identify where image prompts are produced.
5.  Refactor only the reasoning and prompt template.
6.  Preserve every public interface.
7.  Verify output compatibility with the existing pipeline.

------------------------------------------------------------------------

# Expected Internal Reasoning

After reading Parts 1--8, your implementation should internally perform:

Narration → Core Meaning → Emotion → Storyboard Planning → Visual
Metaphor Selection → Cinematography Decisions → Continuity Review →
Prompt Construction → Self Critique → Final Prompt

This reasoning is internal only.

The external output format must remain unchanged.

------------------------------------------------------------------------

# Deliverables

When implementation is complete:

-   Explain what files were changed.
-   Explain why each change was made.
-   Confirm that pipeline compatibility has been preserved.
-   Highlight any optional improvements that were intentionally not
    implemented.

------------------------------------------------------------------------

# Success Criteria

The resulting prompts should:

-   Feel like storyboard directions from a documentary director.
-   Avoid generic AI imagery.
-   Use stronger symbolism.
-   Improve emotional storytelling.
-   Maintain character and visual consistency.
-   Increase diversity across scenes.
-   Remain model-agnostic.
-   Preserve existing architecture and interfaces.

If there is uncertainty, prefer preserving the existing architecture
over introducing new components.

This master document is only the entry point.

The detailed implementation rules live in Parts 1--8 and must be
followed collectively.
