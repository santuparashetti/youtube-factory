# Visual Intelligence Layer (VIL)
Version: 1.0

---

# Vision

YouTube Factory currently generates videos using the following pipeline:

Research
↓

Script
↓

Scene Planner
↓

Image Prompt Builder
↓

Image Generation
↓

Vision QA
↓

Prompt Remediation
↓

TTS
↓

Rendering

The current pipeline relies primarily on free-form text prompts.

As the project grows, this causes image models to infer information that should instead be explicitly provided by the system.

Examples:

- Drone flying above an ancient kingdom
- Helicopter above Kurukshetra
- Modern road inside Mahabharata
- Camera crew in a Vedic Ashram
- Electric poles inside an ancient forest
- Glass skyscrapers behind Buddha

These are not image-model problems.

They are missing-context problems.

The pipeline should become visually intelligent instead of relying on prompt engineering.

---

# Goal

Introduce a provider-independent Visual Intelligence Layer.

The Scene Planner should explicitly describe the visual intent.

Every downstream component should consume structured visual metadata rather than attempting to infer historical context.

This architecture must remain provider agnostic.

Image providers must not contain any Atma Theory specific logic.

---

# Design Principles

• Separate storytelling from visual reasoning.

• Keep visual metadata independent of image providers.

• Allow future channels without code changes.

• Eliminate duplicated prompt engineering.

• Improve image consistency.

• Reduce regeneration.

• Improve Vision QA.

---

# Current Pipeline

Scene Planner

↓

Prompt Builder

↓

Image Provider

↓

Vision QA

---

# New Pipeline

Scene Planner

↓

Visual Intelligence Layer

↓

Prompt Builder

↓

Image Provider

↓

Vision QA

↓

Prompt Remediation

---

# Scene Output

Instead of only producing narration and image prompt...

Every scene should produce:

scene

visual_metadata

Example

scene:

    narration:

    visual_description:

visual_metadata:

    version:

    era:

    narrative_role:

    environment:

    mood:

    visual_style:

    allow_modern_objects:

    reason:

The Scene Planner is responsible only for describing the scene.

The Prompt Builder is responsible for converting metadata into provider prompts.

---

# Visual Metadata

Version 1 intentionally keeps metadata compact.

Required fields:

## era

Allowed values

ANCIENT

HISTORICAL

MODERN

SYMBOLIC

TRANSITIONAL

Purpose

Determines historical constraints.

Examples

ANCIENT

Bhagavad Gita

Kurukshetra

Temple

Ashram

Vedic Village

Historical Kingdom

Forest Hermitage

---------------------------------

HISTORICAL

Buddha

Adi Shankaracharya

Ancient Scholars

Kings

Medieval Monastery

---------------------------------

MODERN

Office

Apartment

Traffic

Corporate Life

Smartphone

Social Media

Airport

Coffee Shop

---------------------------------

SYMBOLIC

Soul

Consciousness

Mind

Ego

Fear

Attachment

Meditation

Timeless space

Dreamlike concepts

---------------------------------

TRANSITIONAL

Ancient Wisdom meeting Modern Life

Krishna beside businessman

Ancient temple beside city

Split timeline

Comparison scenes

---

## narrative_role

Purpose

Explains WHY the image exists.

Allowed values

STORY

ANALOGY

METAPHOR

EXPLANATION

ESTABLISHING

CTA

Examples

Battle of Kurukshetra

↓

STORY

Modern office worker

↓

ANALOGY

Floating soul

↓

METAPHOR

Temple overview

↓

ESTABLISHING

Subscribe scene

↓

CTA

---

## environment

Examples

FOREST

TEMPLE

ASHRAM

KINGDOM

BATTLEFIELD

CITY

OFFICE

HOME

MOUNTAIN

RIVER

ABSTRACT

COSMIC

---

## mood

Examples

PEACEFUL

MYSTERIOUS

REVERENT

REFLECTIVE

HOPEFUL

FEARFUL

CURIOUS

LONELY

DETERMINED

---

## visual_style

Independent from Era.

Allowed values

DOCUMENTARY

CINEMATIC

REALISTIC

DREAMLIKE

Future styles

PAINTING

ANIME

WATERCOLOR

