"""DescriptionGenerator — structured YouTube description following the template spec.

Template (fixed section order, per publish-description-template-spec.md):
  2. Hook (1–2 sentences, ≤150 chars visible before "Show More")
  3. Who This Video Is For (3–5 bullet lines)
  4. What You'll Discover (5–9 ✔ bullet phrases)
  5. Key Teachings (3–6 ✔ declarative statements — must be traceable to script)
  6. Questions Answered (8–13 natural search queries)
  7. What You'll Experience (2–4 prose sentences)
  8. This Video Explains (2–4 prose sentences)
  9. Sources (optional — only include if genuinely referenced in video)
 10. Engagement Prompt (1 experience-based question)
 11. Hashtags (5–8, single line)
 12. Links block (from config — Subscribe first; omit rows without a URL)

Pre-generation: search intent queries are generated from the topic first, then used
to validate that the description speaks to real searcher needs.
"""

from __future__ import annotations

import json
import re

from ytfactory.publish.artifacts import description_path
from ytfactory.publish.config import PublishConfig
from ytfactory.publish.models import DescriptionResult


_FALLBACK_DESCRIPTION = (
    "Watch this video to learn more about the topic.\n\n"
    "Like and subscribe for more content."
)

_DESCRIPTION_PROMPT = """\
You are a YouTube content strategist who writes descriptions aligned with real viewer search intent.

VIDEO TITLE: {title}
SCRIPT:
{script}

---

PRE-GENERATION: Search Intent Review
Before drafting, enumerate 3–5 realistic search queries a real viewer would type to find this specific video.
Every section you generate must clearly speak to those queries. Output them in "search_queries".

---

GENERATE each section below. Every section must be traceable to the script's actual content.
Do not generate generic boilerplate that could apply to any spiritual or philosophical video.

HOOK (1–2 sentences):
- Front-load the core question or promise this video specifically addresses
- Must read coherently within the first 150 characters
- No emoji

WHO THIS VIDEO IS FOR (3–5 short lines):
- Framed as relatable states or struggles this video's content actually speaks to
- E.g. "wondered why life feels unfair" — grounded in the video's emotional territory

WHAT YOU'LL DISCOVER (5–9 phrases):
- Topics covered — what the video is about
- Short phrases, not full sentences, ✔ prefix added automatically
- No duplication with Key Teachings or Questions Answered

KEY TEACHINGS (3–6 statements):
- Short, quotable, declarative takeaways (e.g. "Pain is inevitable. Suffering is optional.")
- These are conclusions, not topics
- Hard constraint: every statement must be traceable to something actually in the script
- Do not invent a punchy maxim absent from the content

QUESTIONS ANSWERED (8–13 questions):
- Phrased as natural search queries ("What is Moksha?" not "Understanding the concept of Moksha")
- The kind of phrasing that appears in "People Also Ask" results
- Must be grounded in content the video actually covers

WHAT YOU'LL EXPERIENCE (2–4 prose sentences):
- Emotional/experiential quality of the video — tone, journey, perspective shift
- Not a repeat of the topic list

THIS VIDEO EXPLAINS (2–4 prose sentences):
- Summarizes the substantive content in flowing text
- Combined with What You'll Experience, target ~100–180 words of prose

SOURCES (2–4 lines, or empty list [] if nothing specific):
- Only include sources genuinely referenced in the video
- Examples: "Bhagavad Gita Chapter 2", a named teacher or text from the discourse
- Omit entirely (empty list) if nothing specific is cited

ENGAGEMENT PROMPT (exactly 1 line):
- An experience-based question tied to this video's content — never yes/no
- Invites substantive comments ("What teaching stayed with you after watching?")

HASHTAGS (5–8 with # prefix):
- Most specific and relevant terms for this video
- Each topic appears once only — no keyword stuffing

GENERATION CONSTRAINTS:
- Title, hook, key teachings, and hashtags must all reinforce the same central promise
- No fabricated links, no "trending"/"viral" claims
- No chapters — this template excludes chapter timestamps by design
- No keyword stuffing across sections

Return ONLY valid JSON with no markdown fences or explanation:
{{
  "search_queries": ["...", "...", "..."],
  "hook": "...",
  "who_this_is_for": ["...", "...", "..."],
  "what_you_discover": ["...", "...", "..."],
  "key_teachings": ["...", "...", "..."],
  "questions_answered": ["...", "...", "..."],
  "what_you_experience": "...",
  "this_video_explains": "...",
  "sources": [],
  "engagement_prompt": "...",
  "hashtags": ["#...", "..."]
}}
"""

_SECTION_KEYS = (
    "hook",
    "who_this_is_for",
    "what_you_discover",
    "key_teachings",
    "questions_answered",
    "what_you_experience",
    "this_video_explains",
    "sources",
    "engagement_prompt",
    "hashtags",
)


def _parse_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {}


