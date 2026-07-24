The latest pipeline execution completed successfully and produced a complete review folder containing detailed quality analysis, root-cause reports, recurring issue reports, validation reports, and improvement recommendations.

Your task is NOT to redesign the pipeline.

Your task is NOT to implement every recommendation.

Instead, use the review artifacts as evidence to identify genuine implementation issues and fix them without breaking the current architecture.

---

## Source of Truth

Treat the generated review folder as the primary source of truth.

read - workspace/jobs/test-grass-that-refused-to-die/review

Review every report, including (but not limited to):

- review-report
- quality-report
- root-cause-report
- validation-report
- improvement-roadmap
- recurring-issues
- recurring-patterns
- scene-review
- score-breakdown
- pipeline QA reports

Correlate the findings rather than treating each report independently.

---

## Investigation Process

For every reported issue:

1. Verify it against the implementation.
2. Determine whether it is:
   - implementation bug
   - configuration issue
   - expected behavior
   - false positive
   - already fixed
3. Trace the root cause.
4. Verify against the existing architecture and specifications.
5. Only implement changes that are required by the architecture.

Do not fix symptoms.

Fix root causes.

---

## Motion System (High Priority)

Pay particular attention to the motion system.

The latest rendered video still feels visually weaker than expected.

Specifically investigate:

- camera smoothness
- continuous motion
- zoom visibility
- pan quality
- interpolation
- easing
- FFmpeg motion generation
- renderer output

The camera should feel like it is gliding naturally, not vibrating or stepping.

Do not assume the issue has already been identified in the review reports.

Perform an independent verification.

If the review folder does not mention a motion issue, still inspect the implementation because visual inspection indicates that smooth cinematic motion has not yet been fully achieved.

---

## Preserve Existing Pipeline

Do not break:

- scene planning
- image generation
- Vision QA
- remediation
- rendering
- subtitles
- TTS
- BGM
- publishing

Avoid unrelated refactoring.

Maintain backward compatibility.

---

## Deliverables

Provide:

### 1. Review Summary

Categorize every reported issue:

- Fixed
- Still valid
- False positive
- Configuration issue
- Future enhancement

---

### 2. Root Cause Report

For every remaining issue:

- root cause
- affected files
- implementation status
- proposed fix

---

### 3. Code Changes

Implement only architecture-compliant fixes.

Keep changes minimal.

---

### 4. Regression Verification

Verify that existing functionality has not been broken.

---

### 5. Final Status

Summarize:

- issues resolved
- issues intentionally deferred
- remaining roadmap items

The goal is to improve the pipeline incrementally while preserving the stability of the existing architecture.

---

## Change Impact Analysis (Required)

Before implementing any code changes, produce a Change Impact Matrix.

For every proposed fix, include:

| Issue | Root Cause | Files Affected | Regression Risk | Confidence | Recommended Action |
|------|------------|----------------|-----------------|------------|--------------------|

Classify regression risk as:

- Low
- Medium
- High

Only implement fixes with clear architectural justification.

If a proposed fix has Medium or High regression risk, explain why it is still necessary and identify the safeguards you will use to preserve existing behavior.

---

## Regression Safety Requirements

The current pipeline is considered stable.

Do not make speculative improvements.

Do not perform opportunistic refactoring.

Do not change working behavior simply because it could be improved.

Every code change must satisfy all of the following:

- Solves a verified issue from the review artifacts.
- Has an identified root cause.
- Matches the existing architecture and specifications.
- Has minimal implementation scope.
- Preserves backward compatibility.
- Does not negatively affect other pipeline stages.

If multiple fixes touch the same subsystem, implement them incrementally and verify each one independently before proceeding to the next.

---

## Verification After Each Fix

After every implemented fix, verify that the following pipeline stages continue to function correctly:

- Script generation
- Scene planning
- Image generation
- Vision QA
- Prompt remediation
- Motion generation
- FFmpeg rendering
- Subtitle generation
- Voice generation (if enabled)
- Background music
- Timeline assembly
- Quality review
- Publishing workflow

If any regression is detected, stop further implementation, report the regression, and propose the minimal corrective action before continuing.

---

## Final Validation

After all fixes are complete:

1. Re-run all relevant validation and quality checks.
2. Confirm that every implemented fix resolved the intended issue.
3. Confirm that no new regressions were introduced.
4. Clearly distinguish:

- Issues resolved
- Issues intentionally deferred
- Known limitations
- Future architectural improvements

Do not mark an issue as resolved unless it has been verified through the pipeline and review artifacts.

The objective is to improve the pipeline through small, well-validated changes while preserving the stability of the existing production architecture.