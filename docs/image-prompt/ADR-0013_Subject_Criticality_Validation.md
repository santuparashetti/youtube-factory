# ADR-0013: Subject Criticality & Human Anatomy Validation

## Status

Proposed

## Purpose

Strengthen the Image Quality Review Engine so that images whose primary
storytelling subject is a human body part (hands, face, eyes, etc.) are
held to a much higher quality bar than general scene validation.

------------------------------------------------------------------------

## Background

General image quality models often approve images that have beautiful
lighting and composition while missing subtle anatomical defects.

For documentary storytelling, these defects immediately reduce
credibility.

------------------------------------------------------------------------

## Subject Criticality Rule

If the primary storytelling subject is:

-   Human hand
-   Human face
-   Human eye
-   Human body
-   Human gesture

that subject must be anatomically realistic.

Failure of the primary subject is sufficient reason to reject the entire
image regardless of environment quality.

------------------------------------------------------------------------

## Hand Validation Checklist

The reviewer MUST verify all of the following:

-   Exactly five fingers (unless intentionally hidden)
-   Natural thumb attachment
-   Correct palm proportions
-   Natural wrist transition
-   Correct finger joint placement
-   No fused fingers
-   No duplicated fingers
-   No stretched or melted anatomy
-   Natural resting pose
-   Photorealistic skin texture

If ANY item fails:

-   Reject image
-   Regenerate automatically
-   Re-run validation

------------------------------------------------------------------------

## Review Strategy

Generation

↓

Overall Image Review

↓

Subject Specialist Review

↓

Approve only if BOTH pass

------------------------------------------------------------------------

## Success Criteria

A viewer should not notice any anatomical issue in the primary
storytelling subject. Every approved image should resemble a frame from
a premium documentary rather than an AI-generated illustration.
