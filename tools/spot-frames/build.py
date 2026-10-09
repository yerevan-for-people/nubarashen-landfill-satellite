"""Build a SPOT frame series of a site, aligned to an existing Sentinel-2 series.

For each year: search the summer's single-band scenes of the chosen sensor
(SPOT 5 at 5 m, or SPOT 1-4 at 10 m), take them
clearest first, cut the series frame out of the first one that the site sits
fully inside and that matches the reference unambiguously, and write it as a
PNG plus a manifest entry in the shape `lib/geo/satellite/scene-series.ts`
reads.

Run from the repository root (the downloads are untrusted data, so the script
lives outside the cache it reads, and -P keeps the cache off the import path):

    python3 -P tools/spot-frames/build.py \\
        --reference-series "app/[locale]/topics/(content)/waste/sentinel-scenes.json" \\
        --manifest "app/[locale]/topics/(content)/waste/spot-scenes.json" \\
        --asset-base https://assets.yfp.am/topics/waste/spot \\
        --cache playground/spot/cache --out playground/spot/frames \\
        --decisions "app/[locale]/topics/(content)/waste/spot-decisions.json" \\
        --env-file .env --sensor spot5 --years 2003-2014

Every scene it looks at is recorded in the decisions file, accepted with the
shift that placed it or rejected with the reason. A rerun skips rejected
scenes without downloading them (pass --recheck to look again), and for an
accepted one it recomputes the shift and refuses to continue if it differs
from the recorded one.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dimap import SceneGeometry, read_scene_geometry  # noqa: E402
from geodes import SENSORS, Sensor, SpotScene, download, read_api_key, search_scenes  # noqa: E402
from register import Match, best_offset  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

METERS_PER_DEGREE_LAT = 111_320
SEARCH_MARGIN_M = 600
# The landfill changes between reference and scene; keep it and a band
# around it out of the match.
MASK_BUFFER_M = 100
# A true match scored at least twice the 99th percentile of all offsets in
# every scene checked by hand; anything closer is not trusted.
MIN_DISTINCTNESS = 2.0
# Cloud is reported for the whole 60 km scene, which says little about a
# 2 km frame: a 5-degree scene at 37% matched better than any other. A frame
# that is cloudy over the site does not match clearly, and every frame is
# checked by eye; a defect found that way is recorded as rejected_by_eye.
MAX_SCENE_CLOUD_PERCENT = 50
# Bumped whenever the search changes, so automatic rejections made by an
# older search are looked at again instead of trusted.
METHOD_VERSION = 2
# The wide look for scenes whose corners are far off: 20 m pixels, as wide as
# the scene allows. `_DT_` products were found 0.9-1.3 km off.
COARSE_SCALE = 2
COARSE_MARGINS_M = (2500, 2000, 1500, 1000)
# Around a known position, a short fine search is enough.
REFINE_MARGIN_M = 200
# Scenes of one pass differ in catalog incidence angle by around 0.0001 deg;
# ranking on that noise would pick between them arbitrarily.
ANGLE_RANKING_DECIMALS = 1
SEASON = ("06-01", "09-30")
STRETCH_PERCENTILES = (1, 99)
# The assets CDN refuses Python's default User-Agent.
USER_AGENT = "yfp-spot-frames/1 (+https://yfp.am)"


def main() -> None:
    args = parse_args()
    sensor = SENSORS[args.sensor]
    reference_series = json.loads(Path(args.reference_series).read_text())
    frame = reference_series["frame"]
    outline = reference_series["outline"]
    reference = fetch_reference(reference_series)
    reference_url = reference_series["scenes"][0]["url"]
    decisions = load_decisions(Path(args.decisions), reference_url)
    api_key = read_api_key(Path(args.env_file))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(args.cache)

    first_year, last_year = (int(part) for part in args.years.split("-"))
    scenes = []
    for year in range(first_year, last_year + 1):
        candidates = [
            scene
            for scene in search_scenes(
                sensor,
                tuple(frame["bbox"]),
                f"{year}-{SEASON[0]}T00:00:00Z",
                f"{year}-{SEASON[1]}T23:59:59Z",
            )
            if scene.mode in sensor.panchromatic_modes
        ]
        # Skip, before spending download quota on it, any scene whose
        # footprint does not hold the frame plus the search margin: the same
        # area `sample` needs, since a correction never leaves that margin.
        needed = expanded_box(frame["bbox"], SEARCH_MARGIN_M)
        outside = [scene for scene in candidates if not scene.contains(*needed)]
        candidates = [scene for scene in candidates if scene.contains(*needed)]
        if outside:
            print(f"  skipping {len(outside)} scenes whose footprint misses the site", flush=True)
        # Most vertical first among the acceptably clear: a single shift
        # cannot undo the relief distortion of a steep view, where ridges and
        # ravine floors move by different amounts. The name is the last key:
        # the A and B files of one pass tie on everything else, and the
        # catalog returns them in varying order.
        candidates = [scene for scene in candidates if scene.cloud_cover_percent <= MAX_SCENE_CLOUD_PERCENT]
        candidates.sort(
            key=lambda s: (
                round(abs(s.incidence_angle_deg), ANGLE_RANKING_DECIMALS),
                s.cloud_cover_percent,
                s.acquired_at,
                s.name,
            )
        )
        print(f"{year}: {len(candidates)} candidate {sensor.resolution_m:g} m scenes", flush=True)
        for scene in candidates:
            known = decisions["scenes"].get(scene.name)
            if known is not None and known["status"] == "rejected_by_eye":
                print(f"  {scene.name}: rejected by eye ({known['note']}), skipped", flush=True)
                continue
            current = known is not None and known.get("method") == METHOD_VERSION
            if current and known["status"] != "accepted" and not args.recheck:
                print(f"  {scene.name}: rejected before ({known['status']}), skipped", flush=True)
                continue
            decision, result = try_scene(scene, sensor, api_key, cache_dir, frame, outline, reference)
            if current and known["status"] == "accepted" and decision["status"] == "accepted":
                recorded = (known["shiftEastMeters"], known["shiftNorthMeters"])
                found = (decision["shiftEastMeters"], decision["shiftNorthMeters"])
                if recorded != found:
                    raise RuntimeError(f"{scene.name}: shift {found} differs from the recorded {recorded}")
            decisions["scenes"][scene.name] = {**decision, "method": METHOD_VERSION, "checkedOn": date.today().isoformat()}
            save_decisions(Path(args.decisions), decisions)
            if result is None:
                continue
            image, incidence_angle_deg, residual = result
            day = scene.acquired_at[:10]
            image.save(out_dir / f"{day}.png", optimize=True)
            scenes.append(
                {
                    "year": year,
                    "acquiredOn": day,
                    "sceneId": scene.name.removesuffix(".zip"),
                    "cloudCoverPercent": scene.cloud_cover_percent,
                    "url": f"{args.asset_base}/{day}.png",
                    "registration": {
                        "incidenceAngleDeg": round(incidence_angle_deg, 1),
                        "shiftEastMeters": decision["shiftEastMeters"],
                        "shiftNorthMeters": decision["shiftNorthMeters"],
                        "distinctness": decision["distinctness"],
                        "referenceUrl": reference_url,
                    },
                }
            )
            print(
                f"  {day} {scene.mode} at {incidence_angle_deg:+.1f} deg: shifted {decision['shiftEastMeters']} m east, "
                f"{decision['shiftNorthMeters']} m north; distinctness {decision['distinctness']:.2f}; "
                f"residual after correction {residual} px",
                flush=True,
            )
            break
        else:
            print(f"  {year}: no usable scene", flush=True)

    width_px = round(frame["widthPx"] * frame["metersPerPixel"] / sensor.resolution_m)
    height_px = round(frame["heightPx"] * frame["metersPerPixel"] / sensor.resolution_m)
    manifest = {
        "retrievedOn": date.today().isoformat(),
        "collection": sensor.manifest_collection,
        "product": "panchromatic",
        "frame": {
            "bbox": frame["bbox"],
            "widthPx": width_px,
            "heightPx": height_px,
            "metersPerPixel": frame["widthPx"] * frame["metersPerPixel"] / width_px,
        },
        "outline": outline,
        "scenes": scenes,
    }
    Path(args.manifest).write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{len(scenes)} scenes; manifest written to {args.manifest}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for name in ("reference-series", "manifest", "decisions", "asset-base", "cache", "out", "env-file", "years"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--sensor", required=True, choices=sorted(SENSORS))
    parser.add_argument("--recheck", action="store_true", help="look again at scenes rejected before")
    return parser.parse_args()


def load_decisions(path: Path, reference_url: str) -> dict:
    """The record of every scene checked against this reference.

    Decisions made against another reference image do not carry over: a
    shift is only meaningful relative to the frame it was measured on.
    """
    if not path.exists():
        return {"referenceUrl": reference_url, "scenes": {}}
    decisions = json.loads(path.read_text())
    if decisions["referenceUrl"] != reference_url:
        raise SystemExit(
            f"{path} was made against {decisions['referenceUrl']}, not {reference_url}; move it aside to start over"
        )
    return decisions


def save_decisions(path: Path, decisions: dict) -> None:
    ordered = {"referenceUrl": decisions["referenceUrl"], "scenes": dict(sorted(decisions["scenes"].items()))}
    path.write_text(json.dumps(ordered, indent=2) + "\n")


def fetch_reference(series: dict) -> np.ndarray:
    """The first frame of the reference series, as grey levels on its own 10 m grid."""
    url = series["scenes"][0]["url"]
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        image = Image.open(io.BytesIO(response.read())).convert("RGB")
    expected = (series["frame"]["widthPx"], series["frame"]["heightPx"])
    if image.size != expected:
        raise RuntimeError(f"Reference {url} is {image.size}, the series frame is {expected}")
    return np.asarray(image, dtype=np.float32).mean(axis=2)


def try_scene(
    scene: SpotScene, sensor: Sensor, api_key: str, cache_dir: Path, frame: dict, outline: dict, reference: np.ndarray
):
    zip_path = download(scene, api_key, cache_dir)
    geometry, imagery = open_scene(zip_path)
    west, south, east, north = frame["bbox"]
    try:
        inverse = geometry.local_inverse((west + east) / 2, (south + north) / 2)
    except ValueError:
        print(f"  {scene.name}: site is outside the scene", flush=True)
        return {"status": "outside_scene"}, None

    mask = outside_outline_mask(outline, frame, MASK_BUFFER_M)
    search = Search(imagery, geometry, inverse, frame, reference, mask, sensor.resolution_m)

    fine = search.around(0, 0, SEARCH_MARGIN_M, scale=1)
    if fine is None:
        print(f"  {scene.name}: site is at the edge of the scene", flush=True)
        return {"status": "site_at_edge"}, None
    match, offset_east_m, offset_north_m = fine
    if match.distinctness < MIN_DISTINCTNESS:
        # Some products (the `_DT_` ones) carry corner coordinates a kilometer
        # or more off, beyond the fine search. Look wider at half the
        # resolution, then refine around what that finds.
        coarse = search.widest(COARSE_MARGINS_M, scale=COARSE_SCALE)
        if coarse is None or coarse[0].distinctness < MIN_DISTINCTNESS:
            best = max(match.distinctness, coarse[0].distinctness if coarse else 0)
            print(f"  {scene.name}: no clear match (distinctness {best:.2f})", flush=True)
            return {"status": "no_clear_match", "distinctness": round(best, 2)}, None
        coarse_match, coarse_east_m, coarse_north_m = coarse
        refined = search.around(coarse_east_m, coarse_north_m, REFINE_MARGIN_M, scale=1)
        if refined is None:
            return {"status": "site_at_edge"}, None
        _, offset_east_m, offset_north_m = refined
        # Distinctness means nothing in a short window centered on the match,
        # where every position sits on the peak's shoulder; the wide search
        # already showed the match is clear. What the refinement must show is
        # a peak inside its window rather than pressed against the edge.
        moved = max(abs(offset_east_m - coarse_east_m), abs(offset_north_m - coarse_north_m))
        if moved >= REFINE_MARGIN_M:
            print(f"  {scene.name}: refinement ran to the edge of its window ({moved:.0f} m)", flush=True)
            return {"status": "no_clear_match", "distinctness": round(coarse_match.distinctness, 2)}, None
        match = coarse_match

    # Self-check: searched again around the corrected position, the frame
    # must match with no shift left.
    check = search.around(offset_east_m, offset_north_m, REFINE_MARGIN_M, scale=1)
    if check is None:
        return {"status": "site_at_edge"}, None
    _, check_east_m, check_north_m = check
    residual = round(max(abs(check_east_m - offset_east_m), abs(check_north_m - offset_north_m)) / frame["metersPerPixel"])
    if residual > 1:
        raise RuntimeError(f"{scene.name}: {residual} px of shift left after correcting; the sign convention is wrong")

    pixels = search.frame_pixels(offset_east_m, offset_north_m)
    if pixels is None:
        return {"status": "site_at_edge"}, None
    decision = {
        "status": "accepted",
        "shiftEastMeters": round(offset_east_m),
        "shiftNorthMeters": round(offset_north_m),
        "distinctness": round(match.distinctness, 2),
    }
    return decision, (Image.fromarray(stretch(pixels)), geometry.incidence_angle_deg, residual)


class Search:
    """Matching one scene against the reference around a chosen position.

    Positions are offsets in meters from where the corner model puts the
    frame: east and north. `scale` 2 works on 20 m pixels instead of the
    reference's 10 m, for the wide, coarse look.
    """

    def __init__(self, imagery, geometry, inverse, frame, reference, mask, resolution_m: float):
        self.imagery, self.geometry, self.inverse = imagery, geometry, inverse
        self.resolution_m = resolution_m
        self.frame = frame
        self.west, self.south, self.east, self.north = frame["bbox"]
        self.meters_per_lon = METERS_PER_DEGREE_LAT * math.cos(math.radians((self.south + self.north) / 2))
        self.reference, self.mask = reference, mask

    def around(self, east_m: float, north_m: float, margin_m: float, scale: int):
        """(match, total east m, total north m), or None when the window leaves the scene."""
        reference, mask = self.reference, self.mask
        if scale > 1:
            reference = ndimage.zoom(reference, 1 / scale, order=1)
            mask = ndimage.zoom(mask.astype(np.float32), 1 / scale, order=0) > 0.5
        pixel_m = self.frame["metersPerPixel"] * scale
        margin_px = round(margin_m / pixel_m)
        height, width = reference.shape
        grid = ground_grid(
            self.west + (east_m - margin_px * pixel_m) / self.meters_per_lon,
            self.north + (north_m + margin_px * pixel_m) / METERS_PER_DEGREE_LAT,
            width + 2 * margin_px,
            height + 2 * margin_px,
            (self.east - self.west) / width,
            (self.north - self.south) / height,
        )
        window = sample(self.imagery, self.geometry, self.inverse, *grid, averaging_px=pixel_m / self.resolution_m)
        if window is None:
            return None
        match = best_offset(window, reference, mask)
        # The reference's ground was found `shift` pixels from the window's
        # center, so it lies that much further east and further south.
        return match, east_m + match.shift_x_px * pixel_m, north_m - match.shift_y_px * pixel_m

    def widest(self, margins_m, scale: int):
        """The search at the largest margin that still fits inside the scene."""
        for margin_m in margins_m:
            result = self.around(0, 0, margin_m, scale)
            if result is not None:
                return result
        return None

    def frame_pixels(self, east_m: float, north_m: float):
        width = round(self.frame["widthPx"] * self.frame["metersPerPixel"] / self.resolution_m)
        height = round(self.frame["heightPx"] * self.frame["metersPerPixel"] / self.resolution_m)
        grid = ground_grid(
            self.west + east_m / self.meters_per_lon,
            self.north + north_m / METERS_PER_DEGREE_LAT,
            width,
            height,
            (self.east - self.west) / width,
            (self.north - self.south) / height,
        )
        return sample(self.imagery, self.geometry, self.inverse, *grid, averaging_px=1)


def open_scene(zip_path: Path) -> tuple[SceneGeometry, Image.Image]:
    """Metadata and imagery of a SPOT DIMAP zip, extracted once next to it."""
    extracted = zip_path.with_suffix("")
    metadata_path = extracted / "METADATA.DIM"
    imagery_path = extracted / "IMAGERY.TIF"
    if not imagery_path.exists():
        extracted.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as archive:
            for member, target in (("SCENE01/METADATA.DIM", metadata_path), ("SCENE01/IMAGERY.TIF", imagery_path)):
                target.write_bytes(archive.read(member))
    geometry = read_scene_geometry(metadata_path.read_text(errors="replace"))
    return geometry, Image.open(imagery_path)


def expanded_box(bbox, meters: float) -> tuple[float, float, float, float]:
    west, south, east, north = bbox
    meters_per_lon = METERS_PER_DEGREE_LAT * math.cos(math.radians((south + north) / 2))
    return (
        west - meters / meters_per_lon,
        south - meters / METERS_PER_DEGREE_LAT,
        east + meters / meters_per_lon,
        north + meters / METERS_PER_DEGREE_LAT,
    )


def ground_grid(west, north, width, height, lon_step, lat_step):
    lons = west + (np.arange(width) + 0.5) * lon_step
    lats = north - (np.arange(height) + 0.5) * lat_step
    return np.meshgrid(lons, lats)


def sample(imagery: Image.Image, geometry: SceneGeometry, inverse, lon, lat, averaging_px: float):
    """Scene grey levels at ground positions, or None if any falls off the scene."""
    col, row = inverse(lon, lat)
    if col.min() < 1 or row.min() < 1 or col.max() > geometry.columns or row.max() > geometry.rows:
        return None
    left, top = int(col.min()) - 2, int(row.min()) - 2
    right, bottom = int(col.max()) + 3, int(row.max()) + 3
    window = np.asarray(imagery.crop((left - 1, top - 1, right, bottom)), dtype=np.float32)
    if averaging_px > 1:
        window = ndimage.uniform_filter(window, size=round(averaging_px))
    return ndimage.map_coordinates(window, [row - top, col - left], order=1)


def outside_outline_mask(outline: dict, frame: dict, buffer_m: float) -> np.ndarray:
    west, south, east, north = frame["bbox"]
    width, height = frame["widthPx"], frame["heightPx"]
    points = [((lon - west) / (east - west) * width, (north - lat) / (north - south) * height) for lon, lat in outline["ring"]]
    canvas = Image.new("L", (width, height), 0)
    ImageDraw.Draw(canvas).polygon(points, fill=1)
    inside = np.asarray(canvas, dtype=bool)
    grown = ndimage.binary_dilation(inside, iterations=round(buffer_m / frame["metersPerPixel"]))
    return ~grown


def stretch(pixels: np.ndarray) -> np.ndarray:
    low, high = np.percentile(pixels, STRETCH_PERCENTILES)
    return np.clip((pixels - low) / (high - low) * 255, 0, 255).astype(np.uint8)


if __name__ == "__main__":
    main()
