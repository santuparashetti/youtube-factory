"""Prompt builders for the Atma Theory 7-Beat Script Refinement Pipeline.

Two modes:
  - Initial refinement: edit the base script to satisfy the 7-Beat framework.
  - Targeted refinement: fix only what the human reviewer flagged.

The editor NEVER replaces the script wholesale. It reads what is valuable,
preserves it, and improves structure/pacing/flow around it.
"""

from __future__ import annotations

from ytfactory.domain.script_revision import ScriptIdentity

# ── 7-Beat framework reference (injected into prompts) ───────────────────────
_SEVEN_BEAT_REFERENCE = """\
ATMA THEORY 7-BEAT NARRATIVE FRAMEWORK
=======================================

BEAT 1 — DISRUPT (0:00–0:30)
Create immediate emotional tension, curiosity, surprise, empathy, or a vivid
mental image. Possible openings: dramatized scenario, vivid visual, paradox,
provocative statement, emotional moment, compelling question. Do NOT force
every script to begin with "Imagine." Make the emotional hook earn its place.

BEAT 2 — CHALLENGE (0:30–0:55)
Break the viewer's existing mental model. Expose a common assumption, then
introduce a stronger alternative. Purpose: the belief shift. The pattern
"Most people believe X. But what if Y?" is useful but not mandatory.

BEAT 3 — PROVE (0:55–2:00)
Provide evidence that earns the thesis. Acceptable: verified historical
figure, documented event, credible research, philosophical teaching, clearly
labeled parable, real-world example. Every story must earn its place: it
should prove, demonstrate, or emotionally reinforce the thesis. Do not
include anecdotes merely because they are interesting.

BEAT 4 — REVEAL (2:00–2:40)
Reveal the central mental shift or "aha." The viewer should understand:
"The problem isn't simply X. The deeper issue is how I approach X."
The specific metaphor (e.g. Time Seller vs Mastery Builder) must adapt
to the topic — do NOT hard-code the same framing for every subject.

BEAT 5 — FRAME (2:40–4:10)
Give the viewer a memorable actionable framework — normally three
principles, shifts, questions, or practices. Each must be distinct,
practical, memorable, and directly connected to the thesis. Do not force
Sanskrit terminology unless genuinely relevant.

BEAT 6 — APPLY (4:10–4:40)
Bring the philosophy into everyday life with concrete situations: work,
family, relationships, digital life, money, parenting, career, creativity.
The viewer should think "This applies to my life right now." Avoid generic
motivational filler.

BEAT 7 — TRANSFORM (4:40–5:00)
Deliver the philosophical payoff. Leave the viewer with a changed
perspective or identity. A useful pattern: Stop X → Start Y. Then provide a
soft Atma Theory CTA. The CTA must not overpower the philosophical conclusion.

TARGET LENGTH: 600–750 spoken words (spoken narration only; text inside
[ ] visual/audio directions does not count toward word count).
"""

_FACTUAL_INTEGRITY_RULES = """\
FACTUAL INTEGRITY (mandatory)
- Never invent historical facts, quotations, childhood stories, achievements,
  motivations, statistics, dates, biographical details, or scientific findings.
- Do not create a quotation because it "sounds like something the person would say."
- If a claim cannot be confidently verified: omit it, soften it, clearly label
  it as legend/parable/dramatization, or flag it for human verification.
- Never turn uncertain information into confident factual narration.

ATTRIBUTION (mandatory)
Vague attribution is a form of fabrication. Apply the same standard as
specific factual claims:
- Do not present unnamed traditions, teachings, ancient wisdom, experts,
  studies, research, or historical authorities as established fact without
  sufficient source or context (e.g. "studies show...", "ancient wisdom
  teaches...", "philosophers have long known...").
- If the source is available in the research provided: attribute accurately
  and specifically ("the Bhagavad Gita, Chapter 3" not "ancient teachings").
- If no reliable source is available: rewrite the statement as observation,
  interpretation, or general narration. Do not invent the attribution.
  Acceptable rewrites:
    "Studies show X" with no source → "X seems to be true for most people"
    "Ancient wisdom teaches Y"      → "There's an idea, worth sitting with: Y"
    "Philosophers have long known Z" → "Z — and it holds up under scrutiny"
- Never fabricate sources, authorities, citations, or quotations to make a
  claim sound more credible.
"""

