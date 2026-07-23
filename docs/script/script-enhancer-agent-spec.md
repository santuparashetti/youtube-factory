# Spec: Documentary Script Enhancer Agent

**Version:** 1.0
**Pipeline node:** `script_enhancer`
**Position in flow:** `START → research_agent / script_enhancer → script_writer → human_review_script → ...`
**Consumes:** draft script (markdown, `# Title` line excluded from narration per existing convention)
**Produces:** revised script (same file format, same length class, ready for `script_writer` / `human_review_script`)
**Feeds into:** Retention & Quality Standards gate (Hook 30 / Story Flow 20 / Visuals-Editing 20 / Audio-Pacing 15 / Ending 15) — this agent should raise Hook and Story Flow scores in particular, since those are the dimensions its instructions target directly.

---

## 1. Role Definition

The agent is a script *editor*, not a script *writer*. It receives a complete draft and returns a restructured version of the same story — same philosophy, same core message, same historical claims, same analogies, same author's intent and voice. It does not introduce new arguments, new facts, or new conclusions. Its only job is to change *how* the existing material is delivered so that it plays better as spoken, visual, narrated documentary content rather than as a written essay or lecture.

This distinction should be enforced at the top of the agent's system prompt, not left implicit — it is the single most important constraint on the node, because everything downstream (`human_review_script`, `scene_planner`) assumes the story content didn't drift.

## 2. Objective Function

Optimize for, in this priority order:

1. Viewer retention (hook strength, no dead spots)
2. Emotional engagement and narrative flow
3. Curiosity — created and then paid off
4. Cinematic/visual imagery per idea
5. Spoken-delivery naturalness

Hold constant (non-negotiable, checked at self-review):

- Philosophy / core message
- Historical integrity (no invented events, no altered facts)
- Stories and analogies as given
- Author's voice

## 3. Structural Transformation Rules

These are the mechanical edits the agent applies to a draft. Each should be encoded as an explicit instruction, not left as vague "style" guidance, since that's what makes the rewrite auditable.

| Rule | What it means in practice |
|---|---|
| Story before philosophy | Reorder so each section opens with observation/scene, not abstract claim. Structure: Observation → Story → Conflict → Reflection → Insight |
| Earn every insight | Delay the conclusion until Question → Curiosity → Story → Emotion → Reflection → Realization has played out |
| One continuous journey | No section may read as a standalone unit; every section must end with a bridge line into the next topic |
| Emotional escalation | Sections should generally intensify: Personal → Nature → History → Civilization → Universal Truth → Personal Transformation → Challenge to Viewer. Flag (don't silently fix) any place this would require changing content order in a way that breaks continuity |
| One dominant visual symbol | Identify the strongest visual metaphor introduced early (grass, river, fire, mountain, seed, light, tree, etc.) and re-touch it at intervals; the ending should return to it explicitly |
| Visual-first phrasing | Replace abstract statements with an image the viewer can picture, wherever this doesn't require inventing new facts |
| Rhythm variation | Explicitly avoid repeated "Not X, not Y, but Z" constructions or other repeated syntactic patterns; alternate long cinematic sentences with short ones, statements with questions |
| Continuous curiosity | At minimum every 30–60 seconds of runtime, the script should raise or resolve a question ("what happened," "why," "what changed," "what's next," "how is this connected") |
| Reward curiosity | Every open question introduced must be resolved later in the script — no dangling hooks |
| Memorable lines | Preserve or lightly sharpen naturally-occurring quotable lines; do not manufacture new inspirational quotes not implied by the source |
| Show scale | Where examples are given, consider whether the existing material already implies an individual → family → community → history → civilization → humanity → self progression, and make that progression visible rather than flat |
| Humanize historical figures | For any historical figure already in the script, emphasize struggle/sacrifice/uncertainty/courage/transformation using only facts present in the draft — never invented specifics |
| Invisible transitions | Replace hard section breaks with bridging phrases ("This same truth appeared again...", "But centuries later...") |
| Spoken-performance check | Every rewritten sentence should be readable aloud in one breath at a natural pace; flag anything that reads well but sounds stilted spoken |
| Restraint | No motivational-speaker tone, no exaggeration, no overdramatization — calm documentary confidence throughout |

## 4. Input Contract

- Full draft script in the project's markdown convention.
- The leading `# Title` line, if present, is metadata only — excluded from narration and from this agent's rewrite target, but the agent may read it for context.
- No additional research or fact injection is authorized at this node — if the agent identifies a factual gap, it should flag it in an output note rather than fill it in.

## 5. Output Contract

- Same markdown structure/conventions as input (so it passes cleanly to `script_writer` / `human_review_script` without reformatting).
- Length should stay within a normal band of the original (the agent is restructuring, not padding or cutting the story) — flag significant length changes rather than silently producing a much longer/shorter script.
- Append a short **Editor's Notes** block (not part of narration) listing:
  - The chosen dominant visual symbol
  - Any place where a rule in Section 3 was intentionally skipped or only partially applied, and why
  - Any factual gap noticed but not filled

## 6. Self-Review Gate (run before returning output)

The agent must silently verify all of the following before returning the script; if any answer is "no," it revises before returning:

- [ ] Opening creates immediate curiosity
- [ ] Every section flows into the next with no visible seam
- [ ] Emotional intensity generally increases section over section
- [ ] One dominant visual metaphor unifies the piece and recurs
- [ ] Sentence rhythm is varied, not repetitive
- [ ] Something genuinely new lands roughly every 30–60 seconds
- [ ] Abstract ideas are shown as scenes wherever possible
- [ ] The ending reconnects to the opening image/idea
- [ ] Philosophy, historical accuracy, stories, and author's voice are all unchanged
- [ ] Overall feel is premium documentary, not lecture

This gate maps onto the existing Retention & Quality Standards scoring (Hook, Story Flow, Ending) — a script that fails this internal gate should be expected to score poorly at the `quality_review` stage downstream, so treat this as a pre-check for that gate rather than a separate standard.

## 7. Explicit Non-Goals

- Do not add new philosophical claims, statistics, or historical events.
- Do not change the author's conclusions or add the agent's own opinion.
- Do not manufacture cliffhangers not supported by the material.
- Do not inflate emotional tone into motivational-speaker register.
- Do not restructure so heavily that `scene_planner` downstream would need materially different visual assets than the original draft implied — flag major visual-symbol changes in Editor's Notes rather than silently introducing them.
- Do not rewrite, paraphrase, reorder, or merge the closing, CTA, or signature blocks defined in `brand_config.yaml` (e.g. "This is Atma Theory.", the CTA line, "Clear mind. Meaningful life."). These lines are matched verbatim downstream by `scene_planner._mark_asset_scenes()` to place the brand asset card — paraphrasing them causes the trigger match to fail. Pass these blocks through unchanged, even when the rest of the section around them is rewritten. (`scene_planner` now has a fallback that appends the brand card if no match is found, but that fallback should be treated as a safety net, not a substitute for preserving these lines here.)

## 8. Open Questions for Integration (for Sangram/Hemkumar review)

- Should `script_enhancer` run before or after `research_agent` when both are needed for a given video, or is the flow strictly either/or per the diagram?
- Should the Editor's Notes block be parsed programmatically by `human_review_script`, or is it purely for human reviewers?
- Does the 85/100 quality gate need a new sub-score for "visual symbol consistency," or does it fold into existing Visuals/Editing (20 pts)?
