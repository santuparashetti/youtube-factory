from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class SceneConfig:
    image_path: str
    output_path: str
    duration_seconds: float
    fps: int = 30
    resolution: tuple = (1920, 1080)
    effects: List[str] = field(default_factory=list)
    effect_params: dict = field(default_factory=dict)

    # Human figure bounding boxes as fractions of (W, H): (x0, y0, x1, y1)
    # The engine auto-applies these as exclusion zones to all mask-based effects
    # and as exclude_mask for DustParticles. No manual mask surgery needed.
    figure_boxes: List[Tuple[float, float, float, float]] = field(default_factory=list)
