Task: Perform a COMPLETE production-readiness audit of the Visual Intelligence Layer after completion of Phases 1–6.

This is NOT a feature implementation task.

This is an architecture review, integration review, wiring verification, and production readiness audit.

================================================================================
OBJECTIVE
================================================================================

Assume Phases 1–6 have been fully implemented.

Your task is to verify that everything is correctly integrated,
fully wired,
production ready,
provider agnostic,
maintainable,
efficient,
and free of architectural gaps.

Do NOT add new features unless required to fix architecture problems.

================================================================================
STEP 1
Architecture Review
================================================================================

Review the entire architecture.

Verify:

✓ Single responsibility

✓ No duplicated logic

✓ No circular dependencies

✓ Clean abstraction boundaries

✓ Provider agnostic design

✓ Backward compatibility

✓ Proper dependency direction

✓ No unnecessary complexity

Identify any architecture smells.

================================================================================
STEP 2
Pipeline Wiring
================================================================================

Verify every pipeline stage.

Research

↓

Script

↓

Scene Planner

↓

VisualMetadata

↓

Prompt Builder

↓

PromptPackage

↓

Image Provider

↓

Vision QA

↓

Prompt Remediation

↓

Image

↓

TTS

↓

Subtitles

↓

Renderer

↓

Final Video

Confirm:

✓ Every component receives required inputs.

✓ Every output is consumed.

✓ No orphan objects exist.

✓ No unused metadata exists.

✓ No missing wiring.

================================================================================
STEP 3
VisualMetadata Audit
================================================================================

Verify VisualMetadata flows correctly.

Scene Planner

↓

Prompt Builder

↓

Vision QA

↓

Prompt Remediation

↓

Analytics

↓

Consistency Engine

Confirm:

No stage loses metadata.

No unnecessary copies.

No mutation bugs.

No serialization issues.

================================================================================
STEP 4
PromptPackage Audit
================================================================================

Verify PromptPackage.

Check:

creation

usage

storage

logging

fingerprinting

diff

analytics

remediation

Ensure PromptPackage is the single source of truth.

================================================================================
STEP 5
Vision QA Audit
================================================================================

Verify:

Era rules

Narrative Role

Environment

Mood

Historical constraints

Issue taxonomy

Scoring

Regeneration hints

No provider-specific assumptions.

================================================================================
STEP 6
Remediation Audit
================================================================================

Verify:

minimal edits

prompt diff

retry escalation

strategy selection

preserved constraints

no duplicated prompt logic

================================================================================
STEP 7
Consistency Engine Audit
================================================================================

Verify:

identity registry

scene memory

prompt enrichment

identity persistence

environment continuity

analytics integration

================================================================================
STEP 8
Analytics Audit
================================================================================

Verify:

provider metrics

quality metrics

cost tracking

prompt analytics

reports

dashboard models

benchmark engine

Ensure every metric has a producer.

Ensure every report has consumers.

================================================================================
STEP 9
Configuration Audit
================================================================================

Review every environment variable.

Verify:

used

documented

validated

reasonable defaults

no duplicates

no obsolete settings

no dead configuration

Identify configuration that should be removed.

================================================================================
STEP 10
Performance Audit
================================================================================

Review:

threading

concurrency

caching

memory

serialization

disk IO

network calls

provider initialization

lazy loading

batching

Look for:

duplicate work

redundant API calls

expensive object creation

unnecessary image processing

token waste

================================================================================
STEP 11
Provider Audit
================================================================================

Verify every provider follows the same architecture.

LLM

Image

Vision

TTS

Future providers

Check:

factory

settings

validation

logging

retry

metrics

No provider-specific hacks.

================================================================================
STEP 12
Testing Audit
================================================================================

Review tests.

Identify:

missing tests

duplicate tests

weak assertions

edge cases

regression gaps

integration tests

performance tests

concurrency tests

================================================================================
STEP 13
Documentation Audit
================================================================================

Verify:

architecture docs

module docs

README

configuration docs

examples

developer documentation

Update if required.

================================================================================
STEP 14
Code Quality Audit
================================================================================

Look for:

dead code

duplicate classes

duplicate enums

unused helpers

unused imports

large functions

god classes

violations of SOLID

violations of DRY

violations of KISS

================================================================================
STEP 15
Production Readiness
================================================================================

Verify:

logging

error handling

fallbacks

retry policies

timeouts

cancellation

cleanup

resource release

memory leaks

graceful failures

================================================================================
STEP 16
Cost Optimization
================================================================================

Review the entire pipeline.

Suggest opportunities to reduce:

LLM tokens

Vision tokens

Image generation cost

TTS cost

API calls

Disk IO

CPU usage

Memory usage

Do not reduce quality.

================================================================================
STEP 17
Future Readiness
================================================================================

Verify the architecture can support future additions without major refactoring.

Examples:

new image providers

new TTS providers

new Vision providers

new channels

new visual styles

new consistency modules

new analytics

================================================================================
STEP 18
Final Report
================================================================================

Produce a concise report.

Include:

Overall Architecture Score (0–100)

Production Readiness Score

Maintainability Score

Provider Agnostic Score

Performance Score

Cost Efficiency Score

Testing Score

Documentation Score

List:

Critical Issues

High Priority Issues

Medium Priority Issues

Low Priority Improvements

Quick Wins

Technical Debt

================================================================================
IMPLEMENTATION
================================================================================

Fix ONLY architectural problems discovered during the audit.

Do NOT add unrelated features.

Do NOT redesign working systems.

Prefer minimal targeted fixes.

================================================================================
VERIFICATION
================================================================================

Run the full test suite.

Ensure:

All previous functionality still works.

No regressions.

No wiring gaps.

No dead code.

No unused metadata.

No unused configuration.

================================================================================
STOP
================================================================================

After completing the audit and fixes, STOP.

Do not start implementing any new features.

Provide only a concise implementation summary following Implementation Mode.