"""Timezone consistency check helpers for ExifTool metadata."""

import math
import re
import typing as t
from contextlib import suppress
from datetime import datetime, timedelta

from umann.geo.tz4d import tz_from_coords, tz_offset_from_tz_unaware_dt


class MetadataError(Exception):
    """Base class for metadata-related errors."""


class TzMismatchError(MetadataError):
    """Exception raised for timezone mismatches in metadata."""


class NoCaptureDateTimeError(MetadataError):
    """Exception raised for missing capture date/time in metadata."""


class NoGpsError(MetadataError):
    """Exception raised for missing GPS coordinates in metadata."""


def _parse_exif_datetime(dt_str: str) -> datetime:
    """Parse EXIF-style 'YYYY:MM:DD HH:MM:SS' into a naive datetime.

    Falls back to datetime.fromisoformat for ISO-like strings.
    """
    dt_str = str(dt_str)
    # Common EXIF format
    match = re.match(r"^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})$", dt_str)
    if match:
        return datetime(*map(int, match.groups()))
    # Try ISO
    with suppress(Exception):
        # Handle trailing Z
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        return datetime.fromisoformat(dt_str).replace(tzinfo=None)
    raise TzMismatchError(f"Unrecognized datetime format: {dt_str!r}")


def _format_offset_hhmm(td: t.Optional[timedelta]) -> str:
    """Format a timedelta offset to +HH:MM/-HH:MM string."""
    if td is None:
        raise TzMismatchError("No timezone offset available")
    total_minutes = int(td.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hh, mm = divmod(total_minutes, 60)
    return f"{sign}{hh:02d}:{mm:02d}"


def _extract_lat_lon(md: dict[str, t.Any]) -> tuple[float, float]:
    """Extract latitude and longitude from metadata.

    Looks for Composite and EXIF keys.
    """
    candidates = [
        ("Composite:GPSLatitude", "Composite:GPSLongitude"),
        ("EXIF:GPSLatitude", "EXIF:GPSLongitude"),
    ]
    for lat_key, lon_key in candidates:
        lat = md.get(lat_key)
        lon = md.get(lon_key)
        if lat is not None and lon is not None:
            try:
                return float(lat), float(lon)
            except Exception:  # pylint: disable=broad-exception-caught
                pass
    raise NoGpsError("No GPS coordinates in metadata (latitude/longitude missing)")


def _extract_offset(md: dict[str, t.Any]) -> str:
    """Extract timezone offset from EXIF tags, as +HH:MM/-HH:MM string."""

    def normalize(s: str) -> str | None:
        s = s.strip()
        # Already +HH:MM
        if re.fullmatch(r"[+-]\d{2}:\d{2}", s):
            return s
        # +HHMM -> +HH:MM
        m = re.fullmatch(r"([+-])(\d{2})(\d{2})", s)
        if m:
            sign, hh, mm = m.groups()
            return f"{sign}{int(hh):02d}:{int(mm):02d}"
        # UTC+H[H][:MM] or GMT+H[H][:MM]
        m = re.fullmatch(r"(?i)(?:UTC|GMT)\s*([+-]?\d{1,2})(?::?(\d{2}))?", s)
        if m:
            hh, mm = m.groups()
            sign = "+" if not str(hh).startswith(("+", "-")) else ("+" if str(hh)[0] == "+" else "-")
            hh_int = int(hh)
            if hh_int < 0:
                sign = "-"
                hh_int = abs(hh_int)
            mm_int = int(mm) if mm else 0
            return f"{sign}{hh_int:02d}:{mm_int:02d}"
        # Plain H[H][:MM]
        m = re.fullmatch(r"([+-]?\d{1,2})(?::(\d{2}))?", s)
        if m:
            hh, mm = m.groups()
            hh_int = int(hh)
            sign = "+" if hh_int >= 0 else "-"
            hh_int = abs(hh_int)
            mm_int = int(mm) if mm else 0
            return f"{sign}{hh_int:02d}:{mm_int:02d}"
        return None

    # Primary EXIF tags
    for key in ("EXIF:OffsetTimeOriginal", "EXIF:OffsetTimeDigitized", "EXIF:OffsetTime"):
        val = md.get(key)
        if val:
            if (norm := normalize(str(val))) is not None:
                return norm

    # EXIF:TimeZoneOffset may be number or list (hours)
    key0 = "EXIF:TimeZoneOffset"
    tz_off = md.get(key0)
    if tz_off is not None:
        if isinstance(tz_off, (list, tuple)) and tz_off:
            tz_off = tz_off[0]
        norm = normalize(str(tz_off))
        if norm is not None:
            return norm

    # XMP variants and QuickTime if they contain recognizable offsets

    keys = [
        "XMP:TimeZone",
        "XMP:Timezone",
        "XMP:TimeZoneOffset",
        "XMP:TimezoneOffset",
        "QuickTime:TimeZone",
        "QuickTime:Timezone",
    ]
    for key in keys:
        val = md.get(key)
        if val:
            if (norm := normalize(str(val))) is not None:
                return norm

    # As a last resort, scan all keys for a value that looks like an offset
    for _k, v in md.items():
        if isinstance(v, str) and normalize(v):
            return normalize(v)  # type: ignore[return-value]
    raise TzMismatchError(f"Missing timezone offset tag(s): {', '.join([key0] + keys)}")


def _extract_naive_local_datetime(md: dict[str, t.Any]) -> datetime:
    """Extract a representative local datetime to check offset against."""
    for key in (
        "EXIF:DateTimeOriginal",
        "EXIF:CreateDate",
        "EXIF:DateTimeDigitized",
        "XMP:DateTimeOriginal",
        "QuickTime:CreateDate",
    ):
        val = md.get(key)
        if val:
            return _parse_exif_datetime(str(val))
    raise NoCaptureDateTimeError("Missing capture datetime (e.g., EXIF:DateTimeOriginal)")


# pylint: disable=too-many-locals
def check_timezone_consistency(md: dict[str, t.Any], tolerance_in_meters: int | float = 200) -> None:
    """Check that timezone offset tags agree with GPS coords for the capture time.

    Raises TzMismatchError on any inconsistency or missing required data.
    """
    lat, lon = _extract_lat_lon(md)
    declared = _extract_offset(md)
    dt_local = _extract_naive_local_datetime(md)

    expected_td = tz_offset_from_tz_unaware_dt(lat, lon, dt_local)
    if expected_td is None:
        raise TzMismatchError(f"Cannot resolve timezone at coords ({lat}, {lon}); tz={tz_from_coords(lat, lon)}")
    expected = _format_offset_hhmm(expected_td)

    if expected != declared:
        # Border tolerance: if a neighboring timezone within the specified
        # distance has the declared offset at this wall time, accept it.
        try:
            lat_rad = math.radians(lat)
            # Rough meters-per-degree approximations
            m_per_deg_lat = 111_320.0
            m_per_deg_lon = max(1e-6, m_per_deg_lat * math.cos(lat_rad))
            dlat = float(tolerance_in_meters) / m_per_deg_lat
            dlon = float(tolerance_in_meters) / m_per_deg_lon
            candidates = (
                (lat + dlat, lon),
                (lat - dlat, lon),
                (lat, lon + dlon),
                (lat, lon - dlon),
                (lat + dlat, lon + dlon),
                (lat + dlat, lon - dlon),
                (lat - dlat, lon + dlon),
                (lat - dlat, lon - dlon),
            )
            for la, lo in candidates:
                td = tz_offset_from_tz_unaware_dt(la, lo, dt_local)
                if td is None:
                    continue
                if _format_offset_hhmm(td) == declared:
                    return  # close to a border; treat as acceptable
        except Exception:  # pylint: disable=broad-exception-caught
            # On any unexpected error in tolerance logic, fall back to strict behavior
            pass

        raise TzMismatchError(f"Timezone offset mismatch: {declared=}, {expected=} at ({lat}, {lon}) for {dt_local}")
