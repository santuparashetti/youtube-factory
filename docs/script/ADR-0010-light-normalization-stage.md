# ADR-0010: Introduce Light Normalization Stage Before Documentary Script Enhancer

**Status:** Proposed

**Priority:** High

**Owner:** YouTube Factory

---

# Background

The current script generation pipeline passes the original discourse transcript directly into the Script Enhancer.

The Script Enhancer is currently responsible for both:

1. Cleaning transcription artifacts
2. Rewriting the discourse into a cinematic YouTube documentary

These are two fundamentally different responsibilities.

To improve maintainability and output quality, we will explicitly separate them.

---

# Current Pipeline

Transcript Input
        ↓
Script Enhancer
        ↓
Scene Planner
        ↓
Image Generation
        ↓
Video Assembly

---

# New Pipeline

Transcript Input
(Original discourse OR Speech-to-Text)
        ↓
Light Normalization
        ↓
Documentary Script Enhancer
        ↓
Scene Planner
        ↓
Image Generation
        ↓
Video Assembly

---

# Supported Inputs

The pipeline must support two equivalent transcript sources.

## Option 1

Original discourse transcript supplied via CLI.

Example

```bash
ytfactory create \
    --script discourse.md
```

This is currently the primary workflow.

---

## Option 2

Speech-to-text transcript generated from audio.

Example

```bash
ytfactory create \
    --audio discourse.mp3
```

After transcription, both workflows converge into the same pipeline.

The Documentary Script Enhancer must never depend on how the transcript was produced.

Its only contract is:

> "Receive a transcript."

---

# Why This Change

Raw discourse transcripts contain:

- spoken language
- conversational repetition
- filler phrases
- transcription artifacts
- emotional pauses
- stories
- analogies
- humor
- scripture
- audience interaction

The Script Enhancer should focus exclusively on narrative quality.

It should not spend effort fixing formatting problems.

Likewise, the normalization stage must never become an editor.

Each stage should have exactly one responsibility.

---

# Implementation Guidelines

This ADR specifies a **contract**, not a mechanism. The implementation is free to choose whatever approach best satisfies the guarantees and validation criteria defined below — a single LLM call, rule-based text processing, a hybrid, or existing utilities already in the codebase. Nothing in this document should be read as mandating a specific technique.

Before introducing new classes or utilities:

- Inspect the existing pipeline and reuse existing abstractions where they fit.
- Avoid duplicate helpers or parallel implementations of things that already exist (e.g. no `normalizer_v2.py` alongside an existing normalizer if it can be extended instead).
- Preserve backwards compatibility wherever practical.
- Prefer extending or composing existing stages/utilities over introducing new parallel ones, unless the existing code genuinely cannot satisfy the contract.

---

# Ambiguity Handling

The original spec says to remove content "only when clearly not intentional." That instruction alone is not enforceable — "clearly" is a judgment call, and an LLM-driven stage under this instruction will occasionally guess wrong in the direction of over-editing.

## Rule

**Default to preservation.** When the normalization stage cannot determine with high confidence whether a repetition or phrase is ASR noise vs. intentional emphasis, it must leave the text unchanged rather than remove it.

## What must be true, regardless of technique

- Removal is only acceptable for clear, low-risk machine artifacts — e.g. an immediate word-level stutter with no punctuation or pause between repeats, or exact duplication of a short filler word with no semantic content.
- Removal must NOT occur for: repetition separated by punctuation, line breaks, or a pause marker; repetition of a full clause or sentence (almost always rhetorical, not ASR error); or any repetition inside or adjacent to a scripture span (never touched, full stop — see below).
- For genuinely borderline cases that don't meet the confident-removal bar, the implementation must **flag rather than silently decide** — the exact mechanism (inline marker, sidecar annotation, span list) is an implementation choice, but the flag must be visible to the Documentary Script Enhancer or a human reviewer downstream.

---

# Scripture / Sacred Reference Detection

