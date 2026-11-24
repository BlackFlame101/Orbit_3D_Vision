"""Detect nearly uniform color in the visible interior of a reconstruction input."""

import numpy as np
from PIL import Image


def has_photographic_variation(image: Image.Image) -> bool:
    """Require a robust spread in at least one RGB channel of opaque pixels."""
    rgba = np.asarray(image.convert("RGBA"))
    foreground = rgba[rgba[..., 3] >= 240, :3]
    if not foreground.size:
        return False
    low, high = np.percentile(foreground, (5, 95), axis=0)
    return bool(np.max(high - low) >= 5)
