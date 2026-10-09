"""Placing a SPOT scene window on a reference frame.

The corner model in `dimap.py` puts a window within about a hundred meters;
relief displacement alone is that much for a scene taken a few degrees off
nadir over ground a kilometer above the ellipsoid. That residual is almost a
pure translation over a frame this small, so it is found by sliding the scene
over a reference image of the same ground and keeping the offset where their
edges agree best.

Edges rather than brightness: the reference is a color image from another
decade and season, but a road, a ravine or a village street sits where it sat.
The part of the frame that is expected to change (the landfill itself) is
masked out of the score.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

EDGE_SMOOTHING_PX = 1.0


@dataclass(frozen=True)
class Match:
    shift_x_px: int
    shift_y_px: int
    score: float
    # The 99th percentile of every candidate's score. A real match stands well
    # clear of it; a peak that does not is noise that happened to win.
    background_p99: float

    @property
    def distinctness(self) -> float:
        return self.score / self.background_p99 if self.background_p99 > 0 else float("inf")


def edge_strength(image: np.ndarray) -> np.ndarray:
    smoothed = ndimage.gaussian_filter(image.astype(np.float32), EDGE_SMOOTHING_PX)
    magnitude = np.hypot(ndimage.sobel(smoothed, 0), ndimage.sobel(smoothed, 1))
    return (magnitude - magnitude.mean()) / (magnitude.std() + 1e-6)


def best_offset(search: np.ndarray, reference: np.ndarray, mask: np.ndarray) -> Match:
    """Where `reference` fits inside the larger `search` image.

    Both are already on the same pixel size. `mask` is True where the
    reference should count. Returns the top-left offset of the best fit,
    measured from the centered position.
    """
    reference_edges = edge_strength(reference)
    search_edges = edge_strength(search)
    weights = mask.astype(np.float32)
    weighted_reference = reference_edges * weights
    height, width = reference.shape
    rows = search.shape[0] - height + 1
    cols = search.shape[1] - width + 1
    if rows < 1 or cols < 1:
        raise ValueError("The search image must be larger than the reference")

    scores = np.empty((rows, cols), dtype=np.float32)
    for dy in range(rows):
        for dx in range(cols):
            window = search_edges[dy : dy + height, dx : dx + width]
            masked = window[mask]
            scores[dy, dx] = float((window * weighted_reference).sum() / (masked.std() * mask.sum() + 1e-6))

    dy, dx = np.unravel_index(np.argmax(scores), scores.shape)
    center_y, center_x = (rows - 1) // 2, (cols - 1) // 2
    return Match(
        shift_x_px=int(dx) - center_x,
        shift_y_px=int(dy) - center_y,
        score=float(scores[dy, dx]),
        background_p99=float(np.percentile(scores, 99)),
    )
