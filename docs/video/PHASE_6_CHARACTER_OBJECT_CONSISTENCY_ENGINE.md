# Phase 6 -- Character & Object Consistency Engine

Version: 1.0

## Goal

Implement Phase 6 of the Visual Intelligence Layer.

The objective is to maintain visual consistency for recurring
characters, objects, environments, clothing, symbols and visual identity
across scenes and across future videos.

This phase is provider agnostic.

------------------------------------------------------------------------

# Out of Scope

Do NOT modify:

-   Scene Planner logic
-   Prompt Builder architecture
-   Vision QA rules
-   Prompt Remediation strategies
-   Image Providers

Consume existing outputs from Phases 1--5.

------------------------------------------------------------------------

# Design Principles

The system should answer:

-   Is this the same Krishna?
-   Is this the same monk?
-   Does Arjuna still wear the same armor?
-   Is the palace consistent?
-   Does the temple look similar?
-   Is the color palette stable?

Consistency should be intentional rather than accidental.

------------------------------------------------------------------------

# Step 1 -- Identity Domain

Create:

video_core/visual_intelligence/consistency/

Suggested modules:

-   identities.py
-   registry.py
-   scene_memory.py
-   prompt_enricher.py
-   validator.py
-   reports.py

------------------------------------------------------------------------

# Step 2 -- Identity Model

Create VisualIdentity.

Fields:

-   identity_id
-   identity_type
-   display_name
-   description
-   canonical_attributes
-   optional_reference_images
-   created_at
-   updated_at

identity_type examples:

-   Character
-   Object
-   Animal
-   Building
-   Environment
-   Symbol

------------------------------------------------------------------------

# Step 3 -- Character Profiles

Support reusable character profiles.

Examples:

Krishna

Arjuna

Buddha

Monk

King

Farmer

Business Executive

Mother

Child

Each profile stores:

-   approximate age
-   gender (if applicable)
-   ethnicity / cultural context when relevant
-   clothing
-   hairstyle
-   beard
-   accessories
-   body type
-   recurring colors
-   distinctive traits

Avoid hardcoding channel-specific characters.

Profiles should be data-driven.

------------------------------------------------------------------------

# Step 4 -- Object Profiles

Support recurring objects.

Examples:

Bow

Conch

Temple Bell

Meditation Cushion

Lotus

Sword

Scroll

Book

Office Desk

Laptop

Store:

-   material
-   shape
-   scale
-   recurring appearance

------------------------------------------------------------------------

# Step 5 -- Environment Consistency

Maintain consistency for:

Temple

Ashram

Palace

Battlefield

Forest

Office

Apartment

Mountain

City

Store recurring:

-   architecture
-   lighting style
-   terrain
-   color palette
-   atmosphere

------------------------------------------------------------------------

# Step 6 -- Scene Memory

Create SceneMemory.

Track:

-   identities used
-   first appearance
-   latest appearance
-   prompt fingerprint
-   visual metadata
-   provider
-   regeneration history

Allow future scenes to reference prior identities.

------------------------------------------------------------------------

# Step 7 -- Prompt Enrichment

Before image generation, enrich PromptPackage using SceneMemory.

Example:

Instead of:

"A monk"

Generate:

"The same elderly monk introduced in Scene 03, wearing saffron robes,
grey beard, wooden prayer beads, calm expression."

Only enrich when continuity is intended.

------------------------------------------------------------------------

# Step 8 -- Continuity Rules

Maintain consistency for:

-   clothing
-   colors
-   hairstyle
-   accessories
-   body proportions
-   architecture
-   symbolic objects

Allow intentional changes when narration specifies:

-   aging
-   costume changes
-   transformation
-   different timeline

------------------------------------------------------------------------

# Step 9 -- Vision QA Support

Vision QA should optionally compare generated images with expected
identity attributes.

Examples:

Character mismatch

Clothing mismatch

Environment mismatch

Object mismatch

Identity drift

Report issues without requiring provider-specific logic.

------------------------------------------------------------------------

# Step 10 -- Analytics

Track:

-   identity reuse
-   continuity score
-   identity drift
-   object drift
-   environment drift
-   successful continuity corrections

------------------------------------------------------------------------

# Step 11 -- Reports

Generate Consistency Report.

Include:

-   recurring identities
-   first/last appearance
-   continuity score
-   drift events
-   remediation events

Support JSON and Markdown.

------------------------------------------------------------------------

# Step 12 -- Configuration

Add configurable settings:

CONSISTENCY_ENABLED=true

CONSISTENCY_MEMORY_ENABLED=true

CONSISTENCY_REFERENCE_IMAGES=false

CONSISTENCY_MAX_HISTORY=500

No breaking changes.

------------------------------------------------------------------------

# Step 13 -- Tests

Verify:

-   recurring identities persist across scenes
-   continuity survives regeneration
-   optional reference images work when enabled
-   prompt enrichment preserves story intent
-   intentional appearance changes are respected
-   backward compatibility maintained

------------------------------------------------------------------------

# Future Extensions

The architecture should later support:

-   embedding-based identity matching
-   face similarity models
-   costume similarity
-   scene graph consistency
-   cross-video identity memory
-   thumbnail consistency

These are future enhancements and should not block Phase 6.

------------------------------------------------------------------------

# Deliverables

-   VisualIdentity model
-   SceneMemory
-   Character/Object registry
-   Prompt enrichment
-   Continuity validator
-   Consistency analytics
-   Consistency reports
-   Full automated tests

Stop after Phase 6 implementation and provide a summary and
architectural review.
