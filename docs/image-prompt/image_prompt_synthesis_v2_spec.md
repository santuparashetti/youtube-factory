# Image Prompt Synthesis V2

## Goal

Build a new image-prompt synthesis stage from scratch.

Do NOT extend, repair, or preserve the existing image-prompt generation/QA flow. This is a new stage with a clean contract.

The stage should perform one high-quality LLM synthesis:

Canonical Script + Scene Narration + Adjacent Context + Scene/Beat Purpose + Visual Bible + Continuity/Story Context + Global Style
→ ONE LLM CALL
→ Final rich image prompt
→ Lightweight deterministic contract validation
→ Image Generation

## Source hierarchy

When inputs conflict, use this priority:

1. Narration
2. Explicit `[Visual:]` direction
3. Scene/beat purpose
4. Continuity requirements
5. Visual Bible
6. Story/scene context
7. Global style
8. Creative enhancement

Creative enhancement must never override higher-priority information.

## Context

For each scene provide:
- Current scene narration
- Immediately preceding scene narration, when available
- Immediately following scene narration, when available
- Scene/beat purpose
- Relevant Visual Bible constraints
- Relevant Story/continuity constraints
- Global visual style

Do not pass the entire script when adjacent context is sufficient.

If narration is empty, use scene purpose, explicit visual direction, continuity and Visual Bible. Never invent narrative events.

## Synthesis requirements

Generate ONE coherent, image-generator-ready cinematic prompt.

The prompt should naturally express, when relevant:
- primary subject and supporting subjects
- exact action and relationships
- environment and setting
- era/location
- composition and spatial hierarchy
- camera/lens/framing
- depth and scale
- lighting
- atmosphere
- color
- emotional tone
- visual metaphor
- continuity with surrounding scenes
- required negative constraints

Do not output metadata blocks such as `PRIMARY SUBJECT`, `PRIMARY ACTION`, `ANT`, etc.

Do not repeat the narration verbatim.

Do not invent unsupported characters, props, actions, settings, history or symbolism.

Add rich cinematic detail only when it strengthens the narrated moment.

## Hybrid visual style

The environment is 100% photorealistic cinematic photography.

Every human, animal or bird is 100% hand-painted 2D storybook/illustrated style with the established ink-outline, painterly/cel-shaded treatment.

When a human or animal appears inside a photorealistic environment, apply the two styles independently: illustrated subject + photorealistic environment.

Never convert the whole scene to one style because a character is present.

## Text and branding

Image generation must not create readable text, titles, subtitles, logos, UI or branding unless the scene explicitly designates image-generated text.

For compositor-owned text/CTA/end-screen content, create appropriate clean space and visual framing; do not generate the actual text.

## Character handling

There is NO global Kai character.

Remove the hardcoded/global Kai anchor and injection architecture from this new stage.

Characters must exist only when required by narration, scene context, continuity or explicit scene metadata.

If recurring-character infrastructure exists, keep it generic and data-driven; do not assume Kai.

## Continuity

Maintain established:
- recurring characters
- subject appearance
- environment/world
- era
- dominant metaphor
- visual motifs
- color/lighting direction
- spatial progression

Do not introduce a competing visual world unless the narrative explicitly requires it.

## Validation

Use lightweight deterministic validation only for hard contract failures:
- missing/empty prompt
- invalid output/schema
- accidental global Kai injection
- obvious forbidden meta-instructions
- prohibited text/branding generation
- required hybrid-style markers
- unreasonable prompt length

Validation must not become another creative rewrite stage.

If a hard failure occurs, report it clearly.

## Output contract

One final `visual_prompt` per scene.

No analysis, repair notes, metadata blocks, alternative prompts, A/B versions, or second-pass rewriting.

## Implementation rules

Build this as a clean new stage rather than incrementally modifying the old prompt-generation architecture.

Do not migrate old prompt-repair logic into the new stage.

Do not add another LLM call.

Do not reintroduce A/B generation, recomposition, semantic repair, or prompt-QA loops.

Reuse only independent infrastructure that is genuinely useful, such as model/provider access, Visual Bible, Story Bible, scene data, configuration and downstream image-generation interfaces.

First inspect the repository only to identify reusable inputs/contracts. Then implement the new stage independently.

Preserve downstream compatibility where required, but do not preserve obsolete upstream prompt-generation behavior for compatibility.

## Tests

Add focused tests for:
- narration subject/action preservation
- explicit visual-direction preservation
- adjacent-context usage
- Visual Bible continuity
- hybrid human/animal + environment styling
- no invented subjects
- no global Kai
- no-narration scene handling
- compositor text handling
- continuity across recurring subjects
- single LLM call
- final prompt contract

Run focused tests and the full suite.

No unrelated refactoring.
