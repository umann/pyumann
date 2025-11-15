"""DateTime consistency checking for image metadata.

Validates that datetime-related tags are consistent across EXIF, IPTC, and XMP namespaces.
"""

import datetime as dt
import re
import typing as t
from collections import defaultdict

from munch import Munch

from umann.config import get_config
from umann.metadata.chk_tz import MetadataError
from umann.utils.data_utils import get_multi, recurse
from umann.utils.trace_utils import calling_signature, str_exc
from umann.utils.yaml_utils import stringify_dt, stringify_timedelta

EXIFTOOL_GROUP = get_config("exiftool.group", "G1")
G0_TO_G1 = {
    "ExifIFD": "EXIF",
    "System": "File",
    "IFD0": "EXIF",
    "IFD1": "EXIF",
    "InteropIFD": "EXIF",
    "GPS": "EXIF",
    "XMP-dc": "XMP",
    "XMP-xmp": "XMP",
    "XMP-x": "XMP",
    "XMP-exif": "XMP",
    "MWG": "Composite",
    "IFD1:Compression": "IFD1:Compression",
    "IFD1:XResolution": "IFD1:XResolution",
    "IFD1:YResolution": "IFD1:YResolution",
}


class DateTimeConsistencyError(MetadataError):
    """Exception raised for datetime metadata inconsistencies."""


class DateTimeParseError(DateTimeConsistencyError):
    """Exception raised for datetime parsing errors."""


class OffsetParseError(DateTimeConsistencyError):
    """Exception raised for offset parsing errors."""


# patterns ending with 0 mean no ^ and $ anchors, can be used in larger patterns
EXIF_D0 = r"(?P<year>[0-9]{4}):(?P<month>[0-9]{2}):(?P<day>[0-9]{2})"
EXIF_T0 = r"(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
EXIF_DT0 = EXIF_D0 + r" " + EXIF_T0
EXIF_TZ0 = r"(?P<offset>[+-][0-9]{2}:[0-9]{2}|Z)"
EXIF_Z0 = r"(?P<offset>[+-]00:00|Z)"
EXIF_OPT_F0 = r"(?:[.](?P<subsec>[0-9]*))?"  # fraction of second, optional

# compile to speed up
# EXIF_D = re.compile(rf"^{EXIF_D0}$")
# EXIF_T = re.compile(rf"^{EXIF_T0}$")
EXIF_DT = re.compile(rf"^{EXIF_DT0}$")
# EXIF_DT_TZ = re.compile(rf"^{EXIF_DT0}{EXIF_TZ0}$")
EXIF_DT_OPT_TZ = re.compile(rf"^{EXIF_DT0}{EXIF_TZ0}?$")
EXIF_DT_OPT_F_OPT_TZ = re.compile(rf"^{EXIF_DT0}{EXIF_OPT_F0}{EXIF_TZ0}?$")
EXIF_DT_OPT_F_Z = re.compile(rf"^{EXIF_DT0}{EXIF_OPT_F0}{EXIF_Z0}$")
# EXIF_T_TZ = re.compile(rf"^{EXIF_T}{EXIF_TZ0}$")

