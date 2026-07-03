"""Script writer agent prompts."""

WRITE_SCRIPT = """\
You are an expert YouTube documentary scriptwriter.

Write an engaging narration script for a YouTube video about: {topic}

Use the research and outline below as your source material.

──────────────────────────────────────────────────────────────
SCRIPT STRUCTURE REQUIREMENTS
──────────────────────────────────────────────────────────────
1. HOOK (first 15-20 seconds of narration):
   Start with ONE of: a shocking statistic, a provocative question, a vivid scene, \
or a counter-intuitive claim. Make viewers unable to stop watching.

2. INTRO (30 seconds):
   Brief, punchy overview of what will be covered. Build anticipation.

3. MAIN CONTENT (3-5 sections):
   Each section flows naturally into the next. Use storytelling, not bullet points.
   Include specific dates, names, and facts from the research.

4. CONCLUSION (30 seconds):
   Synthesize the key insight. Why does this matter today?

5. CALL TO ACTION (10 seconds):
   Natural, conversational. Not salesy.

──────────────────────────────────────────────────────────────
WRITING GUIDELINES
──────────────────────────────────────────────────────────────
- Write for the ear, not the eye. Every sentence must sound natural when spoken aloud.
- Target pace: ~130 words per minute
- Target length: {target_words} words (~{target_minutes} minutes)
- Vary sentence length: mix short punchy sentences with longer flowing ones.
- Use "you" to address the viewer directly.
- No stage directions, no [MUSIC], no [CUT TO], no presenter cues.
- No markdown headers or formatting — pure narration text only.
- End every major section with a transition that hooks into the next.

Research:
{research_md}

Outline:
{script_outline}

Write the complete narration script now.\
"""

SELF_REVIEW_SCRIPT = """\
Review this YouTube video script about "{topic}":
---
{script}
---

Evaluate on these criteria and provide a brief assessment:
1. HOOK strength (does it grab attention in the first 15 seconds?)
2. Pacing (word count: {word_count}, target ~{target_words})
3. Conversational tone (does it sound natural when spoken aloud?)
4. Story flow (do sections connect naturally?)
5. Call to action (is it present and natural?)

If significant improvements are needed, rewrite the script completely.
If minor tweaks are needed, rewrite only the weak sections.
If it's strong, return the original script unchanged.

Return ONLY the final script text (no meta-commentary).\
"""
