"""Geometry of a SPOT Level-1A scene, from its DIMAP metadata.

A Level-1A scene is the raw sensor grid: rows and columns, not a map. Its
METADATA.DIM gives the ground position of the four corners. Over a couple of
kilometers the mapping between them is close to affine, so a site-sized window
is placed with an affine fit to the bilinear corner model, and whatever error
that leaves (mostly relief displacement, which shifts the whole window) is
taken out afterwards by `register.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

_VERTEX_TAGS = ("FRAME_LON", "FRAME_LAT", "FRAME_COL", "FRAME_ROW")


@dataclass(frozen=True)
class SceneGeometry:
    columns: int
    rows: int
    # (col, row) of each corner -> (lon, lat)
    corners: dict[tuple[int, int], tuple[float, float]]
    imaging_date: str
    # Off-vertical angle of the view at the ground, signed by side. Every SPOT
    # generation states it; only SPOT 5 adds VIEWING_ANGLE, the angle at the
    # satellite. Relief displacement on the ground goes with this one.
    incidence_angle_deg: float

    def forward(self, col: np.ndarray, row: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Sensor grid -> (lon, lat), bilinear between the four corners."""
        u = (col - 1) / (self.columns - 1)
        v = (row - 1) / (self.rows - 1)
        p00 = self.corners[(1, 1)]
        p10 = self.corners[(self.columns, 1)]
        p11 = self.corners[(self.columns, self.rows)]
        p01 = self.corners[(1, self.rows)]
        weights = ((1 - u) * (1 - v), u * (1 - v), u * v, (1 - u) * v)
        lon = sum(w * p[0] for w, p in zip(weights, (p00, p10, p11, p01)))
        lat = sum(w * p[1] for w, p in zip(weights, (p00, p10, p11, p01)))
        return lon, lat

    def local_inverse(self, near_lon: float, near_lat: float, span_px: int = 1500):
        """An affine (lon, lat) -> (col, row) fitted around one ground point.

        Found by fitting the forward model on a grid of sensor positions near
        the point; raises if the point is not inside the scene at all.
        """
        col_guess, row_guess = self._coarse_position(near_lon, near_lat)
        cols = np.linspace(col_guess - span_px, col_guess + span_px, 25)
        rows = np.linspace(row_guess - span_px, row_guess + span_px, 25)
        grid_cols, grid_rows = np.meshgrid(cols, rows)
        lon, lat = self.forward(grid_cols.ravel(), grid_rows.ravel())
        design = np.c_[lon, lat, np.ones(lon.size)]
        coef_col, *_ = np.linalg.lstsq(design, grid_cols.ravel(), rcond=None)
        coef_row, *_ = np.linalg.lstsq(design, grid_rows.ravel(), rcond=None)

        def inverse(lon_in: np.ndarray, lat_in: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            col = coef_col[0] * lon_in + coef_col[1] * lat_in + coef_col[2]
            row = coef_row[0] * lon_in + coef_row[1] * lat_in + coef_row[2]
            return col, row

        return inverse

    def _coarse_position(self, lon: float, lat: float) -> tuple[float, float]:
        cols = np.linspace(1, self.columns, 241)
        rows = np.linspace(1, self.rows, 241)
        grid_cols, grid_rows = np.meshgrid(cols, rows)
        grid_lon, grid_lat = self.forward(grid_cols, grid_rows)
        distance = np.hypot(grid_lon - lon, grid_lat - lat)
        row_index, col_index = np.unravel_index(np.argmin(distance), distance.shape)
        last = len(cols) - 1
        if row_index in (0, last) or col_index in (0, last):
            # The closest sample on the scene's own border means the point lies
            # beyond it. Windows that are only partly inside are caught later,
            # when every sampled position is checked against the grid.
            raise ValueError(f"({lon}, {lat}) is not inside the scene")
        return float(grid_cols[row_index, col_index]), float(grid_rows[row_index, col_index])


def read_scene_geometry(metadata_text: str) -> SceneGeometry:
    frame_start = metadata_text.index("<Dataset_Frame>")
    frame_end = metadata_text.index("</Dataset_Frame>")
    frame = metadata_text[frame_start:frame_end]
    corners: dict[tuple[int, int], tuple[float, float]] = {}
    for vertex in frame.split("<Vertex>")[1:]:
        lon, lat, col, row = (_tag(vertex, tag) for tag in _VERTEX_TAGS)
        corners[(int(col), int(row))] = (lon, lat)
    columns = int(_tag(metadata_text, "NCOLS"))
    rows = int(_tag(metadata_text, "NROWS"))
    expected = {(1, 1), (columns, 1), (columns, rows), (1, rows)}
    if set(corners) != expected:
        raise ValueError(f"Dataset_Frame corners {sorted(corners)} are not the scene's four corners")
    date_match = re.search(r"<IMAGING_DATE>([^<]+)</IMAGING_DATE>", metadata_text)
    if date_match is None:
        raise ValueError("METADATA.DIM has no IMAGING_DATE")
    return SceneGeometry(
        columns=columns,
        rows=rows,
        corners=corners,
        imaging_date=date_match.group(1),
        incidence_angle_deg=_tag(metadata_text, "INCIDENCE_ANGLE"),
    )


def _tag(text: str, tag: str) -> float:
    match = re.search(f"<{tag}>([^<]+)</{tag}>", text)
    if match is None:
        raise ValueError(f"METADATA.DIM has no {tag}")
    return float(match.group(1))