TAGS = {
    "ExifIFD:DateTimeOriginal": {
        "anchor": True,
        "pattern": EXIF_DT_OPT_F_OPT_TZ,
        "offset_tag": "ExifIFD:OffsetTimeOriginal",
        "subsec_tag": "ExifIFD:SubSecTimeOriginal",
    },
    "ExifIFD:CreateDate": {
        "pattern": EXIF_DT_OPT_F_OPT_TZ,
        "offset_tag": "ExifIFD:OffsetTime",
        "subsec_tag": "ExifIFD:SubSecTime",
    },
    "ExifIFD:DateTimeDigitized": {
        "pattern": EXIF_DT_OPT_F_OPT_TZ,
        "offset_tag": "ExifIFD:OffsetTimeDigitized",
        "subsec_tag": "ExifIFD:SubSecTimeDigitized",
    },
    "XMP:DateTimeOriginal": {"pattern": EXIF_DT_OPT_F_OPT_TZ},
    "XMP:CreateDate": {"pattern": EXIF_DT_OPT_F_OPT_TZ},
    "XMP:DateCreated": {"pattern": EXIF_DT_OPT_F_OPT_TZ},
    "XMP:DateTimeDigitized": {"pattern": EXIF_DT_OPT_F_OPT_TZ},
    "XMP-exif:GPSDateTime": {"pattern": EXIF_DT_OPT_F_Z, "tz_aware": True},
    "IPTC:DateCreated": {"time_tag": "IPTC:TimeCreated", "pattern": EXIF_DT_OPT_TZ},
    "QuickTime:CreateDate": {"pattern": EXIF_DT_OPT_TZ},  # no subsec
    "MakerNotes:DateTimeUTC": {"pattern": EXIF_DT, "offset_val": "Z", "tolerance_secs": 10},
    "MakerNotes:TimeStamp": {"pattern": EXIF_DT_OPT_F_OPT_TZ, "tolerance_secs": 10},
    "EXIF:GPSDateStamp": {
        "time_tag": "EXIF:GPSTimeStamp",
        "pattern": EXIF_DT,
        "offset_val": "Z",
        "tolerance_secs": 1799,
        "tz_aware": True,
    },
}


def g0_to_g1(string: str) -> str:
    """Convert exiftool key string from exiftool G0 to G1 format."""
    if match := re.search(r"^(\w+):(\w+)", string):
        if ret := G0_TO_G1.get(string):
            return ret
        if ret := G0_TO_G1.get(match[1]):
            return ret + ":" + match[2]
    return string


if EXIFTOOL_GROUP == "G0":
    TAGS = recurse(TAGS, g0_to_g1, what=("key", "value"))


# Build entries for tags that are derived from a primary tag (time/offset/subsec companions)
# Avoid mutating TAGS while iterating over it to prevent RuntimeError.
def set_derived_additions() -> dict[str, dict[str, str]]:
    derived_additions: dict[str, dict[str, str]] = {}
    for tag, dic in TAGS.items():
        for key in ("time_tag", "offset_tag", "subsec_tag"):
            if derived_tag := dic.get(key):
                assert derived_tag not in TAGS, f"Derived tag already present: {derived_tag}"
                derived_additions[derived_tag] = {"derived_from": tag}
    if derived_additions:
        TAGS.update(derived_additions)
    return derived_additions


set_derived_additions()


# pylint: disable=too-many-locals
def _parse_dt_with_offset_from_md_tagname(
    md: dict[str, str], dt_tag: str
) -> tuple[dt.datetime, dt.timedelta | None, str | None]:
    """Parse datetime from metadata dictionary."""
    try:
        multi_tag = dt_tag  # for err msg
        dt_str = md[dt_tag]
        for key, prefix in dict(time_tag=" ", subsec_tag=".", offset_tag="").items():  # order matters
            if tag := get_multi(TAGS, [dt_tag, key], None):
                if val := md.get(tag):
                    multi_tag += "+" + tag
                    dt_str += prefix + str(val)
        # print(dt_tag, dt_str)
        pattern = get_multi(TAGS, [dt_tag, "pattern"])
        if match := re.search(pattern, dt_str):
            groupdict = match.groupdict()
            if offset := get_multi(TAGS, [dt_tag, "offset_val"], groupdict.pop("offset", None)):
                offset_timedelta = _parse_offset(offset)
            else:
                offset_timedelta = None
            subsec = groupdict.pop("subsec", None) or None
            # # Convert subseconds to microseconds at string level to avoid float rounding errors
            # subsec_str = groupdict.pop("subsec", "") or "0"
            # # Pad or truncate to 6 digits: "0163" -> "016300", "0163456789" -> "016345"
            # groupdict["microsecond"] = (subsec_str + "000000")[:6]

            dt_naive = dt.datetime(**{k: int(v) for k, v in groupdict.items()})
        else:
            raise DateTimeParseError(f"{dt_str!r} does not match {pattern.pattern!r}")

    except (DateTimeParseError, KeyError) as e:
        raise DateTimeParseError(f"Cannot parse {multi_tag} {str_exc(e)}") from e

    return dt_naive, offset_timedelta, subsec


