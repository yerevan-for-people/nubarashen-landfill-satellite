"""CNES GEODES: search and download Spot World Heritage Level-1A scenes.

Search is anonymous; a download needs a GEODES API key in the `X-API-Key`
header (the same header CNES's own pyGeodes client sends). The key is read
from an env file and never printed.

Two catalogue traps, both found against the live API:
- `datetime` on these items is when CNES processed the scene (2020s), not
  when it was taken. The acquisition time is `start_datetime`, so date ranges
  go through a `query` on that field.
- The asset file name carries the imaging mode: `_A_`/`_B_` are SPOT 5's two
  5 m panchromatic modes, `_J_` is 10 m multispectral, `_S_` the HRS stereo pair;
  SPOT 1-3 `_P_` and SPOT 4 `_M_` are their 10 m single-band modes, `_X_`/`_I_`
  the 20 m multispectral ones.
- Every generation's items carry `view:incidence_angle`, the off-vertical
  angle at the ground; only SPOT 5's add `sensor_angle`, the angle at the
  satellite. Ranking uses the one they share.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

SEARCH_URL = "https://geodes-portal.cnes.fr/api/stac/search"
PAGE_LIMIT = 500
TIMEOUT_S = 120
DOWNLOAD_TIMEOUT_S = 900
PROGRESS_EVERY_BYTES = 10 << 20
DOWNLOAD_ATTEMPTS = 5
RETRY_WAIT_S = 30
QUOTA_WAIT_S = 15 * 60
MAX_QUOTA_WAITS = 8

# The imager is HRV on SPOT 1-3, HRVIR on SPOT 4, HRG (and the HRS stereo
# instrument) on SPOT 5; all of them name their mode the same way.
_MODE = re.compile(r"_HR(?:V|VIR|G|S)-\d_(?P<mode>[A-Z])_[A-Z0-9]+_[A-Z0-9]+\.zip$")


@dataclass(frozen=True)
class Sensor:
    """One archive the tool can build a series from."""

    collections: tuple[str, ...]
    # The single-band modes at the finest pixel the sensor has.
    panchromatic_modes: frozenset[str]
    resolution_m: float
    # The `collection` the manifest declares, one of lib/geo/satellite/scene-series.ts.
    manifest_collection: str


SENSORS = {
    "spot5": Sensor(
        collections=("SWH_SPOT5_L1",),
        panchromatic_modes=frozenset({"A", "B"}),
        resolution_m=5,
        manifest_collection="swh-spot5-l1a",
    ),
    "spot1-4": Sensor(
        collections=("SWH_SPOT123_L1", "SWH_SPOT4_L1"),
        panchromatic_modes=frozenset({"P", "M"}),
        resolution_m=10,
        manifest_collection="swh-spot1-4-l1a",
    ),
}


class QuotaExceeded(Exception):
    """GEODES refused the download because the hourly quota is spent."""


class TruncatedDownload(Exception):
    """The server closed the connection before sending the whole file."""


@dataclass(frozen=True)
class SpotScene:
    name: str
    acquired_at: str
    platform: str
    mode: str
    cloud_cover_percent: float
    incidence_angle_deg: float
    download_url: str
    # The scene's ground footprint, its four corners as (lon, lat).
    footprint: tuple[tuple[float, float], ...]

    def contains(self, west: float, south: float, east: float, north: float) -> bool:
        """Whether the whole box lies inside the footprint.

        The footprint is a convex quadrilateral, so the box is inside exactly
        when its four corners are.
        """
        corners = ((west, south), (east, south), (east, north), (west, north))
        return all(_inside_convex(self.footprint, point) for point in corners)


def _inside_convex(polygon: tuple[tuple[float, float], ...], point: tuple[float, float]) -> bool:
    signs = set()
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        cross = (x2 - x1) * (point[1] - y1) - (y2 - y1) * (point[0] - x1)
        if cross != 0:
            signs.add(cross > 0)
    return len(signs) <= 1


def read_api_key(env_file: Path) -> str:
    for line in env_file.read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "GEODES_API_KEY":
            value = value.strip().strip('"').strip("'")
            if value:
                return value
    raise SystemExit(f"GEODES_API_KEY is not set in {env_file}")


def search_scenes(sensor: Sensor, bbox: tuple[float, float, float, float], start: str, end: str) -> list[SpotScene]:
    # One request per collection: GEODES answers a search naming two
    # collections with no features at all.
    return [scene for collection in sensor.collections for scene in _search_collection(sensor, collection, bbox, start, end)]


def _search_collection(
    sensor: Sensor, collection: str, bbox: tuple[float, float, float, float], start: str, end: str
) -> list[SpotScene]:
    # `bbox`, not `intersects`: a point geometry is ignored and the search
    # returns scenes from anywhere.
    body = {
        "collections": [collection],
        "bbox": list(bbox),
        "query": {"start_datetime": {"gte": start, "lte": end}},
        "limit": PAGE_LIMIT,
    }
    request = urllib.request.Request(
        SEARCH_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        payload = json.load(response)
    features = payload["features"]
    if len(features) >= PAGE_LIMIT:
        raise RuntimeError(f"GEODES returned a full page of {len(features)} scenes; narrow the window")

    scenes = []
    for feature in features:
        properties = feature["properties"]
        zips = [(name, asset) for name, asset in feature["assets"].items() if name.endswith(".zip")]
        if len(zips) != 1:
            raise RuntimeError(f"{feature['id']} has {len(zips)} zip assets, expected one")
        name, asset = zips[0]
        mode_match = _MODE.search(name)
        if mode_match is None:
            raise RuntimeError(f"Cannot read the imaging mode from {name}")
        scenes.append(
            SpotScene(
                name=name,
                acquired_at=properties["start_datetime"],
                platform=properties["platform"],
                mode=mode_match.group("mode"),
                cloud_cover_percent=float(properties["eo:cloud_cover"]),
                incidence_angle_deg=float(properties["view:incidence_angle"]),
                download_url=asset["href"],
                footprint=tuple((float(lon), float(lat)) for lon, lat in feature["geometry"]["coordinates"][0][:-1]),
            )
        )
    return scenes


def download(scene: SpotScene, api_key: str, cache_dir: Path) -> Path:
    """The scene's zip, from the cache when it is already there."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / scene.name
    if target.exists():
        return target
    partial = target.with_suffix(".part")
    attempt = 0
    quota_waits = 0
    while True:
        attempt += 1
        try:
            _download_once(scene, api_key, partial)
            break
        except QuotaExceeded:
            # GEODES caps products downloaded per hour per account (HTTP 403,
            # "Downloading products per hour exceeds quota limit"). The cap is
            # not published; waiting it out is the only remedy.
            quota_waits += 1
            if quota_waits > MAX_QUOTA_WAITS:
                raise
            print(f"    hourly download quota reached; waiting {QUOTA_WAIT_S // 60} min ({quota_waits}/{MAX_QUOTA_WAITS})", flush=True)
            time.sleep(QUOTA_WAIT_S)
            attempt -= 1
        except (urllib.error.HTTPError, TruncatedDownload) as error:
            # The endpoint answers 500 intermittently, and sometimes closes a
            # download half way; the same URL works a moment later. Client
            # errors (4xx) are not retried.
            retryable = isinstance(error, TruncatedDownload) or error.code >= 500
            if not retryable or attempt == DOWNLOAD_ATTEMPTS:
                raise
            print(f"    {scene.name[:40]}: {error}, retry {attempt} in {RETRY_WAIT_S} s", flush=True)
            time.sleep(RETRY_WAIT_S)
    partial.rename(target)
    return target


