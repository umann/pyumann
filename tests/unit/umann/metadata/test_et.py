"""Unit tests for the et metadata module."""

import unittest
from unittest.mock import call, patch

import pytest
from munch import munchify

from umann.metadata import et
from umann.metadata.chk_tz import TzMismatchError
from umann.utils.fs_utils import project_root

pytestmark = pytest.mark.unit


class TestEt(unittest.TestCase):
    """Test suite for et metadata transforms and helpers."""

    def test_apply_tag_type_known_and_fallback(self):
        """Test tag type conversion and fallback-to-string behavior."""
        with patch("umann.metadata.et.get_tag_type", return_value="list[str]"):
            assert et.apply_tag_type("XMP:Subject", ["a", "b"]) == ["a", "b"]

        et.SEEN.clear()
        with patch("umann.metadata.et.get_tag_type", return_value="int"):
            assert et.apply_tag_type("XMP:Rating", "oops") == "oops"

    def test_apply_tag_type_in_place_and_get_tag_type(self):
        """Test in-place application and tag type lookup defaults."""
        with patch("umann.metadata.et.read_tag_types_yaml", return_value={"XMP:Title": "str"}):
            assert et.get_tag_type("XMP:Title") == "str"
            assert et.get_tag_type("missing", default="fallback") == "fallback"

        md = {"XMP:Title": "keep"}
        with patch("umann.metadata.et.get_tag_type", return_value="str"):
            et.apply_tag_type_in_place(md, "XMP:Title")
        assert md == {"XMP:Title": "keep"}

    def test_default_et_config_and_helper(self):
        """Test config helpers and helper construction."""
        config = et.default_et_config()
        self.assertIn("common_args", config)
        self.assertIn("config_file", config)

        with patch("umann.metadata.et.exiftool.ExifToolHelper") as mock_helper:
            helper = et.helper(extra="value")
        mock_helper.assert_called_once()
        self.assertIs(helper, mock_helper.return_value)

    def test_set_exif_types(self):
        """Test ExifTool type application across metadata keys."""
        metadata = {"XMP:Title": "keep", "XMP:Rating": "7"}

        with patch("umann.metadata.et.apply_tag_type_in_place") as mock_apply:
            result = et.set_exif_types(metadata)

        self.assertEqual(result, metadata)
        self.assertEqual(mock_apply.call_args_list, [call(metadata, "XMP:Title"), call(metadata, "XMP:Rating")])

    def test_read_tag_types_yaml_uses_loader(self):
        """Test tag type YAML loading uses the shared file loader."""
        with (
            patch("umann.metadata.et.project_root", return_value="/tmp/tag_types.yaml"),
            patch("umann.metadata.et.yaml_safe_load_file", return_value={"XMP:Title": "str"}) as mock_load,
        ):
            et.read_tag_types_yaml.cache_clear()
            assert et.read_tag_types_yaml() == {"XMP:Title": "str"}
        mock_load.assert_called_once_with("/tmp/tag_types.yaml")
        et.read_tag_types_yaml.cache_clear()

    def test_transform_metadata_none_and_error(self):
        """Test transform_metadata empty input and error propagation."""
        assert et.transform_metadata(None) is None

        def boom(_metadata):
            raise ValueError("boom")

        with patch.dict(et.TRANSFORMATORS, {"boom": boom}, clear=False):
            with pytest.raises(ValueError):
                et.transform_metadata({}, transformations=("boom",), debug={"fname": "test.jpg"})

    def test_get_metadata_multi_one_by_one_and_get_metadata_passthrough(self):
        """Test one-by-one fetch and no-extension early return."""
        with (
            patch("umann.metadata.et.glob.glob", return_value=["test.jpg"]),
            patch("umann.metadata.et.get_metadata", return_value={"ok": True}) as mock_get,
        ):
            assert et.get_metadata_multi(["test*"], one_by_one=True) == {"test.jpg": {"ok": True}}
        mock_get.assert_called_once_with("test.jpg")

        with patch("umann.metadata.et.has_metadata_ext", return_value=False):
            assert et.get_metadata("test.txt") == {}

    def test_get_metadata_multi_raw_cache_and_json_string(self):
        """Test raw cache lookup and JSON-string parsing in multi-file reads."""
        with (
            patch("umann.metadata.et.helper") as mock_helper,
            patch("umann.metadata.et.get_file_rec_multi") as mock_cache,
        ):
            extl = mock_helper.return_value.__enter__.return_value
            extl.execute.return_value = '[{"XMP:Title": "keep"}]'

            def _cache(_wildcards, *, func, cmd, **_kwargs):  # pylint: disable=unused-argument
                return {"test.jpg": func("test.jpg")}

            mock_cache.side_effect = _cache
            result = et.get_metadata_multi(["test.jpg"], transformations=())

        assert result == {"test.jpg": {"XMP:Title": "keep"}}

    def test_get_metadata_multi_skips_unsupported_and_handles_errors(self):
        """Test unsupported files short-circuit and extraction errors are returned."""
        with (
            patch("umann.metadata.et.helper") as mock_helper,
            patch("umann.metadata.et.get_file_rec_multi") as mock_cache,
            patch("umann.metadata.et.can_handle", side_effect=lambda fname: fname.endswith(".jpg")),
            patch("umann.metadata.et.has_metadata_ext", return_value=True),
        ):
            extl = mock_helper.return_value.__enter__.return_value

            def execute(fname):
                if fname == "bad.jpg":
                    raise RuntimeError("boom")
                return [{"XMP:Title": "ok"}]

            extl.execute.side_effect = execute

            def _cache(_wildcards, *, func, cmd, **_kwargs):  # pylint: disable=unused-argument
                return {"skip.txt": func("skip.txt"), "bad.jpg": func("bad.jpg")}

            mock_cache.side_effect = _cache
            result = et.get_metadata_multi(["skip.txt", "bad.jpg"], transformations=())

        assert result["skip.txt"] == {}
        assert result["bad.jpg"]["Error"] == "boom"

    def test_get_metadata_raises_through_cache(self):
        """Test get_metadata propagates cache failures after logging."""
        with (
            patch("umann.metadata.et.has_metadata_ext", return_value=True),
            patch("umann.metadata.et.get_file_rec", side_effect=RuntimeError("boom")),
        ):
            with pytest.raises(RuntimeError):
                et.get_metadata("test.jpg")

    def test_default_config(self):
        """Test default configuration values."""
        config = et.default_et_config()
        self.assertEqual(config["common_args"], ["-struct", "-G1", "-j", "-api", "StructFormat=JSONQ"])
        self.assertEqual(config["config_file"], project_root(".ExifTool_config"))

    def test_transform_metadata(self):
        """Test transform_metadata function with simple_out transformation."""
        metadata = {"wanted": "keep", "unwanted": {"field": "remove"}}

        with patch("umann.metadata.et.read_metadata_yaml") as mock_yaml:
            mock_yaml.return_value = {"_del": {"unwanted.field": None}}
            result = et.transform_metadata(metadata.copy(), transformations=["simple_out"])

        self.assertIn("wanted", result)
        self.assertNotIn("field", result.get("unwanted", {}))

    def test_get_metadata_transforms_after_cache_lookup(self):
        """Test that read-time transforms run after raw cache lookup."""
        raw = {"wanted": "keep"}

        with (
            patch("umann.metadata.et.has_metadata_ext", return_value=True),
            patch("umann.metadata.et.get_file_rec", return_value=raw) as mock_cache,
            patch("umann.metadata.et.transform_metadata", return_value={"presented": True}) as mock_transform,
        ):
            result = et.get_metadata("test.jpg", transformations=("simple_out",))

        mock_cache.assert_called_once()
        mock_transform.assert_called_once_with(raw, debug={"fname": "test.jpg"}, transformations=("simple_out",))
        self.assertEqual(result, {"presented": True})

    def test_get_metadata_multi_transforms_after_cache_lookup(self):
        """Test that multi-file reads keep cache raw and transform on return."""
        raw_map = {"test.jpg": {"wanted": "keep"}}

        with (
            patch("umann.metadata.et.helper") as mock_helper,
            patch("umann.metadata.et.get_file_rec_multi", return_value=raw_map) as mock_cache,
            patch("umann.metadata.et.transform_metadata", return_value={"presented": True}) as mock_transform,
        ):
            mock_helper.return_value.__enter__.return_value = object()
            result = et.get_metadata_multi(["test.jpg"], transformations=("simple_out",))

        mock_cache.assert_called_once()
        mock_transform.assert_called_once_with(
            raw_map["test.jpg"], debug={"fname": "test.jpg"}, transformations=("simple_out",)
        )
        self.assertEqual(result, {"test.jpg": {"presented": True}})

    def test_check_metadata_consistency(self):
        with patch("umann.metadata.et.read_metadata_yaml") as mock_yaml:
            mock_yaml.return_value = munchify({"_eq": [["field1", "field2"]]})

            metadata = {"field1": "value", "field2": "value"}
            result = et.check(metadata)
            self.assertEqual(result, metadata)

            metadata_bad = {"field1": "value1", "field2": "value2"}
            with self.assertRaises(ValueError):
                et.check(metadata_bad)

    def test_read_metadata_yaml(self):
        """Test that read_metadata_yaml loads configuration."""
        result = et.read_metadata_yaml()
        self.assertIsNotNone(result)

    def test_simple_out_transformations(self):
        """Test simple_out transformation function."""
        with patch("umann.metadata.et.read_metadata_yaml") as mock_yaml:
            mock_yaml.return_value = {"_del": {"unwanted.field": None}}

            metadata = {"wanted": "keep", "unwanted": {"field": "remove"}}

            result = et.simple_out(metadata)
            self.assertIn("wanted", result)
            self.assertNotIn("field", result.get("unwanted", {}))

    def test_set_metadata_single(self):
        """Test writing metadata and refreshing its cache entry."""
        tags = {"IPTC:Keywords": ["tag1", "tag2"]}

        with patch("umann.metadata.et.helper") as mock_helper, patch("umann.metadata.et.get_metadata") as mock_get:
            mock_exiftool = mock_helper.return_value.__enter__.return_value
            result = et.set_metadata("test.jpg", tags)

        mock_exiftool.set_tags.assert_called_once_with("test.jpg", tags)
        mock_get.assert_called_once_with("test.jpg")
        self.assertEqual(result, mock_exiftool.set_tags.return_value)

    def test_set_metadata_multi(self):
        """Test that writing multiple files delegates once per file."""
        tags = {"IPTC:Keywords": ["tag1", "tag2"]}

        with patch("umann.metadata.et.helper") as mock_helper, patch("umann.metadata.et.get_metadata") as mock_get:
            mock_exiftool = mock_helper.return_value.__enter__.return_value
            et.set_metadata(["test1.jpg", "test2.jpg"], tags)

        self.assertEqual(
            mock_exiftool.set_tags.call_args_list,
            [call("test1.jpg", tags), call("test2.jpg", tags)],
        )
        self.assertEqual(mock_get.call_args_list, [call("test1.jpg"), call("test2.jpg")])

    def test_set_metadata_wraps_incompatible_exception_constructor(self):
        """Test that write failures preserve the original exception as the cause."""

        class NeedsMoreArgsError(Exception):
            """Man, it's a small class within a func, no docstring."""

            def __init__(self, one, two, three, four):
                super().__init__(one, two, three, four)

        tags = {"IPTC:CodedCharacterSet": "UTF8"}

        with patch("umann.metadata.et.helper") as mock_helper, patch("umann.metadata.et.get_metadata") as mock_get:
            mock_exiftool = mock_helper.return_value.__enter__.return_value
            mock_exiftool.set_tags.side_effect = NeedsMoreArgsError(1, 2, 3, 4)

            with pytest.raises(RuntimeError, match="Error setting") as excinfo:
                et.set_metadata("test.jpg", tags)

        mock_get.assert_not_called()
        assert isinstance(excinfo.value.__cause__, NeedsMoreArgsError)