---

## allow_modern_objects

Boolean

Ancient

false

Historical

false

Modern

true

Symbolic

Planner decides

Transitional

true

---

## reason

Purpose

Debugging only.

Never sent to image providers.

Example

"The narration describes Kurukshetra, therefore modern technology should not exist."

---

# Visual Profiles

Create

video_core/visual_intelligence/profiles/

Profiles

ancient_documentary.py

historical_documentary.py

modern_documentary.py

symbolic_documentary.py

transitional_documentary.py

Each profile defines

Positive prompt

Negative prompt

Architecture

Materials

Lighting

Clothing

Landscape

Atmosphere

Camera language

Color palette

---

# Era Rules

ANCIENT

Positive

Stone

Wood

Natural materials

Oil lamps

Ancient architecture

Traditional clothing

Natural landscapes

Authentic weapons

Animals

Negative

Drone

Helicopter

Aircraft

Cars

Roads

Electric poles

LED

Plastic

Glass towers

Phones

Camera

Tripod

Microphone

Satellite

Modern clothing

Laptop

Television

Power lines

Concrete highway

---------------------------------

HISTORICAL

Same philosophy.

Historically authentic.

---------------------------------

MODERN

Modern technology allowed.

No unnecessary ancient styling.

---------------------------------

SYMBOLIC

No forced historical constraints.

Prefer timeless metaphorical imagery.

---------------------------------

TRANSITIONAL

Intentional coexistence.

Ancient and modern may appear together.

---

# Prompt Builder

The Prompt Builder becomes responsible for assembling prompts.

Inputs

Scene description

Visual metadata

Visual profile

Output

Final provider prompt

The Scene Planner should never write negative prompts directly.

---

# Vision QA

Vision QA must receive VisualMetadata.

Validation becomes context aware.

Examples

Ancient

Drone

↓

Reject

Ancient

Smartphone

↓

Reject

Modern

Smartphone

↓

Accept

Modern

Office

↓

Accept

Symbolic

Floating temple

↓

Accept

Transitional

Modern city beside ancient temple

↓

Accept

If an anachronism is detected

Category

Anachronism

Severity

HIGH

recommend_regeneration=true

---

# Prompt Remediation

Prompt remediation should use metadata.

Example

Ancient

↓

Drone detected

↓

Regeneration prompt

"Preserve historical authenticity.
Remove all modern technology.
Maintain ancient architecture."

Do not regenerate using the same prompt.

---

# Logging

Log metadata for every generated scene.

Example

Scene 08

Era

ANCIENT

Role

STORY

Environment

TEMPLE

Mood

REVERENT

Reason

Bhagavad Gita setting.

---

# Metrics

Track

Scenes by Era

Scenes by Narrative Role

Vision failures by Era

Vision failures by Narrative Role

Most common anachronisms

Regeneration rate

Average confidence by Era

---

# Configuration

DEFAULT_VISUAL_STYLE=documentary

Future

photoreal

anime

painting

watercolor

Only visual appearance changes.

Era rules remain independent.

---

# Backward Compatibility

Existing providers

Must continue working.

No provider-specific logic.

No channel-specific logic.

No breaking API changes.

---

# Tests

Verify

✓ Ancient scenes never contain modern technology.

✓ Historical scenes remain historically authentic.

✓ Modern scenes allow phones.

✓ Modern scenes allow offices.

✓ Symbolic scenes remain timeless.

✓ Transitional scenes intentionally mix eras.

✓ Prompt builder injects correct profile.

✓ Vision QA validates according to metadata.

✓ Remediation strengthens historical constraints.

✓ Existing image providers continue working.

✓ Existing vision providers continue working.

✓ Existing pipelines continue working.

---

# Implementation Order (IMPORTANT)

Implement incrementally to avoid regressions.

Phase 1
- Add VisualMetadata model.
- Extend Scene Planner output.
- Keep existing prompts unchanged.

Phase 2
- Build Visual Profiles.
- Update Prompt Builder to consume metadata.

Phase 3
- Make Vision QA era-aware.

Phase 4
- Update Prompt Remediation.

Phase 5
- Add metrics, logging, and analytics.

Each phase should preserve compatibility with the previous pipeline.