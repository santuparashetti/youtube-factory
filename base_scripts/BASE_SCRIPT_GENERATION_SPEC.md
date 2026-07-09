# BASE_SCRIPT_GENERATION_SPEC_V2

## Mission

Transform long spiritual discourses into YouTube-ready base scripts
**without changing the original discourse**.

The objective is NOT to rewrite the guru.

The objective is to preserve the guru's wisdom while presenting it with
the pacing, clarity and emotional flow of an Atma Theory documentary.

The audience should feel:

> "This is exactly what the speaker said... only more beautifully
> structured."

---

# Golden Principle

Faithfulness always wins over creativity.

Priority:

1. Preserve the soul.
2. Preserve the philosophy.
3. Preserve the reasoning path.
4. Preserve stories.
5. Preserve analogies.
6. Preserve emotional progression.
7. Remove repetition.
8. Improve transitions.
9. Improve pacing.

Never reverse this order. Every other section in this document —
including Reasoning Path Preservation and Emotional Curve below — is
subordinate to this ordering. Where a prescribed pattern in this spec
would conflict with what the source discourse actually does, priorities
1–6 win and the pattern is not imposed.

---

# Success Criteria

The finished script must sound like:

- the original guru
- speaking the same discourse
- with unnecessary repetition removed
- using cinematic pacing

It must NEVER sound like:

- a translation
- an essay
- ChatGPT
- a motivational speaker
- a documentary that replaced the guru

---

# Core Theme Extraction (Mandatory)

Before writing identify:

- Core Theme
- Supporting Teachings
- Stories
- Analogies
- Emotional Destination
- Final Realization

Everything must support the same theme.

**Multi-theme discourses:** some source material legitimately braids two
or three related ideas rather than serving a single theme. When this is
the case, identify the *primary* theme the discourse returns to most and
treat secondary themes as supporting teachings under it — do not force
an artificial single theme by dropping material that belongs to a
genuine second thread. If the discourse is truly structured as two
distinct, co-equal teachings with no primary/secondary relationship,
flag this explicitly rather than picking one arbitrarily; it may warrant
two separate base scripts instead of one.

---

# Soul Preservation

Preserve:

- philosophy
- intention
- conclusion
- emotional journey
- spiritual message
- reasoning path

Never introduce new philosophy.

Never modernize teachings.

Never reinterpret.

---

# Voice Preservation

The listener should feel the original guru is speaking.

If the guru listened to the generated script they should say:

"I said this."

not

"Someone rewrote my discourse."

---

# Reasoning Path Preservation

**This is a pattern to recognize and preserve when the source discourse
actually follows it — not a structure to impose on material that
doesn't.**

Where present, preserve the natural flow:

Question
↓
Story
↓
Analogy
↓
Reflection
↓
Realization
↓
Teaching

Every realization should naturally emerge from the previous one — when
the source builds that way.

If the guru moves directly from a story to a teaching with no explicit
analogy stage, or opens with a statement rather than a question, preserve
*that* actual path rather than inserting a missing stage to complete the
template. Manufacturing a step that wasn't in the source to fit this
pattern is itself a form of introducing new philosophy/structure, which
Golden Principle #1–3 forbids. This section describes what to look for
and protect when it's there, not a checklist every teaching must satisfy.

---

# Story Integrity

Stories are the teaching.

Never replace stories with summaries.

Preserve:

- setup
- curiosity
- conflict
- turning point
- realization
- teaching

Trim repetition around stories instead.

---

# Analogy Integrity

Analogies are visual teaching tools.

Critical analogies must remain complete.

Examples:

- Banana Peel
- Dustbin
- Village Garbage
- Birds
- Saints
- Pocket
- Train Seat
- Children Leaving Home

Do not reduce them to one sentence.

---

# Reflection Bridges

Between major teachings insert short reflective transitions.

Purpose:

- absorb previous idea
- prepare next idea

Reflection must emerge from the discourse.

Never introduce outside philosophy.

---

# Documentary Enhancement

Improve only:

- hook
- transitions
- pacing
- curiosity
- readability

Do NOT replace the guru's style.

---

# Narration Style

Match existing Atma Theory scripts.

Characteristics:

- Calm
- Reflective
- Cinematic
- Thoughtful
- Minimalistic
- Natural
- Human

