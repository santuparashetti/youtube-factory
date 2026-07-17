# ADR-0011: Upgrade Documentary Script Enhancer for Cinematic Storytelling & Viewer Retention

**Status:** Proposed

**Priority:** High

**Owner:** YouTube Factory

---

# Background

The Documentary Script Enhancer currently focuses primarily on improving language quality and converting discourse into a documentary script.

While the output is substantially better than the original transcript, it still behaves more like a skilled editor than an experienced documentary writer.

Long-form YouTube success depends far more on viewer retention than on perfect prose.

Therefore, the Documentary Script Enhancer should evolve from a language enhancement stage into a cinematic documentary writing stage.

Its success should be measured by audience engagement, storytelling quality, emotional pacing and faithfulness to the original discourse—not simply grammatical elegance.

---

# Input Contract (from ADR-0010)

This stage receives its input from Light Normalization and may rely on the following guarantees already having been established:

- The transcript is clean, whitespace-normalized, and free of obvious machine artifacts.
- Paragraph order matches the original discourse (never reordered).
- Scripture, Sanskrit, and transliterated spans are preserved byte-for-byte and — per ADR-0010 — may be identifiable as marked/flagged spans if source-side marking was implemented.
- Any spans Light Normalization was uncertain about are flagged, not silently resolved.

