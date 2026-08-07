"""Tests for standards-conforming FDR GeoJSON conversion."""

from __future__ import annotations

from datetime import date, time
import json
from typing import Any, cast
import unittest

from xpwebapi.fdr import FDRDataref, FDRHeader, FDRRecording, FDRSample, recording_to_geojson


class FDRGeoJSONTests(unittest.TestCase):
    """Verify the public FDR recording to GeoJSON conversion."""

    def header(self, **changes: object) -> FDRHeader:
        values: dict[str, object] = {
            "source_version": 4,
            "source_origin": "A",
            "comments": (),
            "metadata": (),
            "datarefs": (
                FDRDataref("sim/test/ratio", 0.5),
                FDRDataref("sim/test/count", 1.0),
            ),
            "legacy_columns": (),
            "local_date": None,
        }
        values.update(changes)
        return FDRHeader(**values)  # type: ignore[arg-type]

    def sample(self, **changes: object) -> FDRSample:
        values: dict[str, object] = {
            "time_utc": time(23, 59, 59, 500000),
            "longitude": -87.9048,
            "latitude": 41.9742,
            "altitude_msl_ft": 640,
            "heading_magnetic_deg": 270,
            "pitch_deg": 2,
            "roll_deg": -1,
            "additional_values": (0.75, 3),
            "legacy_values": (),
        }
        values.update(changes)
        return FDRSample(**values)  # type: ignore[arg-type]

    def recording(self, **changes: object) -> FDRRecording:
        values: dict[str, object] = {"header": self.header(), "samples": (self.sample(),)}
        values.update(changes)
        return FDRRecording(**values)  # type: ignore[arg-type]

    def features(self, result: dict[str, object]) -> list[dict[str, Any]]:
        """Return the JSON feature list with the shape asserted by these tests."""
        return cast(list[dict[str, Any]], result["features"])

    def test_point_features_are_2d_and_keep_measurements_in_properties(self) -> None:
        result = recording_to_geojson(self.recording())
        features = self.features(result)

        self.assertEqual("FeatureCollection", result["type"])
        self.assertEqual(1, len(features))
        point = features[0]
        self.assertEqual("Feature", point["type"])
        self.assertEqual("Point", point["geometry"]["type"])
        self.assertEqual([-87.9048, 41.9742], point["geometry"]["coordinates"])
        self.assertEqual(2, len(point["geometry"]["coordinates"]))
        self.assertEqual(
            {
                "time_utc": "23:59:59.500000",
                "altitude_msl_ft": 640,
                "altitude_msl_m": 195.072,
                "heading_magnetic_deg": 270,
                "pitch_deg": 2,
                "roll_deg": -1,
                "additional_values": {"sim/test/ratio": 0.75, "sim/test/count": 3},
            },
            point["properties"],
        )
        self.assertNotIn("properties", point["geometry"])

    def test_absolute_timestamps_use_model_rollover_resolution_only_when_requested(self) -> None:
        recording = self.recording(
            samples=(
                self.sample(),
                self.sample(time_utc=time(0, 0, 1, 500000), longitude=-87.9),
            )
        )

        without_date = recording_to_geojson(recording)
        with_date = recording_to_geojson(recording, first_utc_date=date(2026, 8, 7))
        without_date_features = self.features(without_date)
        with_date_features = self.features(with_date)

        self.assertNotIn("timestamp_utc", without_date_features[0]["properties"])
        self.assertEqual("2026-08-07T23:59:59.500000Z", with_date_features[0]["properties"]["timestamp_utc"])
        self.assertEqual("2026-08-08T00:00:01.500000Z", with_date_features[1]["properties"]["timestamp_utc"])

    def test_fewer_than_two_samples_do_not_create_a_path_feature(self) -> None:
        self.assertEqual([], self.features(recording_to_geojson(self.recording(samples=()))))
        self.assertEqual(1, len(self.features(recording_to_geojson(self.recording()))))

    def test_normal_path_is_a_linestring_after_point_features(self) -> None:
        result = recording_to_geojson(self.recording(samples=(self.sample(), self.sample(longitude=-87.0, latitude=42.0))))

        path = self.features(result)[-1]
        self.assertEqual("Feature", path["type"])
        self.assertEqual({}, path["properties"])
        self.assertEqual("LineString", path["geometry"]["type"])
        self.assertEqual([[-87.9048, 41.9742], [-87.0, 42.0]], path["geometry"]["coordinates"])

    def test_antimeridian_crossing_splits_path_with_interpolated_boundary_latitude(self) -> None:
        result = recording_to_geojson(
            self.recording(
                samples=(
                    self.sample(longitude=179.0, latitude=10.0),
                    self.sample(longitude=-179.0, latitude=20.0),
                )
            )
        )

        path = self.features(result)[-1]["geometry"]
        self.assertEqual("MultiLineString", path["type"])
        self.assertEqual(
            [[[179.0, 10.0], [180.0, 15.0]], [[-180.0, 15.0], [-179.0, 20.0]]],
            path["coordinates"],
        )
        self.assertTrue(all(len(line) >= 2 for line in path["coordinates"]))

    def test_boundary_equivalent_antimeridian_endpoints_remain_valid_multilines(self) -> None:
        for first_longitude, second_longitude, boundary_longitude in ((-180, 180, -180), (180, -180, 180)):
            with self.subTest(first_longitude=first_longitude, second_longitude=second_longitude):
                result = recording_to_geojson(
                    self.recording(
                        samples=(
                            self.sample(longitude=first_longitude, latitude=10.0),
                            self.sample(longitude=second_longitude, latitude=20.0),
                        )
                    )
                )

                path = self.features(result)[-1]["geometry"]
                self.assertEqual("MultiLineString", path["type"])
                self.assertEqual(
                    [
                        [[first_longitude, 10.0], [boundary_longitude, 10.0]],
                        [[-boundary_longitude, 10.0], [second_longitude, 20.0]],
                    ],
                    path["coordinates"],
                )
                self.assertTrue(all(len(line) >= 2 for line in path["coordinates"]))

    def test_result_is_strictly_json_serializable(self) -> None:
        result = recording_to_geojson(self.recording())

        self.assertIsInstance(json.dumps(result, allow_nan=False), str)

    def test_exactly_representable_large_integer_altitude_stays_json_serializable(self) -> None:
        altitude_msl_ft = 1250 * 10**400
        result = recording_to_geojson(self.recording(samples=(self.sample(altitude_msl_ft=altitude_msl_ft),)))

        properties = self.features(result)[0]["properties"]
        self.assertEqual(381 * 10**400, properties["altitude_msl_m"])
        self.assertIsInstance(json.dumps(result, allow_nan=False), str)