_VOICE_RULES = """\
ATMA THEORY VOICE
- Cinematic, grounded, intelligent, deeply human, philosophical.
- High-conviction without being preachy. Religion-agnostic.
- Accessible to modern Western/global English-speaking viewers.
- Avoid: generic motivational clichés, fake profundity, exaggerated promises,
  get-rich-quick language, unnecessary Sanskrit, excessive spiritual terminology,
  preachiness, repetitive rhetorical questions, empty inspirational language.
- Prefer: concrete imagery, precise language, meaningful contrasts, emotionally
  grounded storytelling, simple but deep philosophical ideas, memorable natural language.
"""

_EDITOR_RULES = """\
EDITOR MANDATE
You are a professional script editor, not a replacement writer.

STEP 1: Read the script fully. Identify what is already working:
- The strongest emotional moments
- The best stories and examples
- Unique insights and memorable lines
- The distinctive voice and philosophical depth
- Important factual anchors

STEP 2: Identify what needs improvement:
- Which beats of the 7-Beat framework are missing or underdeveloped
- Weak ordering or transitions
- Repetition or redundant exposition
- Generic language that can be made precise
- Beat allocation issues

STEP 3: Edit with surgical precision:
- Preserve all protected content from SCRIPT IDENTITY (listed below).
- Restructure or reorder ONLY where it serves the 7-Beat framework better.
- Improve wording only where it is clearly weak — not just to sound polished.
- Do not flatten the original into generic motivational YouTube language.
- Do not over-polish away personality.

PRESERVATION OVER REPLACEMENT — NON-NEGOTIABLE:
Distinctive source metaphors (e.g. an ant climbing Everest, a craftsman's patient work),
original philosophical concepts (e.g. Patanjali's Yoga Sutras, a named ancient teaching),
and unique framing devices are the soul of the script.
- STRENGTHEN them — give them sharper language, more resonance, better integration.
- NEVER replace a specific, original metaphor or concept with generic motivational language.
  ("Every journey begins with a single step" in place of a specific ant metaphor is a
   regression, not an improvement. A named philosophical teaching replaced by vague
   "ancient wisdom" is a loss, not a simplification.)
- A well-executed original metaphor is always stronger than a polished generic substitute.
- If a visual metaphor runs through the whole script, KEEP it running through the whole script.
  Introducing a competing metaphor (e.g. bricks and construction alongside an ant story)
  creates visual incoherence that will fail the scene-planning quality gate.

THE CORE PRINCIPLE: Preserve the soul. Improve the structure. Strengthen the impact.

Protected content may ONLY be changed or removed when it is:
- Factually incorrect
- Redundant (exact duplicate within the script)
- Contradictory to the thesis
- Clearly weak (undermines the piece)
- Incompatible with the 7-Beat framework
"""


