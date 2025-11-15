"""Tests for tz4d.py functions."""

import time
from datetime import datetime, timedelta
from unittest import mock

import pytest

from umann.geo.tz4d import (
    _expected_geojson_ids,
    _geojson_dir_complete,
    _needs_rebuild,
    local_time_from_timestamp,
    parse_iso,
    tz_from_coords,
    tz_offset_from_tz_unaware_dt,
)

pytestmark = pytest.mark.unit

PARIS = (48.8566, 2.3522)  # Europe/Paris
NEW_YORK = (40.7128, -74.0060)  # America/New_York
BUDAPEST = (47.4979, 19.0402)  # Europe/Budapest
LONDON = (51.5074, -0.1278)  # Europe/London
TOKYO = (35.6762, 139.6503)  # Asia/Tokyo
SYDNEY = (-33.8688, 151.2093)  # Australia/Sydney
LOS_ANGELES = (34.0522, -118.2437)  # America/Los_Angeles
MEDITERRANEO_FRA_OLBIA_E_LIVORNO = (41.81099325, 9.84918343)


def test_tz_from_coords_paris():
    assert tz_from_coords(*PARIS) == "Europe/Paris"


def test_tz_from_coords_new_york():
    assert tz_from_coords(*NEW_YORK) == "America/New_York"


def test_tz_from_coords_budapest():
    assert tz_from_coords(*BUDAPEST) == "Europe/Budapest"


def test_tz_from_coords_london():
    assert tz_from_coords(*LONDON) == "Europe/London"


def test_tz_from_coords_tokyo():
    assert tz_from_coords(*TOKYO) == "Asia/Tokyo"


def test_tz_from_coords_sydney():
    assert tz_from_coords(*SYDNEY) == "Australia/Sydney"


def test_tz_from_coords_los_angeles():
    assert tz_from_coords(*LOS_ANGELES) == "America/Los_Angeles"


def test_tz_from_coords_mediterraneo():
    assert tz_from_coords(*MEDITERRANEO_FRA_OLBIA_E_LIVORNO) == "Europe/Rome"


def test_tz_from_coords_mediterraneo_no_tolerance():
    assert tz_from_coords(*MEDITERRANEO_FRA_OLBIA_E_LIVORNO, tolerance_lon_delta_deg=0) is None


def test_tz_offset_for_mediterraneo_fra_olbia_e_livorno():
    # Offset for 2011-07-01T12:00:00 at : 2:00:00 (Europe/Rome)
    dt = datetime(2011, 7, 1, 12, 0, 0)
    off = tz_offset_from_tz_unaware_dt(*MEDITERRANEO_FRA_OLBIA_E_LIVORNO, dt)
    assert off == timedelta(hours=2)


def test_tz_from_coords_ocean_returns_nearest():
    # Middle of Pacific Ocean should fall back to nearest timezone
    result = tz_from_coords(0.0, -160.0)
    assert isinstance(result, str) and len(result) > 0


def test_offset_normal_day_paris():
    # Jan 10, 2024 12:00 local in Paris -> UTC+1
    dt = datetime(2024, 1, 10, 12, 0, 0)
    off = tz_offset_from_tz_unaware_dt(*PARIS, dt)
    assert off == timedelta(hours=1)


def test_offset_summer_day_paris():
    # July 15, 2024 12:00 local in Paris -> UTC+2
    dt = datetime(2024, 7, 15, 12, 0, 0)
    off = tz_offset_from_tz_unaware_dt(*PARIS, dt)
    assert off == timedelta(hours=2)


def test_offset_winter_new_york():
    # Jan 10, 2024 12:00 local in New York -> UTC-5
    dt = datetime(2024, 1, 10, 12, 0, 0)
    off = tz_offset_from_tz_unaware_dt(*NEW_YORK, dt)
    assert off == timedelta(hours=-5)


def test_offset_summer_new_york():
    # July 15, 2024 12:00 local in New York -> UTC-4
    dt = datetime(2024, 7, 15, 12, 0, 0)
    off = tz_offset_from_tz_unaware_dt(*NEW_YORK, dt)
    assert off == timedelta(hours=-4)


def test_offset_no_tz():
    # July 15, 2024 12:00 local in New York -> UTC-4
    with mock.patch("umann.geo.tz4d.tz_from_coords", return_value=None):
        dt = datetime(2024, 7, 15, 12, 0, 0)
        off = tz_offset_from_tz_unaware_dt(*NEW_YORK, dt)
        assert off is None


