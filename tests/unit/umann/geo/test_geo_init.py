"""Unit tests for the umann.geo public API wrappers."""

from datetime import datetime

import pytest

from umann.geo import local_time_from_timestamp, tz_from_coords, tz_offset_from_tz_unaware_dt

pytestmark = pytest.mark.unit


@pytest.mark.unit
def test_tz_from_coords_wrapper():
    """Test the public API wrapper for tz_from_coords."""
    # Budapest coordinates
    tz_name = tz_from_coords(47.4979, 19.0402)
    assert tz_name == "Europe/Budapest"


@pytest.mark.unit
def test_tz_offset_from_tz_unaware_dt_wrapper():
    """Test the public API wrapper for tz_offset_from_tz_unaware_dt."""
    # Budapest in summer (CEST = UTC+2)
    dt_naive = datetime(2024, 7, 15, 12, 0, 0)
    offset = tz_offset_from_tz_unaware_dt(47.4979, 19.0402, dt_naive)
    assert offset is not None
    assert offset.total_seconds() == 2 * 3600  # +02:00


@pytest.mark.unit
def test_local_time_from_timestamp_wrapper():
    """Test the public API wrapper for local_time_from_timestamp."""
    # 2024-07-15 12:00:00 UTC as timestamp
    ts = 1721044800.0
    tz_name, offset, dt_local = local_time_from_timestamp(47.4979, 19.0402, ts)
    assert tz_name == "Europe/Budapest"
    assert offset is not None
    assert offset.total_seconds() == 2 * 3600  # CEST = UTC+2
    assert dt_local.hour == 14  # 12 UTC + 2 = 14 local