Short sentences.

One idea at a time.

Lots of breathing space.

Never overload paragraphs.

---

# Hook

Create curiosity.

Reveal the teaching gradually.

Do not reveal conclusions immediately.

Never use misleading clickbait.

---

# Trimming Rules

Remove only:

- filler
- duplicate wording
- repeated explanations
- unnecessary audience interaction

Never remove:

- stories
- analogies
- philosophy
- memorable examples
- emotional transitions

---

# Repetition Threshold

Occurs twice:

Usually intentional emphasis. Keep unless nearly identical.

Occurs three or more times:

Keep strongest occurrences.

Remove the rest.

---

# Script Structure

Default:

Opening Hook

Introduction

Chapter 1...

Final Reflection

Closing

Production Notes

Chapter count is flexible.

Chapter titles are metadata only.

Never narrate them. (Enforcement of this rule is tracked explicitly in
the Validation Checklist below — see the note there on mechanical vs.
subjective checks.)

---

# Emotional Curve

A common pattern in Atma Theory discourse moves through:

Curiosity
↓
Understanding
↓
Reflection
↓
Realization
↓
Inner Peace

**This describes a frequent shape, not a mandatory ending.** Golden
Principle #1 (preserve the soul) and the requirement to preserve the
original conclusion take precedence over this curve. If the source
discourse actually ends somewhere else — a call to action, an
unresolved contemplation left deliberately open, grief work that doesn't
resolve into peace within the discourse itself — preserve that real
ending. Do not reshape the closing to land on "Inner Peace" if that
isn't where the guru actually took the listener.

---

# Scene Preservation

Every major story and analogy should naturally become a scene group.

Avoid collapsing multiple visual beats into one paragraph.

**Downstream connection:** "scene group" here means a story or analogy
should map to one coherent unit that the scene-planning stage can treat
as a single visual sequence — not that the Script Engine itself outputs
scene-boundary markers or timing. If ytfactory's scene planner expects
explicit delimiters (e.g. a marker between scene groups) rather than
inferring boundaries from paragraph structure, that expectation should
be stated in the Scene Plan stage's own spec, not assumed here. This
document's responsibility ends at keeping each story/analogy intact and
undivided in the text; boundary detection format is the consuming
stage's concern.

---

# Pause Style

Use ellipses (...)

only to mark meaningful narration pauses.

Do not overuse.

Downstream pause engine (ThoughtPauseRanges) determines pause duration
from these markers — this document only marks *where* a pause belongs,
never how long it should be.

---

# Word Count

Target:

5–10 minutes

Approx:

1300–1700 words

If preserving stories and teachings requires exceeding this target:

Preservation wins.

Never sacrifice philosophy for word count.

---

# Validation Checklist

Before finalizing, verify the following. Each item is marked by how it
should be checked — mechanically (M) means it can be verified by
comparing generated text against the source discourse in a structured
way (e.g. an automated or semi-automated ReviewPipeline-style pass);
subjectively (S) means it requires human judgment and cannot be reliably
automated. Treat (S) items as requiring an actual human read-through
before a script is considered final — do not let self-reported model
confidence stand in for this.

- (M) Core theme preserved
- (S) Soul preserved
- (M) Philosophy preserved — no statements contradicting or replacing
  source teaching
- (M) Original conclusion preserved
- (S) Reasoning path preserved
- (M) Story order preserved
- (M) Story integrity preserved — setup/conflict/turning
  point/realization/teaching all present for each retained story
- (M) Critical analogies preserved — full analogy present, not reduced
  to one sentence
- (S) Emotional curve preserved (or, per Emotional Curve section above,
  faithfully diverges to match the source's real arc)
- (M) No new philosophy introduced
- (M) No meaning changed
- (S) Sounds like original guru
- (S) Matches previous Atma Theory narration style
- (S) Scene-planner friendly
- (M) Subtitle friendly (line length / pacing constraints met)
- (M) Chapter headings do not appear anywhere in narrated text
- (M) Production ready — all Production Notes formatting rules followed

---

# Definition of Success

The finished script should feel like:

"The original discourse... carefully polished for modern YouTube...
without losing a single drop of its wisdom."

That is the standard every future Base Script must achieve.
