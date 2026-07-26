# ADR-0015: Human Subject Quality Gate

## Status
Proposed

## Background

Recent pipeline runs produced human images with severe quality issues despite successful generation and review.

Observed failures include:

- Deformed hands and fingers
- Incorrect anatomy
- Missing or incorrect clothing
- Broken body proportions
- Prompt compliance failures

These images reached the final pipeline, indicating the QA stage is too permissive.

## Goal

Human subjects must meet documentary-quality realism before approval.

## Human Criticality Rule

If a human occupies more than 20% of the frame or is the primary storytelling subject, mandatory Human QA is required.

Failure of Human QA MUST reject the image.

## Mandatory Human QA

Reject if any of the following are detected:

- Missing body parts
- Extra body parts
- Broken anatomy
- Impossible pose
- Deformed face
- Wrong age (if specified)
- Wrong gender (if specified)
- Wrong ethnicity (if specified)
- Wrong emotion (if specified)
- Subject cropped incorrectly

## Mandatory Hand QA

If hands are visible, reject for:

- Incorrect finger count
- Fused fingers
- Missing fingers
- Duplicate fingers
- Deformed thumb
- Distorted palm
- Unnatural wrist
- Impossible finger joints

## Clothing Validation

If clothing is specified in the prompt, it is mandatory.

Example:

Prompt:
- Young man wearing a grey shirt

Generated:
- Shirtless person

Result:
- Reject

## Prompt Compliance

Verify:

- Subject
- Clothing
- Pose
- Camera angle
- Environment
- Emotion
- Key props

Any critical mismatch must reject the image.

## Recommended Review Pipeline

Generate

↓

Overall Quality Review

↓

Human QA

↓

Hand QA (if visible)

↓

Prompt Compliance Review

↓

Approve

Any failed stage triggers regeneration.

## Success Criteria

Approved images should resemble real documentary photography. Human anatomy, clothing, and prompt intent must be correct before an image is accepted.
