import numpy as np


class BaseEffect:
    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        """
        Apply effect to frame at time t.

        Args:
            frame: numpy array (H, W, 3), uint8, BGR color
            t: time in seconds (0.0 = start of clip)

        Returns:
            Modified frame as numpy array, same shape and dtype as input
        """
        raise NotImplementedError
