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


MODERN_DOCUMENTARY = VisualProfile(
    name="modern_documentary",
    positive_fragments=[
        "contemporary setting",
        "modern technology",
        "realistic everyday environment",
        "authentic modern life",
    ],
    negative_fragments=[
        "ancient styling",
        "historical costumes",
        "outdated technology",
        "forced historical elements",
    ],
    lighting="modern interior lighting, natural daylight, office fluorescence, city ambient",
    architecture="modern architecture, contemporary design, glass, steel, concrete",
    materials="modern materials, glass, steel, concrete, synthetic fabrics, electronics",
    atmosphere="contemporary, authentic, everyday realism",
    camera="modern documentary style, eye-level observation, natural framing",
    color_palette="neutral, natural, slightly desaturated, gravitas over beauty",
)