The Documentary Script Enhancer must not assume additional guarantees beyond these, and must not re-do normalization work (e.g. it should not need to fix whitespace or duplicated punctuation — if it encounters such issues, that's a signal of an upstream defect, not something to silently patch here).

---

# Objective

Transform a discourse transcript into a cinematic YouTube documentary script that maximizes viewer retention while preserving the original philosophy, emotional intent and speaker's authentic voice.

The enhancer should think like

- a documentary writer
- a storyteller
- a narrative editor
- a viewer-retention specialist

It should NOT think like

- a grammar checker
- a copy editor
- a summarizer
- a generic AI rewriter

---

# Enhancement Philosophy

The enhancer exists to amplify the teacher's voice.

It must never replace it.

The audience should feel they are listening to the original speaker—not Claude.

The philosophy must remain identical.

Only the presentation becomes more cinematic.

---

# Documentary Identity

Every documentary should feel like one continuous conversation rather than a collection of chapters.

Transitions should feel invisible. The viewer should never feel "now we're in Chapter 4."

The narrative should flow naturally from one idea to the next, carried by curiosity and emotional momentum rather than by visible structural markers. Chapter or section boundaries (if used elsewhere in the pipeline, e.g. by the Scene Planner) are an organizational convenience for production — they should not be perceptible to the viewer as breaks in the narration itself.

---

# Priority Order

The enhancer should optimize in the following order.

1. Preserve meaning
2. Preserve philosophy
3. Preserve speaker intent
4. Preserve stories and analogies
5. Increase viewer retention
6. Improve storytelling
7. Improve cinematic narration
8. Improve English

Language quality is intentionally the lowest priority.

A beautifully written script with poor retention is considered a failure.

**If retention and philosophical fidelity ever conflict, fidelity always wins — no exceptions.** A story, analogy, or pacing choice that increases retention but alters, softens, or reframes the underlying philosophy must be rejected, not "improved." This is not a matter of degree within the ranking above — it is an absolute constraint on every rule that follows.

---

# Scripture Protection (Hard Constraint)

This is a hard constraint that overrides every other rule in this document, including retention and pacing goals.

- Any span identified as scripture, Sanskrit, or a direct quotation (whether marked upstream by Light Normalization or otherwise recognizable as such) **must be reproduced exactly as received** — no rephrasing, no compression, no re-ordering, no modernizing, no splitting for pacing effect.
- The enhancer may change how a scriptural passage is *introduced* or *framed* (the surrounding narration), but never the passage itself.
- If the enhancer is uncertain whether a span qualifies as protected scripture, it must default to treating it as protected. This mirrors the default-to-preserve rule established for ambiguous spans in ADR-0010.
- This constraint applies independently of Pass 1 / Pass 2 below — it is not something Pass 2 is permitted to relax in service of retention.

---

# Fabrication Guardrail

Rules 1 and 2 below encourage the enhancer to introduce stories, analogies, historical examples, and relatable situations to break up exposition. This creates a real risk: an LLM asked to supply a "historical example" can invent specific people, dates, or events that sound plausible but aren't real — a well-known failure mode, not a hypothetical one.

The enhancer must follow this constraint for any illustrative material it introduces beyond what's in the original discourse:

- **Drawn from the source.** If the original discourse already contains the story, analogy, or example, use that — this is always preferred and carries no fabrication risk.
- **Generic or clearly hypothetical.** If the enhancer introduces new illustrative material not present in the source, it must be generic or explicitly framed as illustrative ("imagine someone who...", "consider a person who...") rather than presented as a specific real, verifiable historical event, figure, or date.
- **Never presented as verified fact.** The enhancer must not state a specific historical claim (a named person, a dated event, a specific place and outcome) as fact unless that claim was present in the original discourse. This applies equally to Rule 7's memorable lines — a memorable line may be invented as phrasing, but must not assert a fabricated fact.

---

# Two-Pass Enhancement

The enhancer should internally operate in two distinct passes. This two-pass structure is a required behavioral guarantee — a fidelity gate must exist before retention optimization runs — but the internal mechanics of each pass (single call, multiple calls, chain-of-thought, etc.) are an implementation choice, not specified here.

---

## Pass 1 — Faithful Enhancement

Goals

- Preserve philosophy exactly.
- Preserve emotional intent.
- Preserve stories.
- Preserve analogies.
- Preserve historical references.
- Preserve humor.
- Preserve speaker personality.
- Improve clarity.
- Improve flow.

This pass should never optimize for engagement at the cost of fidelity.

Pass 1 output must satisfy the fidelity validation criteria (see Validation Criteria below) before Pass 2 is allowed to run against it.

---

## Pass 2 — Viewer Retention Optimization

After the script faithfully represents the original discourse,

optimize it for long-form YouTube viewing.

Goals

- stronger hook
- better transitions
- improved storytelling
- increased curiosity
- emotional pacing
- cinematic narration
- memorable reflections

Pass 2 must not violate Scripture Protection or the Fabrication Guardrail, even in service of these goals.

---

# Viewer Retention Rules

## Rule 1

Prefer stories over abstract philosophy.

Whenever an idea can be communicated through

- story
- analogy
- historical example
- relatable life situation

prefer that over direct exposition.

People remember stories.

Not lectures.

New illustrative material introduced under this rule is subject to the Fabrication Guardrail above.

---

## Rule 2

Avoid long uninterrupted philosophical exposition.

If a section contains continuous explanation for too long,

introduce variation.

Possible variations

- story
- analogy
- question
- practical example
- historical event
- emotional reflection

Alternate naturally.

Never feel repetitive.

---

## Rule 3

Preserve cinematic pacing.

Do NOT merge every short sentence into long paragraphs.

Intentional pauses should remain.

Example

Instead of

Life changes constantly and suffering follows.

Prefer

Life changes.

Everything changes.

And because everything changes...

suffering follows.

The script should feel written for narration,

not reading.

---

## Rule 4

Delay branding.

Never interrupt the opening hook.

Do NOT introduce

- channel name
- subscribe request
- greetings

before the audience is emotionally engaged.

Branding belongs naturally after the opening hook or near the conclusion.

---

## Rule 5

Maintain curiosity.

Whenever possible

raise a question

delay the answer

reward the audience later.

The enhancer should continuously create reasons for the viewer to continue watching.

---

## Rule 6

End chapters with momentum.

Avoid complete conclusions.

Create transitions that naturally pull viewers into the next chapter.

Instead of

"This is why suffering exists."

Prefer

"But understanding suffering...

is only the beginning."

---

## Rule 7

Create memorable lines.

Generate concise reflections that viewers remember.

Examples

"You don't suffer because life changes.

You suffer because you wish it wouldn't."

or

"The storm was never your enemy.

Your resistance was."

These should emerge naturally from the original discourse.

Never invent philosophy. Never assert a fabricated fact (see Fabrication Guardrail).

---

## Rule 8

Reduce unnecessary repetition.

Distinguish between

- rhetorical repetition
- spoken-language repetition

Remove only repetition that weakens pacing.

Never remove repetition that increases emotional impact.

**Note on relationship to ADR-0010:** Light Normalization already preserves all repetition (it never removes anything for stylistic reasons — see ADR-0010's Ambiguity Handling). This rule governs a *different, later* decision: this stage is explicitly permitted to reduce repetition for pacing/style, which normalization is not. The two ADRs are not in conflict — normalization protects raw fidelity, this stage makes stylistic judgment calls on top of a fully-preserved input.

---

## Rule 9

Preserve speaker voice.

The script must never feel AI-generated.

It should feel like

the original teacher speaking more clearly.

---

## Rule 10

Do not rewrite for the sake of rewriting.

If a section already satisfies fidelity, retention, and pacing, leave it unchanged.

The goal is the best possible script, not the most heavily edited one. A lightly-touched section that already works is a better outcome than a rewritten section that works equally well — the rewrite adds risk (drift from the source, potential fabrication, voice inconsistency) without adding value.

---

# Narrative Density Self-Review

Before returning the final script,

the enhancer should internally evaluate the following.

---

## Story Density

Does the script introduce a meaningful story,

analogy,

historical example

or relatable situation

within the first minute?

Does every major section contain at least one narrative element?

If not,

rewrite.

---

## Narrative Variety

Alternate naturally between

- story
- reflection
- philosophy
- question
- history
- practical application

Avoid long stretches of the same presentation style.

---

## Curiosity Check

Would a viewer naturally want to hear the next section?

If not,

rewrite transitions.

---

## Quote Density

Approximately every 45–90 seconds,

the script should naturally contain a memorable reflection,

quote

or emotionally resonant statement.

These should emerge from the original teaching.

Never manufacture philosophy.

---

## Emotional Rhythm

Avoid a flat emotional experience.

Create natural waves of

- curiosity
- tension
- reflection
- calm
- inspiration

Documentaries feel alive because emotional intensity changes over time.

---

## Cinematic Breathing Room

Allow important ideas room to breathe.

Do not compress everything into paragraphs.

Maintain deliberate pauses.

---

## Audience Accessibility

Assume the audience has no prior knowledge of

- Vedanta
- Bhagavad Gita
- Hindu philosophy

Introduce spiritual ideas through universal human experience before scripture whenever practical.

Ancient wisdom should feel accessible rather than academic.

---

## Documentary Test

Ask

"If this script were narrated over cinematic visuals with music,

would it feel like a professional documentary rather than an essay?"

If the answer is no,

continue refining.

---

# Narrative Score (Self-Assessment)

Before returning the final script, the enhancer should score its own output against the Narrative Density Self-Review dimensions:

```
Narrative Score

Hook ............ _/10
Story Density ... _/10
Curiosity ....... _/10
Emotional Rhythm  _/10
Accessibility ... _/10

Overall ......... _/10
```

If Overall < 8.5, continue improving — do not return the script yet.

**This score is a self-assessment aid, not a substitute for the objective checks below.** Self-reported scores from the enhancer are useful for driving iteration and consistency, but they are not independently verifiable — a script can be confidently over-scored without the underlying quality actually improving. The Objective checks under Validation Criteria remain the binding gate; the Narrative Score is what the enhancer uses internally to decide whether it's done, not what determines whether the output is accepted downstream.

---

# Validation Criteria

The self-review above is a useful internal guide for the enhancer, but — consistent with ADR-0010 — this stage also needs checks that don't rely solely on the enhancer's own subjective judgment of its output.

## Objective checks (can be automated or mechanically verified)

- **Scripture exact-match.** Every protected span present in the input must appear byte-for-byte identical in the output. Hard failure, not a warning — same standard as ADR-0010.
- **No unattributed factual claims.** Any specific historical figure, date, or event named in the output that does not appear in the original discourse should be flagged for review before publishing (supports the Fabrication Guardrail — this doesn't have to be perfect, but a basic diff against the source transcript for proper nouns/dates not present upstream is a cheap first pass).
- **Coverage check.** Every major idea/section present in the source discourse should have a corresponding section in the output — the enhancer is optimizing presentation, not summarizing or cutting content. A significant drop in content coverage should fail the stage.
- **Pass 1 gate.** Pass 1 output must pass the scripture and coverage checks above before Pass 2 is allowed to run. This operationalizes the "fidelity gate before retention optimization" requirement.

## Subjective checks (human or reviewer judgment, retained from the original self-review)

- Story density, narrative variety, curiosity, quote density, emotional rhythm, cinematic breathing room, audience accessibility, and the documentary test remain valuable as a review guide for the enhancer and for human QA, but are not mechanically verifiable and should not be treated as blocking gates the way the objective checks above are.

---

# Internal Acceptance Checklist

The enhancer should continue refining until all of the following are true.

✓ Philosophy preserved

✓ Stories preserved

✓ Analogies preserved

✓ Emotional intent preserved

✓ Speaker voice preserved

✓ Scripture spans reproduced exactly

✓ No fabricated facts introduced

✓ Retention never overrode philosophical fidelity

✓ Narrative Score Overall ≥ 8.5

✓ No section rewritten without cause

✓ Narrative flows as one continuous conversation, not visible chapters

✓ Opening hook creates curiosity

✓ Branding delayed appropriately

✓ Story density is high

✓ Viewer curiosity maintained

✓ Emotional rhythm feels natural

✓ Memorable reflections included

✓ Cinematic pacing preserved

✓ Documentary narration feels natural

✓ Audience with no prior spiritual background can follow the message

---

# Design Principle

The Documentary Script Enhancer is not an English editor.

It is a professional documentary writer.

Its success is measured by

- viewer retention
- emotional impact
- storytelling quality
- documentary pacing
- fidelity to the original discourse

rather than grammatical perfection.

---

# Success Criteria

A human comparing

Original Transcript

↓

Enhanced Documentary Script

should conclude

"This feels like the same teacher delivering the same wisdom—but presented with the narrative quality of a premium documentary."

If instead the output merely sounds like cleaner English,

the enhancement has failed.

The enhancer should consistently produce scripts that are engaging enough to sustain long-form YouTube viewing while remaining faithful to the original discourse, and must pass the objective checks under Validation Criteria in addition to this human judgment.

---

# Implementation Deliverables

This ADR is not documentation only.

Implement the following:

- [ ] Implement the two-pass structure (Pass 1 fidelity, Pass 2 retention optimization) as a required gate, leaving internal mechanics as an implementation choice.
- [ ] Implement Scripture Protection as a hard constraint enforced across both passes.
- [ ] Implement the fidelity-over-retention constraint from Priority Order as a hard tie-breaker at the code/prompt level, not just as guidance.
- [ ] Implement the Fabrication Guardrail for any newly-introduced illustrative material.
- [ ] Implement the Narrative Score self-assessment and iteration loop (threshold 8.5), kept clearly separate from the objective validation gate.
- [ ] Implement editing-restraint behavior (Rule 10) so unchanged-quality sections aren't rewritten unnecessarily.
- [ ] Implement the objective validation checks (scripture exact-match, unattributed factual claims, coverage check, Pass 1 gate).
- [ ] Wire the input contract from ADR-0010 (consume Light Normalization's output and any flagged/marked spans without re-doing normalization).
- [ ] Add unit tests for Scripture Protection and the Fabrication Guardrail specifically, given they are hard constraints.
- [ ] Add integration tests covering the Pass 1 → Pass 2 gate.
- [ ] Update architecture documentation to reflect the enhancer's new responsibilities and its relationship to ADR-0010.
- [ ] Reuse existing pipeline abstractions where practical; avoid parallel implementations (consistent with ADR-0010's Implementation Guidelines).
