# Claude Code Prompt — Sync Docs After Phase 0 (commit 06c358b)

Paste into Claude Code, run from repo root. This is a **targeted edit
pass**, not a rewrite — touch only the specific sections named below.
Both files are large; don't regenerate them wholesale.

---

## File 1: `docs/MASTER_CONTEXT.md`

### Edit A — Repo layout section
Find the section showing the `src/` tree. Add `video_core/` as a
top-level package alongside `ytfactory/`:

```
src/
├── video_core/          # NEW — Phase 0 extraction (2026-07-12, commit 06c358b)
│   ├── providers/       # llm, search, image, tts (excl. pacing/), vision
│   ├── models/          # LAMM: manager, registry, bundle, capabilities
│   └── domain/          # LLMResponse, SearchResult, ImageRequest
│
└── ytfactory/           # unchanged product code — review, publish, bgm,
                          # branding, agents, build, scenes, providers/tts/pacing/,
                          # domain/project.py, config/, everything else
```

### Edit B — Provider System table
Find the table with columns `Provider type | Base class | Implementations
| Setting key`. Update the `Base class` column paths:

| Provider type | Old path | New path |
|---|---|---|
| LLM | `ytfactory.providers.llm.base` | `video_core.providers.llm.base` |
| Search | `ytfactory.providers.search.base` | `video_core.providers.search.base` |
| Image | `ytfactory.providers.image.base` | `video_core.providers.image.base` |
| TTS | `ytfactory.providers.tts.base` | `video_core.providers.tts.base` (pacing engine stays at `ytfactory.providers.tts.pacing`) |
| Vision | `ytfactory.providers.vision.base` | `video_core.providers.vision.base` |

Add a one-line note: "`get_<type>_provider()` factory functions moved
with their base classes — call sites unchanged, only import paths
changed."

### Edit C — Domain Models section
Find the line listing `Project`, `LLMResponse`, `SearchResult`,
`ImageRequest`. Split it:

> `src/ytfactory/domain/` — `Project` (metadata + stage status dict),
> `ProjectRepository` (unchanged, still factory-owned).
>
> `src/video_core/domain/` — `LLMResponse`, `SearchResult`,
> `ImageRequest` (generic provider I/O shapes, moved in Phase 0).

### Edit D — LAMM section
Wherever `models/` (LocalAIModelManager, registry, bundle, capabilities)
is described, update the path prefix from `ytfactory.models` to
`video_core.models`. Keep all behavioral description text unchanged —
only the path changed, not the design ("single authority," "no feature
pipeline downloads models directly" still applies verbatim).

### Edit E — Add a Phase 0 changelog entry
Add near the top (wherever recent-changes/changelog entries live):

```
## 2026-07-12 — Phase 0 structural extraction complete (commit 06c358b)
Moved to `video_core`: providers/{llm,search,image,tts-excl-pacing,vision},
models/ (LAMM), domain/{llm,search,image}.py.
Stayed in `ytfactory`: everything else (review, branding, publish, bgm,
agents, build, scenes, providers/tts/pacing, domain/project.py).
Test baseline unchanged: 2159 passing, 0 failing.
Layering enforced via scripts/check_layering.py.
Known allowlisted Bucket-C exceptions (tracked for Phase 1, not yet
extracted): ytfactory.config.settings, ytfactory.shared.constants.
```

### Do NOT touch
Everything under Bucket B/C in the architecture spec — review layer
internals, BGM engine internals, publish generators, branding rules,
workspace layout diagrams, invariants list. None of that changed.

---

## File 2: `CLAUDE.md`

### Edit — Provider System table only
Same table update as Edit B above — this table exists in both files.
Leave every other section of `CLAUDE.md` untouched: commands, pipeline
pattern, workspace layout, test patterns, gotchas. None of those
changed in Phase 0.

Add one line under the Provider System table:

> Base classes and factory functions live in `video_core.providers.*`
> as of Phase 0 (2026-07-12). Product-specific implementations (e.g.
> the Contemplative Pacing Engine) remain in `ytfactory.providers.tts.pacing`.

---

## Verification

After edits, grep for any remaining stale path references so nothing
gets missed:

```bash
grep -rn "ytfactory\.providers\.\(llm\|search\|image\|vision\)\." docs/ CLAUDE.md
grep -rn "ytfactory\.providers\.tts\.\(base\|factory\)" docs/ CLAUDE.md
grep -rn "ytfactory\.models\." docs/ CLAUDE.md
```

Any hits outside `providers/tts/pacing/` context are stale and need the
same path update. Report what you found and fixed.

Commit as a single doc-only commit: `docs: sync MASTER_CONTEXT and
CLAUDE.md with Phase 0 extraction (06c358b)`.
