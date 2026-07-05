# VIDEO_VALIDATION_RULES_V1

## Purpose

Define every validation rule used by the Video Quality Review Engine.
These rules determine whether a generated video is production-ready.

------------------------------------------------------------------------

# 1. Validation Philosophy

Every validation must be: - Deterministic where possible - Explainable -
Configurable - Repeatable - Independently testable

Each failed rule must produce: - Rule ID - Severity - Timestamp -
Evidence - Suggested root cause - Suggested engine owner

------------------------------------------------------------------------

# 2. Validation Categories

## A. Script Validation

-   Matches original topic and intent
-   No unnecessary filler
-   Duration within configured tolerance
-   Logical flow maintained
-   No repeated paragraphs

## B. Narration Validation

-   No clipped words
-   Natural pacing
-   Appropriate pauses
-   Correct pronunciation (where detectable)
-   No long unwanted silence

## C. Subtitle Validation

-   Subtitle matches narration
-   Correct timing
-   Reading speed within limit
-   Maximum characters per line
-   Proper line breaks
-   No overlaps
-   No spelling/formatting errors
-   Safe screen margins
-   ASS and SRT consistency

## D. Image Validation

-   Matches current narration
-   Matches current scene objective
-   Character continuity
-   Environment continuity
-   No repeated generic imagery
-   No visible text or watermarks
-   Correct aspect ratio and quality

## E. Motion Validation

-   Smooth transitions
-   No black frames
-   No frozen frames
-   Appropriate scene duration
-   Motion matches scene mood

## F. Audio Validation

-   Voice clarity
-   Consistent loudness
-   Background music balance
-   No clipping
-   No distortion

## G. Rendering Validation

-   Resolution correct
-   Frame rate correct
-   No corrupted frames
-   All assets rendered
-   No missing scenes

## H. Story Validation

-   Scene order correct
-   Story progression logical
-   Visuals support narration
-   Emotional consistency
-   Documentary flow maintained

------------------------------------------------------------------------

# 3. Severity Levels

Critical - Publishing must fail

High - Requires regeneration

Medium - Should be corrected

Low - Cosmetic improvement

------------------------------------------------------------------------

# 4. Validation Output

Each failed rule produces:

-   Rule ID
-   Category
-   Description
-   Severity
-   Timestamp
-   Evidence
-   Confidence
-   Responsible engine (placeholder for RCA)

------------------------------------------------------------------------

# 5. Pass Criteria

PASS only if: - No critical failures - All mandatory rules pass -
Overall quality threshold achieved

------------------------------------------------------------------------

# 6. Configuration

Every rule must support: - Enable/Disable - Threshold - Severity
override - Custom project configuration

------------------------------------------------------------------------

# 7. Future Rules

Reserved for: - Human attention analysis - Emotion consistency - Visual
composition scoring - AI hallucination detection - Brand consistency -
Viewer engagement prediction
