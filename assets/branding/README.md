# Branding Assets

Place channel branding images here.

## Required

| File | Purpose |
|------|---------|
| `atma-theory-brand.png` | Atma Theory brand card — shown during closing narration |

## Specifications

- Resolution: 1920×1080 (Full HD, 16:9)
- Format: PNG with transparency supported
- The pipeline will warn clearly if a referenced asset is missing

## How it works

When the Scene Planner detects a closing phrase (e.g. "Think deeper... live clearer."),
it automatically creates an Asset Scene referencing this file instead of generating
an AI image. The brand card renders with a slow zoom animation for the duration of
the closing narration.