"Preserve scripture exactly" is only as strong as the mechanism used to detect what counts as scripture. This needs to be explicit, not left to model discretion.

## Required outcome

Scripture, Sanskrit, and transliterated spans must be reliably identified before either the deterministic or model-assisted parts of normalization touch the text. The implementation is free to choose the detection approach — source-side marking at transcript creation, Unicode/script-range detection, a verse glossary, verbal-cue detection, or a combination — provided it meets the guarantee below. Source-side marking (delimiting scripture at the point the transcript is produced) is likely the most reliable option and is worth strong consideration, but this ADR does not mandate it.

## Guarantee

Whatever detection method is used, once a span is classified as scripture, it is passed through **byte-for-byte unchanged** — not merely "not rewritten," but excluded from even the deterministic whitespace/punctuation pass, since even a punctuation change inside a verse could alter meaning or meter.

## Open item

If source-side marking is not currently produced anywhere upstream (research/scripting stage), this ADR recommends adding it there as a fast follow, since it is materially more reliable than post-hoc detection and removes the biggest risk to this guarantee.

---

# Preserve Chronological Order

Never reorder paragraphs.

Never move sections.

Never summarize.

Never restructure.

---

# Preserve Speaker Intent

Never reinterpret philosophy.

Never modernize teachings.

Never simplify concepts.

Never inject new opinions.

---

# Preserve All Narrative Assets

Never remove

- stories
- analogies
- jokes
- examples
- historical references
- emotional moments

These are valuable documentary material.

---

# Preserve Emotional Pacing

If the speaker intentionally repeats something for emphasis, leave it unchanged. See Ambiguity Handling above for how "intentional" is determined in practice.

The Documentary Script Enhancer will later decide whether to compress repetition.

---

# Explicitly Forbidden

The Light Normalization stage MUST NOT

❌ Rewrite sentences

❌ Improve English

❌ Improve storytelling

❌ Shorten paragraphs

❌ Add examples

❌ Add transitions

❌ Add hooks

❌ Add chapter titles

❌ Remove stories

❌ Remove analogies

❌ Reduce repetition for style

❌ Change tone

❌ Change pacing

❌ Change emotional intensity

❌ Convert discourse into documentary

Those responsibilities belong exclusively to the Documentary Script Enhancer.

---

# Documentary Script Enhancer

The existing Script Enhancer should be renamed to

**Documentary Script Enhancer**

Its responsibility is no longer cleaning.

Its responsibility is narrative optimization.

---

## Primary Objective

Transform the discourse into a cinematic documentary suitable for YouTube while preserving the original philosophy and emotional intent.

---

## Enhancement Goals

The enhancer should optimize for viewer retention before language elegance.

Priority order

1. Preserve meaning
2. Preserve philosophy
3. Preserve emotional intent
4. Improve narrative flow
5. Increase viewer retention
6. Improve storytelling
7. Improve cinematic pacing
8. Produce memorable lines

---

## Storytelling Rules

Prefer stories over abstract explanation whenever possible.

If a philosophical idea can be explained using

- analogy
- story
- historical example
- everyday situation

prefer that over exposition.

---

## Viewer Retention Rules

The enhancer should think like a documentary writer rather than a copy editor.

It should

- create curiosity
- delay answers when appropriate
- end chapters with momentum
- alternate between story and reflection
- avoid long uninterrupted philosophical exposition

---

## Cinematic Rhythm

Preserve deliberate pauses.

Do not merge every short sentence into long paragraphs.

The output should feel like it was written to be narrated over cinematic visuals.

Not read as an essay.

---

## Branding

Never introduce the channel name before the opening hook.

The first 20–40 seconds should exist only to emotionally hook the viewer.

Channel branding belongs after viewer engagement has been established.

---

## Memorable Quotes

Whenever appropriate, create concise memorable lines that viewers are likely to remember or share.

These should emerge naturally from the philosophy.

