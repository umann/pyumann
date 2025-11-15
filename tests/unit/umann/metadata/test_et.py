"""Unit tests for the ExifTool metadata module.

These tests verify the behavior of the et module using mocks to isolate
the tests from actual ExifTool operations and file system interactions.
"""

import unittest
from unittest.mock import patch

import pytest
from munch import munchify

from umann.metadata import et
from umann.utils.fs_utils import project_root

pytestmark = pytest.mark.unit


class TestEt(unittest.TestCase):
    """Test suite for the et module."""

    def setUp(self):
        """Set up test fixtures."""
        self.patcher = patch("exiftool.ExifToolHelper")
        mock = self.patcher.start()
        self.mock_exiftool = mock.return_value.__enter__.return_value

    def tearDown(self):
        """Clean up test fixtures."""
        self.patcher.stop()

    def test_default_config(self):
        """Test default configuration values."""
        config = et.default()
        self.assertEqual(config["common_args"], ["-struct", "-G1"])
        self.assertEqual(config["config_file"], project_root(".ExifTool_config"))

    def test_get_metadata_single(self):
        """Test getting metadata for a single file."""
        test_file = "test.jpg"
        expected = {"EXIF:Make": "TestCamera"}
        self.mock_exiftool.get_metadata.return_value = [expected]  # ExifTool returns list even for single file

        result = et.get_metadata(test_file)

        self.mock_exiftool.get_metadata.assert_called_once_with(test_file)
        self.assertEqual(result, expected)

    def test_get_metadata_multi(self):
        """Test getting metadata for multiple files."""
        test_files = ["test1.jpg", "test2.jpg"]
        expected = [{"EXIF:Make": "Camera1"}, {"EXIF:Make": "Camera2"}]
        self.mock_exiftool.get_metadata.return_value = expected

        result = et.get_metadata_multi(test_files)

        self.mock_exiftool.get_metadata.assert_called_once_with(test_files)
        self.assertEqual(result, dict(zip(test_files, expected)))

    def test_cool_in_gps(self):
        """Test GPS coordinate transformation."""
        tags = {"Composite:GPSPosition": "40.7128, -74.0060", "EXIF:GPSPosition": "51.5074, -0.1278"}

        result = et.cool_in(tags)

        # Check Composite GPS transformation
        self.assertNotIn("Composite:GPSPosition", result)
        self.assertEqual(result["Composite:GPSLatitude"], 40.7128)
        self.assertEqual(result["Composite:GPSLongitude"], -74.0060)

        # Check EXIF GPS transformation
        self.assertNotIn("EXIF:GPSPosition", result)
        self.assertEqual(result["EXIF:GPSLatitude"], 51.5074)
        self.assertEqual(result["EXIF:GPSLongitude"], -0.1278)

    def test_cool_in_keywords(self):
        """Test keywords transformation."""
        tags = {"XMP:Subject": "tag1, tag2", "IPTC:Keywords": "tag3;tag4", "Composite:Keywords": "tag5, tag6; tag7"}

        result = et.cool_in(tags)

        self.assertEqual(result["XMP:Subject"], ["tag1", "tag2"])
        self.assertEqual(result["IPTC:Keywords"], ["tag3", "tag4"])
        self.assertEqual(result["Composite:Keywords"], ["tag5", "tag6", "tag7"])

    def test_set_metadata_single(self):
        """Test setting metadata for a single file."""
        test_file = "test.jpg"
        tags = {"IPTC:Keywords": ["tag1", "tag2"]}

        et.set_metadata(test_file, tags)

        self.mock_exiftool.set_tags.assert_called_once_with(test_file, tags)

    def test_set_metadata_multi(self):
        """Test setting metadata for multiple files."""
        test_files = ["test1.jpg", "test2.jpg"]
        tags = {"IPTC:Keywords": ["tag1", "tag2"]}

        et.set_metadata(test_files, tags)

        self.mock_exiftool.set_tags.assert_called_once_with(test_files, tags)

    def test_cli_main(self):
        """Test CLI interface with subcommands."""
        # Test get command
        self.mock_exiftool.get_metadata.return_value = [{"EXIF:Make": "TestCamera"}]

        with patch("sys.argv", ["et", "get", "test.jpg"]):
            with patch("builtins.print") as mock_print:
                try:
                    et.main()
                except SystemExit:
                    pass
                mock_print.assert_called_once()
                printed_output = mock_print.call_args[0][0]
                self.assertIn("EXIF:Make: TestCamera", printed_output)

        # Test get with --dictify
        self.mock_exiftool.get_metadata.return_value = [{"EXIF:Make": "TestCamera"}]

        with patch("sys.argv", ["et", "get", "--dictify", "test.jpg"]):
            with patch("builtins.print") as mock_print:
                try:
                    et.main()
                except SystemExit:
                    pass
                mock_print.assert_called_once()
                printed_output = mock_print.call_args[0][0]
                self.assertIn("test.jpg", printed_output)

        # Test set command
        self.mock_exiftool.set_tags.return_value = None

        with patch("sys.argv", ["et", "set", "--tags", '{"IPTC:Keywords": "tag1, tag2"}', "test.jpg"]):
            try:
                et.main()
            except SystemExit:
                pass
            self.mock_exiftool.set_tags.assert_called()

    def test_transform_metadata(self):
        """Test transform_metadata function."""
        metadata = {
            "Composite:GPSPosition": "47.5, 19.0",  # Comma or semicolon separated
            "IPTC:Keywords": "tag1, tag2",
        }

        # Test with cool_in transformation
        result = et.transform_metadata(metadata.copy(), transformations=["cool_in"])
        self.assertIn("Composite:GPSLatitude", result)
        self.assertIn("Composite:GPSLongitude", result)
        self.assertEqual(result["Composite:GPSLatitude"], 47.5)
        self.assertEqual(result["Composite:GPSLongitude"], 19.0)

    def test_check_metadata_consistency(self):
        """Test check function for metadata consistency."""
        # Mock the metadata_tags.yaml to have _eq groups
        with patch("umann.metadata.et.read_metadata_yaml") as mock_yaml:
            mock_yaml.return_value = munchify({"_eq": [["field1", "field2"]]})

            # Test with consistent fields
            metadata = {"field1": "value", "field2": "value"}
            result = et.check(metadata)
            self.assertEqual(result, metadata)

            # Test with inconsistent fields
            metadata_bad = {"field1": "value1", "field2": "value2"}
            with self.assertRaises(ValueError):
                et.check(metadata_bad)

    def test_read_metadata_yaml(self):
        """Test that read_metadata_yaml loads the config file."""
        result = et.read_metadata_yaml()
        # Result should be a Munch object
        self.assertIsNotNone(result)

    def test_cool_out_transformations(self):
        """Test cool_out transformation function."""
        with patch("umann.metadata.et.read_metadata_yaml") as mock_yaml:
            mock_yaml.return_value = munchify(
                {
                    "_type": {"int": ["field1", "list_path.[].a"], "float": ["field2", "list_path.[].c"]},
                    "_convert": {"x_separated": ["size"], "flatten_if_not_multiple": ["single_item"]},
                }
            )

            metadata = {
                "field1": "42",
                "field2": "3.14",
                "size": "1920 1080",
                "single_item": ["only_one"],
                "list_path": [{"a": "1", "b": "b"}, {"c": "3.14"}],
            }

            result = et.cool_out(metadata)
            self.assertEqual(result["field1"], 42)
            self.assertEqual(result["field2"], 3.14)
            self.assertEqual(result["size"], "1920x1080")
            self.assertEqual(result["single_item"], "only_one")
            self.assertEqual(result["list_path"], [{"a": 1, "b": "b"}, {"c": 3.14}])

    def test_simple_out_transformations(self):
        """Test simple_out transformation function."""
        with patch("umann.metadata.et.read_metadata_yaml") as mock_yaml:
            mock_yaml.return_value = {"_del": {"unwanted.field": None}}

            metadata = {"wanted": "keep", "unwanted": {"field": "remove"}}

            result = et.simple_out(metadata)
            self.assertIn("wanted", result)
            # The field should be removed or empty


if __name__ == "__main__":
    unittest.main()
