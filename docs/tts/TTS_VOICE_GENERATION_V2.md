# TTS_VOICE_GENERATION_V2.md

# TTS Voice Generation V2 --- Documentary Narration Upgrade

## Objective

Refactor only the TTS generation pipeline so narration sounds like a
professional documentary narrator instead of a text reader.

## Preserve Existing Architecture

Do NOT modify: - LangGraph flow - Pipeline architecture - Scene
splitting - JSON schema - Audio generation flow - Video rendering -
Downstream integrations

Only improve the TTS generation stage.

## Voice Profile

-   American English
-   Neutral US accent
-   Mature adult voice
-   Calm, warm, trustworthy
-   Intelligent documentary style

## Emotional Speech Engine

Before synthesis analyze: - dominant emotion - pacing - emphasis -
dramatic weight - pauses - vocal energy

## Emotional Categories

Curiosity, Wonder, Reflection, Mystery, Peace, Hope, Compassion,
Urgency, Sadness, Awe, Determination, Revelation.

## Natural Pauses

Insert meaningful pauses after key statements, before revelations, and
around rhetorical questions.

## Dynamic Speaking Rate

Slow for philosophy and emotional insights. Slightly faster for
storytelling and transitions.

## Pitch

Higher for curiosity and hope. Lower for wisdom, seriousness and
mystery.

## Emphasis

Stress only semantically important words.

## Breathing

Insert natural breathing opportunities.

## Scene Awareness

Adapt delivery: - Questions → Curious - Reflection → Calm - Revelation →
Quiet confidence - Call to action → Warm inspiration

## Pronunciation

Use natural American pronunciation and correctly pronounce names, places
and philosophical terminology.

## Emotional Arc

Beginning: Curious Middle: Reflective Ending: Hopeful

## Audio Quality

Warm, intimate, cinematic, broadcast quality. Avoid robotic pacing and
metallic voices.

## Provider Independence

Use SSML or equivalent controls when available. Gracefully degrade when
unavailable.

## Acceptance Criteria

The narration should sound like a premium documentary narrator who
understands every sentence.

------------------------------------------------------------------------

# Prompt for Claude Code

Read this document completely before making any code changes.

Upgrade ONLY the TTS generation stage.

Preserve: - LangGraph - Pipeline - JSON schema - Scene timing - Video
rendering - Public interfaces

First analyze the current implementation and produce an implementation
plan. Wait for approval before coding.

After approval: 1. Refactor the TTS generation logic. 2. Use
provider-specific expressive controls (SSML or equivalent) where
available. 3. Maintain the existing provider abstraction. 4. Degrade
gracefully when advanced controls are unavailable. 5. Explain every
change and why it improves narration quality.

The goal is narration that sounds like a professional documentary
narrator rather than a synthetic voice.
