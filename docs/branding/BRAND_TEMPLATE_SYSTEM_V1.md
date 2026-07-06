# BRAND_TEMPLATE_SYSTEM_V1

## Goal

Implement a configurable Brand Template System so channel branding is
managed through configuration rather than hardcoded into prompts or
code.

This enables every YouTube channel to maintain a consistent identity
while allowing future branding changes without modifying the pipeline.

------------------------------------------------------------------------

## Create

`config/brand_config.yaml`

Example:

``` yaml
channel_name: "Atma Theory"

opening:
  enabled: true
  template: |
    Welcome to Atma Theory...
    where ancient wisdom meets modern life.

closing:
  enabled: true
  template: |
    This is Atma Theory.

cta:
  enabled: true
  template: |
    If this reflection stayed with you,
    consider joining us on this journey.

signature:
  enabled: true
  template: |
    Think deeper...
    Live clearer.

voice:
  pace: calm
  pause_after_opening_ms: 800
  pause_after_closing_ms: 1000

branding:
  opening_position: after_hook
  closing_position: before_final_quote
  max_opening_seconds: 10
```

------------------------------------------------------------------------

## Standard Structure

Hook

↓

Welcome to Atma Theory

↓

Teaching

↓

Reflection

↓

This is Atma Theory

↓

CTA

↓

Think deeper... Live clearer.

------------------------------------------------------------------------

## Rules

-   Brand welcome appears exactly once after the hook.
-   Brand signature appears exactly once before the CTA.
-   Never insert branding in the middle of the teaching.
-   Never use branding as duration padding.
-   Read all branding from `brand_config.yaml`.
-   Support future channels by replacing only the configuration file.

------------------------------------------------------------------------

## Validation

Before finalizing every script verify:

-   Hook exists.
-   Opening welcome exists once.
-   Closing signature exists once.
-   No branding interrupts the teaching.
-   CTA appears once.
-   Closing quote ends the video.

Automatically rewrite if validation fails.

------------------------------------------------------------------------

## Success Criteria

The channel identity is instantly recognizable while remaining
consistent, configurable, and non-intrusive.
