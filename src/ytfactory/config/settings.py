from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration."""

    # ------------------------------------------------------------------
    # API Keys
    # ------------------------------------------------------------------

    gemini_api_key: str = Field(default="")
    tavily_api_key: str = Field(default="")
    hf_token: str = Field(default="")
    groq_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")
    anthropic_base_url: str = Field(default="https://api.anthropic.com")

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------

    llm_provider: str = "gemini"
    search_provider: str = "tavily"
    tts_provider: str = "edge"
    image_provider: str = "pollinations"

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    gemini_text_model: str = "gemini-2.5-flash"
    gemini_image_model: str = "gemini-3.1-flash-image"

    hf_image_model: str = "black-forest-labs/FLUX.1-schnell"

    groq_model: str = "llama-3.1-8b-instant"
    anthropic_model: str = "claude-haiku-4-5"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # Automatic1111 / SD WebUI
    a1111_base_url: str = "http://localhost:7860"
    a1111_steps: int = 30
    a1111_cfg_scale: float = 7.0
    a1111_sampler: str = "DPM++ 2M Karras"

    # ------------------------------------------------------------------
    # Image Defaults
    # ------------------------------------------------------------------

    # Native YouTube Full HD
    image_width: int = 1920
    image_height: int = 1080

    # ------------------------------------------------------------------
    # Video Defaults
    # ------------------------------------------------------------------

    video_width: int = 1920
    video_height: int = 1080
    video_fps: int = 30

    # ------------------------------------------------------------------
    # Rendering Profile
    # ------------------------------------------------------------------

    # Cinematic quality level applied by MotionPlanner and TransitionPlanner.
    # draft    — static frame, hard cuts (fastest render, no motion)
    # balanced — simple zoom/pan, cross-dissolves (default)
    # cinematic — full emotion-aware motion + transitions, ease_in_out
    # premium   — wider scale ranges, longer fades
    render_profile: str = "balanced"

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

    # Font size in pixels at PlayResX × PlayResY (1920 × 1080)
    subtitle_ass_font_size: int = 52

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

    # Safe margins from the video edges in pixels (1920 × 1080 reference)
    subtitle_ass_margin_l: int = 80
    subtitle_ass_margin_r: int = 80
    subtitle_ass_margin_v: int = 60

    # Subtitle alignment (numpad layout: 2 = bottom-center)
    subtitle_ass_alignment: int = 2

    # Border style: 1 = outline + shadow, 3 = opaque box
    subtitle_ass_border_style: int = 1

    # Script resolution — must match video dimensions
    subtitle_ass_play_res_x: int = 1920
    subtitle_ass_play_res_y: int = 1080

    # Extend the last subtitle cue by this many seconds so it remains visible
    # through the fade-to-black transition at the end of each scene.
    subtitle_tail_extension_seconds: float = 1.0

    # ------------------------------------------------------------------
    # Image Prompt Engine V4 — Debug & Quality Control
    # ------------------------------------------------------------------

    # Write per-scene debug files to workspace/jobs/<id>/images/debug/
    # Saves scene-XXX-original.txt, scene-XXX-optimized.txt, image_prompt_debug.json
    image_prompt_debug: bool = False

    # ------------------------------------------------------------------
    # TTS Debug & Quality Control
    # ------------------------------------------------------------------

    # Write intermediate text files + metadata to workspace/jobs/<id>/tts-debug/
    tts_debug: bool = False

    # Validate every generated audio clip (file size, duration, word-count ratio)
    tts_validate_audio: bool = True

    # Automatically retry synthesis when validation fails
    tts_auto_retry: bool = True

    # Maximum retry attempts per scene (exponential backoff between attempts)
    tts_max_retries: int = 3

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

    # Master enable — False = no BGM (default; opt-in per project)
    bgm_enabled: bool = False

    # BGM category. "auto" selects based on video topic.
    # Options: auto | spiritual | meditation | cinematic_ambient |
    #          emotional_documentary | inspirational | calm_piano | nature_ambient
    bgm_category: str = "auto"

    # Directory containing music files.
    # Layout: <path>/<category>/*.mp3  or  <path>/*.mp3 (flat)
    bgm_library_path: str = "workspace/music"

    # BGM volume relative to full scale during quiet sections (0.0–1.0).
    bgm_volume: float = 0.20

    # Sidechain compress threshold — amplitude above which ducking engages.
    bgm_duck_threshold: float = 0.02

    # Ducking compression ratio (BGM is reduced by this factor under speech).
    bgm_duck_ratio: float = 4.0

    # Milliseconds for ducking to engage after speech onset.
    bgm_duck_attack_ms: int = 200

    # Milliseconds for music to recover after speech ends.
    bgm_duck_release_ms: int = 1000

    # Music fade-in at video start (seconds).
    bgm_fade_in_seconds: float = 3.0

    # Music fade-out at video end (seconds).
    bgm_fade_out_seconds: float = 4.0

    # Crossfade between loop iterations (seconds).
    bgm_crossfade_seconds: float = 2.0

    # Randomly select from available tracks in the category.
    bgm_random_track: bool = True

    # ------------------------------------------------------------------
    # Cinematic Intro
    # ------------------------------------------------------------------

    # Prepend a silent black screen before Scene 1 in the final video.
    # Intentional cinematic pause — does NOT trigger black-frame validation.
    video_intro_enabled: bool = True
    video_intro_seconds: float = 1.5

    # ------------------------------------------------------------------
    # Runtime
    # ------------------------------------------------------------------

    request_timeout: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
