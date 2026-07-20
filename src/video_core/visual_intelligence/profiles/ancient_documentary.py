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


ANCIENT_DOCUMENTARY = VisualProfile(
    name="ancient_documentary",
    positive_fragments=[
        "historically authentic",
        "ancient architecture",
        "stone temples",
        "natural materials",
        "traditional clothing",
        "cinematic documentary realism",
    ],
    negative_fragments=[
        "drones",
        "aircraft",
        "helicopters",
        "cars",
        "roads",
        "smartphones",
        "cameras",
        "tripods",
        "microphones",
        "satellite dishes",
        "power lines",
        "glass buildings",
        "modern clothing",
        "plastic",
        "electronics",
        "television",
        "laptops",
    ],
    lighting="natural sunlight, oil lamp glow, golden hour, pre-dawn blue",
    architecture="ancient Indian temple architecture, stone columns, carved lintels, verandas, stepped roofs",
    materials="stone, wood, clay, natural fibers, brass, bronze, terracotta",
    atmosphere="sacred, timeless, weathered, organic, spiritual",
    camera="documentary realism, environmental portraiture, natural lighting, contemplative wide shots",
    color_palette="warm amber, ochre, earth tones, indigo, saffron, deep maroon",
)