_ENGAGEMENT_LAYER_SPEC = """\
ENGAGEMENT LAYER (integrated, not separate beats)
==================================================

These five elements are NOT additional beats. Weave them naturally around the
7-Beat framework. All engagement narration counts toward the 600–750 word limit.
Do NOT simply append CTA text. The video must still feel like a philosophical
documentary, not a collection of CTAs.

MARKER CONTRACT (mandatory):
All six structural markers must appear on their own line, immediately before
the associated content. Do not omit, rename, paraphrase, or relocate any
marker independently of its content. These markers are pipeline metadata —
downstream stages depend on them.

  [NARRATIVE_ENDING]           — immediately before the narrative resolution
  [ENGAGEMENT: value_promise]
  [ENGAGEMENT: journey_invitation]
  [ENGAGEMENT: comment_prompt]
  [ENGAGEMENT: subscribe_promise]
  [ENGAGEMENT: branding_end]

[NARRATIVE_ENDING] marks the paragraph where the story, metaphor, question,
conflict, or central narrative device is resolved or echoed. It is distinct
from all ENGAGEMENT elements. It must appear before [ENGAGEMENT: subscribe_promise]
and [ENGAGEMENT: branding_end]. A CTA, subscribe message, or end-screen
description never satisfies this marker's role.

VOICE for all engagement elements:
  Cinematic, intelligent, understated, non-salesy.
  Never use: "smash that subscribe button", "don't forget to subscribe",
  generic engagement bait, exaggerated promises, repetitive CTA language.

──────────────────────────────────────────────────────────
1. VALUE_PROMISE  (placement: after DISRUPT/CHALLENGE)
──────────────────────────────────────────────────────────
Tell the viewer what they will understand, discover, or be able to apply by
staying. Must be:
  - Specific to this video's thesis (not generic "watch until the end")
  - Truthful to the actual payoff
  - Curiosity-building
  - No subscription request
Marker: [ENGAGEMENT: value_promise] immediately before the content.
Example:
  [ENGAGEMENT: value_promise]
  By the end of this, you'll understand why your mind keeps comparing —
  and the simple shift that can finally break the cycle.

──────────────────────────────────────────────────────────
2. JOURNEY_INVITATION  (placement: mid-video, after trust/value established)
──────────────────────────────────────────────────────────
A short, standalone paragraph inviting the viewer into the recurring Atma
Theory journey. It MUST be its own dedicated paragraph — do not attach it
to an unrelated narrative scene. Wording adapts to the video's topic.
Marker: [ENGAGEMENT: journey_invitation] immediately before the content.
Example:
  [ENGAGEMENT: journey_invitation]
  Every week, one ancient idea that explains something your mind already does —
  and how to use it. Join us on this journey.

Requirements:
  - Short (2–4 sentences)
  - Understated, not aggressive marketing
  - Communicates the recurring Atma Theory promise

──────────────────────────────────────────────────────────
3. COMMENT_PROMPT  (placement: after a fully explained concept or framework)
──────────────────────────────────────────────────────────
Exactly one question tied directly to this video's content. The question must:
  - Be derived from concepts actually present in the script
  - Offer 2–3 concrete answer choices when appropriate
  - Be easy to answer
  - NOT introduce a new topic
  - NOT be generic ("Let me know what you think")
Marker: [ENGAGEMENT: comment_prompt] immediately before the content.

PLACEMENT RULE (mandatory):
Place the comment_prompt only after the concept or framework it asks about
has been fully explained. Never interrupt an explanation mid-way to ask a
reflection question — the viewer cannot reflect on something they have not
yet understood. The comment_prompt belongs at the natural end of a section,
not within it. If the script currently places it mid-explanation, move it
to after that section's conclusion.

Example:
  [ENGAGEMENT: comment_prompt]
  Which of these three do you struggle with most — chasing the outcome,
  cutting corners, or losing faith in the process? Tell me below.

──────────────────────────────────────────────────────────
4. SUBSCRIBE_PROMISE  (placement: after the main philosophical payoff)
──────────────────────────────────────────────────────────
Connect the subscription to the recurring Atma Theory value. Must:
  - Come AFTER the main payoff
  - Be understated and natural
  - Not repeat the JOURNEY_INVITATION verbatim
  - Not use generic YouTube CTA language
Marker: [ENGAGEMENT: subscribe_promise] immediately before the content.
Example:
  [ENGAGEMENT: subscribe_promise]
  If this landed for you, here's what happens next — one ancient idea like
  this, every single week. Subscribe so the next one finds you.

──────────────────────────────────────────────────────────
5. BRANDING_END  (final scene — preserve existing branding)
──────────────────────────────────────────────────────────
The final scene must remain the existing Atma Theory branding/end-card scene.
Do not redesign or replace it.
Marker: [ENGAGEMENT: branding_end] immediately before the content.

──────────────────────────────────────────────────────────
INTENDED FLOW:
DISRUPT → CHALLENGE → VALUE_PROMISE → PROVE → JOURNEY_INVITATION
→ REVEAL → FRAME → APPLY → TRANSFORM → COMMENT_PROMPT
→ SUBSCRIBE_PROMISE → BRANDING_END

Small placement adjustments are allowed when required by the actual story.
The result must feel like: story first → value → reflection → relationship.
Not: story + several inserted CTAs.
"""