def _parse_offset(offset_str: str) -> dt.timedelta:
    """Parse offset string like '+01:00' or '-05:30' to timedelta."""
    # offset_str = str(offset_str).strip()

    # Handle Z
    offset_str = re.sub(r"Z$", "+00:00", offset_str)
    # Parse +HH:MM or -HH:MM
    if match := re.match(r"^([+-])(\d{2}):(\d{2})$", offset_str):
        sign = 1 if match[1] == "+" else -1
        hours = int(match[2])
        minutes = int(match[3])
        return dt.timedelta(hours=sign * hours, minutes=sign * minutes)
    raise OffsetParseError(f"Invalid offset format: {calling_signature()}")


def _format_offset(td: dt.timedelta | None) -> str:
    """Format timedelta as +HH:MM or -HH:MM."""
    if td is None:
        return ""
    return stringify_timedelta(td)


def _datetime_to_utc(dt_naive: dt.datetime, offset: dt.timedelta) -> dt.datetime:
    """Convert naive datetime + offset to UTC datetime."""
    return dt_naive - offset


def exif_repr(data: t.Any) -> str:
    """Represent value in EXIF-compatible string format."""
    if data == "offset_timedelta":
        return "offset"
    if isinstance(data, (dt.datetime, dt.date, dt.time, dt.timedelta)):
        return stringify_dt(data, exif_compatible=True)
    return str(data)


def tag_and_derived(tag: str, md: dict) -> str:
    ret = tag
    for key in ("subsec_tag", "offset_tag"):
        if sub_tag := get_multi(TAGS, [tag, key], None):
            if md.get(sub_tag) is not None:
                ret += "+" + sub_tag
    return ret