def test_local_time_from_timestamp_no_tz():
    with mock.patch("umann.geo.tz4d.tz_from_coords", return_value=None):
        tz_name, offset, local_dt = local_time_from_timestamp(*NEW_YORK, 1704888000)
        assert tz_name is None
        assert offset is None
        assert local_dt is None


@pytest.mark.parametrize(
    "dt_local, expected_hours",
    [
        # Spring forward gap in Paris: 2024-03-31 02:00 skips to 03:00
        (datetime(2024, 3, 31, 2, 30, 0), 2),
        # Fall back ambiguity in Paris: 2024-10-27 02:30 occurs twice; prefer new tz (UTC+1)
        (datetime(2024, 10, 27, 2, 30, 0), 1),
    ],
)
def test_transition_rules_paris(dt_local, expected_hours):
    off = tz_offset_from_tz_unaware_dt(*PARIS, dt_local)
    assert off == timedelta(hours=expected_hours)


def test_local_time_from_timestamp_paris():
    # Unix timestamp 1721001600 = 2024-07-15 00:00:00 UTC
    # Paris in July is UTC+2 -> 2024-07-15 02:00:00
    tz_name, offset, local_dt = local_time_from_timestamp(*PARIS, 1721001600)
    assert tz_name == "Europe/Paris"
    assert offset == timedelta(hours=2)
    assert local_dt.year == 2024
    assert local_dt.month == 7
    assert local_dt.day == 15
    assert local_dt.hour == 2
    assert local_dt.minute == 0


def test_local_time_from_timestamp_new_york():
    # Unix timestamp 1704888000 = 2024-01-10 12:00:00 UTC
    # New York in January is UTC-5 -> 2024-01-10 07:00:00
    tz_name, offset, local_dt = local_time_from_timestamp(*NEW_YORK, 1704888000)
    assert tz_name == "America/New_York"
    assert offset == timedelta(hours=-5)
    assert local_dt.hour == 7


def test_local_time_from_timestamp_ocean_returns_nearest():
    # Middle of ocean should fall back to nearest timezone
    tz_name, offset, local_dt = local_time_from_timestamp(0.0, -160.0, 1720965000)
    assert isinstance(tz_name, str) and len(tz_name) > 0
    assert offset is not None
    assert local_dt is not None


def test_parse_iso_with_z():
    dt = parse_iso("2024-07-15T12:00:00Z")
    assert dt.year == 2024
    assert dt.month == 7
    assert dt.day == 15
    assert dt.hour == 12
    assert dt.tzinfo.tzname(None) == "UTC"


def test_parse_iso_with_offset():
    dt = parse_iso("2024-07-15T12:00:00+02:00")
    assert dt.year == 2024
    assert dt.month == 7
    assert dt.day == 15
    assert dt.hour == 12
    assert dt.tzinfo is not None


def test_parse_iso_naive():
    dt = parse_iso("2024-07-15T12:00:00")
    assert dt.year == 2024
    assert dt.month == 7
    assert dt.day == 15
    assert dt.hour == 12


def test_tz_offset_for_ocean_returns_nearest():
    # Middle of ocean - should fall back to nearest timezone
    dt = datetime(2024, 7, 15, 12, 0, 0)
    off = tz_offset_from_tz_unaware_dt(0.0, -160.0, dt)
    assert off is not None


def test_offset_tokyo_no_dst():
    # Tokyo doesn't observe DST, always UTC+9
    dt_winter = datetime(2024, 1, 10, 12, 0, 0)
    dt_summer = datetime(2024, 7, 15, 12, 0, 0)
    off_winter = tz_offset_from_tz_unaware_dt(*TOKYO, dt_winter)
    off_summer = tz_offset_from_tz_unaware_dt(*TOKYO, dt_summer)
    assert off_winter == timedelta(hours=9)
    assert off_summer == timedelta(hours=9)


def test_offset_sydney_southern_hemisphere():
    # Sydney: summer in Jan (UTC+11), winter in July (UTC+10)
    dt_jan = datetime(2024, 1, 15, 12, 0, 0)
    dt_jul = datetime(2024, 7, 15, 12, 0, 0)
    off_jan = tz_offset_from_tz_unaware_dt(*SYDNEY, dt_jan)
    off_jul = tz_offset_from_tz_unaware_dt(*SYDNEY, dt_jul)
    assert off_jan == timedelta(hours=11)
    assert off_jul == timedelta(hours=10)


