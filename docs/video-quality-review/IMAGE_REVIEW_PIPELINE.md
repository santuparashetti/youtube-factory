# IMAGE_REVIEW_PIPELINE.md

> **Implementation Specification for Claude Code**

**Prerequisites**

-   Read `MASTER_CONTEXT_V4.md`
-   Read `PRODUCTION_DOCKER_AND_BOOTSTRAP_SYSTEM.md`

## Purpose

Extend the existing **ReviewPipeline** with a production-ready, fully
automated image quality review system that detects AI-generated
artifacts, scores cinematic quality, and automatically regenerates weak
images.

This implementation must:

-   Extend the existing architecture.
-   Preserve backward compatibility.
-   Reuse ReviewPipeline, AutoRemediation, BuildPipeline, Incremental
    Build Engine, Bootstrap Engine and the Local AI Model Manager.
-   Never introduce a parallel review system.
-   Keep the review pipeline model-agnostic.

------------------------------------------------------------------------

# Architecture

Image Generation → Technical QA (OpenCV) → Vision Provider → Local AI
Model Manager → Structured Review → PASS → Continue

FAIL → Auto Remediation → Prompt Refinement → New Seed → Regenerate →
Review Again

Maximum retries are configurable.

------------------------------------------------------------------------

# Local AI Model Manager

The ReviewPipeline must **never** download or manage models directly.

Instead it requests a vision model from the Local AI Model Manager.

Responsibilities:

-   discover required models
-   automatic download
-   checksum verification
-   version management
-   cache management
-   backend selection (CUDA / MPS / CPU)
-   corruption detection
-   self-healing
-   upgrades
-   rollback
-   manifest management

The current default local reviewer is **MiniCPM‑V 2.6**, but the
pipeline must not contain MiniCPM-specific logic.

Changing reviewers should require only configuration.

Example:

``` yaml
vision_review:
  provider: local
  local_model: minicpm_v2_6
```

Later:

``` yaml
vision_review:
  provider: local
  local_model: qwen2_5_vl_3b
```

No code changes.

------------------------------------------------------------------------

# Vision Review Checklist

## Human Anatomy

-   Hands
-   Fingers
-   Feet
-   Legs
-   Arms
-   Neck
-   Shoulders
-   Body proportions
-   Walking posture
-   Sitting posture

## Face

-   Eyes
-   Ear placement
-   Teeth
-   Symmetry
-   Expression consistency

## Lighting

-   Light direction
-   Shadows
-   Reflections
-   Exposure

## Environment

-   Perspective
-   Floating objects
-   Duplicate objects
-   Object fusion
-   Missing object parts

## AI Artifacts

-   Extra / missing fingers
-   Twisted limbs
-   Unrealistic poses
-   Warped anatomy
-   Distorted geometry
-   Hallucinated textures
-   Broken reflections
-   Texture artifacts
-   Watermarks
-   Text artifacts
-   Blurry focal subject

## Cinematic Quality

-   Composition
-   Framing
-   Storytelling
-   Emotional consistency
-   Depth
-   Realism

------------------------------------------------------------------------

# Review Response

Return structured JSON only:

-   status
-   score
-   confidence
-   issues
-   recommend_regeneration

------------------------------------------------------------------------

# Pass Criteria

Default:

-   Score \>= 90
-   Confidence \>= 80
-   No HIGH severity issues
-   Maximum one MEDIUM issue

Otherwise regenerate.

------------------------------------------------------------------------

# Auto Remediation

On failure:

1.  Analyze review findings.
2.  Append targeted prompt improvements.
3.  Change random seed.
4.  Regenerate image.
5.  Review again.

Never rewrite the original prompt.

------------------------------------------------------------------------

# Workspace Artifacts

Per scene:

-   image-review.json
-   image-review-prompt.txt
-   image-remediation.json

Global:

-   image-quality-summary.json

------------------------------------------------------------------------

# Configuration

``` yaml
image_review_enabled: true

vision_review_provider: local
vision_review_local_model: minicpm_v2_6

image_review_min_score: 90
image_review_confidence: 80
image_review_max_attempts: 3
image_review_auto_remediate: true
image_review_debug: false
```

Model lifecycle is fully managed by the Local AI Model Manager.

------------------------------------------------------------------------

# Incremental Builds

If a review fails:

-   Regenerate only the failed scene.
-   Never rebuild successful scenes.
-   Never rebuild narration or subtitles.
-   Respect locked scenes.

------------------------------------------------------------------------

# Testing

Add tests for:

-   Vision provider abstraction
-   Local AI Model Manager integration
-   ReviewPipeline integration
-   AutoRemediation
-   Retry logic
-   JSON parsing
-   Incremental builds
-   Model switching via configuration
-   Report generation

Run Ruff, MyPy and the full pytest suite.

------------------------------------------------------------------------

# Deliverables

-   ReviewPipeline extension
-   Local vision provider abstraction
-   Local AI Model Manager integration
-   Prompt refinement
-   Retry workflow
-   Reports
-   Configuration
-   Tests
-   Documentation

------------------------------------------------------------------------

# Success Criteria

Fresh machine:

1.  Clone repository
2.  Configure required API keys
3.  docker compose up -d
4.  ytfactory setup

The Local AI Model Manager automatically provisions, validates and
maintains the configured local vision model.

The ReviewPipeline remains completely model-agnostic while automatically
rejecting, refining and regenerating images with visible AI artifacts.

No manual model downloads. No manual Hugging Face setup. No manual
environment fixes.