# pylint: disable=too-many-branches,too-many-locals,too-many-statements
def check_datetime_consistency(
    md: dict[str, t.Any],
) -> dict[str, dict[str, t.Any]]:
    """Check datetime metadata consistency across EXIF, IPTC, and XMP tags.

    Args:
        md: Metadata dictionary from ExifTool
    Raises:
        DateTimeConsistencyError: If inconsistencies are found
    """
    ret = {}
    errors = []

    # Check if any datetime tag exists
    if not set(md) & set(TAGS):  # DERIVED_TAGS):
        return ret  # OK

    anchor_tag = next((tag for tag, dic in TAGS.items() if dic.get("anchor")), None)
    anchor = Munch(tag=anchor_tag, utc=None, dt_naive=None, offset_timedelta=None, subsec=None)

    # If any datetime-related tag exists, {EXIF,ExifIFD}:DateTimeOriginal must exist
    # Parse anchor datetime
    try:
        anchor.dt_naive, anchor.offset_timedelta, anchor.subsec = _parse_dt_with_offset_from_md_tagname(md, anchor.tag)

    except DateTimeParseError as e:
        if md.get(anchor.tag) is None or md.get(anchor.tag) == "                   ":
            if match := re.search(r"photos/(....)/(..)/(..)", md.get("SourceFile", "")):
                return {"fixable": {anchor.tag: f"{match[1]}:{match[2]}:{match[3]} 00:00:00"}}
        return {"fatal": {tag_and_derived(anchor.tag, md): str_exc(e)}}

    if anchor.offset_timedelta is None:
        errors.append(f"{anchor.tag}: missing offset")
    else:
        anchor.utc = _datetime_to_utc(anchor.dt_naive, anchor.offset_timedelta)

    dts = defaultdict(Munch)

    def deletable(datetime_tag: str, error_message: str):
        tags = tag_and_derived(datetime_tag, md).split("+")
        ret.setdefault("deletable", {})
        for tag in tags:
            if tag in ret["deletable"]:
                ret["deletable"][tag] += "; " + error_message
            else:
                ret["deletable"][tag] = error_message

    for datetime_tag, tag_dict in TAGS.items():
        if datetime_tag not in md:
            continue
        if derived_from := tag_dict.get("derived_from"):
            if derived_from not in md:
                deletable(datetime_tag, f"Missing {derived_from}")
            continue
        if datetime_tag == anchor.tag:
            continue
        try:
            dt_naive, offset_timedelta, subsec = _parse_dt_with_offset_from_md_tagname(md, datetime_tag)
            dts[datetime_tag].dt_naive = dt_naive

            if offset_val := tag_dict.get("offset_val"):
                offset_timedelta = _parse_offset(offset_val)
            if offset_timedelta is not None:
                dts[datetime_tag].offset_timedelta = offset_timedelta
                if anchor.offset_timedelta is None and offset_val is None:
                    anchor.offset_timedelta = offset_timedelta
                utc = _datetime_to_utc(dt_naive, offset_timedelta)
                dts[datetime_tag].utc = utc
                if anchor.utc is None:
                    anchor.utc = utc
            if subsec is not None and anchor.subsec is None:
                dts[datetime_tag].subsec = subsec
                anchor.subsec = subsec
        except (DateTimeConsistencyError, TypeError) as e:
            deletable(datetime_tag, str_exc(e))

    # End parsing pass; proceed to comparisons
    for datetime_tag, dic in dts.items():
        for key, val in dic.items():
            # tags with fixed offset_val are skipped because other tags have their own TZ offset and cannot compare
            if key != "utc" and get_multi(TAGS, [datetime_tag, "offset_val"], None) is not None:
                continue
            if key == "dt_naive" and get_multi(TAGS, [datetime_tag, "tz_aware"], None):
                continue
            anchor_val = anchor[key]
            if key in ["utc", "dt_naive"]:
                tolerance_secs = TAGS[datetime_tag].get("tolerance_secs", 0)
                diff_secs = int(abs((val - anchor_val).total_seconds()))
                if diff_secs > tolerance_secs:
                    error_message = (
                        f"{datetime_tag} {exif_repr(key)}={exif_repr(val)} vs. "
                        + f"{anchor.tag} {exif_repr(anchor_val)} {diff_secs=} {tolerance_secs=}"
                    )
                    deletable(datetime_tag, error_message)
            else:
                if val != anchor_val:
                    if (
                        key == "offset_timedelta"
                        and not TAGS[datetime_tag].get("offset_tag")
                        and not TAGS[datetime_tag].get("tz_aware")
                    ):
                        fix_value = md[datetime_tag].removesuffix(exif_repr(val)) + exif_repr(anchor_val)
                        ret.setdefault("fixable", {})[datetime_tag] = fix_value
                    else:
                        error_message = (
                            f"{datetime_tag} {exif_repr(key)}={exif_repr(val)} != {anchor.tag} {exif_repr(anchor_val)}"
                        )
                        deletable(datetime_tag, error_message)
        if "utc" not in dic and anchor.get("utc"):
            if anchor.offset_timedelta is not None and (offset := _format_offset(anchor.offset_timedelta)):
                if offset_tag := TAGS[datetime_tag].get("offset_tag"):
                    ret.setdefault("fixable", {})[offset_tag] = offset
                elif time_tag := TAGS[datetime_tag].get("time_tag"):
                    ret.setdefault("fixable", {})[time_tag] = f"{md[time_tag]}{offset}"
                else:
                    ret.setdefault("fixable", {})[datetime_tag] = f"{md[datetime_tag]}{offset}"
            else:
                deletable(datetime_tag, "could not determine UTC datetime for comparison")
    return ret