Not feel artificially inserted.

---

## Preserve Voice

Never replace the speaker's personality.

The output should still feel like the original teacher.

Only clearer, tighter and more cinematic.

---

# Handoff Contract

Light Normalization guarantees

✓ clean formatting

✓ readable transcript

✓ chronological structure

✓ preserved meaning

✓ preserved emotion

✓ preserved stories

✓ untouched scripture spans

✓ flagged (not resolved) ambiguous spans, if any

The Documentary Script Enhancer guarantees

✓ cinematic narration

✓ improved storytelling

✓ higher viewer retention

✓ documentary pacing

✓ stronger emotional impact

---

# Design Principle

Normalize the transcript.

Do not normalize the teaching.

Rewrite the narrative.

Do not rewrite the philosophy.

---

# Validation Criteria

The human read-through test below remains the top-level acceptance bar, but given how strict the preservation guarantees are, they should also be enforced with automated checks rather than relying solely on subjective review.

## Automated checks (Light Normalization output)

- **Change-ratio bound.** Character- or token-level diff between input and output should stay under a defined threshold (e.g. a low single-digit percentage change). A jump above threshold fails the stage and flags for review — it's a strong signal the stage drifted into editing.
- **Scripture exact-match.** Every detected scripture/scripture-adjacent span in the input must appear byte-for-byte identical in the output. Any mismatch is a hard failure, not a warning.
- **Paragraph-count / order invariant.** Paragraph count should not decrease, and paragraph ordering (by content hash or leading n-grams) should be monotonic — catches reordering or merging.
- **No new content.** Output should not contain any sentence with no reasonably close match in the input (catches the stage inventing transitions or hooks, which is explicitly forbidden).

## Human checks

- If a human compares Original Transcript → Light Normalization, they should conclude "This is the same discourse, only easier to read."
- If a human compares Light Normalization → Documentary Script Enhancer, they should conclude "This is the same wisdom transformed into a compelling documentary."

Failing either automated or human check should block promotion of that stage's output to the next stage in the pipeline, the same way image QA gates currently block low-quality generations from advancing.

---

# Rename Migration Checklist

Since "Script Enhancer" → "Documentary Script Enhancer" is a rename of an existing component, not just the introduction of a new one, the following should be swept before this ships:

- Class/module/file names referencing `ScriptEnhancer`
- Config keys and CLI flags referencing the old name
- Log messages and metrics/telemetry tags
- References in Scene Planner or any downstream stage that names the enhancer explicitly
- Any existing hardened specs or docs (e.g. Base Script Generation Style guide) that refer to "Script Enhancer" by name

---

# Success Criteria

If a human compares

Original Transcript

↓

Light Normalization

they should conclude

"This is the same discourse, only easier to read."

If a human compares

Light Normalization

↓

Documentary Script Enhancer

they should conclude

"This is the same wisdom transformed into a compelling documentary."

Additionally, the automated checks under Validation Criteria must pass for both stage transitions. That is the intended separation of responsibilities.

---

# Implementation Deliverables

This ADR is not documentation only.

Implement the following:

- [ ] Introduce the new Light Normalization stage.
- [ ] Wire it into the pipeline before the Documentary Script Enhancer.
- [ ] Rename Script Enhancer → Documentary Script Enhancer across the codebase (see Rename Migration Checklist above).
- [ ] Update pipeline orchestration to reflect the new stage order.
- [ ] Update CLI workflow if required (Option 1 / Option 2 input paths must both converge correctly).
- [ ] Implement scripture-span detection satisfying the guarantee above.
- [ ] Implement the flagging mechanism for ambiguous spans.
- [ ] Add unit tests covering the ambiguity heuristics and scripture preservation.
- [ ] Add integration tests covering the automated validation checks (change-ratio bound, scripture exact-match, paragraph-order invariant, no-new-content).
- [ ] Update architecture documentation.
- [ ] Ensure existing pipelines continue to work end to end.
