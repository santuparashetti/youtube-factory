# CINEMATIC_MOTION_ENGINE_V1.md

# Cinematic Motion Engine V1

## Objective

Transform the Video Renderer from a slideshow renderer into a cinematic
documentary renderer.

The renderer should create the illusion of camera movement, visual
continuity and emotional pacing from still images.

The goal is for viewers to feel they are watching a professionally
directed documentary rather than a sequence of static images.

------------------------------------------------------------------------

# Preserve Existing Architecture

Do NOT redesign:

-   LangGraph workflow
-   Research pipeline
-   Script Writer
-   Scene Planner
-   Image Generation
-   Speech Optimizer
-   TTS
-   Subtitle Generation
-   Public interfaces

Only enhance the rendering stage.

------------------------------------------------------------------------

# Motion Philosophy

Movement must always serve the story.

Never animate simply because movement is available.

Every camera movement should reinforce the emotion of the narration.

------------------------------------------------------------------------

# Supported Camera Movements

Implement configurable support for:

-   Slow Push In
-   Slow Push Out
-   Pan Left
-   Pan Right
-   Crane Up
-   Crane Down
-   Dolly In
-   Dolly Out
-   Gentle Camera Drift
-   Orbit Simulation
-   Perspective Shift
-   Focus Pull
-   Depth Zoom
-   Subtle Rotation
-   Foreground Parallax

Movements must remain smooth and cinematic.

------------------------------------------------------------------------

# Emotion Driven Motion

Examples:

Reflection → Slow Push In

Mystery → Gentle Drift

Wonder → Crane Up

Power → Low Angle Push

Landscape → Slow Pan

Revelation → Push Through

Peace → Minimal Movement

Hope → Lift Upward

The motion planner should infer movement from scene intent.

------------------------------------------------------------------------

# Transition Engine

Replace generic slideshow transitions.

Support:

-   Cross Dissolve
-   Film Dissolve
-   Match Cut
-   Blur Dissolve
-   Light Leak
-   Luma Fade
-   Atmospheric Fade
-   Motion Blur Blend
-   Soft Zoom Transition

Transitions should be selected intelligently based on adjacent scenes.

Avoid random transitions.

------------------------------------------------------------------------

# Scene Rhythm

Motion should be planned across the entire video.

Avoid repeating the same movement repeatedly.

Balance:

-   push
-   pan
-   drift
-   stillness

to create cinematic rhythm.

------------------------------------------------------------------------

# Visual Continuity

Maintain continuity between scenes:

-   camera direction
-   lighting
-   color mood
-   pacing
-   emotional tone

Avoid abrupt visual jumps.

------------------------------------------------------------------------

# Asset Scene Support

Asset Scenes must receive the same cinematic treatment.

Suggested defaults:

-   Slow Fade In
-   Gentle Zoom
-   Camera Drift
-   Fade Out

Never display branding or title cards as static images.

------------------------------------------------------------------------

# Subtitle Awareness

Camera motion must never interfere with subtitle readability.

Keep subtitles within safe areas.

Avoid excessive motion behind subtitles.

------------------------------------------------------------------------

# Motion Constraints

Avoid:

-   Fast zooms
-   Random movement
-   Constant animation
-   PowerPoint-style effects
-   Slide transitions
-   Spin effects

Prefer:

-   Slow
-   Smooth
-   Intentional
-   Documentary quality

------------------------------------------------------------------------

# Performance

Rendering should remain efficient.

Allow configurable quality profiles:

-   Draft
-   Balanced (default)
-   Cinematic (new default)
-   Premium

**Static fallback eliminated:** Unmapped emotions and unrecognized motion types now fall back to `drift` rather than `static`. Asset scenes with unknown animation strings fall back to `slow_zoom` instead of static.

**Duration-aware drift:** Drift magnitude scales with scene duration relative to `reference_duration_seconds` (default 5s), clamped by `max_drift_scale_factor` (default 2.0), so longer scenes maintain continuous motion without fading to a hold.

Premium may enable parallax, depth motion and more advanced transitions.

------------------------------------------------------------------------

# Future Expansion

Design for future support of:

-   AI depth maps
-   Image segmentation
-   Layered parallax
-   Object-aware camera motion
-   Dynamic lighting
-   Particle effects
-   Fog
-   Rain
-   Dust
-   Volumetric light
-   Cinematic lens effects

without redesigning the renderer.

------------------------------------------------------------------------

# Acceptance Criteria

The renderer should:

-   Eliminate slideshow feel.
-   Produce smooth cinematic motion.
-   Use emotion-aware camera movements.
-   Use intelligent scene transitions.
-   Animate Asset Scenes.
-   Preserve subtitle readability.
-   Maintain backward compatibility.

------------------------------------------------------------------------

# Prompt for Claude Code

Read this specification completely before making any code changes.

Enhance only the Video Renderer.

Do NOT redesign the existing pipeline.

Before implementation:

1.  Analyze the current rendering pipeline.
2.  Explain how motion is currently applied.
3.  Identify where a Cinematic Motion Engine should integrate.
4.  Present an implementation plan.

Wait for approval before coding.

After implementation:

-   List every modified file.
-   Explain every architectural decision.
-   Explain the motion planner.
-   Explain the transition engine.
-   Explain Asset Scene animation support.
-   Explain how subtitle safety is preserved.
-   Confirm backward compatibility.

The objective is to transform YouTube Factory from a slideshow renderer
into a cinematic documentary renderer with professional camera movement,
emotionally driven transitions and film-quality visual storytelling.
