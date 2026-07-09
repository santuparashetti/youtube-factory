# YouTube Factory Context — Base Script Generation Style

## Purpose

This document defines the standard for converting long spiritual
discourses, philosophical talks, and lectures into **Atma Theory** base
scripts.

The objective is **not to rewrite the speaker**.

The objective is to preserve the original wisdom while making it
engaging for a modern YouTube audience.

---

# Core Philosophy

Every script must preserve:

- The original message.
- The original intention.
- The original philosophy.
- The original emotional journey.
- The original conclusion.

The script should feel like the speaker is still speaking — only with
unnecessary repetition removed.

Never invent new philosophy.

Never change the meaning.

Never modernize the teaching in a way that alters its intent.

---

# Target Video Length

Target duration: **5–10 minutes**

Approximate narration: **1,300–1,700 words**

Only trim repetition.

Never trim wisdom.

**This target is a guideline, not a quota.** It applies in two directions:

- If the source discourse is already close to this length with little
  repetition to trim, leave it near-untouched. Do not hunt for
  additional material to cut just to reach a lower number — the target
  describes a typical *output* of the trimming rules below, not a floor
  to cut down to.
- If applying every trimming rule in this document (repetition, filler,
  duplicate explanations) still leaves the script above 1,700 words
  because the source genuinely contains that much distinct stories,
  analogies, and teaching — **exceed the target rather than cut a
  story, analogy, or core teaching.** Preservation (Core Philosophy)
  always outranks the word count when the two conflict. The word count
  exists to guide *how much repetition to remove*, not to cap how much
  wisdom survives.

---

# What To Preserve

Always preserve:

- Every important story.
- Every important analogy.
- Every memorable example.
- Every philosophical insight.
- Every major teaching.
- Every emotional transition.
- Every important quotation (when appropriate).

Stories are the heart of the discourse.

Analogies are the teaching.

Never remove them unless they are repeated multiple times (see
Repetition Threshold below).

---

# Repetition Threshold

"Repeated multiple times" is defined precisely to avoid ambiguity:

- **Occurs twice** → treat as intentional emphasis, not repetition.
  Speakers commonly restate a story or analogy once for effect — this
  is a rhetorical technique, not padding. Keep both occurrences unless
  they are near-verbatim duplicates with no added nuance between them.
- **Occurs three or more times** → candidate for trimming. Keep the
  strongest 1–2 occurrences (typically the first full telling and the
  most emotionally resonant restatement, if they differ meaningfully)
  and cut the rest.
- When in doubt, keep the occurrence rather than cut it — this rule
  exists to remove clear padding, not to aggressively minimize length.

---

# What To Remove

Remove only:

- Repeated sentences (per Repetition Threshold above).
- Duplicate explanations.
- Repeated examples.
- Filler speech.
- Conversational pauses that don't add meaning.
- Audience interaction that doesn't move the teaching forward.

Never remove a story simply to shorten the script.

Instead, shorten repetitive explanation around the story.

---

# Narration Style

Narration should be:

- Calm
- Reflective
- Contemplative
- Cinematic
- Emotionally engaging
- Easy to follow

Avoid sounding like a textbook.

Avoid sounding like a motivational speaker.

Avoid sounding like AI.

---

# Hook Style

The opening should create curiosity.

Do not reveal everything immediately.

Lead the audience naturally into the discourse while staying faithful to
the original theme.

---

# Storytelling Rules

Stories should remain in the same order as the original discourse.

Do not rearrange stories unless it dramatically improves flow without
changing meaning.

Do not merge different stories into one.

Do not invent new stories.

---

# Analogy Rules

Analogies are critical.

Examples:

- Dustbin
- Banana peel
- Pocket
- Train seat
- Children leaving home
- Village gossip

Keep every important analogy.

Use them as visual anchors for scene generation.

---

# Meaning Preservation

Never change:

- The intended message.
- Philosophical meaning.
- Moral lesson.
- Spiritual conclusion.

Minor wording improvements are allowed only if the meaning remains
identical.

---

# Script Structure

Use this structure as a default:

1. Opening Hook
2. Introduction
3. Chapter 1
4. Chapter 2
5. Chapter 3
6. Chapter 4
7. Final Reflection
8. Closing
9. Production Notes

**Chapter count is flexible, not fixed at four.** Use as many chapters
as the source material naturally supports — minimum 2. A discourse with
only two distinct teaching movements should produce a 2-chapter script,
not be artificially padded or subdivided to fill four slots. Likewise, a
richer discourse may warrant 5–6 chapters rather than compressing
distinct teachings into one. The structure's purpose is pacing, not a
quota.

Chapter titles are metadata only.

They must never be narrated.

**Validation of this rule**: since chapter titles being accidentally
narrated is a hard content error (not a style preference), the Script
Engine's output must be checked — either by a ReviewPipeline-style pass
scanning generated narration text for literal chapter-heading strings,
or, at minimum, a manual spot-check step noted in this doc's adoption
checklist — before this rule is treated as reliably enforced rather than
aspirational.

---

# Trimming Rules

When reducing a long discourse, apply in this order:

1. Remove repetition first (per Repetition Threshold).
2. Remove filler second.
3. Keep all stories.
4. Keep all analogies.
5. Keep the emotional flow.
6. Keep the philosophical progression.

Never shorten by deleting the core teaching.

If after all six steps the script still exceeds the 1,300–1,700 word
target, stop trimming — see Target Video Length above for the
resolution rule. Do not proceed to cutting stories or analogies as a
seventh step to force the word count down.

---

# Original Voice

The finished script should feel like:

"The original speaker delivering a tighter, more cinematic version of
the same discourse."

Not:

"A new author explaining the topic."

---

# Scene Planning Considerations

Write with visual storytelling in mind.

Preserve imagery from stories and analogies because they become strong
visual scenes.

Do not over-compress these sections.

---

# Pause Notation and ThoughtPauseRanges

Preserve ellipses (`...`) in the script text for narration pauses — this
document's role is to mark *where* a pause belongs in the base script,
using plain ellipsis notation, because at script-writing time the
downstream pause classification system hasn't run yet.

**Relationship to ThoughtPauseRanges:** this ellipsis notation is not a
duplicate or competing pause system. It is the upstream signal that the
TTS/pause-classification stage (ThoughtPauseRanges: small / realization
/ insight tiers) reads and classifies later in the pipeline. The Script
Engine's job is only to mark *that* a pause belongs at a point in the
text; classifying *how long* that pause should be (small vs. realization
vs. insight tier) is the downstream stage's responsibility, not this
document's. Do not have the Script Engine attempt to pre-classify pause
tiers — that would create two independent systems making the same
decision, with no defined precedence if they disagree.

---

# Production Notes

- Preserve ellipses (`...`) for narration pauses — see Pause Notation
  above for how this connects to ThoughtPauseRanges downstream.
- Keep chapter headings as metadata only, and verify they never leak
  into narrated text (see Script Structure validation note above).
- Maintain semantic sentence boundaries.
- Avoid changing chronology.
- Keep transitions smooth and natural.
- Preserve the soul of the original discourse.
- Optimize for YouTube retention without sacrificing authenticity.
- When the word-count target and full preservation conflict, preservation
  wins — see Target Video Length.
