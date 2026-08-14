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
        "Return ONLY the edited script — no preamble, no explanation, no beat labels, "
        "no JSON. The output is the complete narration script, ready for voice recording."
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
        "If the reviewer requested a structural change, broader revision is allowed.\n\n"
        "Return ONLY the corrected script — no preamble, no explanation."
    )
