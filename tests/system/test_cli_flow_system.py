"""System tests for CLI workflow."""

import shutil
import tempfile
import unittest
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from tests.utils import get_test_data_dir
from umann.metadata.et import cli as et_cli

pytestmark = pytest.mark.system


class TestCliFlow(unittest.TestCase):
    """System tests for CLI workflow."""

    def setUp(self):
        """Create a temporary workspace with test data."""
        self.tempdir = tempfile.mkdtemp()
        self.workspace = Path(self.tempdir)

        # Copy test files to temporary workspace
        test_data = get_test_data_dir()
        for f in test_data.glob("*.jpg"):
            shutil.copy2(f, self.workspace)

        self.runner = CliRunner()

    def tearDown(self):
        """Clean up temporary workspace."""
        shutil.rmtree(self.tempdir)

    def test_metadata_cli_workflow(self):
        """Test the complete CLI workflow:
        1. Read metadata from an image
        2. Modify some tags
        3. Write back and verify
        """
        image_path = next(self.workspace.glob("*.jpg"))

        # 1. Read initial metadata
        result = self.runner.invoke(et_cli, ["get", str(image_path)])
        self.assertEqual(result.exit_code, 0)

        # 2. Modify tags
        new_tags = {
            "IPTC:Keywords": "test1, test2",
            "XMP:Subject": "subject1; subject2",
        }
        args = (
            et_cli,
            [
                "set",
                "--tags",
                yaml.dump(new_tags, default_flow_style=True).strip(),
                "--transform",
                "cool_in",
                str(image_path),
            ],
        )
        result = self.runner.invoke(*args)
        self.assertEqual(result.exit_code, 0)

        # 3. Read back and verify
        result = self.runner.invoke(et_cli, ["get", str(image_path)])
        self.assertEqual(result.exit_code, 0)
        updated_meta = yaml.safe_load(result.output)
        self.assertIn("test1", updated_meta.get("IPTC:Keywords", []))
        self.assertIn("subject1", updated_meta.get("XMP-dc:Subject", []))


if __name__ == "__main__":
    unittest.main()