def _build_links_block(config: PublishConfig) -> str:
    lines = []
    if config.subscribe_url:
        lines.append(f"▶ Subscribe: {config.subscribe_url}")
    if config.watch_next_url:
        lines.append(f"▶ Watch next: {config.watch_next_url}")
    if config.playlist_url:
        lines.append(f"▶ Playlist: {config.playlist_url}")
    if config.newsletter_url:
        lines.append(f"▶ Newsletter: {config.newsletter_url}")
    for url in (config.socials_urls or []):
        if url.strip():
            lines.append(f"▶ {url.strip()}")
    return "\n".join(lines)


def _assemble(data: dict, links_block: str, config: PublishConfig) -> str:
    parts: list[str] = []

    # 2. Hook
    hook = data.get("hook", "").strip()
    if hook:
        parts.append(hook)

    # 3. Who This Video Is For
    who = [str(w).strip() for w in data.get("who_this_is_for", []) if str(w).strip()]
    if who:
        body = "\n".join(f"• {w}" for w in who)
        parts.append(f"This video is for you if you've ever:\n{body}")

    # 4. What You'll Discover
    discover = [str(d).strip() for d in data.get("what_you_discover", []) if str(d).strip()]
    if discover:
        body = "\n".join(f"✔ {d}" for d in discover)
        parts.append(f"✔ What You'll Discover:\n{body}")

    # 5. Key Teachings
    teachings = [str(t).strip() for t in data.get("key_teachings", []) if str(t).strip()]
    if teachings:
        body = "\n".join(f"✔ {t}" for t in teachings)
        parts.append(f"✔ Key Teachings:\n{body}")

    # 6. Questions Answered
    questions = [str(q).strip() for q in data.get("questions_answered", []) if str(q).strip()]
    if questions:
        body = "\n".join(f"• {q}" for q in questions)
        parts.append(f"Questions Answered in This Video:\n{body}")

    # 7. What You'll Experience
    experience = data.get("what_you_experience", "").strip()
    if experience:
        parts.append(f"What You'll Experience:\n{experience}")

    # 8. This Video Explains
    explains = data.get("this_video_explains", "").strip()
    if explains:
        parts.append(f"This Video Explains:\n{explains}")

    # 9. Sources (optional)
    sources = [str(s).strip() for s in data.get("sources", []) if str(s).strip()]
    if sources:
        body = "\n".join(f"• {s}" for s in sources)
        parts.append(f"Sources:\n{body}")

    # 10. Engagement Prompt
    engagement = data.get("engagement_prompt", "").strip()
    if engagement:
        parts.append(engagement)

    # 11. Hashtags (capped per spec)
    raw_hashtags = [str(h).strip() for h in data.get("hashtags", []) if str(h).strip()]
    hashtags = raw_hashtags[: config.description_max_hashtags]
    if hashtags:
        parts.append(" ".join(hashtags))

    # 12. Links block (from config — omit if empty)
    if links_block.strip():
        parts.append(links_block)

    return "\n\n".join(parts)


def _sections_present(data: dict) -> list[str]:
    present = []
    for key in _SECTION_KEYS:
        val = data.get(key)
        if val and (
            (isinstance(val, str) and val.strip())
            or (isinstance(val, list) and any(str(v).strip() for v in val))
        ):
            present.append(key)
    return present


class DescriptionGenerator:
    def __init__(self, llm, config: PublishConfig | None = None):
        self._llm = llm
        self._config = config or PublishConfig()

    def generate(
        self,
        project_id: str,
        project_title: str,
        script: str = "",
        # Legacy parameters absorbed silently for backward compatibility
        script_excerpt: str = "",
        chapters_block: str = "",
        seo_keywords: list[str] | None = None,
    ) -> DescriptionResult:
        """Generate a structured description following the template spec.

        Args:
            project_id: Used to write description.md.
            project_title: Video title (used in prompt).
            script: Full enhanced script text — the primary input.
            script_excerpt: Ignored (legacy; absorbed for caller compat).
            chapters_block: Ignored (spec: no chapters for 7–10 min videos).
            seo_keywords: Ignored (description derives keywords from script directly).
        """
        # Use `script` if provided; fall back to script_excerpt for old callers
        effective_script = script or script_excerpt
        prompt = _DESCRIPTION_PROMPT.format(
            title=project_title,
            script=effective_script[: self._config.description_script_chars],
        )
        response = self._llm.generate(prompt)
        data = _parse_json(response.text)

        links_block = _build_links_block(self._config)
        full_text = _assemble(data, links_block, self._config)

        if not full_text.strip():
            full_text = _FALLBACK_DESCRIPTION

        full_text = full_text[: self._config.max_description_length]

        result = DescriptionResult(
            full_text=full_text,
            word_count=len(full_text.split()),
            has_chapters=False,  # spec: no chapters for 7–10 min format
            has_cta=any(
                cta in full_text.lower()
                for cta in ("subscribe", "like", "comment", "follow")
            ),
            search_queries=data.get("search_queries", []),
            sections_present=_sections_present(data),
        )
        description_path(project_id).write_text(result.full_text, encoding="utf-8")
        return result
