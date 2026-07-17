"""Light normalization prompt — clean transcript artifacts without editing content."""

_NORMALIZATION_TEMPLATE = """\
You are a transcript formatter, not an editor.

Your ONLY job is to clean machine-level formatting artifacts from a raw discourse transcript
while leaving the speaker's words, meaning, structure, and emotion entirely unchanged.

---

WHAT YOU MAY DO (and ONLY this):

✓ Fix obvious ASR/transcription artifacts:
    — Remove an immediately repeated word with no punctuation or pause between repeats
      (e.g. "the the path" → "the path" | "is is this" → "is this")
    — Remove isolated filler tokens that carry no meaning and appear mid-sentence
      in a way that clearly disrupts grammar (e.g. "um", "uh", "er" in isolation)
      BUT: only when they appear as standalone non-intentional noise, not when they
      appear as stylistic breath marks the speaker uses deliberately.

✓ Normalize whitespace:
    — Collapse multiple blank lines to a single blank line between paragraphs.
    — Remove trailing spaces from lines.
    — Ensure consistent line endings.

✓ Fix clear transcription punctuation errors:
    — Missing period at the end of a sentence where it's unambiguous.
    — Duplicate punctuation: "..." "..." → "...".

---

WHAT YOU MUST NOT DO:

❌ Rewrite any sentence
❌ Change any word choice
❌ Improve grammar or style
❌ Merge or split paragraphs
❌ Reorder content
❌ Remove repetition for style (repetition = emphasis in discourse)
❌ Remove stories, analogies, examples, or emotional passages
❌ Summarize or condense anything
❌ Add transitions, hooks, or bridging sentences
❌ Change tone or emotional intensity
❌ Touch scripture, Sanskrit, or transliterated sacred text spans — these are marked with
   {{SCRIPTURE_N}} placeholders and must be returned EXACTLY as given

---

AMBIGUITY RULE:

When you are NOT certain whether something is a transcription error or intentional speech:

  → KEEP IT UNCHANGED. Do not remove it.

If you are genuinely uncertain about a specific span (e.g. a repetition that could be
rhetorical OR could be an ASR glitch), you MAY wrap it with [FLAG: <reason>]...[/FLAG]
to signal it for human review. Do NOT resolve it yourself.

Only use [FLAG:...] when you truly cannot tell — do not flag everything, and do not
over-flag minor variation. When in doubt about whether to flag: leave it unflagged and
unchanged. A flag is a signal to a reviewer, not a decision.

---

SCRIPTURE / SACRED TEXT PLACEHOLDERS:

The following placeholders represent scripture, Sanskrit, or sacred text spans extracted
before this call. Return them EXACTLY as written — character-for-character.

{scripture_placeholder_list}

Do not modify, expand, translate, or paraphrase any {{SCRIPTURE_N}} placeholder.

---

INPUT TRANSCRIPT:

{transcript}

---

OUTPUT:

Return ONLY the cleaned transcript. No explanations, no preamble, no meta-commentary.
The output will be parsed directly as the normalized transcript.
Return scripture placeholders ({{SCRIPTURE_N}}) exactly as they appear in the input.
"""


_SCRIPTURE_HINT_NONE = "(No scripture placeholders in this transcript.)"

_SCRIPTURE_HINT_LIST = """The following placeholders were extracted and must be returned verbatim:
{items}"""


def build_light_normalization_prompt(
    transcript: str,
    scripture_placeholders: dict[str, str],
) -> str:
    """Build the LLM prompt for the light normalization stage.

    Args:
        transcript: The transcript text, with scripture spans already replaced
            by {{SCRIPTURE_N}} placeholders.
        scripture_placeholders: Mapping of placeholder key (e.g. "SCRIPTURE_1")
            to the original text it replaced (for the hint list only — not re-inserted
            by the LLM; restoration is done post-call).
    """
    if scripture_placeholders:
        items = "\n".join(
            f"  {{{{SCRIPTURE_{i+1}}}}} — [sacred text, do not touch]"
            for i in range(len(scripture_placeholders))
        )
        placeholder_list = _SCRIPTURE_HINT_LIST.format(items=items)
    else:
        placeholder_list = _SCRIPTURE_HINT_NONE

    return _NORMALIZATION_TEMPLATE.format(
        scripture_placeholder_list=placeholder_list,
        transcript=transcript,
    )
