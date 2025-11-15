"""Geospatial utilities for timezone resolution and coordinate handling.

This module provides stable import surfaces while avoiding heavy imports at
package import time. Functions are lazily imported from ``.tz4d`` to prevent
``python -m umann.geo.tz4d`` from triggering a runpy warning.
"""

import datetime as dt

__all__ = [
    "tz_from_coords",
    "tz_offset_from_tz_unaware_dt",
    "local_time_from_timestamp",
]


def tz_from_coords(lat: float, lon: float) -> str | None:
    from .tz4d import tz_from_coords as _impl  # pylint: disable=import-outside-toplevel

    return _impl(lat, lon)


def tz_offset_from_tz_unaware_dt(lat: float, lon: float, dt_naive: dt.datetime) -> dt.timedelta | None:
    from .tz4d import tz_offset_from_tz_unaware_dt as _impl  # pylint: disable=import-outside-toplevel

    return _impl(lat, lon, dt_naive)


def local_time_from_timestamp(lat: float, lon: float, ts: float):
    from .tz4d import local_time_from_timestamp as _impl  # pylint: disable=import-outside-toplevel

    return _impl(lat, lon, ts)
