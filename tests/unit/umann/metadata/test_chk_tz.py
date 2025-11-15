"""Tests for timezone consistency checking in EXIF metadata."""

import pytest

from umann.metadata.chk_tz import TzMismatchError
from umann.metadata.et import check_timezone_consistency

pytestmark = pytest.mark.unit


def test_chk_tz_happy_path_budapest_summer():
    md = {
        "Composite:GPSLatitude": 47.4979,
        "Composite:GPSLongitude": 19.0402,
        "EXIF:DateTimeOriginal": "2024:07:15 12:00:00",
        "EXIF:OffsetTimeOriginal": "+02:00",
    }
    # Should not raise
    check_timezone_consistency(md)


def test_chk_tz_missing_gps_raises():
    md = {
        "EXIF:DateTimeOriginal": "2024:07:15 12:00:00",
        "EXIF:OffsetTimeOriginal": "+02:00",
    }
    with pytest.raises(TzMismatchError):
        check_timezone_consistency(md)


def test_chk_tz_mismatch_raises():
    md = {
        "Composite:GPSLatitude": 47.4979,
        "Composite:GPSLongitude": 19.0402,
        "EXIF:DateTimeOriginal": "2024:07:15 12:00:00",
        "EXIF:OffsetTimeOriginal": "+01:00",  # Wrong
    }
    with pytest.raises(TzMismatchError):
        check_timezone_consistency(md)


def test_chk_tz_fallback_xmp_timezone_string():
    md = {
        "Composite:GPSLatitude": 47.4979,
        "Composite:GPSLongitude": 19.0402,
        "EXIF:DateTimeOriginal": "2024:07:15 12:00:00",
        # No EXIF OffsetTime*, but XMP fallback present
        "XMP:TimeZone": "UTC+2",
    }
    check_timezone_consistency(md)


def test_chk_tz_exif_timezoneoffset_numeric_list():
    # Los Angeles in July is UTC-7
    md = {
        "Composite:GPSLatitude": 34.0522,
        "Composite:GPSLongitude": -118.2437,
        "EXIF:DateTimeOriginal": "2024:07:15 12:00:00",
        # Some cameras store as a list [standard, daylight] or a single number
        "EXIF:TimeZoneOffset": [-7, -7],
    }
    check_timezone_consistency(md)  # la_summer
