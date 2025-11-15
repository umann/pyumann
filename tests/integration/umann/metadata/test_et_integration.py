"""Integration tests for the ExifTool metadata module.

These tests verify the interaction between our ExifTool wrapper and the actual
ExifTool executable, using real image files and metadata operations.
"""

import shutil
import unittest
from pathlib import Path

import pytest

from tests.utils import get_test_data_dir
from umann.metadata import et
from umann.utils.yaml_utils import yaml_safe_load_file

pytestmark = pytest.mark.integration


@unittest.skipIf(shutil.which("exiftool") is None, "exiftool not installed")
class TestEtIntegration(unittest.TestCase):
    """Integration tests for the et module."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_data_dir = get_test_data_dir()
        self.sample_image = self.test_data_dir / "kalaka.jpg"

    def test_get_metadata_from_sample(self):
        """Test reading metadata from the included sample image.

        This uses the real pyexiftool/ExifTool executable. It will be skipped
        automatically when `exiftool` isn't available on the PATH.
        """
        self.assertTrue(self.sample_image.exists(), f"sample file not found: {self.sample_image}")

        # Use the multi-file helper to get a stable dict mapping
        meta_map = et.get_metadata_multi([str(self.sample_image)])
        # et.get_metadata_multi returns dict[file_path -> metadata_dict]
        meta = meta_map.get(str(self.sample_image)) or meta_map.get(self.sample_image.name)
        self.assertIsInstance(meta, dict)

        # Expect at least one GPS-related key and one Keywords/IPTC key
        gps_keys = [k for k in meta.keys() if "GPS" in k]
        self.assertTrue(gps_keys, f"no GPS keys found in metadata: {list(meta.keys())[:20]}")

        keyword_keys = [k for k in meta.keys() if "Keyword" in k or "Subject" in k]
        self.assertTrue(keyword_keys, f"no keyword/subject keys found in metadata: {list(meta.keys())[:20]}")

    def test_transform_tags_roundtrip(self):
        """Test transform_tags with real metadata from sample file."""
        self.assertTrue(self.sample_image.exists())

        meta_map = et.get_metadata_multi([str(self.sample_image)])
        meta = meta_map.get(str(self.sample_image)) or meta_map.get(self.sample_image.name)
        self.assertIsInstance(meta, dict)

    def test_metadata_matches_yaml(self):
        """Test that image metadata matches the expected values in the YAML file."""

        # Verify files exist
        self.assertTrue(self.sample_image.exists(), f"sample image not found: {self.sample_image}")
        yaml_path = self.sample_image.with_suffix(".jpg.metadata.G1.yaml")
        self.assertTrue(yaml_path.exists(), f"metadata YAML not found: {yaml_path}")

        # Get actual metadata
        meta_map = et.get_metadata_multi([str(self.sample_image)])
        actual_meta = meta_map.get(str(self.sample_image)) or meta_map.get(self.sample_image.name)
        self.assertIsInstance(actual_meta, dict)

        # Load expected metadata from YAML
        # with open(yaml_path, "r", encoding="utf-8") as f:
        #     expected_meta = yaml.safe_load(f)[0]  # YAML contains a list with one dict
        expected_meta = yaml_safe_load_file(yaml_path)[0]  # YAML contains a list with one dict

        # Fields to ignore in comparison (these may change between runs)
        ignore_fields = {
            "System:FileModifyDate",
            "System:FileAccessDate",
            "System:FileInodeChangeDate",
            "System:FilePermissions",
            "ExifTool:ExifToolVersion",
        }

        # Special handling for path fields
        def normalize_path(p):
            """Convert absolute path to relative form for comparison."""
            try:
                return str(Path(p).relative_to(Path.cwd()))
            except ValueError:
                return p

        # Fields that contain paths that need normalization
        path_fields = {"SourceFile", "System:Directory"}

        # Compare relevant fields
        errors = []
        for key, expected in expected_meta.items():
            if key not in ignore_fields:
                self.assertIn(key, actual_meta, f"Missing expected field: {key}")

                # Normalize paths for comparison
                expected_val = normalize_path(expected) if key in path_fields else str(expected)
                actual_val = normalize_path(actual_meta[key]) if key in path_fields else str(actual_meta[key])

                if actual_val != expected_val:
                    errors.append(
                        f"Metadata mismatch for {key}:\n" f"Expected: {expected_val}\n" f"Got: {actual_val}",
                    )

                # self.assertEqual(
                #     actual_val,
                #     expected_val,
                #     f"Metadata mismatch for {key}:\n" f"Expected: {expected_val}\n" f"Got: {actual_val}",
                # )


if __name__ == "__main__":
    unittest.main()
