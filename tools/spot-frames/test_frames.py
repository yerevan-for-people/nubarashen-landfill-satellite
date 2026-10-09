"""Run with: python3 -P -m unittest discover -s tools/spot-frames -p 'test_*.py'"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dimap import read_scene_geometry  # noqa: E402
from geodes import SpotScene  # noqa: E402
from register import best_offset  # noqa: E402

# Corners of a real scene (SPOT 5, 2006-08-12, K134 J269), trimmed to the tags read.
METADATA = """
<Dataset_Frame>
<Vertex><FRAME_LON>44.518593</FRAME_LON><FRAME_LAT>40.138677</FRAME_LAT><FRAME_ROW>1</FRAME_ROW><FRAME_COL>1</FRAME_COL></Vertex>
<Vertex><FRAME_LON>45.204112</FRAME_LON><FRAME_LAT>39.997391</FRAME_LAT><FRAME_ROW>1</FRAME_ROW><FRAME_COL>12000</FRAME_COL></Vertex>
<Vertex><FRAME_LON>45.019913</FRAME_LON><FRAME_LAT>39.474110</FRAME_LAT><FRAME_ROW>12000</FRAME_ROW><FRAME_COL>12000</FRAME_COL></Vertex>
<Vertex><FRAME_LON>44.339423</FRAME_LON><FRAME_LAT>39.614701</FRAME_LAT><FRAME_ROW>12000</FRAME_ROW><FRAME_COL>1</FRAME_COL></Vertex>
</Dataset_Frame>
<IMAGING_DATE>2006-08-12</IMAGING_DATE><INCIDENCE_ANGLE>6.292969</INCIDENCE_ANGLE>
<NCOLS>12000</NCOLS><NROWS>12000</NROWS>
"""


class SceneGeometryTest(unittest.TestCase):
    def test_corners_map_to_their_ground_positions(self):
        geometry = read_scene_geometry(METADATA)
        lon, lat = geometry.forward(np.array([12000.0]), np.array([1.0]))
        self.assertAlmostEqual(float(lon[0]), 45.204112, places=6)
        self.assertAlmostEqual(float(lat[0]), 39.997391, places=6)

    def test_local_inverse_round_trips_within_a_pixel(self):
        geometry = read_scene_geometry(METADATA)
        inverse = geometry.local_inverse(44.548, 40.107)
        col, row = inverse(np.array([44.548]), np.array([40.107]))
        lon, lat = geometry.forward(col, row)
        five_meters_in_degrees = 5 / 111_320
        self.assertLess(abs(float(lon[0]) - 44.548), five_meters_in_degrees)
        self.assertLess(abs(float(lat[0]) - 40.107), five_meters_in_degrees)

    def test_a_point_off_the_scene_is_refused(self):
        geometry = read_scene_geometry(METADATA)
        with self.assertRaises(ValueError):
            geometry.local_inverse(43.0, 41.0)


class BestOffsetTest(unittest.TestCase):
    def test_recovers_a_known_shift_with_its_sign(self):
        rng = np.random.default_rng(7)
        search = rng.random((120, 120)).astype(np.float32)
        # The reference is the patch 10 px right and 4 px down of center.
        center = (120 - 60) // 2
        reference = search[center + 4 : center + 64, center + 10 : center + 70]
        mask = np.ones(reference.shape, dtype=bool)
        match = best_offset(search, reference, mask)
        self.assertEqual((match.shift_x_px, match.shift_y_px), (10, 4))
        self.assertGreater(match.distinctness, 2)

    def test_masked_area_does_not_steer_the_match(self):
        rng = np.random.default_rng(11)
        search = rng.random((120, 120)).astype(np.float32)
        center = (120 - 60) // 2
        reference = search[center : center + 60, center : center + 60].copy()
        reference[20:40, 20:40] = rng.random((20, 20))
        mask = np.ones(reference.shape, dtype=bool)
        mask[18:42, 18:42] = False
        match = best_offset(search, reference, mask)
        self.assertEqual((match.shift_x_px, match.shift_y_px), (0, 0))


def scene_with(footprint):
    return SpotScene(
        name="x.zip",
        acquired_at="2006-08-12T08:00:57Z",
        platform="SPOT5",
        mode="A",
        cloud_cover_percent=0,
        incidence_angle_deg=0,
        download_url="",
        footprint=footprint,
    )


class FootprintTest(unittest.TestCase):
    # Real footprints of two scenes from the same 2006 pass, one row apart.
    NORTH_SCENE = ((44.518593, 40.138677), (44.339423, 39.614701), (45.019913, 39.47411), (45.204112, 39.997391))
    SOUTH_SCENE = ((44.513184, 40.122961), (44.334081, 39.598971), (45.014421, 39.4584), (45.198551, 39.981697))
    # The landfill frame plus the 600 m search margin on every side.
    NEEDED = (44.5324, 40.0945, 44.5644, 40.1202)

    def test_a_scene_holding_the_whole_box_contains_it(self):
        self.assertTrue(scene_with(self.NORTH_SCENE).contains(*self.NEEDED))

    def test_a_scene_cutting_through_the_box_does_not(self):
        self.assertFalse(scene_with(self.SOUTH_SCENE).contains(*self.NEEDED))


if __name__ == "__main__":
    unittest.main()