_RETENTION_RULES = """\
RETENTION AND SPOKEN CLARITY (apply only where the script genuinely benefits)
==============================================================================

These are editorial checks, not mandatory additions. If the script already
handles an item well, leave it. Do not force any of these where they are
not needed.

1. OPENING MOMENTUM
   The first phrase of Beat 1's narration must be the subject, situation, or
   action itself — not a frame around it. Open mid-scene or mid-fact.
   If the opening sentence begins with any of the following, rewrite it:
     "What if I told you..."  "Imagine..."  "Have you ever wondered..."
     "Did you know..."  "In this video..."  "Today we're going to..."
     "Let me ask you something..."  or any variant that announces the topic
     before committing to a scene, a character, or a concrete fact.
   These are frames, not openings. The viewer should feel dropped into a
   situation, not invited to consider one.
   Good: "He had done it ten thousand times." / "The mountain did not move."
   Bad: "What if I told you the secret to consistency?" / "Imagine an ant..."

2. CURIOSITY LOOP
   Beat 1 must contain a specific unresolved question or contrast — something
   the viewer cannot answer yet and must stay to resolve. This is a separate
   requirement from the opening hook. The hook creates immediate tension; the
   loop creates a reason to continue watching past Beat 2.
   The VALUE_PROMISE must reference this same tension without answering it.
   "You'll understand why X keeps happening — and what actually breaks the
   pattern" is a valid VALUE_PROMISE: it names the destination without
   revealing the insight.
   "The answer is consistency" is not: it collapses the loop before the
   viewer has any reason to trust the explanation.
   Test: after reading the VALUE_PROMISE, does the viewer still have a
   meaningful open question? If not, rewrite the VALUE_PROMISE to name the
   destination without revealing the route.

3. SPOKEN REGISTER
   Read each sentence mentally as spoken aloud. If it sounds like a lecture,
   a thesis abstract, or a written essay, rewrite it in natural spoken
   language. Prefer short, direct sentences. Avoid nominalizations
   ("the utilization of" → "using"), passive constructions, and academic
   conjunctions. Replace unnecessarily formal transitions ("furthermore",
   "consequently", "it is noteworthy that") with natural spoken alternatives.
   Use concrete human language over abstract definitions.
   Do not make every sentence casual — only rewrite where the phrasing
   would feel unnatural to a listener.

4. ABRUPT TRANSITIONS
   When the narrative shifts scale (ancient India to a modern office),
   topic (philosophical concept to personal practice), or example type
   (historical story to scientific finding), add a short bridge — one
   sentence — only when the gap genuinely needs one. Do not add explanatory
   filler to transitions that already flow naturally.

5. PACING RESET
   After a genuinely dense conceptual section, consider a short pacing reset:
   a concrete image, a short question, or a brief shift in sentence rhythm
   before resuming depth. Keep it to 1–2 sentences maximum. Do not add this
   where the passage already varies its texture, and do not add filler merely
   to create a pattern interrupt.

6. VISUAL CLARITY FOR ABSTRACT NARRATION
   When narration contains 2+ consecutive abstract sentences with no concrete
   image, consider whether the existing [Visual: ...] convention can express
   the idea more concretely. Prefer useful visual contrasts, actions,
   metaphors, or transformations over generic imagery. Do not add visual
   directions merely for decoration or to satisfy a count.

7. THEME COHERENCE
   Every major section must materially support the script's central thesis.
   Apply this rule regardless of the script's topic, philosophy, or examples.

   When a secondary idea appears, apply in order:
   1. Connect — add one sentence that shows how this idea serves the central
      thesis. The connection must add meaning; restating the thesis is not
      sufficient.
   2. Condense — if the idea is useful but not central, reduce it to one or
      two sentences and move on.
   3. Remove — only when no honest connection to the thesis exists.

   A secondary idea has drifted when it:
   - Could stand alone as a different video's thesis or argument
   - Introduces a separate virtue, principle, or philosophy without linking
     it back to the central thesis
   - Develops beyond a supporting role into an independent claim

   This rule does not require removing nuance or complexity. It requires
   that every part of the script be in service of the same destination.
   Beat 3 (PROVE) and Beat 5 (FRAME) are highest-risk: do not include
   evidence or framework points that are adjacent to but not load-bearing
   for this specific thesis.

8. NARRATIVE CLOSURE — [NARRATIVE_ENDING] marker required
   The narrative ending must close the narrative established by the opening.
   Before finalizing the script, identify the primary opening device used
   in Beat 1: a vivid image, a metaphor, a question, a conflict, a promise,
   a narrative situation, or a central contrast. Before the branding/end-screen
   section, the script should echo, resolve, transform, or meaningfully return
   to that opening device.
   Mark that paragraph with [NARRATIVE_ENDING] on its own line immediately
   before the resolution text. The marker is required pipeline output — the
   downstream quality gate reads it directly. Do not place the marker on a
   CTA, subscribe message, or end-screen line.
   Rules:
   - A generic inspirational conclusion does not satisfy closure when the
     opening established a specific narrative device.
   - The callback does not need to be literal; conceptual or transformed
     returns are often stronger.
   - Do not invent an opening callback solely to satisfy this rule.
   - Keep the closure concise and natural — do not add filler to force a loop.

9. NARRATIVE ENDING vs BRANDING ENDING
   Treat these as two distinct concerns.
   NARRATIVE_ENDING: the moment where the story, metaphor, question, conflict,
   or central narrative device is resolved, echoed, or transformed. This
   belongs to the content — it is the final thing the viewer hears before
   formal engagement elements.
   BRANDING_END: the Atma Theory end-screen, subscribe graphics, related
   video prompts, and channel-level presentation. This is structural, not
   narrative, and does not satisfy narrative closure.
   Required structure:
     final narrative resolution → NARRATIVE_ENDING → CTA/subscribe (if applicable)
     → BRANDING_END
   Never allow CTA → BRANDING_END to substitute for a missing narrative ending.

10. NO OVER-EDITING
    All rules above are conditional editorial mechanisms, not mandatory
    transformations. Only apply a rule when the script genuinely benefits.
    Do not:
    - add filler sentences or phrases
    - manufacture suspense or tension
    - force callbacks or closures that feel artificial
    - force visual directions where the narration is already concrete
    - create transition bridges where the narrative already flows
    - repeat the thesis or main lesson more than once
    - add engagement elements beyond the four designated in the ENGAGEMENT LAYER
    - apply every rule mechanically, making the script formulaic
    Preserve strong writing when it already satisfies the intent.
"""


