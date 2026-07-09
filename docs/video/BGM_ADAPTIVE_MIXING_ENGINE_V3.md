# BGM_ADAPTIVE_MIXING_ENGINE_V3.md

> **Implementation Specification for Claude Code**

## Objective

Fix the current BGM behaviour so background music behaves cinematically instead of pumping during narration.

### Current Problem

The current mixer raises BGM immediately whenever narration briefly pauses (between words, commas, breaths or short dramatic pauses). This creates distracting volume pumping.

### Required Behaviour

- Narration is always the primary audio.
- Background music is emotional support.
- Keep BGM consistently ducked while narration is active.
- Do NOT raise BGM during:
  - breaths
  - commas
  - short pauses
  - dramatic pauses
- Raise BGM only during genuine silence (default: >2.5 seconds).

## Replace Binary Ducking

Replace:

Speech -> Duck
No Speech -> Raise

with a state machine:

NO_NARRATION
→ FULL_MUSIC

Narration starts
→ NARRATION_ACTIVE

Short pause
→ Stay in NARRATION_ACTIVE

Long silence (>2.5 s)
→ MUSIC_FEATURE

Narration resumes
→ Smooth duck
→ NARRATION_ACTIVE

## Music States

FULL:
- Intro
- Outro
- Long silence
- Cinematic transitions
- Target ≈ -16 to -18 LUFS

SUPPORT:
- Any narration
- Target ≈ -28 to -32 LUFS
- Stable volume
- No pumping

TRANSITION:
- Smooth fades only

## Ducking Parameters

Attack: 150–250 ms
Hold: 2000–2500 ms
Release: 1500–2000 ms

The HOLD period is mandatory. Music must remain ducked after speech ends until the hold timer expires.

## Pause Detection

Do not rely only on VAD.

Priority:
1. Kokoro word timestamps
2. Phrase timestamps
3. Sentence timestamps
4. VAD fallback

Classify pauses as:
- breath
- comma
- dramatic_pause
- sentence_pause
- long_silence

Only long_silence may restore music.

## Configuration

```yaml
bgm:
  adaptive_mixing: true
  hold_after_speech_ms: 2200
  long_silence_ms: 2500
  duck_attack_ms: 180
  duck_release_ms: 1800
  narration_level_lufs: -30
  music_level_lufs: -17
  transition_curve: ease_in_out
```

## ReviewPipeline

Extend audio review to reject:
- pumping
- abrupt gain jumps
- narration masking
- unnatural transitions

Generate:
- bgm-mix-report.json

## Debug

Generate a timeline showing:
- narration
- BGM level
- state changes
- duck curves

## Tests

Test:
- continuous narration
- breaths
- commas
- dramatic pauses
- long silence
- narration resume
- intro
- outro

## Success Criteria

- Narration always dominates.
- BGM stays gently suppressed during narration.
- BGM rises only during real silence.
- No audible pumping.
- No regressions.
- Preserve existing architecture.
