# Two-Phase Workflow Acceptance Test Checklist

## Objective

Validate that the new two-phase workflow functions correctly end-to-end,
ensuring both the new workflow and the legacy single-shot workflow
operate without regressions.

------------------------------------------------------------------------

# Acceptance Criteria

## Test 1 - Phase 1 (New Project)

**Goal**

Verify that a new project completes only the preparation phase.

### Steps

-   Start a new project using:
    -   `uv run ytfactory` (Select **New**)
    -   OR `uv run ytfactory --phase prep_only`

### Expected Results

-   [ ] Script generation completes.
-   [ ] Script enhancer completes.
-   [ ] Scene planner completes.
-   [ ] TTS generation completes.
-   [ ] Audio generation completes.
-   [ ] Subtitle generation completes.
-   [ ] Workflow stops after preparation.
-   [ ] No video rendering begins.
-   [ ] No publish stage executes.

### Image Generation Validation

-   [ ] Search logs for `HF_IMAGE_MODEL`.
-   [ ] Search logs for Tier 1/2/3 image provider calls.
-   [ ] Zero image generation requests found.

### Manifest Validation

-   [ ] `image_prompts_manifest.json` exists.
-   [ ] One manifest entry exists for every scene.
-   [ ] Every entry contains:
    -   [ ] `scene_id`
    -   [ ] `expected_filename`
    -   [ ] `visual_prompt`

### Reporting Validation

-   [ ] `phase1_report.md` exists.
-   [ ] `phase1_report.json` exists.
-   [ ] Reports show completed preparation stages.
-   [ ] QC warnings (if any) are included.

------------------------------------------------------------------------

# Test 2 - Missing Image Validation (Negative Test)

**Goal**

Ensure Resume fails immediately when no images are available.

### Setup

Do **not** add any images.

### Steps

Run Resume from the CLI or `--phase resume`.

### Expected Results

-   [ ] Resume exits immediately.
-   [ ] Rendering never starts.
-   [ ] Motion effects never start.
-   [ ] Publish never starts.
-   [ ] Error clearly lists every missing image.
-   [ ] Missing list includes:
    -   [ ] Scene IDs
    -   [ ] Expected filenames

### Verify

-   [ ] No off-by-one filename bugs.
-   [ ] Correct image path resolution.
-   [ ] Correct scene numbering.

------------------------------------------------------------------------

# Test 3 - Partial Image Validation

**Goal**

Ensure Resume reports only the remaining missing images.

### Setup

Copy only some images into the project using the exact
`expected_filename`.

Leave at least one scene missing.

### Expected Results

-   [ ] Resume fails.
-   [ ] Only missing images are reported.
-   [ ] Existing images are recognized correctly.
-   [ ] Rendering never starts.

------------------------------------------------------------------------

# Test 4 - Full Phase 2 Resume

**Goal**

Validate successful completion using externally supplied images.

### Setup

Add every remaining image using the exact filenames from the manifest.

### Expected Pipeline

-   [ ] Motion effects
-   [ ] Video rendering
-   [ ] Subtitle burn-in
-   [ ] Background music mixing
-   [ ] Scene concatenation
-   [ ] CTA generation
-   [ ] Quality review
-   [ ] Publish

### Image QA Validation

-   [ ] ImageReviewEngine is never invoked.
-   [ ] No anatomy QA runs.
-   [ ] No image review pipeline executes.

### Thumbnail Validation

-   [ ] No thumbnail generation occurs.
-   [ ] Publish artifacts contain no generated thumbnail.

### Final Output Validation

-   [ ] `final.mp4` exists.
-   [ ] File is playable.
-   [ ] Video duration appears correct.
-   [ ] Output is not corrupted.

> This specifically guards against the previous regression where the
> pipeline exited successfully but never produced a final video.

------------------------------------------------------------------------

# Test 5 - Interactive CLI Validation

**Goal**

Validate the interactive user experience.

### Steps

Run:

``` bash
uv run ytfactory
```

### Expected Results

-   [ ] Main menu appears.
-   [ ] Option 1: New
-   [ ] Option 2: Resume

### Resume Menu Validation

-   [ ] Lists existing prep-only projects.
-   [ ] Shows Phase 1 completion timestamp.
-   [ ] Excludes completed projects.
-   [ ] Excludes fresh/incomplete projects.
-   [ ] Shows only projects ready for Phase 2.

------------------------------------------------------------------------

# Test 6 - Legacy Workflow Regression

**Goal**

Ensure existing users are unaffected.

### Steps

Run the original single-shot workflow (without `--phase`).

### Expected Results

-   [ ] Complete pipeline executes successfully.
-   [ ] Image generation still functions.
-   [ ] Image QA still functions.
-   [ ] Video rendering succeeds.
-   [ ] Publish succeeds.
-   [ ] Final output matches previous behavior.
-   [ ] No regressions introduced by two-phase support.

------------------------------------------------------------------------

# Final Acceptance Summary

The feature is accepted only if all of the following are true:

-   [ ] Phase 1 completes without rendering.
-   [ ] No image provider is invoked during Phase 1.
-   [ ] Image manifest is generated correctly.
-   [ ] Phase 1 reports are generated.
-   [ ] Resume fails cleanly when images are missing.
-   [ ] Resume reports only the remaining missing images.
-   [ ] Resume succeeds when all required images exist.
-   [ ] External images bypass all image QA/review pipelines.
-   [ ] No thumbnail is generated during Resume.
-   [ ] A valid `final.mp4` is produced.
-   [ ] Interactive CLI correctly supports New and Resume.
-   [ ] Resume menu lists only Phase 1-ready projects.
-   [ ] Legacy single-shot workflow passes without regressions.
