"""Recompute every published area from the outlines, with the standard library only.

    python3 tools/measure/check_areas.py

Reads data/outlines.geojson, measures each outline again, and compares the
result with the numbers in data/outlines.geojson and data/areas.csv. Exits
with status 1 on any difference larger than the rounding of the published
value.

The measure is the one the published numbers were made with (OpenLayers
`getArea` and `getLength` with an EPSG:4326 geometry): a sphere of radius
6 371 008.8 m, the mean radius of the WGS84 ellipsoid. Area is the spherical
polygon area with great-circle edges; length is the sum of great-circle
distances between consecutive points. On the WGS84 ellipsoid itself the
areas come out a few tenths of a percent different, far inside the stated
uncertainty.

The uncertainty is the perimeter times the pixel size of the frame the
outline was traced on: how much the area changes when the whole line is moved
one pixel outward or inward.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

EARTH_RADIUS_M = 6_371_008.8
SQUARE_METERS_PER_HECTARE = 10_000
# Published values are rounded to 0.01 ha; allow that plus float noise.
TOLERANCE_HA = 0.005 + 1e-9

ROOT = Path(__file__).resolve().parents[2]


def spherical_area_m2(ring: list[list[float]]) -> float:
    """Area of a closed lon/lat ring on the sphere.

    R. G. Chamberlain and W. H. Duquette, "Some Algorithms for Polygons on a
    Sphere", JPL Publication 07-03, 2007, https://trs.jpl.nasa.gov/handle/2014/40409
    """
    total = 0.0
    x1, y1 = ring[-1]
    for x2, y2 in ring:
        total += math.radians(x2 - x1) * (2 + math.sin(math.radians(y1)) + math.sin(math.radians(y2)))
        x1, y1 = x2, y2
    return abs(total * EARTH_RADIUS_M * EARTH_RADIUS_M / 2)


def great_circle_m(start: list[float], end: list[float]) -> float:
    lat1, lat2 = math.radians(start[1]), math.radians(end[1])
    half_lat_delta = (lat2 - lat1) / 2
    half_lon_delta = math.radians(end[0] - start[0]) / 2
    a = math.sin(half_lat_delta) ** 2 + math.sin(half_lon_delta) ** 2 * math.cos(lat1) * math.cos(lat2)
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def perimeter_m(ring: list[list[float]]) -> float:
    return sum(great_circle_m(start, end) for start, end in zip(ring, ring[1:]))


def main() -> int:
    outlines = json.loads((ROOT / "data" / "outlines.geojson").read_text())
    with (ROOT / "data" / "areas.csv").open(newline="") as handle:
        table = {row["date"]: row for row in csv.DictReader(handle)}

    problems = []
    for feature in outlines["features"]:
        properties = feature["properties"]
        date = properties["date"]
        [ring] = feature["geometry"]["coordinates"]
        if ring[0] != ring[-1]:
            problems.append(f"{date}: ring is not closed")
            continue
        area_ha = spherical_area_m2(ring) / SQUARE_METERS_PER_HECTARE
        uncertainty_ha = perimeter_m(ring) * properties["meters_per_pixel"] / SQUARE_METERS_PER_HECTARE
        row = table.pop(date, None)
        if row is None:
            problems.append(f"{date}: in outlines.geojson but not in areas.csv")
            continue
        for name, computed, published in (
            ("area", area_ha, properties["area_ha"]),
            ("area in areas.csv", area_ha, float(row["area_ha"])),
            ("uncertainty", uncertainty_ha, properties["uncertainty_ha"]),
            ("uncertainty in areas.csv", uncertainty_ha, float(row["uncertainty_ha"])),
        ):
            if abs(computed - published) > TOLERANCE_HA:
                problems.append(f"{date}: {name} recomputes to {computed:.4f} ha, published {published}")
        print(f"{date}  {area_ha:7.2f} ha  +/- {uncertainty_ha:.2f}")
    problems.extend(f"{date}: in areas.csv but not in outlines.geojson" for date in table)

    if problems:
        print("\n".join(["", "MISMATCHES:", *problems]), file=sys.stderr)
        return 1
    print(f"\nAll {len(outlines['features'])} areas reproduce.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
