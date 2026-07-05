from dataclasses import dataclass, field
from datetime import datetime


def default_stage():
    return {
        "status": "pending",
        "started_at": None,
        "completed_at": None,
        "error": None,
    }


@dataclass(slots=True)
class Project:
    id: str
    title: str

    language: str = "en"

    status: str = "created"

    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    stages: dict = field(
        default_factory=lambda: {
            "research": default_stage(),
            "script": default_stage(),
            "scenes": default_stage(),
            "images": default_stage(),
            "audio": default_stage(),
            "subtitles": default_stage(),
            "video": default_stage(),
            "publish": default_stage(),
        }
    )
