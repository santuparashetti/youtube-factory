# Fix Spec: Opening-Line Leak, Missing Brand Card Scene, Weak/Jerky Motion

## Mode of work
Work autonomously end-to-end. Do NOT stream intermediate exploration, grep dumps,
diffs-in-progress, or narration to the user during execution. Investigate, fix,
test, and verify silently. The ONLY output at the end should be the structured
Final Summary defined at the bottom of this document. No partial updates.

## Context
This is a documentary-style narrated video pipeline (research → script_enhancer →
scene_planner → generate_scene_assets → video_renderer → video_concatenator → cta
→ quality_review → remediation → publish). A rendered sample was reviewed
frame-by-frame and three concrete defects were confirmed. Fix all three. None are
cosmetic — each is an acceptance-blocking defect for publish.

---

## BUG 1 — Banned opening line leaks into the video

**Observed defect:** The opening branding line ("Welcome to Atma Theory... where
ancient wisdom meets modern life", or any paraphrase of it) is NOT supposed to
appear anywhere in the video — it was intentionally disabled. In the reviewed
render it still appears, and it appears near the END of the video, merged in
with the closing lines block, instead of at the start or nowhere at all.

**Required end state:** This opening line (and any script_enhancer paraphrase of
it) must never appear in narration, subtitles, or scene text — not at the start,
not merged into the closing block, not anywhere — under any config state that
currently disables it.

### Investigation (do this before writing any fix)
1. Grep the entire repo (not just scene_planner.py) for the literal opening line
   and its fragments: "Welcome to Atma Theory", "ancient wisdom meets modern
   life". Check prompts, templates, fixtures, and any hardcoded script
   boilerplate — not just runtime logic.
2. Find the exact flag/setting that is meant to disable this line (e.g. an
   "opening line enabled" toggle in `SharedSettings`/factory config, or a
   brand-block config in `script_enhancer.py`). Confirm what value it is
   currently set to in the `.env`/config used for this render.
3. In `src/ytfactory/agents/nodes/scene_planner.py::_mark_asset_scenes()`,
   trace exactly how the "combine enabled closing/CTA/signature text into one
   narration on the last matching scene" logic (from the prior brand-asset-card
   regression fix) decides which lines count as part of that combined block.
   Confirm/deny the hypothesis: the opening line's disabled-flag is not being
   checked before it's swept into the same "brand block" collection that also
   holds the real closing/CTA/signature lines — i.e., disabling the opening
   line only stops it from being placed at the *start*, but something still
   collects it into the end-of-video merge.
4. Also check `script_enhancer.py`'s `_BRAND_BLOCK_PRESERVATION` /
   `_STRUCTURAL_TRANSFORMATION_RULES` constants — confirm whether the opening
   line is classified there as part of the "preserve brand block" category
   (which would explain why it survives paraphrasing/removal passes and
   resurfaces later).
5. Produce a one-paragraph root-cause statement before implementing the fix.
   If the investigation contradicts the hypothesis above, follow the evidence,
   not the hypothesis.

### Required fix
- The opening line must be filtered out at the EARLIEST possible stage (script
  generation / script_enhancer output), not just suppressed later at
  scene_planner or render time. Filtering it late is not acceptable — it must
  not exist in the script object at all when its setting is disabled.
- Do not rely on exact-string matching only (this is exactly what caused the
  original brand-asset-card regression — paraphrasing broke exact matches).
  Use the same semantic/category-tagging approach already used for
  closing/CTA/signature detection, but as its own explicit category
  (`opening_line` / `intro_line`), so it can never be accidentally folded into
  the `closing_block` category by `_mark_asset_scenes()`.
- Add an explicit unit test asserting that when the opening-line setting is
  disabled, no scene/narration/subtitle object anywhere in the pipeline output
  contains the opening line or a fuzzy-matched paraphrase of it (use the same
  paraphrase-tolerant check the brand-block preservation logic already uses).
- Add a regression test reproducing this exact scenario: opening line
  disabled + script_enhancer paraphrasing + closing block present → assert
  the closing block contains ONLY real closing/CTA/signature content.

---

## BUG 2 — Missing dedicated brand card scene at the end

