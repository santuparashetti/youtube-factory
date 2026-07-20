from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class VisualProfile:
    name: str
    positive_fragments: list[str] = None
    negative_fragments: list[str] = None
    lighting: str = ""
    architecture: str = ""
    materials: str = ""
    atmosphere: str = ""
    camera: str = ""
    color_palette: str = ""

    def __post_init__(self) -> None:
        if self.positive_fragments is None:
            self.positive_fragments = []
        if self.negative_fragments is None:
            self.negative_fragments = []


TRANSITIONAL_DOCUMENTARY = VisualProfile(
    name="transitional_documentary",
    positive_fragments=[
        "intentional coexistence of ancient and modern",
        "contrast between eras",
        "bridge between worlds",
        "parallel timelines",
    ],
    negative_fragments=[],
    lighting="contrasting lighting from both eras, modern fluorescent alongside warm oil lamp",
    architecture="blend of ancient and modern architecture, temple beside skyscraper",
    materials="mixed natural and modern materials, stone and glass, wood and steel",
    atmosphere="transitional, contemplative contrast, dialogue between worlds",
    camera="documentary comparison style, split framing, intentional juxtaposition",
    color_palette="warm ancient tones, cool modern tones, saffron and steel grey",
)
