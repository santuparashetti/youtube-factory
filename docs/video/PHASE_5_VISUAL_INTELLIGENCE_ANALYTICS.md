# Phase 5 -- Visual Intelligence Analytics & Optimization

Version: 1.0

## Goal

Implement Phase 5 of the Visual Intelligence Layer.

The objective is to transform YouTube Factory from simply generating
images into continuously measuring, learning, and optimizing image
quality, provider performance, remediation effectiveness, latency, and
cost.

## Out of Scope

Do NOT modify:

-   Scene Planner
-   Prompt Builder
-   Vision QA logic
-   Prompt Remediation logic
-   Image Providers

Consume the outputs from previous phases.

------------------------------------------------------------------------

# Design Principles

Every image generation should leave behind structured telemetry.

The system should answer:

-   Why did this image succeed?
-   Why did it fail?
-   Which provider performs best?
-   Which prompts require frequent remediation?
-   How much did each video cost?
-   Which eras are most difficult?
-   Which issue types are increasing?

The analytics layer must be provider agnostic.

------------------------------------------------------------------------

# Step 1 -- Analytics Domain

Create:

video_core/visual_intelligence/analytics/

Suggested modules:

-   models.py
-   collector.py
-   metrics.py
-   dashboard.py
-   exporter.py
-   reports.py

------------------------------------------------------------------------

# Step 2 -- Analytics Record

Create AnalyticsRecord.

Capture:

-   video_id
-   scene_id
-   timestamp
-   provider
-   model
-   prompt_fingerprint
-   visual_metadata
-   vision_score
-   remediation_attempts
-   latency_ms
-   image_size
-   estimated_cost
-   cache_hit
-   final_status

------------------------------------------------------------------------

# Step 3 -- Provider Analytics

Track:

-   total requests
-   success rate
-   failure rate
-   avg latency
-   avg retries
-   avg cost
-   cache hit ratio
-   timeout rate
-   429 rate
-   503 rate

Support:

-   Hugging Face
-   Gemini
-   Local
-   Future providers

No provider-specific logic.

------------------------------------------------------------------------

# Step 4 -- Quality Analytics

Track:

-   vision score distribution
-   pass rate
-   regeneration rate
-   remediation success
-   anatomy failures
-   anachronism failures
-   lighting failures
-   environment failures
-   mood failures

Break down by:

-   Era
-   Narrative Role
-   Environment
-   Mood
-   Visual Style

------------------------------------------------------------------------

# Step 5 -- Cost Analytics

Track estimated cost per:

-   image
-   scene
-   video
-   provider
-   month

Support configurable pricing tables.

Never hardcode provider pricing.

Allow exporting monthly cost summaries.

------------------------------------------------------------------------

# Step 6 -- Prompt Analytics

Track:

-   prompt length
-   estimated tokens
-   prompt fingerprint reuse
-   prompt stability
-   prompt growth after remediation

Highlight prompts that frequently require remediation.

------------------------------------------------------------------------

# Step 7 -- Dashboard API

Expose a provider-agnostic dashboard model.

Sections:

Pipeline Summary

Provider Comparison

Quality Trends

Era Trends

Narrative Role Trends

Top Failure Categories

Cost Summary

Remediation Summary

Cache Statistics

No UI implementation required.

Return structured objects suitable for CLI or future web UI.

------------------------------------------------------------------------

# Step 8 -- Reports

Generate:

Daily Report

Weekly Report

Monthly Report

Include:

-   videos processed
-   scenes processed
-   average quality score
-   provider comparison
-   estimated cost
-   top issues
-   remediation effectiveness

Support JSON and Markdown exports.

------------------------------------------------------------------------

# Step 9 -- Benchmarking

Provide benchmark comparisons.

Example:

Provider

Average Score

Average Latency

Estimated Cost

Failure Rate

Remediation Rate

This enables informed provider selection.

------------------------------------------------------------------------

# Step 10 -- Learning Insights

Automatically detect trends.

Examples:

-   Ancient scenes produce most anachronisms.
-   Symbolic scenes rarely fail.
-   Environment=Temple frequently needs remediation.
-   Provider X is slower but produces fewer retries.

Insights are advisory only.

------------------------------------------------------------------------

# Step 11 -- Logging

Debug mode:

Log detailed analytics events.

Production:

Compact summaries only.

------------------------------------------------------------------------

# Step 12 -- Configuration

Add configurable settings:

ANALYTICS_ENABLED=true

ANALYTICS_EXPORT_FORMAT=json

ANALYTICS_RETENTION_DAYS=90

COST_TRACKING_ENABLED=true

PROMPT_ANALYTICS_ENABLED=true

No breaking changes.

------------------------------------------------------------------------

# Step 13 -- Tests

Verify:

-   analytics records serialize
-   provider metrics aggregate correctly
-   cost calculations are configurable
-   reports generate successfully
-   benchmark outputs are deterministic
-   no provider-specific assumptions
-   existing pipeline remains unchanged

------------------------------------------------------------------------

# Deliverables

-   AnalyticsRecord
-   Analytics Collector
-   Provider Metrics
-   Cost Tracking
-   Prompt Analytics
-   Benchmark Engine
-   Report Generator
-   Dashboard Model
-   Full automated tests

Stop after Phase 5 implementation and provide a summary before Phase 6.
