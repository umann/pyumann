"""YAML helpers"""

import datetime as dt
import typing as t
from collections import defaultdict

import yaml
from munch import Munch


def stringify_datetime(data: dt.datetime, exif_compatible: bool = False) -> str:
    """Represent datetime as ISO format with space separator instead of 'T', suppressing trailing zeros."""
    iso_str = data.isoformat(sep=" ")
    # Strip trailing zeros from microseconds: "2025-10-27 15:22:36.615000" -> "2025-10-27 15:22:36.615"
    # But keep at least the decimal point if there are microseconds: ".000000" -> ""
    if "." in iso_str:
        iso_str = iso_str.rstrip("0").rstrip(".")
    if exif_compatible:
        # EXIF standard uses ':' as date separator
        iso_str = iso_str.replace("-", ":")
    return iso_str


def stringify_date(data: dt.date, exif_compatible: bool = False) -> str:
    """Represent date as ISO format (YYYY-MM-DD)."""
    iso_str = data.isoformat()
    if exif_compatible:
        # EXIF standard uses ':' as date separator
        iso_str = iso_str.replace("-", ":")
    return iso_str


def stringify_time(data: dt.time, exif_compatible: bool = False) -> str:  # pylint: disable=unused-argument
    """Represent time as ISO format (HH:MM:SS)."""
    iso_str = data.isoformat()
    return iso_str


def stringify_timedelta(data: dt.timedelta, exif_compatible: bool = False) -> str:  # pylint: disable=unused-argument
    """Represent timedelta as offset format (+HH:MM or -HH:MM), without seconds."""
    total_seconds = int(data.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def stringify_dt(data: dt.datetime | dt.date | dt.time | dt.timedelta, exif_compatible: bool = False) -> str:
    """Convert datetime, date, time, or timedelta to string with appropriate formatting."""
    for cls, func in [
        (dt.datetime, stringify_datetime),
        (dt.date, stringify_date),
        (dt.time, stringify_time),
        (dt.timedelta, stringify_timedelta),
    ]:
        if isinstance(data, cls):
            return func(data, exif_compatible)
    raise TypeError(f"Unsupported type for stringify_dt: {type(data)}")


def yaml_dump_cozy(data, stream=None, exif_compatible=False, **kwargs) -> str:
    """Dump data to YAML with custom datetime formatting.

    This function is a wrapper around yaml.dump() that formats datetime objects:
    - datetime.datetime --> ISO format with space separator (not 'T'): '2025-11-01 14:30:45'
    - datetime.date --> ISO format: '2025-11-01'
    - datetime.timedelta --> offset format without seconds: '+05:30' or '-08:00'
    - Munch --> regular dict
    - defaultdict --> regular dict

    Args:
        data: Python data structure to dump to YAML
        stream: File-like object to write to (or None to return string)
        **kwargs: Additional arguments passed to yaml.dump()

    Returns:
        YAML string if stream is None, otherwise None

    Example:
        >>> import datetime as dt
        >>> from umann.utils.data_utils import yaml_dump_cozy
        >>> data = {"created": dt.datetime(2025, 11, 1, 14, 30, 45)}
        >>> print(yaml_dump_cozy(data))
        created: '2025-11-01 14:30:45'
    """

    class DateTimeDumper(yaml.SafeDumper):
        """Custom YAML dumper with datetime formatting."""

    def _represent_datetime(dumper, data: dt.datetime):
        """Represent datetime as ISO format with space separator instead of 'T', suppressing trailing zeros."""
        return dumper.represent_scalar("tag:yaml.org,2002:str", stringify_datetime(data, exif_compatible))

    def _represent_date(dumper, data: dt.date):
        """Represent date as ISO format (YYYY-MM-DD)."""
        return dumper.represent_scalar("tag:yaml.org,2002:str", stringify_date(data, exif_compatible))

    def _represent_time(dumper, data: dt.time):
        """Represent time as ISO format (HH:MM:SS)."""
        return dumper.represent_scalar("tag:yaml.org,2002:str", stringify_time(data, exif_compatible))

    def _represent_timedelta(dumper, data: dt.timedelta):
        """Represent timedelta as offset format (+HH:MM or -HH:MM), without seconds."""
        return dumper.represent_scalar("tag:yaml.org,2002:str", stringify_timedelta(data, exif_compatible))

    def _represent_munch(dumper, data):
        """Represent Munch as a regular dict."""
        return dumper.represent_dict(dict(data))

    def _represent_defaultdict(dumper, data):
        """Represent defaultdict as a regular dict."""
        return dumper.represent_dict(dict(data))

    # Register representers for this dumper
    DateTimeDumper.add_representer(dt.datetime, _represent_datetime)
    DateTimeDumper.add_representer(dt.date, _represent_date)
    DateTimeDumper.add_representer(dt.time, _represent_time)
    DateTimeDumper.add_representer(dt.timedelta, _represent_timedelta)
    DateTimeDumper.add_representer(Munch, _represent_munch)
    DateTimeDumper.add_representer(defaultdict, _represent_defaultdict)

    return yaml.dump(data, stream, Dumper=DateTimeDumper, **kwargs)


def yaml_safe_load_file(fname: str) -> t.Any:
    """Load YAML content from a file handle safely."""
    try:
        with open(fname, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except Exception as e:
        raise RuntimeError(f"Failed to load YAML file '{fname}': {e}") from e