_BEAT_EVIDENCE_OUTPUT_FORMAT = """\
OUTPUT FORMAT (return these two parts in order, with nothing else):

Part 1 — the complete narration script, ready for voice recording.
No preamble, no beat labels, no explanation.

Part 2 — beat evidence, immediately following the script:
---BEAT-EVIDENCE---
{
  "DISRUPT":   {"present": true, "evidence": "exact short excerpt from the script", "reason": "brief note"},
  "CHALLENGE": {"present": true, "evidence": "...", "reason": "..."},
  "PROVE":     {"present": true, "evidence": "...", "reason": "..."},
  "REVEAL":    {"present": true, "evidence": "...", "reason": "..."},
  "FRAME":     {"present": true, "evidence": "...", "reason": "..."},
  "APPLY":     {"present": true, "evidence": "...", "reason": "..."},
  "TRANSFORM": {"present": true, "evidence": "...", "reason": "..."}
}

Evidence rules:
- "present": true only if the beat's narrative function is genuinely fulfilled.
- "evidence": a short phrase or sentence (1-2 sentences) copied verbatim from Part 1.
- "reason": a brief note (20 words or fewer) on how the evidence demonstrates the beat function.
- Do not claim a beat present merely because related keywords appear.
- Do not quote content from [ENGAGEMENT: ...] sections, CTAs, or branding lines.
"""


