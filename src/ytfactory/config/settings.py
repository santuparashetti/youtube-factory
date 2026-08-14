from video_core.config.shared_settings import SharedSettings


class Settings(SharedSettings):
    """ytfactory-specific configuration.

    Extends SharedSettings with pipeline, quality, and content-specific
    settings. API keys, provider selectors, model names, and the fields
    accessed directly by video_core providers live in SharedSettings
    (video_core.config.shared_settings).
    """

    # ------------------------------------------------------------------
    # Image Defaults
    # ------------------------------------------------------------------

    # Native YouTube HD (720p — active default)
    image_width: int = 1280
    image_height: int = 720

    # ------------------------------------------------------------------
    # Video Defaults
    # ------------------------------------------------------------------

    video_width: int = 1280
    video_height: int = 720
    video_fps: int = 30

    # ------------------------------------------------------------------
    # Rendering Profile
    # ------------------------------------------------------------------

    # Cinematic quality level applied by MotionPlanner and TransitionPlanner.
    # draft    — static frame, hard cuts (fastest render, no motion)
    # balanced — simple zoom/pan, cross-dissolves
    # cinematic — full emotion-aware motion + transitions, ease_in_out
    # premium   — wider scale ranges, longer fades
    render_profile: str = "cinematic"

    # ------------------------------------------------------------------
    # Subtitle Intelligence Engine
    # ------------------------------------------------------------------

    # Write per-scene debug files to workspace/jobs/<id>/subtitle-debug/
    subtitle_debug: bool = False

    # Run validation checks on every generated subtitle
    subtitle_validate: bool = True

    # Maximum characters per second (Netflix: 17, BBC: 17, default: 18)
    subtitle_max_cps: float = 18.0

    # Maximum characters per subtitle line
    subtitle_max_chars_per_line: int = 42

    # Maximum number of display lines per subtitle cue
    subtitle_max_lines: int = 2

    # Primary output format: "ass" (default) or "srt"
    # ASS produces professional styled subtitles; SRT is always written alongside for compat.
    subtitle_format: str = "ass"

    # ------------------------------------------------------------------
    # ASS Subtitle Engine — Style Configuration
    # ------------------------------------------------------------------

    # Theme preset: "default" | "minimal" | "high_contrast" | "cinematic"
    subtitle_ass_theme: str = "default"

    # Font family (must be installed on the render machine)
    subtitle_ass_font: str = "Arial"

    # Font size in pixels at PlayResX × PlayResY (1280 × 720)
    subtitle_ass_font_size: int = 35

    # Bold text (-1 = bold, 0 = not bold in ASS convention)
    subtitle_ass_bold: bool = True

    # Italic text
    subtitle_ass_italic: bool = False

    # ASS color format: &HAABBGGRR (alpha, blue, green, red)
    # AA: 00 = opaque, FF = transparent
    subtitle_ass_primary_color: str = "&H00FFFFFF"  # white text
    subtitle_ass_outline_color: str = "&H00000000"  # black outline
    subtitle_ass_back_color: str = "&H80000000"  # 50% transparent black shadow

    # Outline and shadow thickness in pixels
    subtitle_ass_outline: float = 2.0
    subtitle_ass_shadow: float = 1.0

    # Safe margins from the video edges in pixels (1280 × 720 reference)
    subtitle_ass_margin_l: int = 56
    subtitle_ass_margin_r: int = 56
    subtitle_ass_margin_v: int = 40

    # Subtitle alignment (numpad layout: 2 = bottom-center)
    subtitle_ass_alignment: int = 2

    # Border style: 1 = outline + shadow, 3 = opaque box
    subtitle_ass_border_style: int = 1

    # Script resolution — must match video dimensions
    subtitle_ass_play_res_x: int = 1280
    subtitle_ass_play_res_y: int = 720

    # Extend the last subtitle cue by this many seconds so it remains visible
    # through the fade-to-black transition at the end of each scene.
    subtitle_tail_extension_seconds: float = 1.0

    # ------------------------------------------------------------------
    # Subtitle Intelligence Editor (V2)
    # ------------------------------------------------------------------

    # Enable the LLM editorial pass after raw subtitle generation.
    # When True, SubtitleEditingEngine runs after SubtitleEngine and
    # re-writes .srt / .ass with improved punctuation, capitalisation,
    # and line breaks while preserving all timing exactly.
    subtitle_editor_enabled: bool = False

    # Subtitle editor backend: "llm" (uses the configured LLM provider)
    # or "mock" (passthrough, no API calls — useful for tests).
    subtitle_editor_provider: str = "llm"

    # Maximum editorial passes before accepting the best-scoring version.
    subtitle_editor_max_passes: int = 3

    # Quality score threshold (0–100) to stop iterating early.
    # The engine stops as soon as a pass scores >= this value.
    subtitle_editor_pass_threshold: float = 95.0

    # Maximum LLM call retries per pass on cue_id mismatch or parse error.
    subtitle_editor_max_retries: int = 3

    # ------------------------------------------------------------------
    # Image Prompt Engine V4 — Debug & Quality Control
    # ------------------------------------------------------------------

    # Write per-scene debug files to workspace/jobs/<id>/images/debug/
    # Saves scene-XXX-original.txt, scene-XXX-optimized.txt, image_prompt_debug.json
    image_prompt_debug: bool = False

    # ------------------------------------------------------------------
    # Human Quality Validation
    # ------------------------------------------------------------------

    # Maximum additional generation attempts for scenes with detected humans
    # when the generated image is below the sharpness threshold.
    # 0 = disable human-quality retry entirely.
    image_human_max_retries: int = 2

    # Minimum Pillow edge-detection stddev score to accept a human scene.
    # Images below this threshold are regenerated (up to image_human_max_retries).
    # Score reference: < 8 = blurry, 8–15 = marginal, > 15 = sharp.
    image_human_min_sharpness: float = 12.0

    # ADR-0015: enable the staged Human Subject QA Gate (Human QA → Hand QA →
    # Clothing QA → Prompt Compliance) for human-critical scenes.
    # Only active when image_review_enabled is also True.
    image_human_qa_enabled: bool = True

    # Check for visible hands in scenes where hand-avoidance composition was applied.
    # Only active when image_review_enabled is also True.
    image_hand_avoidance_check_enabled: bool = True

    # ------------------------------------------------------------------
    # Scene Planner — Retry Engine Reliability
    # (docs/script/task-2.2-retry-engine-reliability.md)
    # ------------------------------------------------------------------

    # Retry attempts per scene in the per-scene faithfulness retry loop.
    scene_planner_max_retries: int = 2

    # Use response_format={"type": "json_object"} on structured retry LLM calls
    # so the model returns raw JSON instead of prose wrapped in markdown fences.
    scene_planner_json_mode: bool = True

    # Use response_format={"type": "json_schema", ...} (strict schema) on retry
    # calls instead of loose json_object mode, where the provider supports it.
    scene_planner_strict_schema: bool = False

    # Faithfulness gate logs failed scenes to phase1_report.json but never
    # blocks the pipeline — recoverable in Phase 2 by manually fixing the
    # image prompt. Reserved for a future hard-gate mode; currently the gate
    # is always non-blocking regardless of this flag.
    faithfulness_gate_fail_pipeline: bool = False

    # Task 2.6: LLM validation layer for ENVIRONMENT_MISMATCH and
    # HUMAN_CLASSIFICATION_VIOLATED — deterministic checks that require
    # semantic understanding. Only called when these are the ONLY remaining
    # deterministic failures (never on scenes that already pass, never
    # alongside FORBIDDEN_CHARACTER/SYMBOLIC_REPLACEMENT — fix those via
    # retry first).
    faithfulness_llm_validation_enabled: bool = True

    # Cheap/fast model for the LLM validation call — separate from the main
    # generation model. Same provider/base_url/api_key as the main client
    # (routed via _get_cheap_llm's model-override pattern), just a different
    # model name.
    faithfulness_validator_model: str = "google/gemini-2.5-flash-lite"

    # Reserved for future max_tokens tuning. NOT currently wired to the
    # provider call — LLMProvider.generate() has no per-call max_tokens
    # parameter, and adding one is out of scope for Task 2.6 (its own doc
    # forbids touching openai_provider.py's signature).
    faithfulness_validator_max_tokens: int = 150

    # ── Script Selector + Polisher stage ──────────────────────────────────
    # The composer emits two variants (A/B); the polisher picks the stronger,
    # makes only the minimum necessary changes (≤10%), and returns the final
    # script. Runs on a top model via the same provider (model-override pattern,
    # like _get_cheap_llm). Replaces editorial_qa as the graph quality gate.
    script_polisher_model: str = "anthropic/claude-opus-4-5"  # top model for final polish
    script_polisher_temperature: float = 0.3  # low temp — precision, not creativity
    # Reserved for future max_tokens tuning. NOT wired to the provider call —
    # LLMProvider.generate() has no per-call max_tokens param (same limitation
    # documented for faithfulness_validator_max_tokens above); the provider
    # already requests a large ceiling internally.
    script_polisher_max_tokens: int = 4000
    composer_variant_temp_a: float = 0.62  # composer variant A temperature
    composer_variant_temp_b: float = 0.58  # composer variant B temperature

    # Task 2.7: narrative-visual bridge — a batch LLM pass that derives a
    # concrete visual_anchor per scene from its narration, before prompt
    # generation, so abstract/empty-chars scenes get a specific literal
    # directive instead of drifting to generic "spiritual documentary" imagery.
    visual_anchor_enabled: bool = True

    # Cinematic Pacing System — batch LLM pass that assigns reflection beats
    # (post-narration hold), music actions, and a global director pass to every
    # scene. Produces scene_pacing dicts stored in scene-plan.json.
    # The video renderer consumes reflection.duration to insert silent hold
    # segments after narration ends; music.action is informational (BGM future use).
    cinematic_pacing_enabled: bool = True
    # When False, reflection hold segments (still-image pauses after narration)
    # are skipped at render time. Pacing data is still generated and stored.
    reflection_beats_enabled: bool = False

    # ------------------------------------------------------------------
    # TTS Pronunciation Preparation
    # ------------------------------------------------------------------

    # Enable the TTS pronunciation preparation layer. When True, Sanskrit and
    # other non-English terms detected in the scene narration receive structured
    # pronunciation hints. In SSML mode (ssml_enhancement_enabled=True with the
    # speechify provider) hints are injected as <sub alias="..."> SSML tags.
    # Canonical script text is NEVER modified regardless of this setting.
    tts_pronunciation_enabled: bool = True

    # Path to the pronunciation dictionary YAML (relative to CWD).
    # Defaults to config/pronunciations.yaml.
    tts_pronunciation_config: str = "config/pronunciations.yaml"

    # ------------------------------------------------------------------
    # TTS Debug & Quality Control
    # ------------------------------------------------------------------
    # Reviewed 2026-07-12: intentionally factory-side — ytfactory's VoicePipeline
    # owns debug/validate logic. tts_auto_retry and tts_max_retries moved to
    # SharedSettings (accessed directly by KokoroProvider in video_core).

    # Write intermediate text files + metadata to workspace/jobs/<id>/tts-debug/
    tts_debug: bool = False

    # Validate every generated audio clip (file size, duration, word-count ratio)
    tts_validate_audio: bool = True

    # File-level cache: if a scene's audio already exists on disk with a valid
    # size, skip the TTS provider call entirely instead of re-spending credits
    # (e.g. Cartesia) when Phase 1 is re-run against the same script. Separate
    # from TTSCache's API-level key-based cache, which this runs ahead of.
    tts_skip_existing: bool = True

    # ------------------------------------------------------------------
    # Contemplative Pacing Engine
    # ------------------------------------------------------------------

    # Enable sentence-level pause injection (silence gaps between sentences).
    # When True, the optimizer still applies phrase-splitting and keyword emphasis
    # per sentence; silences are injected BETWEEN sentences via FFmpeg concat.
    # Disabled automatically for scene_type=="asset" scenes.
    tts_pacing_enabled: bool = True

    # Pacing profile — controls pause duration ranges per sentence weight class.
    # Options: normal | documentary | spiritual | meditation | slow_reflection
    # "spiritual" inserts generous pauses (500–700ms normal, 1.2–1.8s important,
    # 2.0–2.5s major realization) so viewers have time to absorb each idea.
    tts_pacing_profile: str = "spiritual"

    # ------------------------------------------------------------------
    # Video Encoding — FFmpeg H.264 parameters
    # ------------------------------------------------------------------

    # Supersampling factor for zoompan motion to suppress sub-pixel jitter.
    # 1 = disabled (native resolution), 2 = 2x internal render then lanczos downscale.
    # Higher values increase render time; 2 is the recommended default.
    motion_supersample: int = 2
    # Reviewed 2026-07-12: intentionally factory-side — values tuned for
    # near-static YT slideshow content; a different factory would differ.

    # H.264 Constant Rate Factor (CRF) — 0=lossless, 51=worst.
    # 23 is the H.264 default ("visually lossless" for cinematic content).
    # Lower = higher quality and larger files; 18 is overkill for YouTube.
    video_crf: int = 23

    # x264 encoder preset. Slower presets compress better for motion-heavy content,
    # but for near-static slideshow content (slow zoompan on still images) "medium"
    # is optimal — "slow"/"veryslow" add encoding time without size benefit and can
    # even produce slightly larger files due to increased lookahead overhead.
    # Options: ultrafast fast medium slow veryslow
    video_preset: str = "medium"

    # x264 tune. "film" increases PSY-RD which adds bitrate for fine-detail
    # preservation — counterproductive for AI-generated images at documentary
    # quality. Empty string disables tuning, keeping bitrate as low as possible.
    # Set to "film" for live-action photorealistic content.
    video_tune: str = ""

    # Keyframe (GOP) interval in frames. 60 = every 2 s at 30 fps.
    # Controls seek accuracy; lower = larger files, faster seeking.
    video_keyframe_interval: int = 60

    # AAC audio bitrate for the scene narration track.
    # 128k is sufficient and indistinguishable from 192k for voice content.
    video_audio_bitrate: str = "128k"

    # ------------------------------------------------------------------
    # Background Music (BGM)
    # ------------------------------------------------------------------

    # Master enable — True = BGM on by default
    bgm_enabled: bool = True

    # BGM category. "auto" selects based on video topic.
    # Options: auto | spiritual | meditation | cinematic_ambient |
    #          emotional_documentary | inspirational | calm_piano | nature_ambient
    bgm_category: str = "auto"

    # Directory containing music files.
    # Layout: <path>/<category>/*.mp3  or  <path>/*.mp3 (flat)
    bgm_library_path: str = "workspace/music"

    # BGM volume relative to full scale during quiet/pause sections (0.0–1.0).
    bgm_volume: float = 0.24

    # Minimum BGM level during active speech (0.0–bgm_volume).
    bgm_duck_floor: float = 0.04

    # Sidechain compress threshold — amplitude above which ducking engages.
    # 0.02 ≈ −34 dBFS — detects speech onset.
    bgm_duck_threshold: float = 0.02

    # Ducking compression ratio — 6:1 compression under speech.
    bgm_duck_ratio: float = 6.2

    # Milliseconds for ducking to engage after speech onset.
    # 15 ms: near-instantaneous onset.
    bgm_duck_attack_ms: int = 15

    # Milliseconds for music to recover after speech ends.
    # 350 ms: fast recovery without audible pumping.
    bgm_duck_release_ms: int = 350

    # Music fade-in at video start (seconds).
    bgm_fade_in_seconds: float = 3.0

    # Music fade-out at video end (seconds).
    bgm_fade_out_seconds: float = 4.0

    # Crossfade between loop iterations (seconds).
    bgm_crossfade_seconds: float = 2.0

    # Randomly select from available tracks in the category.
    bgm_random_track: bool = True

    # ── BGM V2: VAD-assisted adaptive ducking ─────────────────────────────

    # Enable VAD pre-analysis for phrase grouping and debug output.
    bgm_vad_enabled: bool = True

    # VAD backend ("silero" preferred; current impl uses FFmpeg silencedetect).
    bgm_vad_provider: str = "silero"

    # Gap (ms) between speech bursts treated as a single continuous phrase (V2 legacy).
    bgm_phrase_gap_ms: int = 300

    # Silence duration (ms) after which music recovers (V2 / review rules).
    bgm_long_silence_ms: int = 2500

    # Vary duck depth with narration energy (louder → deeper duck).
    bgm_dynamic_ducking: bool = True

    # Volume recovery curve after long silence ("logarithmic" matches compressor).
    bgm_restore_curve: str = "logarithmic"

    # ── BGM V3: Adaptive State-Machine Mixing ─────────────────────────────

    # Enable V3 adaptive mixing state machine. When True, uses cinematic
    # attack/release and holds music ducked through short pauses.
    bgm_adaptive_mixing: bool = True

    # Duration (ms) music stays ducked after speech ends (V3 hold timer).
    # Bridges breaths (< 200 ms), commas (200–500 ms), dramatic pauses
    # (500–1500 ms) and sentence pauses (1500–2500 ms).
    bgm_hold_after_speech_ms: int = 2200

    # Threshold (ms) above which a gap is classified as "long_silence".
    bgm_long_silence_threshold_ms: int = 2500

    # Target narration level in LUFS (for review checks and debug reports).
    bgm_narration_level_lufs: float = -30.0

    # Target music level in LUFS during narration (for review checks).
    bgm_music_level_lufs: float = -17.0

    # Duck curve shape for V3 transitions.
    bgm_transition_curve: str = "ease_in_out"

    # ------------------------------------------------------------------
    # Cinematic Intro
    # ------------------------------------------------------------------

    # Prepend a short black screen before Scene 1 in the final video.
    # Intentional cinematic pause — does NOT trigger black-frame validation.
    # Keep ≤300 ms; longer intros risk being perceived as a loading delay.
    video_intro_enabled: bool = True
    video_intro_seconds: float = 0.3

    # ------------------------------------------------------------------
    # Kokoro TTS Provider
    # ------------------------------------------------------------------
    # kokoro_api_key, kokoro_voice, kokoro_speed, kokoro_sample_rate moved to
    # SharedSettings (accessed by KokoroProvider in video_core).

    # BCP-47 language code passed to Kokoro.
    # Reviewed 2026-07-12: zero call sites found — dead field, kept for cleanup pass.
    kokoro_language: str = "en-US"

    # ------------------------------------------------------------------
    # WhisperX Forced Alignment
    # ------------------------------------------------------------------
    # Reviewed 2026-07-12: intentionally factory-side — only ytfactory's
    # VoicePipeline uses WhisperX; a different factory would configure separately.

    # Enable WhisperX forced alignment after TTS generation.
    # When True, alignment.json is written to audio/ alongside timing.json.
    # CaptionPipeline prefers alignment.json for subtitle timing when present.
    whisperx_enabled: bool = True

    # Model size for WhisperX ASR transcription (youtube_ingest.TranscriptionPipeline).
    # Not used by forced alignment above (that path is model-free, phoneme-based).
    # "large-v3" for real transcription accuracy on non-English source audio.
    whisperx_model: str = "large-v3"

    # Device for WhisperX inference: "cpu" or "cuda".
    whisperx_device: str = "cpu"

    # ------------------------------------------------------------------
    # YouTube Ingestion (Phase 1 alternate source: URL instead of a script file)
    # ------------------------------------------------------------------

    # Source language of the discourse audio (ISO 639-1) — passed to WhisperX
    # transcription. Kannada discourses are the primary use case.
    youtube_ingest_language: str = "kn"

    # ------------------------------------------------------------------
    # Subtitle Segmentation
    # ------------------------------------------------------------------

    # Segmentation mode: "semantic" (default, sentence/clause/pause aware)
    # or "legacy" (preserves previous purely-CPS-driven behaviour).
    subtitle_segmentation_mode: str = "semantic"

    # Target characters per second for subtitle segmentation.
    # Subtitles are split when CPS would exceed this value.
    # Lower than max_cps so there is headroom for natural variation.
    subtitle_target_cps: float = 15.0

    # ------------------------------------------------------------------
    # Image Review (Vision Quality Gate)
    # ------------------------------------------------------------------

    # Master enable — True = vision review enabled
    image_review_enabled: bool = True

    # Vision provider: "local" (uses Local AI Model Manager) | "mock" (tests)
    vision_review_provider: str = "local"

    # Local model registry key (switchable via config only — no code changes needed)
    vision_review_local_model: str = "qwen2_5_vl_3b"

    # Minimum vision score to accept a scene (0–100)
    image_review_min_score: float = 90.0

    # Minimum confidence for the score to count (0–100)
    image_review_confidence: float = 80.0

    # Maximum generation+review attempts per scene before accepting best result
    image_review_max_attempts: int = 3

    # Automatically append prompt improvements and regenerate on review FAIL
    image_review_auto_remediate: bool = True

    # Write per-attempt review prompt files for debugging
    image_review_debug: bool = False

    # Target quality score for stage-2 evaluation (0–100)
    image_review_target_quality_score: float = 85.0

    # Anatomy hard-floor defense-in-depth (0–100 scale for sub-score inputs)
    image_review_anatomy_floor_threshold: float = 6.0
    image_review_anatomy_quality_cap: float = 6.0

    # Adaptive quality optimization thresholds (0–10 scale)
    image_escalation_target_quality_score: float = 9.2
    image_escalation_retry_threshold: float = 8.5
    image_escalation_premium_model_threshold: float = 8.5
    image_escalation_max_prompt_refinements: int = 1
    image_escalation_max_model_escalations: int = 2

    # ------------------------------------------------------------------
    # CTA Overlay
    # ------------------------------------------------------------------

    # Total number of render attempts (step 0 = initial, step 1 = same-placement
    # retry, step 2 = minimal-template fallback). Default matches the spec's
    # three-step escalation — reduce to 1 to fail fast with no retries.
    cta_max_retries: int = 3

    # ------------------------------------------------------------------
    # Publish — Chapters
    # ------------------------------------------------------------------

    # Maximum number of chapters written to chapters.txt.
    # When more natural scene boundaries exist, adjacent scenes are merged
    # into even contiguous groups. Short videos get fewer chapters — never
    # padded up to this cap.
    publish_max_chapters: int = 10

    # Minimum chapter duration in seconds (matches YouTube's own rule).
    # If merging to publish_max_chapters still leaves a chapter below this
    # threshold, groups are merged further until every chapter meets it —
    # which may produce fewer than publish_max_chapters chapters.
    publish_min_chapter_seconds: int = 10

    # ------------------------------------------------------------------
    # Pipeline QA Gates
    # ------------------------------------------------------------------

    # Master switch for the Pipeline QA system. When False, all pipeline
    # gates (pre-render and post-render) are skipped entirely.
    pipeline_qa_enabled: bool = True

    # Individual gate toggles — each can be disabled independently without
    # a code revert. Hard-reject gates raise PipelineAbort when enabled and
    # triggered; score-deduction rules only affect the final score.
    frame_naming_gate_enabled: bool = True
    bridge_requirement_enabled: bool = True
    motion_variety_enabled: bool = True
    static_shot_detection_enabled: bool = True
    text_overlay_duration_enabled: bool = True

    # ------------------------------------------------------------------
    # Subtitle Burn-in
    # ------------------------------------------------------------------

    # When False, .ass/.srt files are still generated in subtitles/ (Phase 1
    # unaffected) but never fed into the render filter chain — video renders
    # clean with no caption text, .srt uploaded to YouTube separately.
    # Independent of the brand_card exclusion, which always skips burn-in
    # regardless of this setting.
    subtitle_burn_enabled: bool = True

    # ------------------------------------------------------------------
    # Structural Retention Pass
    # ------------------------------------------------------------------

    # Master switch. Runs after the enhancer passes (Pass 1, Pass 2 if
    # enabled), before scene_planner. When False, script.md passes through
    # unchanged — no LLM calls, no file writes.
    structural_pass_enabled: bool = True

    # Meaning-only faithfulness check after restructuring. Non-blocking by
    # design (see STRUCTURAL_RETENTION_PASS_SPEC.md) — violations are
    # flagged to structural-retention-report.json and logs, never
    # auto-reverted. When False, the check is skipped entirely (one fewer
    # LLM call); report still writes with empty faithfulness_flags.
    structural_pass_faithfulness_check: bool = True

    # ------------------------------------------------------------------
    # Editorial QA Stage (see EDITORIAL_QA_STAGE_SPEC.md)
    # ------------------------------------------------------------------
    # Flags only — never gates, blocks, rejects, or reverts. By design there
    # is no "reject"/"block" config anywhere in this stage.

    # Master switch. Runs after the Structural Retention Pass. When False,
    # no reviewer LLM call, no ledger append, no promoter evaluation.
    editorial_qa_enabled: bool = True

    # Pattern Promoter: a check must FLAG in >= N of the last M ledger
    # entries before it's proposed as a generation-prompt change. A single
    # or occasional flag never promotes.
    qa_promote_n: int = 4
    qa_promote_m: int = 5

    # Runs to wait before re-proposing the same check after a human dismisses
    # it, unless that check's flag-rate has risen since the dismissal.
    qa_promote_cooldown_runs: int = 5

    # callback_to_opening is report-only until this is enabled — its flags
    # are recorded in the ledger but excluded from Pattern Promoter
    # consideration until the human opts it in as a house-style requirement.
    qa_callback_required: bool = False

    # ------------------------------------------------------------------
    # Animation Visual Analyzer
    # ------------------------------------------------------------------

    # Model used by the motion-engine SceneAnalyzer (animate stage).
    # Needs vision capability. Defaults to the main anthropic_model.
    # Set ANIMATE_ANALYZER_MODEL in .env to override independently.
    animate_analyzer_model: str = ""

    # ------------------------------------------------------------------
    # Motion Overlay Compositing
    # ------------------------------------------------------------------

    # When True, skips the overlay-compositing second ffmpeg pass per scene.
    # Useful for fast iteration/testing. Mapped from env SKIP_OVERLAYS.
    skip_overlays: bool = False

    # Path to the overlay manifest JSON.
    overlay_manifest_path: str = "assets/overlays/overlay_manifest.json"

    # Base directory clip "file" entries in the manifest are resolved against.
    # Previously hardcoded to "assets/overlays" in OverlayCompositor — now
    # configurable so a non-default manifest location's clips still resolve.
    overlay_assets_dir: str = "assets/overlays"

    # Master switch — independent of skip_overlays (which exists for the
    # same purpose under a different name; kept for backward compat). If
    # false, the overlay-compositing pass is skipped entirely.
    overlay_enabled: bool = True

    # Master switch for grain specifically (independent of skip_overlays,
    # which disables mood overlays too). Grain itself is also conditional —
    # see OverlayCompositor._should_apply_grain() — this flag is a hard
    # override that skips it regardless of scene composition.
    overlay_grain_enabled: bool = True

    # Per-category switches, same pattern as overlay_grain_enabled. "fog"
    # has no manifest category of its own (aliases to "smoke" — see
    # _MOTION_ALIASES) so it only gates scenes whose overlay was selected
    # via a fog-specific trigger (motion_type="fog" or a fog visual_prompt
    # keyword); smoke-triggered scenes are gated by overlay_smoke_enabled.
    overlay_smoke_enabled: bool = True
    overlay_particles_enabled: bool = True
    overlay_god_rays_enabled: bool = True
    overlay_rain_enabled: bool = True
    overlay_fog_enabled: bool = True

    # ------------------------------------------------------------------
    # Video Debugging
    # ------------------------------------------------------------------

    # Append showinfo filter to per-scene chains for FFmpeg frame-level debugging.
    video_debug_showinfo: bool = False

    # ------------------------------------------------------------------
    # Phase 1.5 — Image QA Gate (verify-images CLI, Task 2.10)
    # ------------------------------------------------------------------

    image_qa_enabled: bool = True

    # Reserved: VisionProvider.review() has no per-call max_tokens param.
    image_qa_max_tokens: int = 200

    # ------------------------------------------------------------------
    # Runtime
    # ------------------------------------------------------------------

    # Reviewed 2026-07-12: zero call sites found — dead field, kept for cleanup pass.
    request_timeout: int = 60

    # ── Shorts (Phase 1A) ───────────────────────────────────────────────

    shorts_target_duration_seconds: float = 52.0
    shorts_max_duration_seconds: float = 60.0

    shorts_scene_count_min: int = 5
    shorts_scene_count_max: int = 9

    shorts_narration_wpm: int = 130

    shorts_min_word_count: int = 90
    shorts_preferred_min_word_count: int = 105
    shorts_preferred_max_word_count: int = 115
    shorts_hard_max_word_count: int = 120

    shorts_validation_overall_threshold: float = 6.5
    shorts_validation_hook_threshold: float = 5.0
    shorts_validation_standalone_threshold: float = 4.0
    shorts_validation_spoiler_max: float = 7.0

    shorts_validation_generic_ai_max: float = 5.0
    shorts_validation_advertising_max: float = 3.0
    shorts_validation_cliche_max: float = 5.0
    shorts_validation_naturalness_min: float = 5.0

    # ── Shorts Phase 1B ──────────────────────────────────────────────────
    shorts_video_width: int = 1080
    shorts_video_height: int = 1920
    shorts_video_fps: int = 30
    shorts_subtitle_play_res_x: int = 1080
    shorts_subtitle_play_res_y: int = 1920
    shorts_bgm_enabled: bool = True

    # ── Scene Continuity Enforcement ────────────────────────────────────
    scene_continuity_enabled: bool = True
    scene_continuity_strict: bool = False
    scene_continuity_max_retries: int = 2
    scene_continuity_prompt_validation: bool = True
    scene_continuity_fail_on_error: bool = False
    scene_continuity_debug: bool = False
