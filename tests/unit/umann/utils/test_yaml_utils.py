"""Tests for YAML datetime formatting."""

import datetime as dt
import io
import unittest
from collections import defaultdict

import pytest
import yaml
from munch import Munch

from umann.utils.yaml_utils import yaml_dump_cozy

pytestmark = pytest.mark.unit


class TestYamlDumpCozy(unittest.TestCase):
    """Tests for YAML datetime formatting."""

    def test_yaml_dump_cozy_datetime_with_space_separator(self):
        """Test that datetime is dumped with space separator instead of T."""
        data = {"timestamp": dt.datetime(2025, 11, 1, 14, 30, 45)}
        result = yaml_dump_cozy(data, default_flow_style=False)

        self.assertIn("2025-11-01 14:30:45", result)
        self.assertNotIn("T", result.replace("timestamp", ""))  # Exclude key name

    def test_yaml_dump_cozy_datetime_with_microseconds(self):
        """Test that datetime with microseconds is formatted correctly."""
        data = {"timestamp": dt.datetime(2025, 11, 1, 14, 30, 45, 123456)}
        result = yaml_dump_cozy(data, default_flow_style=False)

        self.assertIn("2025-11-01 14:30:45.123456", result)

    def test_yaml_dump_cozy_date(self):
        """Test that date is dumped in ISO format (YYYY-MM-DD)."""
        data = {"date": dt.date(2025, 11, 1)}
        result = yaml_dump_cozy(data, default_flow_style=False)

        self.assertIn("2025-11-01", result)

    def test_yaml_dump_cozy_timedelta_positive(self):
        """Test that positive timedelta is dumped as +HH:MM without seconds."""
        data = {"offset": dt.timedelta(hours=5, minutes=30)}
        result = yaml_dump_cozy(data, default_flow_style=False)

        self.assertIn("offset: +05:30", result)

    def test_yaml_dump_cozy_timedelta_negative(self):
        """Test that negative timedelta is dumped as -HH:MM without seconds."""
        data = {"offset": dt.timedelta(hours=-8)}
        result = yaml_dump_cozy(data, default_flow_style=False)

        self.assertIn("offset: -08:00", result)

    def test_yaml_dump_cozy_timedelta_with_seconds_truncated(self):
        """Test that seconds in timedelta are truncated (only HH:MM)."""
        data = {"offset": dt.timedelta(hours=2, minutes=15, seconds=45)}
        result = yaml_dump_cozy(data, default_flow_style=False)

        self.assertIn("offset: +02:15", result)
        self.assertNotIn(":45", result)

    def test_yaml_dump_cozy_timedelta_zero(self):
        """Test that zero timedelta is dumped as +00:00."""
        data = {"offset": dt.timedelta(0)}
        result = yaml_dump_cozy(data, default_flow_style=False)

        self.assertIn("offset: +00:00", result)

    def test_yaml_dump_cozy_timedelta_minutes_only(self):
        """Test timedelta with only minutes (no hours)."""
        data = {"offset": dt.timedelta(minutes=45)}
        result = yaml_dump_cozy(data, default_flow_style=False)

        self.assertIn("offset: +00:45", result)

    def test_yaml_dump_cozy_complex_nested_structure(self):
        """Test that datetime formatting works in nested structures."""
        data = {
            "created": dt.datetime(2025, 11, 1, 14, 30, 45),
            "metadata": {
                "date": dt.date(2025, 11, 1),
                "timezone_offset": dt.timedelta(hours=1),
            },
            "modified": dt.datetime(2025, 11, 1, 15, 45, 30),
        }
        result = yaml_dump_cozy(data, default_flow_style=False)

        self.assertIn("2025-11-01 14:30:45", result)
        self.assertIn("2025-11-01", result)
        self.assertIn("timezone_offset: +01:00", result)
        self.assertIn("2025-11-01 15:45:30", result)

    def test_yaml_dump_cozy_list_of_datetimes(self):
        """Test that datetime formatting works in lists."""
        data = {
            "timestamps": [
                dt.datetime(2025, 11, 1, 10, 0, 0),
                dt.datetime(2025, 11, 1, 12, 30, 0),
                dt.datetime(2025, 11, 1, 15, 45, 0),
            ]
        }
        result = yaml_dump_cozy(data, default_flow_style=False)

        self.assertIn("2025-11-01 10:00:00", result)
        self.assertIn("2025-11-01 12:30:00", result)
        self.assertNotIn("2025-11-01 15:45:30", result)  # Last one has 15:45:00

    def test_yaml_dump_cozy_round_trip(self):
        """Test that YAML can be loaded back (as strings)."""
        original = {
            "timestamp": dt.datetime(2025, 11, 1, 14, 30, 45),
            "offset": dt.timedelta(hours=5, minutes=30),
        }

        # Dump to YAML
        yaml_str = yaml_dump_cozy(original)

        # Load back (will be strings)
        loaded = yaml.safe_load(yaml_str)

        self.assertEqual(loaded["timestamp"], "2025-11-01 14:30:45")
        self.assertEqual(loaded["offset"], "+05:30")

    def test_yaml_dump_cozy_to_stream(self):
        """Test that yaml_dump_cozy can write to a stream."""

        data = {"timestamp": dt.datetime(2025, 11, 1, 14, 30, 45)}
        stream = io.StringIO()

        yaml_dump_cozy(data, stream, default_flow_style=False)
        result = stream.getvalue()

        self.assertIn("2025-11-01 14:30:45", result)

    def test_yaml_dump_cozy_preserves_other_types(self):
        """Test that non-datetime types are still dumped normally."""
        data = {
            "string": "hello",
            "number": 42,
            "float": 3.14,
            "bool": True,
            "none": None,
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
        }

        result = yaml_dump_cozy(data, default_flow_style=False)
        loaded = yaml.safe_load(result)

        self.assertEqual(loaded, data)

    def test_yaml_dump_cozy_munch(self):
        """Test that Munch objects are dumped as regular dicts."""
        data = {
            "config": Munch({"key1": "value1", "key2": "value2", "nested": {"inner": "data"}}),
            "other": "data",
        }

        result = yaml_dump_cozy(data, default_flow_style=False)
        loaded = yaml.safe_load(result)

        # Should be a regular dict, not a Munch
        self.assertIsInstance(loaded["config"], dict)
        self.assertNotIsInstance(loaded["config"], Munch)
        self.assertEqual(loaded["config"]["key1"], "value1")
        self.assertEqual(loaded["config"]["key2"], "value2")
        self.assertEqual(loaded["config"]["nested"]["inner"], "data")

    def test_yaml_dump_cozy_defaultdict(self):
        """Test that defaultdict objects are dumped as regular dicts."""
        dd = defaultdict(list)
        dd["key1"].append("value1")
        dd["key2"].extend(["value2", "value3"])

        data = {"counts": dd, "other": "data"}

        result = yaml_dump_cozy(data, default_flow_style=False)
        loaded = yaml.safe_load(result)

        # Should be a regular dict, not a defaultdict
        self.assertIsInstance(loaded["counts"], dict)
        self.assertNotIsInstance(loaded["counts"], defaultdict)
        self.assertEqual(loaded["counts"]["key1"], ["value1"])
        self.assertEqual(loaded["counts"]["key2"], ["value2", "value3"])

    def test_yaml_dump_cozy_mixed_munch_and_datetime(self):
        """Test that Munch and datetime can be mixed in the same structure."""
        data = Munch(
            {
                "created": dt.datetime(2025, 11, 1, 14, 30, 45),
                "metadata": Munch(
                    {
                        "offset": dt.timedelta(hours=5, minutes=30),
                        "date": dt.date(2025, 11, 1),
                    }
                ),
            }
        )

        result = yaml_dump_cozy(data, default_flow_style=False)
        loaded = yaml.safe_load(result)

        # Munch should be converted to dict, datetimes to strings
        self.assertIsInstance(loaded, dict)
        self.assertEqual(loaded["created"], "2025-11-01 14:30:45")
        self.assertEqual(loaded["metadata"]["offset"], "+05:30")
        self.assertEqual(loaded["metadata"]["date"], "2025-11-01")

    def test_yaml_dump_cozy_nested_defaultdict(self):
        """Test that nested defaultdict objects are handled correctly."""
        dd_outer = defaultdict(lambda: defaultdict(int))
        dd_outer["level1"]["count"] = 42
        dd_outer["level1"]["total"] = 100

        data = {"nested": dd_outer}

        result = yaml_dump_cozy(data, default_flow_style=False)
        loaded = yaml.safe_load(result)

        # All should be regular dicts
        self.assertIsInstance(loaded["nested"], dict)
        self.assertIsInstance(loaded["nested"]["level1"], dict)
        self.assertEqual(loaded["nested"]["level1"]["count"], 42)
        self.assertEqual(loaded["nested"]["level1"]["total"], 100)
