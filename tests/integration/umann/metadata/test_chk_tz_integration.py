"""Integration tests for timezone consistency with border tolerance.

Validates that a declared offset near a timezone border is accepted
when a neighboring zone within the given tolerance matches.
"""

from __future__ import annotations

import pytest

from umann.metadata.chk_tz import check_timezone_consistency

pytestmark = pytest.mark.integration


def test_declared_offset_accepted_near_border_with_tolerance():
    # Coordinates near the Hungary/Ukraine border; in summer 2017, local offsets
    # can differ by one hour across the border (CEST +02 vs EEST +03).
    # Declared here is +02:00 while exact coords may resolve to +03:00.
    # With tolerance enabled, a nearby point within the specified distance
    # matching the declared offset should be accepted.
    md = {
        "Composite:GPSLatitude": 48.09232003,
        "Composite:GPSLongitude": 22.67629623,
        "EXIF:DateTimeOriginal": "2017:07:30 16:09:20",
        "EXIF:OffsetTimeOriginal": "+02:00",
    }  # River Tisza Ukraine side, accepting Hungary side TZ offset

    # Use a practical tolerance to account for being just across the border.
    # Increase if data updates shift polygon boundaries slightly.
    check_timezone_consistency(md, tolerance_in_meters=3000)
