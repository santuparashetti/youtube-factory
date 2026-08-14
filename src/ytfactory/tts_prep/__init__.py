"""TTS Pronunciation Preparation Layer.

Separates canonical script text from TTS pronunciation guidance.
The canonical script is NEVER mutated by this layer.

Pipeline position (after scene splitting, before TTS synthesis):
    Canonical Narration
        ↓
    TTSPreparationService.prepare()   → TTSPreparedScript (hints)
        ↓
    [SSML enhancement — if enabled]   → SSML-wrapped text
        ↓
    apply_pronunciation()             → tts_text with <sub> hints (SSML mode)
        ↓
    TTS provider                      → audio

Usage:
    from ytfactory.tts_prep import TTSPreparationService, apply_pronunciation

    service = TTSPreparationService()
    prepared = service.prepare(scene_narration)
    tts_text = apply_pronunciation(
        tts_text, prepared,
        provider_name=settings.tts_provider,
        ssml_mode=use_ssml,
    )
"""

from .adapter import apply_pronunciation
from .dictionary import reset_cache
from .models import PronunciationHint, TTSPreparedScript
from .preparer import TTSPreparationService

__all__ = [
    "TTSPreparationService",
    "apply_pronunciation",
    "PronunciationHint",
    "TTSPreparedScript",
    "reset_cache",
]
