"""Unit tests for datetime consistency checking."""

import datetime as dt
import unittest

import pytest

from umann.metadata.chk_datetime import _format_offset, _parse_offset, check_datetime_consistency

pytestmark = pytest.mark.unit


class TestDateTimeHelpers(unittest.TestCase):
    """Test datetime parsing helper functions."""

    def test_parse_offset_positive(self):
        """Test parsing positive offset."""
        assert _parse_offset("+01:00") == dt.timedelta(hours=1)
        assert _parse_offset("+05:30") == dt.timedelta(hours=5, minutes=30)

    def test_parse_offset_negative(self):
        """Test parsing negative offset."""
        assert _parse_offset("-08:00") == dt.timedelta(hours=-8)

    def test_parse_offset_utc(self):
        """Test parsing Z as UTC."""
        assert _parse_offset("Z") == dt.timedelta(0)

    def test_format_offset_positive(self):
        """Test formatting positive offset."""
        assert _format_offset(dt.timedelta(hours=1)) == "+01:00"
        assert _format_offset(dt.timedelta(hours=5, minutes=30)) == "+05:30"

    def test_format_offset_negative(self):
        """Test formatting negative offset."""
        assert _format_offset(dt.timedelta(hours=-8)) == "-08:00"


class TestDateTimeConsistency(unittest.TestCase):
    """Test datetime consistency validation."""

    def test_happy_path_minimal(self):
        """Test with minimal valid metadata."""
        md = {
            "ExifIFD:DateTimeOriginal": "2002:12:15 11:37:45",
        }
        self.assertEqual(check_datetime_consistency(md), {})

    def test_happy_path_with_offset(self):
        """Test with datetime and offset tags."""
        md = {
            "ExifIFD:DateTimeOriginal": "2002:12:15 11:37:45",
            "ExifIFD:OffsetTimeOriginal": "+01:00",
            "ExifIFD:CreateDate": "2002:12:15 11:37:45",
        }
        res = check_datetime_consistency(md)
        self.assertEqual(res, {"fixable": {"ExifIFD:OffsetTime": "+01:00"}})

    def test_happy_path_with_subsec(self):
        """Test with subsecond precision."""
        md = {
            "ExifIfd:DateTimeOriginal": "2002:12:15 11:37:45",
            "ExifIfd:SubSecTimeOriginal": "123",
            "ExifIfd:SubSecTime": "123",
        }
        self.assertEqual(check_datetime_consistency(md), {})

    def test_happy_path_xmp_with_tz(self):
        """Test with XMP datetime including timezone."""
        md = {
            "ExifIFD:DateTimeOriginal": "2002:12:15 11:37:45+01:00",
            "XMP:DateTimeOriginal": "2002:12:15 11:37:45+01:00",
        }
        res = check_datetime_consistency(md)
        self.assertEqual(res, {})

    def test_missing_datetimeoriginal_fatal(self):
        """Test that missing DateTimeOriginal results in fatal error when other dates exist."""
        md = {
            "ExifIFD:CreateDate": "2002:12:15 11:37:45",
        }
        res = check_datetime_consistency(md)
        assert res == {
            "fatal": {
                "ExifIFD:DateTimeOriginal": "DateTimeParseError: Cannot parse ExifIFD:DateTimeOriginal "
                + "KeyError: 'ExifIFD:DateTimeOriginal'"
            }
        }

    def test_offset_mismatch_deletable(self):
        """Test that mismatched offset tags result in deletable error."""
        md = {
            "ExifIFD:DateTimeOriginal": "2002:12:15 11:37:45",
            "ExifIFD:OffsetTimeOriginal": "+01:00",
            "ExifIFD:OffsetTime": "+02:00",  # Mismatch
        }
        res = check_datetime_consistency(md)
        assert res == {"deletable": {"ExifIFD:OffsetTime": "Missing ExifIFD:CreateDate"}}

    def test_subsec_mismatch_deletable(self):
        """Test that mismatched SubSec tags result in deletable error."""
        md = {
            "ExifIFD:DateTimeOriginal": "2002:12:15 11:37:45",
            "ExifIFD:SubSecTimeOriginal": "123",
            "ExifIFD:SubSecTime": "456",  # Mismatch
        }
        res = check_datetime_consistency(md)
        assert res == {"deletable": {"ExifIFD:SubSecTime": "Missing ExifIFD:CreateDate"}}

    def test_datetime_mismatch_utc_deletable(self):
        """Test that datetimes representing different UTC instants result in deletable error."""
        md = {
            "ExifIFD:DateTimeOriginal": "2002:12:15 11:37:45",
            "ExifIFD:OffsetTimeOriginal": "+01:00",
            "XMP:DateTimeOriginal": "2002:12:15 12:37:45+01:00",  # 1 hour later
        }
        res = check_datetime_consistency(md)
        self.assertEqual(
            res,
            {
                "deletable": {
                    "XMP:DateTimeOriginal": "XMP:DateTimeOriginal dt_naive=2002:12:15 12:37:45 "
                    + "vs. ExifIFD:DateTimeOriginal 2002:12:15 11:37:45 diff_secs=3600 tolerance_secs=0; "
                    + "XMP:DateTimeOriginal utc=2002:12:15 11:37:45 vs. ExifIFD:DateTimeOriginal 2002:12:15 10:37:45 "
                    + "diff_secs=3600 tolerance_secs=0"
                }
            },
        )

    def test_datetime_within_tolerance(self):
        """Test that datetime differences within tolerance are accepted."""
        md = {
            "ExifIFD:DateTimeOriginal": "2002:12:15 11:37:45+01:00",
            "XMP:DateTimeOriginal": "2002:12:15 11:37:45.5+01:00",  # 0.5s later
        }
        # Should not generate error with default tolerance
        self.assertEqual(check_datetime_consistency(md), {})

    def test_gps_datetime_check(self):
        """Test GPS datetime validation."""
        md = {
            "EXIF:DateTimeOriginal": "2002:12:15 11:37:45+01:00",
            # GPS datetime should match in UTC (10:37:45 UTC)
            "XMP:GPSDateTime": "2002:12:15 10:37:45Z",
        }
        self.assertEqual(check_datetime_consistency(md), {})

    def test_gps_datetime_mismatch_deletable(self):
        """Test that GPS datetime mismatch results in deletable error."""
        md = {
            "ExifIFD:DateTimeOriginal": "2002:12:15 11:37:45+01:00",
            "XMP-exif:GPSDateTime": "2002:12:15 12:00:00Z",  # Wrong time
        }
        res = check_datetime_consistency(md)
        self.assertEqual(
            res,
            {
                "deletable": {
                    "XMP-exif:GPSDateTime": "XMP-exif:GPSDateTime offset=+00:00 != ExifIFD:DateTimeOriginal +01:00; "
                    + "XMP-exif:GPSDateTime utc=2002:12:15 12:00:00 vs. ExifIFD:DateTimeOriginal 2002:12:15 10:37:45 "
                    + "diff_secs=4935 tolerance_secs=0"
                }
            },
        )

    def test_gps_datestamp_timestamp_combined(self):
        """Test GPS date/time from separate EXIF tags."""
        md = {
            "ExifIFD:DateTimeOriginal": "2002:12:15 11:37:45+01:00",
            "ExifIFD:GPSDateStamp": "2002:12:15",
            "ExifIFD:GPSTimeStamp": "10:37:45",  # UTC matches
        }
        res = check_datetime_consistency(md)
        self.assertEqual(res, {})

    def test_iptc_date_match(self):
        """Test IPTC date matching EXIF date."""
        md = {
            "ExifIFD:DateTimeOriginal": "2002:12:15 11:37:45",
            "IPTC:DateCreated": "2002:12:15",
            "IPTC:TimeCreated": "11:37:45",
        }
        res = check_datetime_consistency(md)
        self.assertEqual(res, {})

    def test_iptc_date_mismatch_deletable(self):
        """Test that IPTC date mismatch result in deletable error."""
        md = {
            "ExifIFD:DateTimeOriginal": "2002:12:15 11:37:45",
            "IPTC:DateCreated": "2002:12:16",  # Wrong date
        }
        res = check_datetime_consistency(md)
        self.assertEqual(list(res.keys()), ["deletable"])
        self.assertRegex(res["deletable"]["IPTC:DateCreated"], r"IPTC:DateCreated.*does not match")

    def test_no_datetime_tags_passes(self):
        """Test that metadata without any datetime tags passes."""
        md = {
            "IFD0:Make": "Canon",
            "IFD0:Model": "EOS 5D",
        }
        res = check_datetime_consistency(md)
        self.assertEqual(res, {})

    def test_complex_valid_metadata_fixable(self):
        """Test complex but valid metadata with multiple namespaces."""
        md = {
            "ExifIFD:DateTimeOriginal": "2002:12:15 11:37:45",
            "ExifIFD:CreateDate": "2002:12:15 11:37:45",
            "ExifIFD:OffsetTimeOriginal": "+01:00",
            "ExifIFD:OffsetTime": "+01:00",
            "ExifIFD:SubSecTimeOriginal": "123",
            "ExifIFD:SubSecTime": "123",
            "XMP:DateTimeOriginal": "2002:12:15 11:37:45+01:00",
            "XMP:CreateDate": "2002:12:15 11:37:45+01:00",
            "XMP:MetadataDate": "2025:10:25 23:11:47+02:00",
            "IPTC:DateCreated": "2002:12:15",
            "IPTC:TimeCreated": "11:37:45",
            "XMP:GPSDateTime": "2002:12:15 10:37:45Z",  # UTC equivalent
        }
        res = check_datetime_consistency(md)
        self.assertEqual(res, {"fixable": {"IPTC:TimeCreated": "11:37:45+01:00"}})
