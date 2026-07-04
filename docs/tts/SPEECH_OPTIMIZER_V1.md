# SPEECH_OPTIMIZER_V1.md

# Speech Optimizer --- Pre-TTS Narration Engine

## Objective

Introduce a Speech Optimizer stage between Script Generation and TTS.

Pipeline:

Research → Script Writer → Script Branding → Speech Optimizer → TTS →
Subtitle Generation → Video Rendering

The Speech Optimizer prepares narration for natural speech without
changing the meaning.

------------------------------------------------------------------------

# Preserve Existing Architecture

Do NOT modify:

-   LangGraph workflow
-   Research pipeline
-   Scene planning
-   Image generation
-   Subtitle timing
-   Video rendering
-   Public interfaces

Only add a preprocessing stage before TTS.

------------------------------------------------------------------------

# Why

Scripts are written to be read.

Narration should be written to be spoken.

The Speech Optimizer converts written language into spoken language
while preserving meaning.

------------------------------------------------------------------------

# Responsibilities

-   Split long sentences.
-   Insert natural pauses using punctuation.
-   Improve rhythm.
-   Improve breathing points.
-   Reduce tongue twisters.
-   Preserve emotional flow.
-   Preserve timestamps and scene mapping.

Never change the message or philosophy.

------------------------------------------------------------------------

# Pause Rules

Never use SSML.

Never generate:

-   `<break>`{=html}
-   `<prosody>`{=html}
-   `<emphasis>`{=html}

Instead use:

-   commas
-   periods
-   ellipses (...)
-   paragraph breaks
-   rhetorical questions

Example:

Original: "What if the life you're living isn't actually yours at all?"

Optimized: "What if...

the life you're living...

isn't actually yours at all?"

------------------------------------------------------------------------

# Speaking Rhythm

Prefer short thought groups.

Maximum spoken phrase: 8--12 words before a natural pause.

Avoid large blocks of uninterrupted narration.

------------------------------------------------------------------------

# Emotional Delivery

Rewrite punctuation based on intent.

Curiosity: Use short pauses and questions.

Reflection: Use slower sentence flow.

Revelation: Pause before the key insight.

Hope: Finish with smoother flowing sentences.

------------------------------------------------------------------------

# Breathing

Insert natural breathing opportunities every 12--18 spoken words where
appropriate.

Never interrupt meaningful phrases.

------------------------------------------------------------------------

# Emphasis

Use punctuation rather than markup.

Example:

"You are not your thoughts."

becomes

"You are...

not your thoughts."

Only when it improves delivery.

------------------------------------------------------------------------

# Provider Awareness

If the provider supports SSML: - Optionally generate SSML.

If the provider does NOT support SSML (edge-tts): - Output clean text
only.

The optimizer must remain provider-independent.

------------------------------------------------------------------------

# Quality Checks

Before passing text to TTS verify:

-   Sounds natural when read aloud.
-   No tongue-twisters.
-   Clear breathing opportunities.
-   Emotional pacing preserved.
-   Meaning unchanged.

------------------------------------------------------------------------

# Acceptance Criteria

The optimized narration should sound like a professional documentary
script read aloud.

Listeners should never notice that pauses were artificially inserted.

------------------------------------------------------------------------

# Prompt for Claude Code

Read this specification before making changes.

Implement a new Speech Optimizer stage between Script Branding and TTS.

Do not redesign the pipeline.

Keep all interfaces stable.

The Speech Optimizer should transform written narration into spoken
narration using intelligent punctuation, sentence restructuring, and
breathing rhythm instead of SSML.

If a TTS provider supports SSML, keep support optional through the
provider abstraction.

Present an implementation plan before coding, then implement
incrementally while preserving compatibility.
