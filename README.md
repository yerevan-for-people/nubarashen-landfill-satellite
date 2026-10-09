# Nubarashen landfill from orbit

[Русский](README.ru.md) · [Հայերեն](README.hy.md)

The Nubarashen landfill on the southern edge of Yerevan (40.10733 N,
44.54839 E) receives almost all of the city's waste. This repository is
the record behind the satellite section of
[the Yerevan for People page about it](https://yfp.am/en/topics/waste):
31 summer satellite images taken between 1986 and 2026, the
edge of the dump outlined on each, and the area of every outline.

On 1986-08-06 the traced area was 12.0 ha. On 2026-08-23 it
was 32.8 ha.

Version 1.0.0, released 2026-10-09.

## What is in the repository

| Path                           | Contents                                                                                   |
| ------------------------------ | ------------------------------------------------------------------------------------------ |
| `data/areas.csv`               | One row per traced image: date, satellite, area and its uncertainty.                       |
| `data/outlines.geojson`        | The traced outlines, one polygon per image, with the same numbers as properties.           |
| `data/frames.csv`              | Every published image: scene identifier, cloud cover, view angle, alignment shift, file.   |
| `data/frames/`                 | The images themselves, one folder per satellite and product.                               |
| `data/site.geojson`            | The bounds every image is cut to, and the landfill's outline in OpenStreetMap.             |
| `data/series/`                 | The manifests the images were built from, as the website reads them.                       |
| `data/scene-decisions/`        | Every SPOT scene the tool looked at, accepted with its shift or rejected with the reason.  |
| `methods/sentinel-2/`          | The exact Copernicus Process API request and evalscript behind each Sentinel-2 image.      |
| `tools/spot-frames/`           | The tool that finds, aligns and cuts the SPOT scenes.                                      |
| `tools/measure/check_areas.py` | Recomputes every area and uncertainty from the outlines and compares them with the tables. |

## Results

| Image date | Satellite | Area, ha | Oblique view |
| --- | --- | --- | --- |
| 1986-08-06 | SPOT 1–4 | 12.0 ± 1.3 |  |
| 1989-07-28 | SPOT 1–4 | 15.9 ± 1.6 |  |
| 1990-09-04 | SPOT 1–4 | 16.1 ± 1.5 |  |
| 1991-09-29 | SPOT 1–4 | 15.5 ± 1.5 |  |
| 1992-09-06 | SPOT 1–4 | 19.2 ± 1.7 |  |
| 1994-08-17 | SPOT 1–4 | 19.6 ± 1.7 |  |
| 1997-08-26 | SPOT 1–4 | 21.7 ± 1.8 |  |
| 1999-07-02 | SPOT 1–4 | 21.9 ± 1.8 |  |
| 2000-07-26 | SPOT 1–4 | 21.7 ± 1.8 |  |
| 2002-08-19 | SPOT 1–4 | 22.3 ± 1.8 | yes |
| 2003-09-06 | SPOT 5 | 22.9 ± 0.9 |  |
| 2004-06-18 | SPOT 5 | 22.0 ± 0.9 |  |
| 2005-09-23 | SPOT 5 | 21.9 ± 0.9 | yes |
| 2006-08-12 | SPOT 5 | 20.6 ± 0.9 |  |
| 2007-08-01 | SPOT 5 | 23.7 ± 1.0 |  |
| 2010-07-12 | SPOT 5 | 23.9 ± 1.0 |  |
| 2011-07-11 | SPOT 5 | 24.2 ± 1.0 |  |
| 2012-06-28 | SPOT 5 | 25.7 ± 1.0 | yes |
| 2013-06-02 | SPOT 5 | 26.7 ± 1.0 |  |
| 2014-08-22 | SPOT 5 | 26.6 ± 1.0 | yes |
| 2016-08-25 | Sentinel-2 | 27.8 ± 2.0 |  |
| 2017-09-09 | Sentinel-2 | 26.9 ± 2.0 |  |
| 2018-09-14 | Sentinel-2 | 27.7 ± 2.0 |  |
| 2019-09-24 | Sentinel-2 | 24.7 ± 1.9 |  |
| 2020-09-18 | Sentinel-2 | 25.0 ± 1.9 |  |
| 2021-09-28 | Sentinel-2 | 26.6 ± 2.0 |  |
| 2022-09-28 | Sentinel-2 | 28.0 ± 2.0 |  |
| 2023-08-14 | Sentinel-2 | 27.3 ± 2.0 |  |
| 2024-09-02 | Sentinel-2 | 28.8 ± 2.1 |  |
| 2025-08-18 | Sentinel-2 | 31.2 ± 2.2 |  |
| 2026-08-23 | Sentinel-2 | 32.8 ± 2.4 |  |

The ± is one pixel of the image along the whole edge (step 5). An oblique
view is one taken more than 15° off vertical.

## How the record was made

### 1. One frame for every image

All images are cut to the same box: the landfill's outline in OpenStreetMap
(way 323683797) with 400 m added on every side. Pixels are evenly spaced in
longitude and latitude (WGS84), so a point has the same place on every image
and an outline can be laid over any of them.

### 2. Choosing the images

There is one image per year, from the summer, when the dump is not under
snow and the hills around it are the same dry brown each year.

- **SPOT 1–4** (1986–2002, 10 m pixels) and **SPOT 5** (2003–2014, 5 m
  pixels): single-band Level 1A scenes from the CNES
  [Spot World Heritage](https://dinamis.data-terra.org/en/spot-world-heritage-swh-2/)
  archive. For each year, the scenes taken from June to September whose
  footprint holds the whole frame were considered if no more than 50% of the
  60 × 60 km scene was cloud. They were tried in order of how close to
  vertical they were taken (incidence angle rounded to 0.1°), then by cloud
  cover, time and file name. The first scene that aligned cleanly (step 3)
  was used. Each frame was also checked by eye, and one scene with cloud
  shadow over the site was rejected that way; it is recorded in
  `data/scene-decisions/`. Years with no usable image are missing:
  1987, 1988, 1993, 1995, 1996, 1998, 2001, 2008, 2009, and 2015.
- **Sentinel-2** (2016–2026, 10 m pixels): Level-2A surface reflectance from
  the [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu). For
  each year, the scene from July to September with the least cloud over its
  100 × 100 km tile, among those under 20%, rendered from that day alone, in
  natural color with a gain of 2.5. A shortwave-infrared composite of the same day
  (bands B12, B8A, B04) was used only to judge what a surface was, never to
  place the line; its bands are 20 m.

### 3. Aligning the SPOT scenes

SPOT Level 1A scenes are the raw sensor grid with only the ground position of
the four corners. A window around the site is placed with an affine fit to
those corners, and the image is resampled onto the frame with bilinear
interpolation. Corner positions can be off by more than a kilometer, and
relief shifts the view by tens of meters, so each scene is then matched to the
2016 Sentinel-2 image of the same frame:

- edges are compared: the two images come from different sensors, decades
  and seasons, so their brightness differs, while roads, ravines and streets
  stay where they are;
- the landfill itself and a 100 m band around it are left out of the
  comparison, since that is the part expected to change;
- the search runs first wide and coarse (20 m steps, up to 2.5 km), then fine
  (one pixel, within 200 m of the coarse result);
- a match counts only if its score is at least twice the 99th percentile of
  the scores of all other offsets, and searching again around the corrected
  position must find no remaining shift larger than one pixel.

The shift applied to each scene is in `data/frames.csv`. Contrast is
stretched for each image separately, between its 1st and 99th percentile.

### 4. Tracing the edge

On each image, the edge of the dump was drawn as a polygon. The outline
takes in everything the dump occupies: open waste, sections covered with
soil, and the embankments at its edges. Access roads are left out.

The outlines were drawn by an AI model, Anthropic's Claude (Opus 5.5). It
read each image as a close-up with a coordinate grid laid over it, placed
the vertices by eye, and checked every outline drawn over its image. The Sentinel-2 outlines were
drawn on natural color; the shortwave-infrared composite came later and
changed none of them. No person corrected the outlines; a corrected tracing
is welcome (see Corrections).

### 5. Measuring area and its uncertainty

Area is measured on a sphere of radius 6,371,008.8 m (the mean radius of the
WGS84 ellipsoid), with great-circle edges, as OpenLayers' `getArea` does. On
the ellipsoid itself the result differs by a few tenths of a percent.

The uncertainty is the perimeter of the outline times the pixel size of the
image it was traced on: how much the area changes if the line moves one
pixel outward or inward along its whole length. It covers where the line was
placed, not whether a stretch of ground was read as the right kind of
surface.

## Limits

- Where the dump meets bare ground of the same tone, the line is a reading of
  the image, here a model's. The images are published so that reading can be
  checked and redone.
- In 9 of the
  30 steps between neighboring outlines the area goes down, the
  largest by 3.0 ha, from 2018-09-14 to
  2019-09-24. A step that size can come from where the line was
  drawn as much as from the ground. Read the trend over several years.
- On images taken more than 15° off vertical,
  slopes are displaced against ravine floors by tens of meters. One shift
  corrects the frame as a whole, so the error on those images can be larger
  than the stated uncertainty.
- SPOT 1–3 see one wide visible band, SPOT 4 the red
  band, SPOT 5 a wide visible band at 5 m, and Sentinel-2 natural color. The
  same surface can look different between them; the outlines follow shape and
  texture as much as tone.
- The landfill's outline in OpenStreetMap runs outside the visible edge and
  takes in the slopes around it, so it is larger than the traced area (40.7 ha at the version used).

## Reproduce it

Recompute every area and uncertainty from the outlines (Python 3.9 or later,
no packages):

```sh
python3 tools/measure/check_areas.py
```

Rebuild the SPOT frames from the archive. This needs a free GEODES API key
in a `.env` file as `GEODES_API_KEY=...`, plus `numpy`, `scipy` and
`Pillow`. The archive limits downloads to roughly 30 scenes an hour, and the
tool waits when it reaches that limit. Start from a copy of the published
decisions: the tool then skips the scene rejected by eye, and for every
accepted scene it measures the shift again and stops if it differs from the
recorded one.

```sh
cp data/scene-decisions/swh-spot5-l1a-panchromatic.json spot5-decisions.json
python3 -P tools/spot-frames/build.py \
  --reference-series data/series/sentinel-2-l2a-true-color.json \
  --manifest spot5.json --decisions spot5-decisions.json \
  --asset-base https://example.org/spot5 --cache cache --out frames \
  --env-file .env --sensor spot5 --years 2003-2014
```

For SPOT 1–4 the same command takes `--sensor spot1-4`, the
`swh-spot1-4-l1a-panchromatic.json` decisions and that archive's years.

Re-render a Sentinel-2 image: send the JSON in
`methods/sentinel-2/requests/<product>/<date>.json` to the Copernicus Process
API (`https://sh.dataspace.copernicus.eu/api/v1/process`), with the
evalscript from `methods/sentinel-2/evalscripts/` in its `evalscript` field.

## Fields

`data/areas.csv`

| Field                 | Meaning                                                              |
| --------------------- | -------------------------------------------------------------------- |
| `date`                | Day the image was taken, UTC.                                        |
| `year`                | The summer the image stands for.                                     |
| `satellite`           | Archive: `swh-spot1-4-l1a`, `swh-spot5-l1a` or `sentinel-2-l2a`.     |
| `area_ha`             | Traced area, hectares, rounded to 0.01.                              |
| `uncertainty_ha`      | Plus or minus, hectares: one pixel along the whole edge.             |
| `meters_per_pixel`    | Pixel size of the image the outline was traced on.                   |
| `incidence_angle_deg` | SPOT only: how far off vertical the scene was taken, signed by side. |
| `oblique`             | `true` when that angle is more than 15°.                  |

`data/frames.csv` adds, per image: `product` (`panchromatic`, `trueColor` or
`shortwaveInfrared`), `scene_id` (the archive's identifier),
`scene_cloud_cover_pct` (over the whole scene or tile, not the frame),
`shift_east_m` and `shift_north_m` (the alignment shift, SPOT only),
`match_distinctness` (the match score over the 99th percentile of all other
offsets), the image size, its file in this repository and its URL on the
website.

## Licenses

Code: MIT. Our outlines and tables: CC BY 4.0. SPOT imagery: Etalab Open
Licence 2.0, © CNES. Sentinel-2 imagery: contains modified Copernicus Sentinel
data. OpenStreetMap outline: ODbL 1.0, © OpenStreetMap contributors. Details
and credit lines in [DATA-LICENSE.md](DATA-LICENSE.md).

## How to cite

Kraiz, A., & Yerevan for People (2026-10-09). _Nubarashen landfill from orbit:
traced area, 1986–2026_ (version 1.0.0) [Data set].
https://github.com/yerevan-for-people/nubarashen-landfill-satellite

GitHub's "Cite this repository" button gives the same in other formats.

## Corrections

If you find a mistake in an outline or a number, open an issue or write to
support@yfp.am. Corrections are published as a new version, and the old one
stays available.
