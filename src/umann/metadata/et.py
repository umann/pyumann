"""ExifTool interface for metadata operations.

This module provides a high-level interface to ExifTool for reading and writing
metadata in image files.
"""

import copy
import glob
import json
import re
import shlex
import sys
import typing as t
from functools import lru_cache
from pathlib import Path

import exiftool
import yaml
from munch import Munch, munchify

from umann.config import get_config
from umann.metadata import chk_tz as _chk_tz
from umann.metadata.chk_tz import NoCaptureDateTimeError, NoGpsError, TzMismatchError
from umann.metadata.memoize import get_file_rec, get_file_rec_multi, has_metadata_ext
from umann.utils.data_utils import get_multi, pop_multi
from umann.utils.fs_utils import project_root
from umann.utils.log_utils import setup_package_logger
from umann.utils.yaml_utils import yaml_safe_load_file

_logger = setup_package_logger()

TYPE_NAME_TO_CONVERTER = {
    "int": int,
    "float": float,
    "str": str,
    "list[str]": lambda x: (
        [str(i).strip() for i in x if str(i).strip()]
        if isinstance(x, list)
        else [str(x).strip()] if str(x).strip() else None
    ),
    "x_separated": lambda val: "x".join(val.split()),
    "signed_8f_comma_separated": lambda val: ", ".join(f"{float(v):+.8f}" for v in re.split(r"\s*,\s*", val)),
    "flatten_if_not_multiple": lambda val: val[0] if isinstance(val, list) and len(val) == 1 else val,
    "split_by_semicolon": lambda val: [v.strip() for v in re.split(r"\s*;\s*", val) if v.strip()],
}
EXIFTOOL_GROUP = get_config("exiftool.group", "G1")
EXIFTOOL_ARGS = ["-struct", f"-{EXIFTOOL_GROUP}", "-j", "-api", "StructFormat=JSONQ"]
SEEN = set()


def apply_tag_type(tag: str, value: t.Any) -> t.Any:
    try:
        ret = TYPE_NAME_TO_CONVERTER.get(get_tag_type(tag), lambda x: x)(value)
        # if not isinstance(ret, (type(None), int, float, str, list, dict, bool)):
        #     breakpoint()
        return ret
    except (ValueError, TypeError) as e:
        if tag not in SEEN:
            SEEN.add(tag)
            msg = f"Error converting {tag}: {value!r} to type {get_tag_type(tag)}: {e!r}"
            _logger.error(msg)
        return str(value) if value is not None else None


def apply_tag_type_in_place(metadata: dict, tag: str):
    metadata[tag] = apply_tag_type(tag, metadata[tag])


def get_tag_type(tag: str, default: str = "str") -> str:
    """Get the type of a given ExifTool tag from the tag types YAML configuration. Defaults to "str" """
    return read_tag_types_yaml().get(tag, default)


@lru_cache
def read_tag_types_yaml() -> dict[str, t.Any]:
    """Load and parse the ExifTool tag types YAML configuration file.

    Returns:
        A dict containing the parsed YAML configuration for tag types.
        The result is cached for performance.
    """
    return yaml_safe_load_file(
        project_root(f"data/exiftool/tag_types.{EXIFTOOL_GROUP}.yaml")
    )  # , with_override=True ???


@lru_cache
def default_et_config() -> dict[str, t.Any]:
    """Get default ExifTool configuration.

    Returns:
        Default configuration dictionary with common arguments and config file path.
        The configuration is cached for performance.
    """
    return {"common_args": EXIFTOOL_ARGS, "config_file": project_root(".ExifTool_config")}


def helper(**kwargs) -> exiftool.ExifToolHelper:
    """Create an ExifTool helper with default configuration.

    Args:
        **kwargs: Additional configuration to override defaults.

    Returns:
        Configured ExifTool helper instance.
    """
    return exiftool.ExifToolHelper(**(default_et_config() | kwargs))


def set_exif_types(metadata: dict[str, t.Any]) -> dict[str, t.Any]:
    """Apply correct ExifTool tag types to metadata dictionary."""
    metadata = metadata.copy()
    for tag in metadata:
        apply_tag_type_in_place(metadata, tag)
    return metadata


def simple_out(metadata: dict[str, t.Any]) -> dict[str, t.Any]:
    """Apply simple output transformations to metadata."""

    metadata = copy.deepcopy(metadata)
    md_yaml = munchify(read_metadata_yaml())
    for path, val_to_del in md_yaml._del.items():  # pylint: disable=protected-access
        pop_multi(metadata, path, default=None, pop_list_items=True, val_to_del=val_to_del)

    return metadata


def check(metadata: dict[str, t.Any]) -> dict[str, t.Any]:
    """Check metadata for consistency across equivalent fields.

    Args:
        metadata: Metadata dictionary to check.

    Returns:
        The same metadata dictionary if checks pass.

    Raises:
        ValueError: If equivalent fields have different values.
    """
    md_yaml = munchify(read_metadata_yaml())
    for group in md_yaml._eq:  # pylint: disable=protected-access
        if len(set(i for i in (get_multi(metadata, path, None) for path in group) if i is not None)) > 1:
            # Build error dict with non-None values
            error_dict = {}
            for path in group:
                val = get_multi(metadata, path, None)
                if val is not None:
                    error_dict[path] = val
            raise ValueError(error_dict)
    return metadata


