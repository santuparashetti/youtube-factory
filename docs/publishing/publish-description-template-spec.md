# Publish Stage: Description File Template Spec

**Purpose:** Defines the fixed structure the publish stage must follow when generating a YouTube description file for every video. Content varies per video; section order and rules do not.

**Scope:** Applies to all videos in the current 7–10 minute format. Chapters are intentionally excluded from this template — see "No Chapters" below.

---

# Pre-Generation Step: Search Intent Review

Before generating the description, the publish stage should check the drafted content against a small set of realistic search queries derived from the video's actual topic. For example, for a video on suffering and acceptance:

- "How to stop suffering" — would this description clearly speak to that?
- "Bhagavad Gita suffering" — would this description clearly speak to that?
- "How to accept change" — would this description clearly speak to that?

The specific queries vary per video (generate them from the video's actual central theme — do not use a fixed query list across videos). If the drafted description doesn't clearly answer the queries a real searcher for this topic would use, revise before finalizing. This aligns the description with real user search intent rather than a generic summary of the script.

---

# Section Order (Fixed)

1. Title (reference only — not part of description body)
2. Hook (1–2 sentences)
3. Who This Video Is For (short list)
4. What You'll Discover (bullet list — topics)
5. Key Teachings (bullet list — takeaways)
6. Questions Answered (Q&A block)
7. What You'll Experience (short prose)
8. This Video Explains (short prose)
9. Sources (short list)
10. Engagement prompt (1 line)
11. Hashtags (single line, capped)
12. Links block (channel/playlist/subscribe — populated from config, not generated per video)

Every description file follows this order. No section is optional except Sources (omit if the video doesn't reference specific external teachings/texts beyond general philosophy) and the Links block (may be empty if no links exist yet for a given channel).

---

# Section-by-Section Rules

## 1. Title
Reference only — pulled from the video's actual title metadata, not regenerated here. Not duplicated into the description body beyond what naturally appears in the Hook.

## 2. Hook
- 1–2 sentences, must front-load the core question or promise of the video.
- Target: the hook alone should read coherently within the first ~150 characters, since that's what displays before "Show More" on both mobile and YouTube search. Everything after that point is secondary.
- Must be specific to the video's actual content — never generic across videos ("ancient wisdom awaits" is not acceptable; the hook must reference the actual question/teaching the video addresses).
- No emoji in the hook itself.

## 3. Who This Video Is For
- 3–5 short lines, framed as relatable states or struggles the video speaks to (e.g. "wondered why life feels unfair").
- Must be grounded in the video's actual content and emotional territory — not a generic anxiety/struggle list reused across videos. If the video is about a specific teaching, this section should reflect what that teaching actually addresses.
- Purpose: emotional connection before the informational sections below.

## 4. What You'll Discover
- 5–9 bullet points (✔ prefix), each a short phrase, not a full sentence.
- These are *topics covered* — what the video is about.
- Must reflect content actually present in the video — generated from the enhanced script, not from a generic template of spiritual topics.
- No duplication with Key Teachings (below) or Questions Answered (below).

## 5. Key Teachings
- 3–6 bullet points (✔ prefix), each a short, quotable, declarative statement (e.g. "Pain is inevitable. Suffering is optional.").
- These are *takeaways/conclusions* — distinct from What You'll Discover, which lists topics, not conclusions.
- Hard constraint: every teaching listed here must be traceable to something actually stated or clearly implied in the video's final script. Do not synthesize a punchy-sounding maxim that isn't actually in the content — this is the same fabrication guardrail used in ADR-0011's Documentary Script Enhancer, applied here to description generation.

## 6. Questions Answered
- 8–13 questions, phrased as natural search queries a viewer might type ("What is Moksha?" not "Understanding the concept of Moksha") — the kind of phrasing that shows up in "People Also Ask"-style search results.
- This is the highest-value section for search/AI-citation matching — keep it in Q&A form, not prose.
- Must be grounded in content the video actually covers.

## 7. What You'll Experience
- 2–4 sentences of prose, not bullets.
- Describes the emotional/experiential quality of the video (tone, journey, perspective shift) — not a repeat of the topic list above.

## 8. This Video Explains
- 2–4 sentences of prose, not bullets.
- Summarizes the substantive content in flowing text rather than a list.
- Combined with section 7, target roughly 100–180 words of prose across the two sections. This is intentionally tighter than a pure-SEO-indexing target (some guidance suggests 200–300 words for indexable depth) — the tradeoff here favors skimmability, on the reasoning that YouTube already indexes the full transcript separately, so the description's job is more about viewer readability and search-intent matching than raw word count.

## 9. Sources
- 2–4 short lines listing what the video is actually drawing from (e.g. "Bhagavad Gita Chapter 2," a named teacher or text referenced in the discourse).
- Hard constraint: only include sources genuinely referenced in the video — do not pad with generic "Vedanta teachings" if the video doesn't specifically draw on named texts. Omit this section entirely if there's nothing specific to cite.
- Purpose: builds trust/credibility signal without reading as academic.

## 10. Engagement Prompt
- Exactly one line.
- Must ask a specific, experience-based question tied to the video's content — never a yes/no question. ("What teaching stayed with you after watching?" not "Did you like this?")
- Purpose: invite comments, which are a ranking signal. Experience questions generate more substantive replies than yes/no ones.

## 11. Hashtags
- Single line, 5–8 hashtags maximum.
- No duplication of a separate "Keywords" or "Tags" block — this replaces both. Do not generate a second, longer keyword list elsewhere in the description; that pattern reads as keyword stuffing under current guidance.
- Hashtags should be the most specific and relevant terms for the video, not a maximal list of every tangentially related term.
- YouTube's separate metadata "tags" field (not the visible description) can still carry a broader term list if useful — that's a different field from this hashtag line and isn't governed by this cap.

## 12. Links Block
- Order: Subscribe → Watch Next → Playlist → Newsletter (once it exists) → Socials (once they exist).
- Subscribe goes first, not last — most templates bury it at the bottom; putting it first gives it more consistent visibility.
- Populated from channel configuration, not generated per video.
- Target 3–7 links total when available; do not fabricate links that don't exist yet — omit rows for links that don't exist rather than placeholding them.

---

# No Chapters

Chapter timestamps are intentionally excluded from this template for videos in the 7–10 minute range, for two reasons:

1. Below ~10 minutes, chapter markers add limited navigational value relative to their cost (exposing structure in the description).
2. Per ADR-0011's Documentary Identity principle, these scripts are written to feel like one continuous narrative rather than a segmented structure — a visible chapter list in the description works against that intent by surfacing the segmentation the narration is deliberately avoiding.

If a video's length or format changes materially (e.g. a multi-part series, or videos routinely exceeding ~15 minutes), this exclusion should be revisited — chapters become more valuable as duration increases.

---

# Generation Constraints (apply across all sections)

- **Metadata consistency.** Title, thumbnail, hook, description, questions, key teachings, and hashtags must all reinforce the same central promise of the video. Never introduce a topic into the description that isn't actually central to the video, purely to widen SEO surface area. Example: a title like "The Biggest Mistake Everyone Makes When Life Gets Hard" should not produce a hashtag/keyword spread across unrelated topics (meditation, karma, manifestation, yoga) that the video doesn't actually focus on — stay on the video's actual central theme throughout every section.
- No keyword stuffing: each topic/term should appear once, in its most natural section, not repeated across bullets, prose, questions, and hashtags redundantly.
- Every generated section must be traceable to actual content in the video's final script — do not generate generic spiritual-content boilerplate that could apply to any video in the catalog. This is the same fidelity principle as the Documentary Script Enhancer: the description should reflect what this specific video actually says. This applies with particular force to Key Teachings and Sources, both of which make specific, checkable claims about video content.
- No fabricated links, no fabricated claims of "trending" or "viral," no unverifiable superlatives.
- Output should be a single description text file, ready to paste into YouTube's description field.

---

# Open Item

This template assumes single, non-series videos. If a multi-part series is introduced later, this spec should be extended with a series-specific variant (likely reintroducing lightweight chapter/part references), rather than retrofitted onto this one.