def test_chk_tz_happy_path_budapest_summer():
    metadata = {
        "Composite:GPSLatitude": 47.4979,
        "Composite:GPSLongitude": 19.0402,
        "EXIF:DateTimeOriginal": "2024:07:15 12:00:00",
        "EXIF:OffsetTimeOriginal": "+02:00",
    }
    et.check_timezone_consistency(metadata)


def test_chk_tz_missing_gps_raises():
    metadata = {
        "EXIF:DateTimeOriginal": "2024:07:15 12:00:00",
        "EXIF:OffsetTimeOriginal": "+02:00",
    }
    with pytest.raises(TzMismatchError):
        et.check_timezone_consistency(metadata)


def test_chk_tz_mismatch_raises():
    metadata = {
        "Composite:GPSLatitude": 47.4979,
        "Composite:GPSLongitude": 19.0402,
        "EXIF:DateTimeOriginal": "2024:07:15 12:00:00",
        "EXIF:OffsetTimeOriginal": "+01:00",
    }
    with pytest.raises(TzMismatchError):
        et.check_timezone_consistency(metadata)


def test_chk_tz_fallback_xmp_timezone_string():
    metadata = {
        "Composite:GPSLatitude": 47.4979,
        "Composite:GPSLongitude": 19.0402,
        "EXIF:DateTimeOriginal": "2024:07:15 12:00:00",
        "XMP:TimeZone": "UTC+2",
    }
    et.check_timezone_consistency(metadata)


def test_chk_tz_exif_timezoneoffset_numeric_list():
    metadata = {
        "Composite:GPSLatitude": 34.0522,
        "Composite:GPSLongitude": -118.2437,
        "EXIF:DateTimeOriginal": "2024:07:15 12:00:00",
        "EXIF:TimeZoneOffset": [-7, -7],
    }
    et.check_timezone_consistency(metadata)


if __name__ == "__main__":
    unittest.main()