TRANSFORMATORS = dict(
    set_exif_types=set_exif_types,
    simple_out=simple_out,
    # cool_out=cool_out,
)


def transform_metadata(
    metadata: dict[str, t.Any] | None, /, transformations: t.Iterable[str] = (), debug: t.Any = None
) -> dict[str, t.Any] | None:
    """Transform metadata output as needed.

    Args:
        metadata: The original metadata dictionary.
        transformations: A list of transformation types to apply.

    Returns:
        The transformed metadata dictionary.
    """

    if metadata is None:
        return None
    for transformation, func in TRANSFORMATORS.items():
        if transformation in transformations:
            try:
                metadata = func(metadata)
            except Exception as e:
                print(f"Error applying transformation {transformation}: {e} {debug=}", file=sys.stderr)
                # breakpoint()
                raise
    return metadata


@lru_cache
def read_metadata_yaml() -> Munch:
    """Load and parse the metadata tags YAML configuration file.

    Returns:
        A Munch object containing the parsed YAML configuration for metadata transformations.
        The result is cached for performance.
    """
    with open(Path(__file__).parent / "metadata_tags.yaml", encoding="utf-8") as infh:
        return munchify(yaml.safe_load(infh))


@lru_cache
def exiftool_lower_exts() -> set[str]:
    return {e.lower() for e in get_config("exiftool.exts", [])}


def can_handle(fname: str) -> bool:
    """Check if the file can be handled based on its extension."""
    return Path(fname).suffix.lower() in exiftool_lower_exts()


def get_metadata_multi(
    wildcards: t.Iterable[str], /, one_by_one: bool = False, **kwargs
) -> dict[str, dict[str, t.Any]]:
    """Get metadata for multiple files."""
    if one_by_one:
        ret = {}
        fnames = [f for wildcard in wildcards for f in glob.glob(wildcard)]
        for fname in fnames:
            ret[fname] = get_metadata(fname, **kwargs)
        return ret

    # fnames = list(fnames)  # not to consume it if iterator/generator

    # Open ExifTool once for all files that need metadata extraction
    with helper() as extl:

        def _get(fname):
            """Extract metadata using the shared ExifTool process."""
            if not can_handle(fname) or not has_metadata_ext(fname):
                return {}
            try:
                got_metadata = extl.execute(fname)
            except Exception as e:  # pylint: disable=broad-except  # TODO
                _logger.error(f"Error getting metadata for {fname}: {e}")
                got_metadata = [{"Error": str(e)}]
            if isinstance(got_metadata, str):
                got_metadata = json.loads(got_metadata, parse_float=str, parse_int=str)
            return got_metadata[0]

        # Cache lookup/update happens here; _get is called only for cache misses
        md_multi = get_file_rec_multi(wildcards, func=_get, cmd=shlex.join(["exiftool", *EXIFTOOL_ARGS]))

    # Apply final transformations
    transformed = {}
    for fname, md in md_multi.items():
        transformed[fname] = transform_metadata(md, debug=dict(fname=fname), **kwargs)

    return transformed


def get_metadata(fname: str, /, **kwargs) -> dict[str, t.Any]:
    """Get metadata for one file."""

    if not has_metadata_ext(fname):
        return {}

    def _get(fname):
        with helper() as extl:
            got_metadata = extl.execute(fname)
            if isinstance(got_metadata, str):
                got_metadata = json.loads(got_metadata, parse_float=str, parse_int=str)
            return got_metadata[0]

    try:
        md = get_file_rec(fname, func=_get, cmd=shlex.join(["exiftool", *EXIFTOOL_ARGS]))
    except Exception as e:
        print(f"Error getting metadata for {fname}: {e}", file=sys.stderr)
        raise
    # if not isinstance(md, dict):
    #     breakpoint()
    return transform_metadata(md or {}, debug=dict(fname=fname), **kwargs)


def set_metadata(fname_s: str | t.Iterable[str], tags, /, **kwargs) -> str | bytes | list[str | bytes]:
    """Set metadata for one or multiple files.

    Note: To delete a tag, pass None as the value. It will be converted to an empty string
    which signals exiftool to remove the tag.
    """
    if isinstance(fname_s, str):
        fname = fname_s
    else:
        ret: list[str | bytes] = []
        for fname in fname_s:
            ret += set_metadata(fname, tags, **kwargs)
        return ret

    with helper() as extl:
        try:
            md = dict(tags)
            # Convert None values to empty strings for tag deletion
            md = {k: "" if v is None else v for k, v in md.items()}
            ret = extl.set_tags(fname, md)
        except Exception as e:  # pylint: disable=broad-except  # TODO
            raise RuntimeError(f"Error setting {md=} for {fname=}: {e!r}") from e
    get_metadata(fname)  # Refresh cache after setting metadata
    return ret


def check_timezone_consistency(metadata: dict[str, t.Any], /, tolerance_in_meters: int = 200) -> None:
    """Public wrapper that normalizes missing-data errors to TzMismatchError.

    This keeps unit-test expectations simple when importing from `umann.metadata.md`.
    The CLI uses the underlying implementation directly to skip files with missing data.
    """
    try:
        return _chk_tz.check_timezone_consistency(metadata, tolerance_in_meters=tolerance_in_meters)
    except (NoCaptureDateTimeError, NoGpsError) as exc:
        raise TzMismatchError(str(exc)) from exc
