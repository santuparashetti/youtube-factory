# Claude Code Prompt — Sync Docs After Phase 1 (commits 4df0ecf, e9f9183, 4e9d46b, 6516da3)

Paste into Claude Code, run from repo root. Targeted edits only.

---

## File 1: `docs/context/MASTER_CONTEXT_UPDATED.md`

### Edit A — Changelog
Add above the Phase 0 entry:

```
## 2026-07-12 — Phase 1 Settings split complete (commits 4df0ecf, e9f9183, 4e9d46b, 6516da3)
Split monolithic ytfactory.config.settings.Settings (117 fields) into:
  - video_core.config.SharedSettings — 27 fields (API keys, provider
    selectors, model names, provider-config values consumed by
    video_core providers)
  - ytfactory.config.Settings(SharedSettings) — remaining ~90 fields
    (pipeline/quality/content-specific), inherits all SharedSettings
    fields so every existing `settings.<field>` call site is unchanged
3 known-dead fields (kokoro_language, whisperx_model, request_timeout)
intentionally left in place — separate cleanup, not part of this split.
check_layering.py: ytfactory.config.settings removed from KNOWN_BUCKET_C
allowlist. One remaining Bucket-C exception: ytfactory.shared.constants
(tracked for Phase 2).
Test count unchanged: 2161 passing, 0 failing throughout.
```

### Edit B — Configuration section
Wherever `Settings` / `config/settings.py` is described (likely near
the `.env` example block), add a note:

> As of Phase 1 (2026-07-12), `Settings` is split: shared
> credentials/provider config live in `video_core.config.SharedSettings`;
> pipeline/quality/content config stays in `ytfactory.config.Settings`,
> which inherits from `SharedSettings`. Both are populated from the same
> `.env` file — no change to `.env` structure or usage.

### Edit C — Source layout section (the one added in the Phase 0 sync)
Add `config/` under the `video_core/` tree entry:
```
├── video_core/
│   ├── providers/
│   ├── models/
│   ├── domain/
│   └── config/          # NEW — SharedSettings (Phase 1)
```

### Do NOT touch
Everything else — provider descriptions, LAMM section, workspace
layout, review/bgm/publish internals. None of that changed.

---

## File 2: `CLAUDE.md`

### Edit — Configuration section
Find the block showing the `.env` example (`GEMINI_API_KEY=...` etc.).
Add one line after it:

> `Settings` is split as of Phase 1: `video_core.config.SharedSettings`
> holds credentials/provider config; `ytfactory.config.Settings` extends
> it with pipeline-specific fields. Both load from this same `.env` —
> no workflow change for local development.

Leave every other section untouched.

---

## Verification

```bash
grep -rn "117 fields\|class Settings(BaseSettings)" docs/ CLAUDE.md
```
Any hits describing the old flat 117-field single-class shape are stale
— update or remove them.

Commit as a single doc-only commit:
`docs: sync MASTER_CONTEXT and CLAUDE.md with Phase 1 Settings split`