def test_transition_new_york_spring_forward():
    # 2024-03-10 02:00 AM springs forward to 03:00 AM in New York
    dt = datetime(2024, 3, 10, 2, 30, 0)
    off = tz_offset_from_tz_unaware_dt(*NEW_YORK, dt)
    # Should use post-transition offset (UTC-4)
    assert off == timedelta(hours=-4)


def test_transition_new_york_fall_back():
    # 2024-11-03 02:00 AM falls back to 01:00 AM in New York
    dt = datetime(2024, 11, 3, 1, 30, 0)
    off = tz_offset_from_tz_unaware_dt(*NEW_YORK, dt)
    # Should prefer new tz (UTC-5, standard time)
    assert off == timedelta(hours=-5)


def test_needs_rebuild_missing_pickle(tmp_path):
    # When pickle doesn't exist, should need rebuild
    pkl = tmp_path / "index.pkl"
    geojson_dir = tmp_path / "geojson"
    geojson_dir.mkdir()
    tz_json = tmp_path / "timezones.json"
    tz_json.write_text("{}")

    assert _needs_rebuild(pkl, geojson_dir, tz_json) is True


def test_needs_rebuild_pickle_exists_no_changes(tmp_path):
    # When pickle exists and is newer than all sources, no rebuild needed
    pkl = tmp_path / "index.pkl"
    pkl.write_text("fake pickle")
    geojson_dir = tmp_path / "geojson"
    geojson_dir.mkdir()
    tz_json = tmp_path / "timezones.json"
    tz_json.write_text("{}")

    # Touch pickle to make it newest
    time.sleep(0.01)
    pkl.touch()

    assert _needs_rebuild(pkl, geojson_dir, tz_json) is False


def test_needs_rebuild_timezones_json_newer(tmp_path):
    # When timezones.json is newer, needs rebuild
    pkl = tmp_path / "index.pkl"
    pkl.write_text("fake pickle")
    geojson_dir = tmp_path / "geojson"
    geojson_dir.mkdir()
    tz_json = tmp_path / "timezones.json"

    time.sleep(0.01)
    tz_json.write_text("{}")

    assert _needs_rebuild(pkl, geojson_dir, tz_json) is True


def test_needs_rebuild_geojson_file_newer(tmp_path):
    # When any geojson file is newer, needs rebuild
    pkl = tmp_path / "index.pkl"
    pkl.write_text("fake pickle")
    geojson_dir = tmp_path / "geojson"
    geojson_dir.mkdir()
    tz_json = tmp_path / "timezones.json"
    tz_json.write_text("{}")

    time.sleep(0.01)
    geo_file = geojson_dir / "Europe-Paris-tz.json"
    geo_file.write_text("{}")

    assert _needs_rebuild(pkl, geojson_dir, tz_json) is True


def test_expected_geojson_ids(tmp_path):
    # Test extraction of geojson IDs from timezones.json
    tz_json = tmp_path / "timezones.json"
    tz_json.write_text(
        """
    {
      "Europe/Paris": [{"id": "Europe-Paris-tz"}],
      "America/New_York": [{"id": "America-New_York-tz"}],
      "Asia/Tokyo": [{"id": "Asia-Tokyo-tz"}]
    }
    """
    )

    ids = _expected_geojson_ids(tz_json)
    assert sorted(ids) == ["America-New_York-tz", "Asia-Tokyo-tz", "Europe-Paris-tz"]


def test_geojson_dir_complete_all_present(tmp_path):
    # All expected files present
    geojson_dir = tmp_path / "geojson"
    geojson_dir.mkdir()
    (geojson_dir / "Europe-Paris-tz.json").write_text("{}")
    (geojson_dir / "Asia-Tokyo-tz.json").write_text("{}")

    complete, missing = _geojson_dir_complete(geojson_dir, ["Europe-Paris-tz", "Asia-Tokyo-tz"])
    assert complete is True
    assert not missing


def test_geojson_dir_complete_some_missing(tmp_path):
    # Some files missing
    geojson_dir = tmp_path / "geojson"
    geojson_dir.mkdir()
    (geojson_dir / "Europe-Paris-tz.json").write_text("{}")

    complete, missing = _geojson_dir_complete(geojson_dir, ["Europe-Paris-tz", "Asia-Tokyo-tz", "America-New_York-tz"])
    assert complete is False
    assert sorted(missing) == ["America-New_York-tz", "Asia-Tokyo-tz"]
