"""YouTube ingestion nodes — acquire_audio, transcribe, translate.

Only reached via the source_url entry route (see agents/graph.py
_route_entry); the script_path / AI-research routes never touch these.
"""

from __future__ import annotations

from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.youtube_ingest.pipeline import (
    AudioAcquisitionPipeline,
    TranscriptionPipeline,
    TranslationPipeline,
)


def acquire_audio_node(state: VideoState) -> dict:
    url = state["source_url"]
    assert url is not None, "acquire_audio_node reached without source_url set"
    AudioAcquisitionPipeline().run(state["project_id"], url)
    return {}


def transcribe_node(state: VideoState) -> dict:
    settings = Settings()
    TranscriptionPipeline(settings).run(state["project_id"])
    return {}


def translate_node(state: VideoState) -> dict:
    settings = Settings()
    base_script = TranslationPipeline(settings).run(state["project_id"])
    return {"script_md": base_script}
