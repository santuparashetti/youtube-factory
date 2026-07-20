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


SYMBOLIC_DOCUMENTARY = VisualProfile(
    name="symbolic_documentary",
    positive_fragments=[
        "timeless",
        "dreamlike",
        "ethereal",
        "abstract",
        "metaphorical",
        "conceptual",
    ],
    negative_fragments=[
        "forced historical constraints",
        "specific cultural artifacts",
        "literal interpretation",
    ],
    lighting="soft ethereal light, ambient glow, volumetric light, misty diffusion",
    architecture="abstract forms, timeless space, non-representational structures",
    materials="ethereal materials, light, shadow, translucent forms",
    atmosphere="dreamlike, transcendent, contemplative, otherworldly",
    camera="symbolic composition, metaphorical framing, abstract visual language",
    color_palette="soft blues, whites, gold accents, pastel tones, luminous highlights",
)
