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


HISTORICAL_DOCUMENTARY = VisualProfile(
    name="historical_documentary",
    positive_fragments=[
        "historically authentic",
        "period-accurate details",
        "historical architecture",
        "documentary realism",
        "evidence of time's passage",
    ],
    negative_fragments=[],
    lighting="natural period-appropriate lighting, golden-hour chiaroscuro, dusty shafts",
    architecture="historically accurate architecture, period structures, authentic building methods",
    materials="period-appropriate materials, aged wood, iron, stone, parchment",
    atmosphere="authentic historical atmosphere, aged textures, timeless quality",
    camera="historical documentary style, low-angle hero framing, close-up on aged textures",
    color_palette="warm sepia, amber, earth tones, dramatic shadow",
)