**Observed defect:** The closing lines ("This is Atma Theory.", "If this
reflection stayed with you, consider joining us on this journey.") are shown
over regular narrative footage (a walking/silhouette shot), not over the
pre-defined brand/asset card image that exists specifically for this purpose.

**Required end state:** Every render must end on the dedicated, pre-defined
brand card asset, with the closing lines as the narration/subtitle over that
specific asset — never over a reused narrative scene.

### Investigation
1. In `scene_planner.py::_mark_asset_scenes()`, confirm both branches of the
   documented behavior: (a) combined closing narration attached to "the last
   matching scene", and (b) the fallback that "appends a new brand card scene
   if none match". Determine which branch fired for this render, using the
   actual scene list output for this run if available, or a repro script if
   not.
2. If branch (a) fired: confirm whether "last matching scene" is being matched
   against a real brand-card asset scene, or against the last ordinary
   narrative scene that merely happened to also carry closing-adjacent text.
   This is the likely root cause — the match is keying off narration content
   similarity, not off the scene's asset type/tag (e.g. `scene_type ==
   "brand_card"` or `asset_id == BRAND_CARD_ASSET_ID`).
3. If branch (b) (the fallback) should have fired but didn't: find why the
   "no match" condition wasn't detected as true.
4. Check `generate_scene_assets` / `video_renderer` to confirm there is in
   fact a distinct, addressable brand card visual asset (not just a text
   convention) that can be forced onto a scene, and get its identifier.

### Required fix
- `_mark_asset_scenes()` must guarantee the FINAL scene of every render is the
  dedicated brand card asset, with closing/CTA/signature narration attached to
  it — regardless of whether an existing scene's text happens to match
  closing/CTA/signature phrasing. Matching narrative scenes should never be
  repurposed as the brand card scene; if the brand card scene doesn't already
  exist in the scene list, it must be appended (this path already exists per
  the prior fix — make it the only path, not a fallback that can silently be
  skipped).
- Make this deterministic and testable: e.g. `assert scenes[-1].scene_type ==
  "brand_card"` and `assert scenes[-1].asset_id == BRAND_CARD_ASSET_ID` for
  every completed scene plan, as a hard invariant enforced before
  `human_review_scenes`/render, not just as pipeline behavior.
- Add a post-render automated check (in `quality_review` or the render QA
  step) that inspects the final concatenated video's last scene and fails the
  QA gate if the brand card asset was not used. This should be a real
  assertion, not a log line — wire it as an actual blocking check like the
  existing hard-constraint gates in image QA, not another flag-and-log-only
  rule like `IMG_007`/`IMG_008`.
- Add a unit test and an integration test: scene plan with closing lines
  paraphrased in an unrelated narrative scene → assert the brand card scene is
  still appended/used and the narrative scene's text is unaffected.

---

## BUG 3 — Weak, inconsistent, jerky motion

**Observed defect:** Motion across scenes is inconsistent — some scenes are
fully static for their whole duration (several exceeded 8s completely frozen,
one for over 9s), others have very subtle drift, and cuts between scenes look
jerky because there's no easing in/out — motion (where present) seems to start
and stop abruptly at scene boundaries rather than ramping smoothly. The
result does not look like professional documentary-style Ken Burns motion,
where each shot has a slow, continuous, deliberate zoom/pan that ramps up at
the start and eases down before the cut.

**Required end state:** Every non-still-frame scene gets a slow, continuous,
professional-grade zoom/pan for its full on-screen duration, with eased
acceleration/deceleration so there is no visible "snap" at cut points. No
scene should read as visually static for its full duration unless explicitly
marked as an intentional static beat (rare, e.g. a title card).

### Investigation
1. Read `MotionPlanner.plan()` in `src/video_core/cinematic/motion.py` and
   `FFmpegRenderer._vf_spatial()` end to end. Determine:
   - How `motion_type` is currently assigned per scene (static / drift /
     push-in / pull-out / zoompan), and what fraction of scenes are getting
     `static` vs a real motion type.
   - What easing function (if any) is applied to the zoompan/crop expression.
     Linear interpolation across the whole duration will look mechanical;
     confirm whether an ease-in/ease-out curve (e.g. cubic/sine easing) is
     applied, or whether it's linear/none.
   - What the actual zoom/pan magnitude and speed constants are, and whether
     they're hardcoded or config-driven.
2. Cross-reference the "VISUAL ENGAGEMENT & TONE MATCHING" section already
   added to `_VISUAL_PROMPTS_TEMPLATE` in `scene_planner.py` (from the prior
   QC fix for static visuals) — confirm whether that section actually
   constrains `MotionPlanner`'s output, or only influences the image
   generation prompt text (i.e., check it isn't a no-op with respect to
   motion assignment).
3. Confirm how `IMG_007` (static-hold >8s cap, currently flag-and-log only)
   relates to this — flagging is not fixing. Note for the summary whether
   this bug should also get IMG_007 wired to actual remediation (see below).

### Required fix
- Every scene not explicitly flagged as a static beat must be assigned a real
  `motion_type` (drift / push-in / pull-out / zoompan) with a non-trivial
  magnitude — no scene should render with zero net motion across its full
  duration.
- Zoom/pan magnitude and duration must scale with the scene's actual on-screen
  duration so slow scenes get slow, continuous movement (not a burst of motion
  followed by a static hold, and not a linear crawl that looks the same
  everywhere).
- Apply proper ease-in / ease-out timing to the motion curve (not linear) so
  each scene visually "settles" into and out of its motion — this is what
  will remove the jerk at cuts. This should be implemented as a genuine
  eased interpolation function (cubic or sine ease in/out), applied over the
  scene's full duration, not a hardcoded few-frames transition.
- Make magnitude/speed/easing-curve parameters config-driven (extend the
  existing `MotionPlanner`/render config rather than hardcoding), consistent
  with how `EscalationConfig` was made config-driven for the image pipeline —
  do not introduce new hardcoded literals.
- Wire `IMG_007` from flag-and-log into an actual blocking/remediation check:
  a scene that is fully static beyond the cap should trigger either
  re-planning with a real motion type or an explicit, deliberate
  "intentional static beat" tag — it should never silently pass through to
  final render as it does today.
- Add unit tests: (a) assert no scene (excluding explicitly tagged static
  beats) is emitted with `motion_type == "static"`; (b) assert the easing
  function output is non-linear and monotonic across the scene duration; (c)
  assert magnitude scales sensibly with scene duration (e.g. within a defined
  min/max drift-per-second band, config-driven, not hardcoded); (d) assert
  `IMG_007` violations now block/trigger remediation rather than only
  logging.

---

## Cross-cutting requirements (apply to all three fixes)
- No new hardcoded thresholds/literals — extend existing config
  dataclasses/settings, following the pattern already used for
  `EscalationConfig` and `ValidationRulesConfig`.
- Do not weaken or break any of the existing 2600+ passing tests. Full test
  suite must be run and must pass except for the two known, pre-existing,
  unrelated `test_vision_concurrency` failures (do not "fix" those — they are
  intentional per current config).
- Add docstrings explaining the root cause and the fix at each changed
  function, the same way prior fixes in this codebase documented gap
  resolutions.
- Every fix must include both a unit test and, where applicable, an
  integration/regression test that reproduces the original observed defect
  and proves it no longer occurs.

## Verification & Testing Protocol (must all be done before reporting done)
1. Run the full existing test suite. Record pass/fail counts.
2. Run all new/updated tests in isolation. Record pass/fail counts.
3. Produce one full end-to-end render of a representative multi-scene script
   (reuse an existing fixture/sample script if available) and run an
   automated post-render check that verifies, programmatically:
   - No occurrence of the opening line or a fuzzy-matched paraphrase anywhere
     in the final subtitle/narration track.
   - The final scene of the rendered video is the dedicated brand card asset
     (assert by asset ID / scene type, not by eyeballing).
   - No scene in the final render is fully static (zero pixel motion) for
     more than the configured cap, using a frame-difference or
     freeze-detection check across the whole render (do not use the render
     tool's own internal instrumentation as the only proof — verify against
     the actual output file).
4. If any of the above three checks fail, treat the fix as incomplete —
   iterate before reporting.

## Final Summary (the ONLY thing to output to the user)
Report exactly this, concisely, nothing else:
- Root cause of Bug 1, Bug 2, Bug 3 (one line each)
- Fix applied for each (one or two lines each)
- Files changed (list)
- Tests added/updated + pass counts, and full-suite pass/fail count
- Result of the end-to-end render verification (pass/fail per of the 3 checks
  in the Verification protocol above)
- Any known remaining gaps or follow-ups, clearly labeled as such

## Status: COMPLETED 2026-07-24

All three bugs fixed and verified. See `docs/context/MASTER_CONTEXT.md` entry "2026-07-24 — Bugfix: opening-line leak, missing brand card, static/jerky motion" for detailed implementation list and verification results.
