# HUMAN_QUALITY_AND_SUBJECT_VALIDATION_V1

## Purpose

Improve the Image Prompt Engine and Image Quality Review Engine so that
humans are always rendered with production-quality realism.

## Problem

Modern AI image models often generate beautiful environments but
poor-quality humans.

Typical failures:

-   Blurry faces
-   Unnatural eyes
-   Distorted facial proportions
-   Stiff body posture
-   Low-detail humans
-   People that appear pasted into the environment

These images should never pass quality review.

## Human Quality Priority

Whenever a human appears in an image:

-   Sharp, high-detail face
-   Natural eyes and gaze
-   Correct facial proportions
-   Realistic skin texture
-   Natural body posture
-   Correct anatomy
-   Visible emotion
-   Proper integration with the environment

The human should never appear blurry, low-detail, deformed, or
artificially composited.

## Subject Dominance Rule

Large environments are encouraged, but they must not reduce the quality
of the human subject.

If a human is present:

-   Preserve facial detail.
-   Keep the person visually important enough for realistic rendering.
-   Avoid tiny, low-detail people unless explicitly required by the
    story.

## Prompt Engine Updates

Whenever humans appear, reinforce prompts with:

-   highly detailed human face
-   natural facial expression
-   realistic eyes
-   authentic skin texture
-   natural posture
-   seamless integration with the environment
-   documentary-quality realism

## Image Quality Review

Automatically validate:

-   Face sharpness
-   Eye quality
-   Facial symmetry
-   Human realism
-   Anatomy
-   Body posture
-   Hand quality
-   Emotional expression
-   Integration with the environment

If any validation fails:

-   Reject the image.
-   Regenerate automatically.
-   Repeat until quality standards are met or retry limit is reached.

## Success Criteria

Every image containing a human should look like a frame from a premium
documentary rather than an AI-generated illustration.
