# Incremental Rendering & Scene Workspace V1

## Goal

Implement a professional incremental rendering workflow that allows
creators to manually review, replace, approve, lock, and regenerate
individual scenes without rerunning the expensive AI generation
pipeline.

This should become the primary workflow after the initial video
generation.

The objective is to make YouTube Factory behave like a professional
non-linear video editor while preserving the existing fully automated
pipeline.

------------------------------------------------------------------------

# Core Principles

-   Never regenerate work unnecessarily.
-   Reuse existing assets whenever possible.
-   Rebuild only affected downstream stages.
-   Make manual editing a first-class workflow.
-   Support rapid iteration.
-   Keep builds deterministic and reproducible.

------------------------------------------------------------------------

# 1. Asset Reuse Mode

Add a new execution mode.

``` bash
ytfactory run --resume
```

or

``` bash
ytfactory run --reuse-assets
```

When enabled:

Reuse every valid asset already present inside the workspace.

Never regenerate an asset unless:

-   it does not exist
-   it is invalid
-   the user explicitly forces regeneration
-   one of its dependencies changed

------------------------------------------------------------------------

# 2. Smart Dependency Graph

Represent the pipeline as a dependency graph.

    Research
        ↓
    Script
        ↓
    Scene Planning
        ↓
    Image Prompt Engine
        ↓
    Image Generation
        ↓
    Motion Engine
        ↓
    Scene Video Renderer
        ↓
    Continuous Timeline Renderer
        ↓
    Background Music
        ↓
    Quality Review
        ↓
    Publishing

Whenever an upstream asset changes, invalidate only downstream
dependencies.

Example:

Image changed → Motion → Scene Video → Final Video (not
Research/Script/Planning).

------------------------------------------------------------------------

# 3. Manifest System

Create:

`workspace/.pipeline-manifest.json`

Track:

-   stage
-   file path
-   checksum
-   modification timestamp
-   generation version
-   engine version
-   dependency graph
-   source assets

------------------------------------------------------------------------

# 4. Smart Change Detection

If `scene-008.png` is manually replaced:

-   detect checksum change
-   skip image generation
-   regenerate only:
    -   scene motion
    -   scene video
    -   final timeline
    -   quality review
    -   publishing

------------------------------------------------------------------------

# 5. Validation

Before resuming:

-   Verify every required asset exists.
-   Generate only missing assets.
-   Never restart the full pipeline.

------------------------------------------------------------------------

# 6. CLI Modes

-   `ytfactory run`
-   `ytfactory run --resume`
-   `ytfactory run --force-images`
-   `ytfactory run --force-motion`
-   `ytfactory run --force-video`
-   `ytfactory run --force-subtitles`
-   `ytfactory run --force-narration`
-   `ytfactory run --force-bgm`
-   `ytfactory run --force-publish`

Support combining flags.

------------------------------------------------------------------------

# 7. Manual Image Replacement

Replace `scene-012.png` with the same filename.

Run:

``` bash
ytfactory run --resume
```

Automatically:

-   detect change
-   skip image generation
-   regenerate motion
-   regenerate scene video
-   rebuild final timeline
-   rerun review
-   rerun publishing

------------------------------------------------------------------------

# 8. Debug Output

Example:

    ✓ Research reused
    ✓ Script reused
    ✓ Scene planning reused
    ✓ Image prompts reused
    ✓ Scene 01 reused
    ⚠ Scene 08 modified
    ✓ Motion regenerated
    ✓ Scene video regenerated
    ✓ Final timeline rebuilt
    ✓ BGM mixed
    ✓ Review completed
    ✓ Publishing completed

------------------------------------------------------------------------

# 9. Performance Goal

Replacing one image in a 30-scene project should rebuild only that scene
plus downstream outputs.

------------------------------------------------------------------------

# 10. Scene Workspace

States:

-   Draft
-   Needs Review
-   Needs Revision
-   Approved
-   Locked

Store in:

`workspace/scenes/scene-status.json`

------------------------------------------------------------------------

# 11. Locked State

Locked is the highest approval state.

A locked scene must never regenerate automatically, even if prompts or
engines improve.

Only these commands may unlock or override it:

-   `ytfactory scene unlock <scene>`
-   `ytfactory run --force-scene <scene>`
-   `ytfactory run --scene <scene> --force-video`

Locking guarantees deterministic builds.

------------------------------------------------------------------------

# 12. Scene Review Report

Generate:

`workspace/review/scene-review.md`

Each scene should include:

-   Image
-   Narration
-   Subtitles
-   Motion
-   Overall Status

------------------------------------------------------------------------

# 13. Scene Commands

Support:

-   `ytfactory scene list`
-   `ytfactory scene approve <scene>`
-   `ytfactory scene reject <scene>`
-   `ytfactory scene lock <scene>`
-   `ytfactory scene unlock <scene>`

------------------------------------------------------------------------

# 14. Selective Scene Regeneration

Examples:

-   `ytfactory run --scene 8`
-   `ytfactory run --scene 8 --force-image`
-   `ytfactory run --scene 8 --force-motion`
-   `ytfactory run --scene 8 --force-video`
-   `ytfactory run --scene 8 --force-subtitles`
-   `ytfactory run --scene 8 --force-narration`

------------------------------------------------------------------------

# 15. Resume Workflow

Generate → Review → Approve → Lock → Replace weak assets → Run
`--resume` → Rebuild only affected downstream stages.

------------------------------------------------------------------------

# 16. Quality Review Integration

Per-scene result:

-   PASS
-   WARNING
-   FAIL

Automatically mark failed scenes as **Needs Revision** without failing
the whole project.

------------------------------------------------------------------------

# 17. Future Extensibility

Design for:

-   Multiple image candidates
-   A/B comparison
-   Alternative narrations
-   Subtitle variants
-   Motion variants
-   User notes
-   Manual ratings
-   Scene history
-   Before/After comparison
-   AI recommendations
-   Team review

------------------------------------------------------------------------

# 18. Success Criteria

Creators should be able to:

1.  Generate a full video.
2.  Review each scene independently.
3.  Approve and lock good scenes.
4.  Replace weak assets manually.
5.  Regenerate only affected downstream stages.
6.  Produce a new final video in minutes without rerunning expensive AI
    generation.
