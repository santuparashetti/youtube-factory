# Assets

Reusable static assets for YouTube Factory productions.

## Structure

```
assets/
  branding/   Channel brand cards (shown at closings)
  intro/      Intro cards and logos
  chapter/    Chapter divider cards
  sponsor/    Sponsor screens
  credits/    End credits backgrounds
```

## Asset Scenes

An Asset Scene references a file from this directory instead of generating
an AI image. The scene type, path, and animation are stored in scene-plan.json:

```json
{
  "scene_type": "asset",
  "asset_path": "assets/branding/atma-theory-brand.png",
  "animation": "slow_zoom"
}
```

## Supported Animations

| Value | Effect |
|-------|--------|
| `slow_zoom` | Ken Burns slow zoom in (default for brand cards) |
| `slow_zoom_out` | Ken Burns slow zoom out |
| `drift` | Subtle horizontal drift |
| `static` | No motion (same as generated scenes) |
