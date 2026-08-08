import numpy as np
from typing import List
from .effects.base import BaseEffect


class Compositor:
    def __init__(self, effects: List[BaseEffect]):
        self.effects = effects

    def render_frame(self, base_frame: np.ndarray, t: float) -> np.ndarray:
        frame = base_frame.copy()
        for effect in self.effects:
            frame = effect.apply(frame, t)
        return frame