def _format_identity(identity: ScriptIdentity) -> str:
    lines = ["SCRIPT IDENTITY (protected — do not remove these elements):"]
    if identity.core_topic:
        lines.append(f"  Core topic: {identity.core_topic}")
    if identity.core_thesis:
        lines.append(f"  Core thesis: {identity.core_thesis}")
    if identity.emotional_promise:
        lines.append(f"  Emotional promise: {identity.emotional_promise}")
    if identity.central_conflict:
        lines.append(f"  Central conflict: {identity.central_conflict}")
    if identity.key_story:
        lines.append(f"  Key story excerpt: {identity.key_story[:200]}...")
    if identity.key_philosophical_insight:
        lines.append(
            f"  Key philosophical insight: {identity.key_philosophical_insight}"
        )
    if identity.important_factual_details:
        lines.append("  Important factual details:")
        for detail in identity.important_factual_details[:8]:
            lines.append(f"    - {detail}")
    if identity.intended_audience_takeaway:
        lines.append(
            f"  Intended takeaway: {identity.intended_audience_takeaway[:200]}"
        )
    if identity.strong_original_ideas:
        lines.append(
            "  Distinctive metaphors / original framing (STRENGTHEN, never replace with generic language):"
        )
        for idea in identity.strong_original_ideas[:5]:
            lines.append(f"    - {idea}")
    if identity.important_visual_moments:
        lines.append("  Important visual moments:")
        for visual in identity.important_visual_moments[:5]:
            lines.append(f"    - [{visual}]")
    return "\n".join(lines)


def build_7beat_system_prompt() -> str:
    """System prompt for the 7-Beat editor (initial and targeted refinement)."""
    return "\n\n".join(
        [
            _EDITOR_RULES,
            _SEVEN_BEAT_REFERENCE,
            _ENGAGEMENT_LAYER_SPEC,
            _RETENTION_RULES,
            _FACTUAL_INTEGRITY_RULES,
            _VOICE_RULES,
        ]
    )


def build_initial_refinement_prompt(
    script_text: str,
    identity: ScriptIdentity,
    beats: list[dict] | None = None,
    target_minutes: int = 5,
    source_word_count: int = 0,
) -> str:
    """User prompt for the initial 7-Beat refinement pass.

    When source_word_count is already within 600-750, a stricter ceiling is
    injected so the editor does not expand a well-sized script into overrun.
    """
    target_words = target_minutes * 130
    word_range = f"{max(600, target_words - 75)}–{min(750, target_words + 75)}"

    source_in_range = 600 <= source_word_count <= 750

    if source_in_range:
        word_count_instruction = (
            f"SOURCE IS ALREADY WITHIN RANGE ({source_word_count} spoken words).\n"
            "Target: 650–700 spoken words. HARD CEILING: 750 words.\n"
            "Do NOT expand the script. Cut or tighten where necessary to stay within 750."
        )
    else:
        word_count_instruction = (
            f"TARGET SPOKEN WORD COUNT: {word_range} words "
            "(spoken narration only, not text in [ ] brackets)"
        )

    beats_section = ""
    if beats:
        beats_lines = ["PROTECTED NARRATIVE BEATS (must survive editing):"]
        for b in beats:
            beats_lines.append(f"  {b['id']}. {b['beat']}")
        beats_section = "\n".join(beats_lines)

    identity_section = _format_identity(identity)

    return (
        f"{identity_section}\n\n"
        f"{beats_section}\n\n"
        f"{word_count_instruction}\n\n"
        "=== BASE SCRIPT TO EDIT ===\n"
        f"{script_text}\n\n"
        "=== YOUR TASK ===\n"
        "Edit the script above so it satisfies all 7 beats of the Atma Theory "
        "7-Beat Narrative Framework while preserving every protected element listed "
        "in SCRIPT IDENTITY and PROTECTED NARRATIVE BEATS above.\n\n"
        "Also weave in the five ENGAGEMENT LAYER elements described in the system "
        "prompt (VALUE_PROMISE, JOURNEY_INVITATION, COMMENT_PROMPT, SUBSCRIBE_PROMISE, "
        "BRANDING_END). Each element requires its pipeline marker on its own line "
        "immediately before the content — [ENGAGEMENT: value_promise], "
        "[ENGAGEMENT: journey_invitation], [ENGAGEMENT: comment_prompt], "
        "[ENGAGEMENT: subscribe_promise], [ENGAGEMENT: branding_end]. "
        "Place [NARRATIVE_ENDING] on its own line immediately before the paragraph "
        "that resolves or echoes the opening narrative device — before "
        "[ENGAGEMENT: subscribe_promise] and [ENGAGEMENT: branding_end]. "
        "Do not omit or rename any marker. "
        "All engagement narration counts toward the 600–750 word limit.\n\n"
        "Apply the RETENTION AND SPOKEN CLARITY checks from the system prompt "
        "wherever the script would genuinely benefit — opening momentum, curiosity "
        "loop, spoken register, abrupt transitions, pacing resets, visual clarity "
        "for sustained abstraction, theme coherence, narrative closure, and the "
        "separation of narrative ending from branding ending. Skip any check where "
        "the writing already works well.\n\n"
        "BEFORE RETURNING — silently review all seven narrative functions in order:\n"
        "DISRUPT → CHALLENGE → PROVE → REVEAL → FRAME → APPLY → TRANSFORM\n"
        "For each beat ask: (a) Is its narrative function actually fulfilled — not "
        "merely implied or keyword-present? (b) Is it sufficiently developed, or "
        "thin/generic? (c) Is any material misplaced or redundant with another beat? "
        "(d) Does it support the central thesis?\n"
        "If a beat is weak or missing, make the smallest natural repair using this "
        "priority: preserve strong material → strengthen weak material → "
        "condense or move misplaced material → add minimum content only if nothing "
        "else serves the function. Never add filler to satisfy a beat.\n"
        "APPLY specifically must transfer the core insight into a realistic viewer "
        "situation, decision, or action — not restate the thesis or add generic "
        "motivation. A beat that merely contains related keywords is not fulfilled.\n\n"
        f"{_BEAT_EVIDENCE_OUTPUT_FORMAT}"
    )


