"""Unit tests for the md CLI module."""

import runpy
import unittest
from unittest.mock import call, patch

import pytest
from click.testing import CliRunner

from umann.metadata import md
from umann.metadata.chk_tz import TzMismatchError
from umann.utils.digest.soul import SoulError

pytestmark = pytest.mark.unit


class TestMd(unittest.TestCase):
    """Test suite for md CLI behavior."""

    def setUp(self):
        """Set up test fixtures."""
        self.patcher = patch("exiftool.ExifToolHelper")
        mock = self.patcher.start()
        self.mock_exiftool = mock.return_value.__enter__.return_value

    def tearDown(self):
        """Clean up test fixtures."""
        self.patcher.stop()

    # @pytest.mark.skip(reason="Disabled due to introducing memoize - it cannot handle single file now")
    # def test_get_metadata_single(self):
    #     test_file = "test.jpg"
    #     expected = {"EXIF:Make": "TestCamera"}
    #     self.mock_exiftool.get_metadata.return_value = [expected]  # ExifTool returns list even for single file

    #     result = md.get_metadata(test_file)

    #     self.mock_exiftool.get_metadata.assert_called_once_with(test_file)
    #     self.assertEqual(result, expected)

    @pytest.mark.skip(reason="Disabled due to introducing memoize - it cannot handle multiple files now")
    def test_get_metadata_multi(self):
        """Test getting metadata for multiple files."""
        test_files = ["test1.jpg", "test2.jpg"]
        expected = [{"EXIF:Make": "Camera1"}, {"EXIF:Make": "Camera2"}]
        self.mock_exiftool.get_metadata.return_value = expected

        result = md.get_metadata_multi(test_files)

        self.mock_exiftool.get_metadata.assert_called_once_with(test_files)
        self.assertEqual(result, dict(zip(test_files, expected)))

    def test_set_metadata_single(self):
        """Test setting metadata for a single file."""
        test_file = "test.jpg"
        tags = {"IPTC:Keywords": ["tag1", "tag2"]}

        with patch("umann.metadata.et.get_metadata", return_value={}):
            md.set_metadata(test_file, tags)

        self.mock_exiftool.set_tags.assert_called_once_with(test_file, tags)

    def test_set_metadata_multi(self):
        """Test setting metadata for multiple files."""
        test_files = ["test1.jpg", "test2.jpg"]
        tags = {"IPTC:Keywords": ["tag1", "tag2"]}

        with patch("umann.metadata.et.get_metadata", return_value={}):
            md.set_metadata(test_files, tags)

        self.assertEqual(self.mock_exiftool.set_tags.call_count, 2)
        self.assertEqual(
            self.mock_exiftool.set_tags.call_args_list, [call("test1.jpg", tags), call("test2.jpg", tags)]
        )

    def test_cli_main(self):
        """Test CLI interface with subcommands."""
        # Test get command
        md_map = {"test.jpg": {"EXIF:Make": "TestCamera"}}

        with patch("sys.argv", ["md", "get", "test.jpg"]):
            with patch("umann.metadata.md.get_metadata_multi", return_value=md_map):
                with patch("builtins.print") as mock_print:
                    try:
                        md.main()
                    except SystemExit:
                        pass
                    mock_print.assert_called_once()
                    printed_output = mock_print.call_args[0][0]
                    self.assertIn("EXIF:Make: TestCamera", printed_output)

        # Test get with --dictify
        md_map = {"test.jpg": {"EXIF:Make": "TestCamera"}}

        with patch("sys.argv", ["md", "get", "--dictify", "test.jpg"]):
            with patch("umann.metadata.md.get_metadata_multi", return_value=md_map):
                with patch("builtins.print") as mock_print:
                    try:
                        md.main()
                    except SystemExit:
                        pass
                    mock_print.assert_called_once()
                    printed_output = mock_print.call_args[0][0]
                    self.assertIn("test.jpg", printed_output)

        # Test set command
        self.mock_exiftool.set_tags.return_value = None

        with patch("sys.argv", ["md", "set", "--tags", '{"IPTC:Keywords": "tag1, tag2"}', "test.jpg"]):
            with patch("umann.metadata.md.glob.glob", return_value=["test.jpg"]):
                with patch("umann.metadata.md.set_metadata") as mock_set_metadata:
                    try:
                        md.main()
                    except SystemExit:
                        pass
                    mock_set_metadata.assert_called_once_with(["test.jpg"], {"IPTC:Keywords": "tag1, tag2"})

    def test_cli_get_all_transform(self):
        runner = CliRunner()
        md_map = {"test.jpg": {"EXIF:Make": "TestCamera"}}
        with patch("umann.metadata.md.get_metadata_multi", return_value=md_map) as mock_get:
            result = runner.invoke(md.cli, ["get", "--transform", "ALL", "test.jpg"])

        self.assertEqual(result.exit_code, 0)
        expected = tuple(md.TRANSFORMATORS)
        self.assertEqual(mock_get.call_args.kwargs["transformations"], expected)

    def test_cli_get_quiet_suppresses_print(self):
        runner = CliRunner()
        with patch("umann.metadata.md.get_metadata_multi", return_value={"test.jpg": {}}):
            result = runner.invoke(md.cli, ["get", "--quiet", "test.jpg"])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output, "")

    def test_cli_set_without_transform(self):
        runner = CliRunner()
        with patch("umann.metadata.md.glob.glob", return_value=["test.jpg"]):
            with patch("umann.metadata.md.set_metadata") as mock_set_metadata:
                result = runner.invoke(md.cli, ["set", "--tags", '{"IPTC:Keywords": "tag1"}', "test.jpg"])
        self.assertEqual(result.exit_code, 0)
        mock_set_metadata.assert_called_once_with(["test.jpg"], {"IPTC:Keywords": "tag1"})

    def test_cleanup_callback_branches(self):
        with patch("umann.metadata.md.glob.glob", return_value=["test.jpg"]):
            with patch("umann.metadata.md.get_metadata_multi", return_value={"test.jpg": {}}) as mock_get:
                with patch("builtins.print") as mock_print:
                    md.cli_command_cleanup.callback(
                        fnames=("*.jpg",),
                        transformations=("ALL",),
                        fix_iptc_encoding=False,
                        quiet=False,
                    )
        self.assertTrue(mock_print.called)
        expected = tuple(md.TRANSFORMATORS)
        self.assertEqual(mock_get.call_args.kwargs["transformations"], expected)

    def test_chk_command_emits_error_and_exits(self):
        runner = CliRunner()
        with patch("umann.metadata.md.glob.glob", return_value=["test.jpg", "test.txt"]):
            with patch("umann.metadata.md.get_metadata_multi", return_value={"test.jpg": {}}):
                with patch("umann.metadata.md.check_datetime_consistency", return_value={}):
                    with patch(
                        "umann.metadata.md._chk_tz.check_timezone_consistency",
                        side_effect=TzMismatchError("mismatch"),
                    ):
                        result = runner.invoke(md.cli, ["chk", "test.jpg"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("TzMismatchError", result.output)

    def test_chk_command_no_tz_data_error_passes(self):
        runner = CliRunner()
        with patch("umann.metadata.md.glob.glob", return_value=["test.jpg"]):
            with patch("umann.metadata.md.get_metadata_multi", return_value={"test.jpg": {}}):
                with patch("umann.metadata.md.check_datetime_consistency", return_value={}):
                    with patch(
                        "umann.metadata.md._chk_tz.check_timezone_consistency",
                        side_effect=md.NoGpsError("no gps"),
                    ):
                        result = runner.invoke(md.cli, ["chk", "--geotz", "test.jpg"])
        self.assertEqual(result.exit_code, 0)

    def test_soul_command_outputs_all_cases(self):
        runner = CliRunner()
        with patch("umann.metadata.md.glob.glob", side_effect=[["a.jpg"], [], ["c.jpg"]]):
            with patch("umann.metadata.md.extract_soul", side_effect=[None, "abcd", SoulError("boom")]):
                result = runner.invoke(md.cli, ["soul", "a.jpg", "b.jpg", "c.jpg"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("________________________________  a.jpg", result.output)
        self.assertIn("abcd  b.jpg", result.output)
        self.assertIn("ERR:boom", result.output)

    def test_main_inserts_default_get(self):
        with patch("sys.argv", ["md", "test.jpg"]):
            with patch.dict("os.environ", {}, clear=True):
                with patch("umann.metadata.md.cli") as mock_cli:
                    md.main()
                    mock_cli.assert_called_once()
                    self.assertEqual(md.sys.argv[1], "get")

    def test_main_skips_insert_for_completion(self):
        with patch("sys.argv", ["md", "test.jpg"]):
            with patch.dict("os.environ", {"_MD_COMPLETE": "1"}, clear=True):
                with patch("umann.metadata.md.cli") as mock_cli:
                    md.main()
                    mock_cli.assert_called_once()
                    self.assertEqual(md.sys.argv[1], "test.jpg")

    def test_module_main_entrypoint(self):
        with patch("sys.argv", ["md", "--help"]):
            with patch.dict("os.environ", {}, clear=True):
                with pytest.raises(SystemExit):
                    runpy.run_module("umann.metadata.md", run_name="__main__")


if __name__ == "__main__":
    unittest.main()