def _download_once(scene: SpotScene, api_key: str, partial: Path) -> None:
    request = urllib.request.Request(scene.download_url, headers={"X-API-Key": api_key})
    try:
        response = urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S)
    except urllib.error.HTTPError as error:
        if error.code == 403:
            body = error.read().decode(errors="replace")
            if "quota" in body.lower():
                raise QuotaExceeded(body) from error
        raise
    with response:
        content_type = response.headers.get("Content-Type", "")
        if "zip" not in content_type:
            raise RuntimeError(f"Download of {scene.name} returned {content_type}, not a zip")
        total = int(response.headers.get("Content-Length", "0"))
        received = 0
        reported = 0
        started = time.monotonic()
        # Ranged requests fail with HTTP 500 here, so an interrupted download
        # starts over; the .part file is simply overwritten.
        with partial.open("wb") as handle:
            while chunk := response.read(1 << 20):
                handle.write(chunk)
                received += len(chunk)
                if received - reported >= PROGRESS_EVERY_BYTES or received == total:
                    reported = received
                    elapsed = time.monotonic() - started
                    print(
                        f"    {scene.name[:40]}: {received >> 20} of {total >> 20} MB, {elapsed:.0f} s",
                        flush=True,
                    )
    if total and received != total:
        raise TruncatedDownload(f"Download of {scene.name} stopped at {received} of {total} bytes")