def build_targeted_refinement_prompt(
    current_refined_script: str,
    base_script: str,
    identity: ScriptIdentity,
    reviewer_feedback: str,
    beats: list[dict] | None = None,
) -> str:
    """User prompt for targeted refinement after human rejection.

    The instruction is explicit: fix ONLY what the reviewer flagged.
    Do not blindly regenerate a completely different script.
    """
    beats_section = ""
    if beats:
        beats_lines = ["PROTECTED NARRATIVE BEATS (must survive editing):"]
        for b in beats:
            beats_lines.append(f"  {b['id']}. {b['beat']}")
        beats_section = "\n".join(beats_lines) + "\n\n"

    identity_section = _format_identity(identity)

    return (
        f"{identity_section}\n\n"
        f"{beats_section}"
        "=== REVIEWER FEEDBACK (fix ONLY these specific issues) ===\n"
        f"{reviewer_feedback.strip()}\n\n"
        "=== CURRENT REFINED SCRIPT (this is your working document) ===\n"
        f"{current_refined_script}\n\n"
        "=== SOURCE / BASE SCRIPT (reference for original intent and facts) ===\n"
        f"{base_script}\n\n"
        "=== YOUR TASK ===\n"
        "Fix ONLY the issues identified in REVIEWER FEEDBACK above.\n"
        "Preserve all other content — structure, voice, stories, insights, and "
        "factual details that were NOT flagged.\n"
        "Do NOT blindly regenerate a completely different script.\n"
        "If the reviewer flagged one beat, revise that beat and any necessary "
        "transition into the next beat — leave beats 3–7 untouched unless they "
        "were explicitly flagged.\n"
        "If the reviewer requested a structural change, broader revision is allowed.\n"
        "When fixing clarity, pacing, or transitions, also consult the RETENTION "
        "AND SPOKEN CLARITY guidelines in the system prompt — but only for the "
        "sections being revised.\n"
        "After making the targeted fix, silently verify that the revised section "
        "actually fulfills its narrative function (DISRUPT/CHALLENGE/PROVE/REVEAL/"
        "FRAME/APPLY/TRANSFORM) — not merely mentions it. If it does not, strengthen "
        "it before returning. Leave all other beats untouched.\n\n"
        f"{_BEAT_EVIDENCE_OUTPUT_FORMAT}"
    )
