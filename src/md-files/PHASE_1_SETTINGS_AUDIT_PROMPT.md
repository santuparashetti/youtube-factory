# Claude Code Prompt — Phase 1 Step 1: Audit & Propose Settings Split

Paste into Claude Code, run from repo root. **Investigation and
proposal only — do not split anything yet.** Stop after Step 3 and
report back for sign-off.

---

## Context

`config/settings.py` is a single monolithic `Settings(BaseSettings)`
mixing credentials/provider-selection (clearly shared) with BGM/CTA/
image-review/branding thresholds (clearly factory-specific), plus some
fields that aren't obviously either. Goal: propose a clean split without
breaking any of the ~60+ call sites that currently do `settings.<field>`
on one flat object.

## Step 1 — Inventory every field

```bash
grep -n "^\s*\w\+:\s*\w\+" src/ytfactory/config/settings.py
```
(adjust the pattern if `Settings` fields are declared differently — the
goal is a complete field list with types and defaults)

For each field, categorize:

- **Shared** — API keys/credentials, provider selection enums
  (`LLM_PROVIDER`, `TTS_PROVIDER`, etc.), logging config, anything a
  hypothetical second factory would need identically
- **Factory-specific** — BGM/CTA/image-review/branding/publish
  thresholds, anything encoding ytfactory's specific content pipeline
  decisions
- **Ambiguous** — genuinely unclear; flag these explicitly rather than
  guessing, e.g. workspace root path (structural but maybe shared),
  retry/timeout defaults (generic concept, but current values may be
  YT-workload-tuned)

## Step 2 — Count blast radius

```bash
grep -rln "settings\.\|Settings()" src/ tests/ | wc -l
```
And for the ambiguous fields specifically, find their call sites so we
know which ones are actually risky to move:
```bash
grep -rn "settings\.<ambiguous_field_name>" src/ tests/
```

## Step 3 — Propose the split shape, don't build it yet

Write up (as a comment block or scratch file, not a code change):

1. Field-by-field table: field name → Shared/Factory/Ambiguous →
   proposed home (`video_core.config.SharedSettings` vs
   `ytfactory.config.Settings`)
2. Proposed inheritance shape — most likely
   `ytfactory.config.Settings(video_core.config.SharedSettings)` so
   every existing `settings.<field>` call site keeps working unchanged
   regardless of which class actually declares the field. Confirm this
   is viable given how `Settings` is currently instantiated (singleton?
   constructed per-call? — check `agents/nodes/publish.py`'s
   `_settings = Settings()` pattern noted in BI-005's fix and see if
   that's representative)
3. `.env` loading — confirm `BaseSettings` env-var resolution still
   works cleanly split across two classes (Pydantic supports this via
   inheritance, but confirm the `.env` file doesn't need splitting too,
   or if it does, what that looks like)
4. Migration risk callouts — which specific call sites (if any) would
   need real code changes vs. which are purely "same attribute, moved
   file"

## Stop here

Report the field table, the ambiguous-field list with reasoning, and
the proposed class shape. Do not create `video_core/config/`, do not
move any fields, do not touch `.env` or `.env.example`. This is a
design proposal for review before Phase 1 execution begins.
