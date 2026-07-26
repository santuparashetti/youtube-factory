# Kilo Code Task: Fix root causes from retention QC review

## Context

A quality-review pass flagged five issues in a rendered video. These aren't isolated one-off mistakes — group them by pipeline stage below and fix the underlying logic, not just this one video's output.

---

## Issue 1 — Black screen at open (0:00–0:02)

**Category:** The Hook
**Symptom:** Video opens on 2s of black before the first visual appears. Reads as a loading delay/error, risks early drop-off before content starts.

**Investigate:**
- Where the first frame of the render comes from — likely `video_concatenator` or whatever assembles the final render from the scene list. Check whether the hook scene has a visual asset attached from frame 0, or whether there's a fade-in/leader gap being inserted before the first asset is ready.
- Check `scene_planner` — does the hook scene reliably get `scene_type` and an asset assigned before assembly, or is there a race/ordering issue where narration starts before the visual pipeline has resolved an asset for scene 1?
- Check for a hardcoded fade-in duration or black-frame padding in the render/concat step that was meant for transitions but is also applying to the very first scene.

**Fix:**
- Ensure the hook scene's visual asset is present and rendered starting at frame 0 — no black leader before the first scene unless a fade-in is deliberately short (e.g. ≤300ms) and stylistically intended, not a multi-second gap.
- If the delay is caused by asset generation/resolution timing rather than a fixed fade, fix the ordering so the hook asset is guaranteed ready before assembly starts, or fail loud rather than falling back to black.

**Test:**
- Render a sample video and confirm frame 0 shows visual content within the intended fade window (not blank).
- Add a regression check (even a simple assertion in the render pipeline) that the first N frames aren't pure black, to catch this class of bug going forward.

---

## Issue 2 — Disconnected transition, 'blade' analogy → 'you know this feeling' (1:00–1:10)

**Category:** Re-Hooks & Pacing
**Symptom:** Shift from abstract personification to direct audience address feels abrupt — a narrative flow gap, not a visual one.

**Investigate:**
- This is a script-level issue, not a rendering one — trace back to `script_enhancer` (`DocumentaryScriptEnhancerPipeline`, `src/ytfactory/script_enhancer/pipeline.py`). Check whether its prompts currently instruct it to bridge topic/register shifts (abstract metaphor → direct address) with a connective line, or whether it only restructures within sections without checking the seams between them.

**Fix:**
- Add explicit "invisible transitions" guidance to the Pass 1 (or whichever pass handles structure) prompt: when a section shifts from personification/metaphor to direct audience address (or any register change), require a one-line bridge (e.g. "This same feeling — ...", "You've felt this before, even if you called it something else") rather than a hard cut into the new register.
- This is the same rule already captured in the `script_enhancer` agent spec (`script-enhancer-agent-spec-v2.md`, Section 3, "Invisible transitions") — if that spec isn't wired into the live prompts yet, this is a concrete case showing why it should be.

**Test:**
- Re-run this script (or a similar one) through the enhancer and confirm a bridging line now exists between the two sections.
- Spot-check 2–3 other existing scripts for the same abstract→direct-address pattern to see if this is a recurring gap.

---

## Issue 3 — Static 'river of movement' visuals (2:05–2:24)

**Category:** Re-Hooks & Pacing / visual monotony
**Symptom:** ~19 seconds of static close-up water shots while the message is reiterated — visuals don't progress, risking attention drift on a message that's already being restated.

**Investigate:**
- Trace the visual/b-roll selection logic (Vision Model Bundle or whichever module selects/generates shots per scene). Check whether it has any concept of "movement/progression" as a selection criterion, or purely selects by thematic/keyword match to the narration (e.g. "river," "movement," "flow" → static water clips).
- Check whether there's a max-duration-per-static-shot rule anywhere; if a single visual concept spans 19s of narration, the current logic may not be splitting it into multiple varied shots.

**Fix:**
- Add a duration cap for any single static (non-progressing) shot — e.g. beyond ~6–8s of narration on one idea, require a shot change or a genuinely dynamic clip (camera movement, changing subject, time-lapse) rather than holding one static frame.
- If feasible, add a lightweight "motion" tag/score to the asset selection criteria so scenes reiterating a message across many seconds favor visually progressing footage over single static shots.

**Test:**
- Re-render this scene and confirm no single static shot spans more than the cap duration.
- Spot check other long-narration scenes for the same static-hold pattern.

---

## Issue 4 — Deserted village visual mismatch (3:30–3:40)

**Category:** B-roll & Editing
**Symptom:** Voiceover "You are not too old... not too broken... not too tired" (unbroken-spirit theme) paired with a dark, ambiguous, deserted-village shot that doesn't reinforce the message.

**Investigate:**
- This is a thematic-fit problem in asset selection, not just a technical one. Check whether the selection logic scores candidate visuals against the *emotional tone* of the narration (resilience/strength here) or only against literal keyword/topic match (which a "deserted village" might satisfy loosely via some unrelated keyword).

**Fix:**
- If there's a scoring/ranking step for candidate visuals per scene, add or strengthen an emotional-tone-match criterion (e.g. resilience/strength narration → visuals with light, human presence, forward motion — not desolate/abandoned imagery) as a tiebreaker or filter alongside literal keyword match.
- If no such scoring exists yet, flag this as a gap rather than trying to hand-patch this one scene — this is the same root cause as Issue 5.

**Test:**
- Re-run visual selection for this scene and confirm the replacement asset better matches "unbroken spirit" tone.
- Spot-check whether other resilience/strength-themed narration lines in existing scripts show a similar mismatch pattern.

---

## Issue 5 — Dark, subdued cooking scenes (4:25–4:40)

**Category:** B-roll & Editing
**Symptom:** Visually dark/subdued shots during an emotionally important beat (mother/woman cooking) risk a visual-engagement drop, especially on small or bright screens.

**Investigate:**
- Likely the same asset-selection module as Issue 4. Check whether there's any brightness/exposure check on selected assets, or whether darkness is an artifact of the source footage/generation prompt for this scene.
- If assets are AI-generated (per the Vision Model Bundle), check the generation prompt for this scene — does it bias toward moody/dark lighting by default, or was that specific to this script's tone elsewhere and leaking into scenes that shouldn't inherit it?

**Fix:**
- Add a basic brightness/exposure floor check in asset selection or generation for emotionally warm (not somber) scenes, so visually dark assets aren't selected for beats that call for warmth/intimacy rather than gravity.
- If generation prompts are shared/templated across a script's overall "mood," check that per-scene emotional tone can override the global mood setting rather than being locked to it.

**Test:**
- Regenerate/reselect this scene's visual and confirm it reads brighter/warmer while still fitting the emotional content.
- Spot-check other warmth/intimacy-coded scenes elsewhere in the catalog for the same over-darkening pattern.

---

## Cross-cutting notes for Kilo Code

Issues 3, 4, and 5 all point at the same underlying gap: **visual/b-roll selection currently optimizes for literal topical match, not for movement, emotional tone, or brightness/engagement.** Rather than patching each scene individually, it's worth checking whether a single scoring-layer addition (motion + tone + brightness as selection criteria, alongside existing keyword match) would fix all three at once. Report back whether that's a single shared module or three separate selection paths before implementing — that determines whether this is one fix or three.

Issue 2 ties directly to the `script_enhancer` spec's "invisible transitions" rule — worth confirming whether that spec is actually wired into the live prompts yet, since this is real evidence the rule isn't being applied currently.

Issue 1 is unrelated to the others (rendering/assembly, not selection) — treat as a separate fix.
