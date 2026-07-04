# ASSET_SCENE_SYSTEM_V1.md

# Asset Scene System V1

## Objective

Introduce a reusable **Asset Scene** system into YouTube Factory.

Not every scene should require AI image generation. Some scenes should
instead display pre-designed assets supplied by the project.

Examples:

-   Intro Logo
-   Brand Card
-   Sponsor Card
-   Chapter Divider
-   Quote Card
-   Subscribe Card
-   Thank You Card
-   End Credits

The first implementation will use the **Atma Theory Brand Card**, but
the architecture must be generic and reusable.

------------------------------------------------------------------------

# Preserve Existing Architecture

Do NOT redesign:

-   LangGraph workflow
-   Scene Planner
-   Image Provider
-   Image Generation Pipeline
-   Video Renderer
-   CLI
-   Workspace layout

Only extend the scene model to support reusable asset scenes.

------------------------------------------------------------------------

# Scene Types

Current:

scene_type: generated_image

Add:

scene_type: asset

Future asset types should include:

-   intro_brand
-   chapter
-   sponsor
-   credits

All should reuse the same implementation.

------------------------------------------------------------------------

# Asset Scene Schema

Suggested schema:

scene_type: asset

asset_path: assets/branding/atma-theory-brand.png

generate_image: false

animation: slow_zoom

duration: auto

fit: contain

background: black

overlay: title: "" subtitle: "" opacity: 0

The exact schema may be adjusted if a cleaner implementation exists.

------------------------------------------------------------------------

# Scene Planner

The Scene Planner must intentionally create Asset Scenes.

For Atma Theory:

When narration reaches the closing section such as:

-   "This is Atma Theory..."
-   "Think deeper... live clearer."
-   "The answers you seek are already within you."

Do NOT generate an AI image.

Instead generate an Asset Scene referencing the branding image.

------------------------------------------------------------------------

# Image Generation

If:

scene_type == asset

Then:

-   Skip image generation completely.
-   Do not call any image provider.
-   Do not consume image credits.
-   Do not create placeholder prompts.

------------------------------------------------------------------------

# Renderer

The renderer should detect Asset Scenes.

Instead of loading an AI-generated image:

-   Load the supplied asset.
-   Apply cinematic animation.

Default animations:

-   slow zoom in
-   slow zoom out
-   subtle camera drift
-   fade in
-   fade out

Animation should remain configurable.

------------------------------------------------------------------------

# Asset Management

Store reusable assets in a dedicated directory.

Example:

assets/ branding/ atma-theory-brand.png intro/ sponsor/ chapter/
credits/

Avoid scattering static assets across the repository.

------------------------------------------------------------------------

# Future Expansion

The Asset Scene system should later support:

-   Channel logos
-   Company logos
-   Watermarks
-   Book covers
-   Maps
-   Charts
-   Quote cards
-   Chapter cards
-   Sponsor screens
-   Intro sequences
-   End credits

without requiring architectural changes.

------------------------------------------------------------------------

# Backward Compatibility

Existing projects must continue working.

If scene_type is omitted:

Treat it as:

scene_type: generated_image

------------------------------------------------------------------------

# Acceptance Criteria

A successful implementation ensures:

-   Existing projects remain unchanged.
-   AI image generation continues normally.
-   Asset Scenes bypass image generation.
-   Renderer displays supplied assets correctly.
-   Asset Scenes support configurable cinematic animation.
-   Brand cards can appear anywhere in the timeline.
-   The solution is generic and reusable.

------------------------------------------------------------------------

# Prompt for Claude Code

Read this document completely before making any code changes.

Implement the Asset Scene system described above.

Do NOT redesign the existing architecture.

Before coding:

1.  Review the current Scene model.
2.  Explain how Asset Scenes integrate into the existing pipeline.
3.  Present the proposed schema.
4.  Explain renderer changes.
5.  Wait for approval.

After implementation:

-   List every modified file.
-   Explain every schema extension.
-   Explain renderer changes.
-   Confirm backward compatibility.
-   Confirm that only Asset Scenes bypass image generation while all
    other scenes continue using AI-generated images.

The goal is to make Asset Scenes a first-class feature of YouTube
Factory rather than a special-case implementation for the Atma Theory
ending.
