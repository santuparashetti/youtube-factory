# ADR-0012: Religion-Agnostic Presentation Policy

**Status:** Proposed
**Priority:** High
**Owner:** YouTube Factory
**Relates to:** ADR-0011 (Documentary Script Enhancer), Publish Stage Description Template Spec

---

# Background

Content is currently framed with explicit references to its source tradition — named texts (Bhagavad Gita, Upanishads, Puranas), tradition names (Vedanta, Advaita Vedanta, Hindu philosophy, Sanatan Dharma), and Sanskrit terms quoted in the original language.

For a US audience in particular, explicit religious/tradition labeling can act as a gatekeeping signal — viewers who don't identify with or are unfamiliar with the named tradition may self-select out of content before engaging with it, even when the underlying philosophy is universal and would resonate with them.

This ADR defines a policy shift: the philosophy and teaching content remain unchanged, but explicit tradition and text labels are dropped from what's presented to the audience, in favor of universal wisdom framing.

**This is a presentation change, not a content change.** The underlying teaching, philosophy, and meaning must be preserved exactly, per ADR-0011's existing fidelity rules. What changes is how the source is attributed and labeled — not what is taught.

---

# Goals

- Reduce viewer drop-off caused by explicit religious/tradition labeling in titles, descriptions, and narration.
- Increase accessibility for audiences unfamiliar with or unaffiliated with the source tradition, particularly a US audience.
- Preserve 100% of the original philosophy and teaching content — this policy changes attribution, never substance.
- Maintain historical honesty — attribution to a named teacher must reflect what the source discourse actually says; nothing is presented as more or less certain than the source supports.
- Never fabricate attribution — no inventing a different historical figure, tradition, or text to fill the gap left by a dropped label (this extends ADR-0011's Fabrication Guardrail to attribution specifically, not just factual claims like dates and events).

These goals are what future changes to this policy should be checked against — a proposed change that improves reach at the cost of philosophical fidelity, historical honesty, or introduces fabricated attribution should be rejected even if it appears to serve the first two goals.

---

# What Gets Dropped

- **Tradition/religion names**: Vedanta, Advaita Vedanta, Hindu philosophy, Sanatan Dharma, or any other explicit naming of the religious/philosophical tradition the content draws from.
- **Named texts**: Bhagavad Gita, Upanishads, Puranas, or any other specific scripture/text named by title, including chapter/verse citations (e.g. "Gita Chapter 2").
- **Untranslated Sanskrit terms presented as Sanskrit.** If a Sanskrit phrase would otherwise be quoted (e.g. "Dukheshu Anudvigna Manah"), it should instead be translated and presented purely as the teaching's meaning in English, without labeling the phrase as Sanskrit or attributing it to a named source.

# What Stays

- **The philosophy and teaching itself, exactly as it is.** Dropping the tradition label must never alter, soften, simplify, or reframe what is actually being taught. This is the same fidelity standard ADR-0011 already requires — only the attribution layer changes, not the substance.
- **Named ancient teachers/wisdom figures across any tradition** (e.g. Adi Shankaracharya, Buddha, Rumi, or teachers from any other religious or philosophical lineage), presented as historical wisdom figures rather than as representatives of a named religious tradition. A teacher's name functions here the way citing Marcus Aurelius does in other content — it signals "this comes from someone real, long ago, who thought deeply about this" without requiring the viewer to identify with a specific religious label. This rule is not specific to the current source material's tradition — it applies equally if content ever draws on a named teacher/guru/leader from any other religion or philosophy.
- **Universal framing devices already established in ADR-0011**: "the sages," "the ancient teachers," "ancient wisdom" — these remain fully usable since they don't name a specific tradition.
- **Story/analogy material** (the thorn, the rain, the insult scenario, etc.) — none of this required tradition labeling in the first place and should be unaffected by this policy.

---

# Interaction with ADR-0011's Scripture Protection

ADR-0011 established a hard constraint: any span identified as scripture, Sanskrit, or direct quotation must be reproduced exactly, byte-for-byte, whenever it's included in the output. That constraint governs *fidelity when scripture is included* — it does not require that scripture be included, named, or quoted in its original language in the first place.

Under this policy:

- If a teaching originates from scripture, the enhancer should translate and integrate the *meaning* into the narration without naming the source text or quoting it in the original language.
- The Scripture Protection hard constraint from ADR-0011 still applies fully to Light Normalization's handling of the input transcript — the source-language text is still preserved and protected upstream. This policy only affects what the Documentary Script Enhancer surfaces in the final output, not how the raw discourse is handled internally.
- If, for any reason, an untranslated scriptural quotation is deemed necessary for a specific video (e.g. its cadence/power doesn't survive translation), that's a deliberate exception to raise for review — not a default the enhancer should reach for.

---

# Script Generation Rules (Documentary Script Enhancer — Narration Body)

- Never speak the name of a specific religious tradition or named text in the narration.
- Never quote Sanskrit or other source-language terms as such — translate the idea into plain English.
- Named ancient teachers may be referenced by name and treated as historical wisdom figures, not as representatives of a named tradition.
- If the original discourse names a specific text or tradition as part of making its point (e.g. "as the Gita teaches..."), rewrite the attribution to a generic wisdom framing ("as one ancient teaching puts it...") while preserving the actual content of what follows.
- This rule sits alongside ADR-0011's existing Fabrication Guardrail: generalizing an attribution is not the same as fabricating one. "An ancient teaching says..." is a safe generic framing; inventing a specific alternate source ("a Greek philosopher once said...") to replace a dropped Sanskrit citation would be fabrication and is not permitted.

---

# Preferred Vocabulary

The rules above define what to avoid. This section gives the enhancer positive replacement language, so genericizing an attribution doesn't produce awkward workarounds or inconsistent phrasing across scripts.

Preferred phrases for generic attribution:

- "Ancient wisdom"
- "Ancient teachers"
- "Timeless insight" / "a timeless principle"
- "One ancient teaching..."
- "Wise people throughout history observed..."
- "The sages understood..."
- "Across generations, people have discovered..."

These replace tradition/text names directly — e.g. "as the Gita teaches" becomes "as one ancient teaching puts it," not a hedge or a clunky circumlocution. The rewritten line should read as naturally as the original, not as a visibly-edited-around version of it.

---

# Source Attribution Ladder

To keep attribution behavior predictable across scripts, the enhancer should choose attribution in this order:

1. **Named historical teacher, when the source material actually provides one** — e.g. "Adi Shankaracharya taught..." This tier requires an actual named figure present in the source discourse. It is not license to substitute a different tradition's figure (do not swap in "Plato" or "Marcus Aurelius" as stand-ins for what a Vedic source actually attributes to Adi Shankaracharya) — that would be fabrication under ADR-0011's Fabrication Guardrail, not genericization. Examples like "Plato observed..." or "Marcus Aurelius wrote..." illustrate the *pattern* of this tier — a real, named figure attributed to an idea they actually taught — they are not substitute names to reach for when the actual source names someone else.
2. **Generic ancient attribution, when no specific named teacher is available or the individual reference isn't needed** — "One ancient teaching says...", "The sages believed..."
3. **No attribution at all** — present the idea naturally as narration, when neither a named figure nor a generic attribution adds anything to the moment.

Prefer tier 1 when the source material actually supports it (usually the case here, given Adi Shankaracharya is the named teacher throughout the discourse), falling back to tier 2 for teachings attributed more diffusely to "the tradition" rather than the named teacher specifically, and tier 3 for narration beats that don't need attribution at all.

---

# Script Title Heading Should Not Be Narrated

The script file produced by the Documentary Script Enhancer currently opens with a title heading (e.g. `# WHEN SUFFERING KNOCKS, DON'T OPEN THE DOOR WITHIN`). This heading should **not** be treated as spoken narration content or rendered as an on-screen subtitle line — it's a structural/reference label for the script file, the same way a document title isn't read aloud as the document's first sentence.

This is a pipeline correctness fix, not strictly a religion-agnostic content rule, but it's recorded here because it surfaced during this policy discussion:

- The TTS/narration stage and the subtitle-generation stage should both skip the leading H1 heading when consuming `script.md` / `script_pass1.md` — narration should begin at the actual opening line ("Here's a question that stops most people cold...") not at the title.
- The heading remains useful as a human-readable label for the script file and as a candidate source for the video's actual YouTube title, but that's a separate, deliberate hand-off to the publish stage — not something that should be spoken or subtitled as part of the video itself.
- Wherever this heading does get used downstream (e.g. as a candidate for the YouTube metadata title), it is still subject to the religion-agnostic rules under Publish Stage Rules below — that requirement doesn't go away, it just applies to the metadata use case rather than to spoken narration.

---

# Publish Stage Rules (Description Template Spec)

This policy also affects the description template spec defined for the publish stage — this is the YouTube-facing title/description metadata, separate from the in-script title/subtitle covered above, but governed by the same underlying rules:

- **Title (YouTube metadata)**: should not include explicit tradition/text names going forward (e.g. "Advaita Vedanta," "Bhagavad Gita") for new videos under this policy.
- **Sources section**: the "Sources" section defined in the publish spec (e.g. "Inspired by Bhagavad Gita Chapter 2") directly conflicts with this policy and should be either removed or genericized (e.g. "Drawing on ancient wisdom traditions") for videos produced under this policy.
- **Hashtags**: tradition/text-specific hashtags (`#AdvaitaVedanta`, `#BhagavadGita`, `#Vedanta`) should be replaced with universal equivalents (`#AncientWisdom`, `#InnerPeace`, `#Philosophy`) consistent with the Metadata Consistency constraint already in the publish spec.
- **Questions Answered / Key Teachings / What You'll Discover**: should already be largely unaffected, since these were mostly framed around universal questions (suffering, peace, acceptance) rather than tradition-specific terms — spot-check each video's generated content against this policy rather than assuming.

---

# Validation

- A simple term-list check (tradition names, named texts, Sanskrit-term detection) can flag violations across the surfaces this policy governs: the narration body, and the publish-stage title/description/hashtags. The script's title heading is out of scope for this check by default now that it's excluded from narration — it only needs checking if and when it's reused as a candidate YouTube title.
- The Source Attribution Ladder is a review heuristic, not a mechanically enforceable rule — a reviewer can spot-check whether tier 1 was used when the source clearly supported it, but this isn't something a script should hard-fail on automatically.
- This is a review-flag mechanism, not a hard block, since edge cases (a teacher's name that also happens to reference a tradition, e.g. "Shankaracharya" itself implies a lineage title) will need human judgment rather than pure pattern matching.

---

# Open Items

1. **Existing published content** — this ADR does not require retroactively editing anything already published on the channel. Note: the Adi Shankaracharya / Advaita Vedanta description discussed earlier in this conversation was an example description shared for formatting purposes, not one of this channel's own published videos — so there's no known existing content that needs a retroactive decision under this policy. If any of the channel's actual published videos do carry explicit tradition/text labels in titles or descriptions, review those separately and decide case by case, since re-titling published videos has its own SEO tradeoffs (losing search history tied to the old title) independent of this policy.
2. **Channel identity** — "Atma Theory" (Sanskrit for "self/soul theory") and taglines like "Ancient Clarity for Modern Minds" are brand-level, not per-video content, and are out of scope for this ADR. Flagging only so it's a conscious choice that brand identity is not being changed here, even though it sits adjacent to this policy's goals.
