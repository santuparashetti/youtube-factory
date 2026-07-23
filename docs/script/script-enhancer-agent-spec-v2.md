# Spec: Documentary Script Enhancer Agent

**Version:** 2.0 (reconciled with existing implementation)
**Pipeline node:** `script_enhancer`
**Implementation:** `DocumentaryScriptEnhancerPipeline`, `src/ytfactory/script_enhancer/pipeline.py` — two-pass, mode-driven (`expand` / `shorten` / `polish`)
**Position in flow (actual, per `graph.py`):** `script_enhancer → scene_planner`
**Consumes:** draft script (markdown, `# Title` line excluded from narration per existing convention)
**Produces:** revised script (same file format), length governed by whichever `mode` is active for the run — not held to the original's length
**Feeds into:** Retention & Quality Standards gate (Hook 30 / Story Flow 20 / Visuals-Editing 20 / Audio-Pacing 15 / Ending 15) — this agent should raise Hook and Story Flow scores in particular, since those are the dimensions its instructions target directly.

---

## 1. Role Definition

The agent is a script *editor*, not a script *writer*. It receives a complete draft and returns a restructured version of the same story — same philosophy, same core message, same historical claims, same analogies, same author's intent and voice. It does not introduce new arguments, new facts, or new conclusions. Its only job is to change *how* the existing material is delivered so that it plays better as spoken, visual, narrated documentary content rather than as a written essay or lecture, and — separately, via the `mode` system — to hit the target word count for the run (`expand`/`shorten`/`polish`).

This distinction should be enforced at the top of the agent's system prompt, not left implicit — it is the single most important constraint on the node, because everything downstream (`scene_planner`) assumes the story content didn't drift.

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

These are the mechanical edits the agent applies to a draft, to be folded into the existing multi-pass prompts (Pass 1 structuring / Pass 2 scoring) rather than treated as a separate pass. Each should be encoded as an explicit instruction, not left as vague "style" guidance, since that's what makes the rewrite auditable.

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
- Active `mode` for the run (`expand` / `shorten` / `polish`) and its target word count, as already determined by the existing pipeline logic.
- No additional research or fact injection is authorized at this node — if the agent identifies a factual gap, it should flag it in an output note rather than fill it in.

## 5. Output Contract

- Same markdown structure/conventions as input (so it passes cleanly to `scene_planner` without reformatting).
- Length is governed by the existing `mode` system (`expand`/`shorten`/`polish`) targeting a specific word count for the run — this spec's structural rules apply *within* whatever length the active mode produces; they do not constrain the pipeline to a fixed length class.
- Editor's Notes: fold into the existing Pass 2 **Narrative Score** output rather than as a separate block — add fields for:
  - The chosen dominant visual symbol
  - Any place where a rule in Section 3 was intentionally skipped or only partially applied, and why
  - Any factual gap noticed but not filled

## 6. Narrative Score Criteria (Pass 2)

The following criteria should feed the existing Narrative Score, rather than exist as a separate gate. If a script scores poorly against these, Pass 2 should revise before returning:

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

This maps onto the existing Retention & Quality Standards scoring (Hook, Story Flow, Ending) — a script that scores poorly here should be expected to score poorly at the `quality_review` stage downstream, so treat this as a leading indicator for that gate rather than a separate standard.

## 7. Explicit Non-Goals

- Do not add new philosophical claims, statistics, or historical events.
- Do not change the author's conclusions or add the agent's own opinion.
- Do not manufacture cliffhangers not supported by the material.
- Do not inflate emotional tone into motivational-speaker register.
- Do not restructure so heavily that `scene_planner` downstream would need materially different visual assets than the original draft implied — flag major visual-symbol changes in the Narrative Score notes rather than silently introducing them.
- Do not rewrite, paraphrase, reorder, or merge the closing, CTA, or signature blocks defined in `brand_config.yaml` (e.g. "This is Atma Theory.", the CTA line, "Clear mind. Meaningful life."). These lines are matched verbatim downstream by `scene_planner._mark_asset_scenes()` to place the brand asset card — paraphrasing them causes the trigger match to fail. Pass these blocks through unchanged, even under `expand`/`shorten` modes and even when the rest of the section around them is rewritten. (`scene_planner` now has a fallback that appends the brand card if no match is found, but that fallback should be treated as a safety net, not a substitute for preserving these lines here.)
- Do not include the disabled channel opening line (e.g. "Welcome to Atma Theory...") anywhere in the output when `opening.enabled=false` in `brand_config.yaml`. The script enhancer pipeline strips it at the Final script stage before `script-segments.json` is written.
